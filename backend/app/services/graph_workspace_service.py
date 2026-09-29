"""Bounded read-only graph workspace for Flutter Graph UI."""

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, case, func, literal, or_, select, union_all
from sqlalchemy.orm import Session, aliased

from app.api.schemas import EdgeOut, ObjectOut
from app.db.models import Edge, Object
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.task_lifecycle import TERMINAL_TASK_STATUSES_FOR_READS
from app.domain.task_relations import PART_OF
from app.domain.telegram_mtproto_visibility import telegram_mtproto_active_object_predicate
from app.services.errors import ConstellationTooLargeError, NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.provenance import AGENT_ORIGIN, CONFIRMED_STATE, REJECTED_STATE, USER_ORIGIN

DEFAULT_SEED_LIMIT = 12
MAX_SEED_LIMIT = 24
DEFAULT_NEIGHBOR_LIMIT = 12
MAX_NEIGHBOR_LIMIT = 24
DEFAULT_NODE_LIMIT = 80
MAX_NODE_LIMIT = 120
SOFT_WINDOW_NODE_TARGET = 80
MAX_COMPLETE_WINDOW_NODES = 500
PEOPLE_LANDSCAPE_TASK_CONTEXT_CAP = 500
PRIORITY_TASK_FLOW_TYPES = ("references", "related_to", "depends_on")
PRIORITY_TASK_FLOW_ORIGINS = (USER_ORIGIN, AGENT_ORIGIN)


@dataclass(frozen=True)
class GraphWorkspaceResult:
    root_id: UUID | None
    seed_ids: list[UUID]
    nodes: list[Object]
    edges: list[Edge]
    truncated: bool
    window_index: int = 0
    window_count: int = 1
    has_previous_window: bool = False
    has_next_window: bool = False
    constellation_root_ids: tuple[UUID, ...] = ()
    semantic_window_complete: bool = False


@dataclass(frozen=True)
class _Constellation:
    """One indivisible overview unit.

    Order key is the minimum active-member seed key:
    missing due_at last, then earliest due_at, confirmed before other states,
    most recently updated, then task id. Unrelated lower-priority constellations
    therefore sort after earlier pages.
    """

    root_id: UUID
    members: dict[UUID, Object]
    sort_key: tuple
    node_ids: frozenset[UUID] = field(default_factory=frozenset)


class GraphWorkspaceService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._graph = GraphService(session, user_id)

    def get_workspace(
        self,
        root_id: UUID | None = None,
        seed_limit: int = DEFAULT_SEED_LIMIT,
        neighbor_limit: int = DEFAULT_NEIGHBOR_LIMIT,
        node_limit: int = DEFAULT_NODE_LIMIT,
        window_index: int = 0,
        soft_window_target: int | None = None,
        max_complete_window_nodes: int | None = None,
    ) -> GraphWorkspaceResult:
        # seed_limit remains accepted for older clients. Overview membership is
        # whole constellations, so this bound must not slice one.
        _ = min(max(1, seed_limit), MAX_SEED_LIMIT)
        neighbor_limit = min(max(1, neighbor_limit), MAX_NEIGHBOR_LIMIT)
        node_limit = min(max(1, node_limit), MAX_NODE_LIMIT)

        if root_id is not None:
            return self._rooted_workspace(root_id, neighbor_limit, node_limit, max_complete_window_nodes)
        return self._semantic_overview(
            window_index=window_index,
            soft_target=soft_window_target or SOFT_WINDOW_NODE_TARGET,
            emergency_ceiling=max_complete_window_nodes or MAX_COMPLETE_WINDOW_NODES,
        )

    def _rooted_workspace(
        self,
        root_id: UUID,
        neighbor_limit: int,
        node_limit: int,
        max_complete_window_nodes: int | None,
    ) -> GraphWorkspaceResult:
        root = self._session.scalar(
            select(Object).where(
                Object.id == root_id,
                Object.user_id == self._user_id,
                telegram_mtproto_active_object_predicate(),
            )
        )
        if root is None or is_object_hidden_from_active_reads(root):
            raise NotFoundError("object", root_id)
        node_map: dict[UUID, Object] = {root.id: root}
        edge_map: dict[UUID, Edge] = {}
        truncated = False
        emergency = max_complete_window_nodes or MAX_COMPLETE_WINDOW_NODES
        if root.kind == "task":
            constellation = self._constellation_containing(root.id, require_non_terminal=False)
            if constellation is not None:
                if len(constellation.node_ids) > emergency:
                    raise ConstellationTooLargeError
                node_map = dict(constellation.members)
                edge_map = {}

        ordinary_cap = max(node_limit, len(node_map))
        truncated = truncated or self._admit_ordinary_neighbors(
            center_ids=[root_id],
            node_map=node_map,
            edge_map=edge_map,
            neighbor_limit=neighbor_limit,
            node_limit=ordinary_cap,
        )

        edge_map = self._complete_edges_among_nodes(edge_map, node_map)
        return GraphWorkspaceResult(
            root_id=root_id,
            seed_ids=[],
            nodes=self._ordered_nodes(node_map, root_id),
            edges=list(edge_map.values()),
            truncated=truncated,
        )

    def _semantic_overview(
        self,
        *,
        window_index: int,
        soft_target: int,
        emergency_ceiling: int,
    ) -> GraphWorkspaceResult:
        constellations = self._overview_constellations(emergency_ceiling)
        windows = self._pack_constellation_windows(constellations, soft_target)
        if not windows:
            windows = [[]]
        if window_index < 0 or window_index >= len(windows):
            raise ValidationError("graph window index is out of range")
        chosen = windows[window_index]
        node_map: dict[UUID, Object] = {}
        root_ids: list[UUID] = []
        for constellation in chosen:
            node_map.update(constellation.members)
            root_ids.append(constellation.root_id)
        edge_map = self._complete_edges_among_nodes({}, node_map)
        window_count = len(windows)
        return GraphWorkspaceResult(
            root_id=None,
            seed_ids=root_ids,
            nodes=self._ordered_nodes(node_map, None),
            edges=list(edge_map.values()),
            truncated=window_count > 1,
            window_index=window_index,
            window_count=window_count,
            has_previous_window=window_index > 0,
            has_next_window=window_index + 1 < window_count,
            constellation_root_ids=tuple(root_ids),
            semantic_window_complete=True,
        )

    def _overview_constellations(self, emergency_ceiling: int) -> list[_Constellation]:
        tasks = self._visible_tasks()
        if not tasks:
            return []
        parent_of, children_of = self._confirmed_part_of_forest(set(tasks))
        roots = [task_id for task_id in tasks if task_id not in parent_of]
        constellations: list[_Constellation] = []
        for root_id in roots:
            member_ids = self._descendant_ids(root_id, children_of)
            members = {task_id: tasks[task_id] for task_id in member_ids}
            if not any(self._task_is_overview_seed(task) for task in members.values()):
                continue
            flows = self._priority_flows_for_tasks(set(members))
            members.update(flows)
            if len(members) > emergency_ceiling:
                raise ConstellationTooLargeError
            ordering_members = [
                task
                for task in members.values()
                if task.kind == "task" and self._task_is_overview_seed(task)
            ] or [task for task in members.values() if task.kind == "task"]
            constellations.append(
                _Constellation(
                    root_id=root_id,
                    members=members,
                    sort_key=min(self._task_seed_key(task) for task in ordering_members),
                    node_ids=frozenset(members),
                )
            )
        constellations.sort(key=lambda item: (item.sort_key, str(item.root_id)))
        return constellations

    def _pack_constellation_windows(
        self,
        constellations: list[_Constellation],
        soft_target: int,
    ) -> list[list[_Constellation]]:
        windows: list[list[_Constellation]] = []
        current: list[_Constellation] = []
        occupied: set[UUID] = set()
        for constellation in constellations:
            added = constellation.node_ids - occupied
            if current and len(occupied) + len(added) > soft_target:
                windows.append(current)
                current = [constellation]
                occupied = set(constellation.node_ids)
                continue
            current.append(constellation)
            occupied.update(constellation.node_ids)
        if current:
            windows.append(current)
        return windows

    def _constellation_containing(
        self,
        task_id: UUID,
        *,
        require_non_terminal: bool,
    ) -> _Constellation | None:
        tasks = self._visible_tasks()
        if task_id not in tasks:
            return None
        parent_of, children_of = self._confirmed_part_of_forest(set(tasks))
        root_id = task_id
        seen_parents: set[UUID] = set()
        while root_id in parent_of and root_id not in seen_parents:
            seen_parents.add(root_id)
            root_id = parent_of[root_id]
        member_ids = self._descendant_ids(root_id, children_of)
        members = {member_id: tasks[member_id] for member_id in member_ids}
        if require_non_terminal and not any(
            self._task_is_overview_seed(task) for task in members.values()
        ):
            return None
        members.update(self._priority_flows_for_tasks(set(members)))
        return _Constellation(
            root_id=root_id,
            members=members,
            sort_key=(),
            node_ids=frozenset(members),
        )

    def _visible_tasks(self) -> dict[UUID, Object]:
        rows = self._session.scalars(
            select(Object).where(
                Object.user_id == self._user_id,
                Object.kind == "task",
                Object.state != REJECTED_STATE,
                telegram_mtproto_active_object_predicate(),
            )
        ).all()
        return {
            task.id: task
            for task in rows
            if not is_object_hidden_from_active_reads(task)
        }

    def _confirmed_part_of_forest(
        self,
        task_ids: set[UUID],
    ) -> tuple[dict[UUID, UUID], dict[UUID, list[UUID]]]:
        if not task_ids:
            return {}, {}
        edges = self._session.scalars(
            select(Edge).where(
                Edge.user_id == self._user_id,
                Edge.type == "part_of",
                Edge.state == CONFIRMED_STATE,
                Edge.source_id.in_(task_ids),
                Edge.target_id.in_(task_ids),
            )
        ).all()
        parent_of: dict[UUID, UUID] = {}
        children_of: dict[UUID, list[UUID]] = {}
        for edge in sorted(edges, key=lambda item: (item.created_at, str(item.id))):
            if edge.source_id in parent_of:
                continue
            parent_of[edge.source_id] = edge.target_id
            children_of.setdefault(edge.target_id, []).append(edge.source_id)
        return parent_of, children_of

    def _descendant_ids(
        self,
        root_id: UUID,
        children_of: dict[UUID, list[UUID]],
    ) -> set[UUID]:
        seen = {root_id}
        pending = [root_id]
        while pending:
            current = pending.pop()
            for child_id in children_of.get(current, []):
                if child_id in seen:
                    continue
                seen.add(child_id)
                pending.append(child_id)
        return seen

    def landscape_task_context(
        self,
        anchor_ids: set[UUID],
    ) -> tuple[list[Object], list[Edge], bool]:
        """Full confirmed part_of Task constellations for later client projection.

        Returns tasks, Task↔Task edges, and completeness. Overflow or an anchor
        outside the visible Task universe fails closed with an empty context.
        """
        if not anchor_ids:
            return [], [], True
        visible = self._visible_tasks()
        if any(anchor_id not in visible for anchor_id in anchor_ids):
            return [], [], False
        parent_of, children_of = self._confirmed_part_of_forest(set(visible))
        member_ids: set[UUID] = set()
        for anchor_id in anchor_ids:
            root_id = anchor_id
            seen_up: set[UUID] = set()
            while root_id in parent_of and root_id not in seen_up:
                seen_up.add(root_id)
                root_id = parent_of[root_id]
            member_ids.update(self._descendant_ids(root_id, children_of))
        if len(member_ids) > PEOPLE_LANDSCAPE_TASK_CONTEXT_CAP:
            return [], [], False
        tasks = [visible[task_id] for task_id in sorted(member_ids)]
        edges = self._complete_edges_among_nodes({}, {task.id: task for task in tasks})
        return tasks, [edges[edge_id] for edge_id in sorted(edges)], True

    def _priority_flows_for_tasks(self, task_ids: set[UUID]) -> dict[UUID, Object]:
        buckets = self._priority_task_flow_buckets(task_ids)
        flows: dict[UUID, Object] = {}
        for rows in buckets.values():
            for _edge, flow in rows:
                flows[flow.id] = flow
        return flows

    def _ordered_nodes(self, node_map: dict[UUID, Object], root_id: UUID | None) -> list[Object]:
        tasks = [obj for obj in node_map.values() if obj.kind == "task"]
        others = [obj for obj in node_map.values() if obj.kind != "task"]
        if root_id is not None and root_id in node_map and node_map[root_id].kind == "task":
            tasks = [node_map[root_id]] + sorted(
                (task for task in tasks if task.id != root_id),
                key=self._task_seed_key,
            )
        else:
            tasks = sorted(tasks, key=self._task_seed_key)
        others.sort(key=lambda obj: (obj.title, str(obj.id)))
        return tasks + others

    def _task_is_overview_seed(self, task: Object) -> bool:
        return task.status is None or task.status not in TERMINAL_TASK_STATUSES_FOR_READS

    def _task_seed_key(self, task: Object) -> tuple:
        due_missing = task.due_at is None
        due_token = "" if due_missing else task.due_at.isoformat()
        updated = task.updated_at or datetime.min.replace(tzinfo=UTC)
        return (
            due_missing,
            due_token,
            0 if task.state == CONFIRMED_STATE else 1,
            -updated.timestamp(),
            str(task.id),
        )

    def _trim_nodes_deterministically(
        self,
        node_map: dict[UUID, Object],
        node_limit: int,
        priority_ids: list[UUID],
    ) -> dict[UUID, Object]:
        keep: set[UUID] = set()
        for object_id in priority_ids:
            if object_id in node_map and len(keep) < node_limit:
                keep.add(object_id)
        remaining = sorted(
            [obj for obj in node_map.values() if obj.id not in keep],
            key=lambda obj: (obj.kind, obj.title, str(obj.id)),
        )
        for obj in remaining:
            if len(keep) >= node_limit:
                break
            keep.add(obj.id)
        return {object_id: node_map[object_id] for object_id in keep}

    def _close_confirmed_part_of(
        self,
        frontier_ids: list[UUID],
        node_map: dict[UUID, Object],
        edge_map: dict[UUID, Edge],
        node_limit: int,
    ) -> bool:
        """Add the confirmed Task part_of component reachable from the frontier.

        Ordinary neighbor_limit does not apply. node_limit still bounds the
        workspace. Hierarchy-added tasks are not returned as new expansion centers.
        """
        truncated = False
        queue: deque[UUID] = deque(
            object_id
            for object_id in frontier_ids
            if object_id in node_map and node_map[object_id].kind == "task"
        )
        seen: set[UUID] = set()
        while queue:
            current_id = queue.popleft()
            if current_id in seen:
                continue
            seen.add(current_id)
            for edge in self._confirmed_part_of_edges(current_id):
                other_id = edge.target_id if edge.source_id == current_id else edge.source_id
                if other_id not in node_map:
                    if len(node_map) >= node_limit:
                        truncated = True
                        continue
                    other = self._session.get(Object, other_id)
                    if (
                        other is None
                        or other.user_id != self._user_id
                        or other.kind != "task"
                        or other.state == REJECTED_STATE
                        or is_object_hidden_from_active_reads(other)
                    ):
                        continue
                    node_map[other.id] = other
                    queue.append(other.id)
                if edge.source_id in node_map and edge.target_id in node_map:
                    edge_map[edge.id] = edge
        return truncated

    def _confirmed_part_of_edges(self, task_id: UUID) -> list[Edge]:
        neighbor = aliased(Object)
        neighbor_filters = [
            neighbor.user_id == self._user_id,
            neighbor.kind == "task",
            neighbor.state != REJECTED_STATE,
            telegram_mtproto_active_object_predicate(neighbor),
            object_is_active(neighbor),
        ]
        stmt = (
            select(Edge)
            .join(
                neighbor,
                or_(
                    and_(Edge.source_id == task_id, Edge.target_id == neighbor.id),
                    and_(Edge.target_id == task_id, Edge.source_id == neighbor.id),
                ),
            )
            .where(
                Edge.user_id == self._user_id,
                Edge.type == PART_OF,
                Edge.state == CONFIRMED_STATE,
                or_(Edge.source_id == task_id, Edge.target_id == task_id),
                *neighbor_filters,
            )
            .order_by(Edge.id)
        )
        edges: list[Edge] = []
        seen_ids: set[UUID] = set()
        for edge in self._session.scalars(stmt):
            if edge.id in seen_ids:
                continue
            seen_ids.add(edge.id)
            edges.append(edge)
        return edges

    def _admit_priority_task_flow(
        self,
        node_map: dict[UUID, Object],
        edge_map: dict[UUID, Edge],
        node_limit: int,
    ) -> bool:
        """Admit confirmed user/agent Task-Flow evidence before ordinary neighbors.

        One new Flow endpoint per admitted Task per pass, in Task id order.
        Each Task's edges are taken by created_at, then id. node_limit still
        caps the workspace. neighbor_limit does not apply here.
        """
        task_ids = sorted(obj.id for obj in node_map.values() if obj.kind == "task")
        if not task_ids:
            return False
        buckets = self._priority_task_flow_buckets(task_ids)
        if not buckets:
            return False

        indexes = {task_id: 0 for task_id in task_ids}
        while len(node_map) < node_limit:
            admitted_new = False
            for task_id in task_ids:
                if len(node_map) >= node_limit:
                    break
                queue = buckets.get(task_id, [])
                index = indexes[task_id]
                while index < len(queue) and queue[index][1].id in node_map:
                    edge_map[queue[index][0].id] = queue[index][0]
                    index += 1
                indexes[task_id] = index
                if index >= len(queue):
                    continue
                edge, flow = queue[index]
                node_map[flow.id] = flow
                edge_map[edge.id] = edge
                indexes[task_id] = index + 1
                admitted_new = True
            if not admitted_new:
                break

        for task_id in task_ids:
            queue = buckets.get(task_id, [])
            for edge, flow in queue[indexes[task_id] :]:
                if flow.id in node_map:
                    edge_map[edge.id] = edge
                else:
                    return True
        return False

    def _priority_task_flow_buckets(
        self,
        task_ids: list[UUID],
    ) -> dict[UUID, list[tuple[Edge, Object]]]:
        flow = aliased(Object)
        task_id_set = set(task_ids)
        rows = self._session.execute(
            select(Edge, flow)
            .join(
                flow,
                or_(
                    and_(Edge.source_id.in_(task_ids), Edge.target_id == flow.id),
                    and_(Edge.target_id.in_(task_ids), Edge.source_id == flow.id),
                ),
            )
            .where(
                Edge.user_id == self._user_id,
                Edge.state == CONFIRMED_STATE,
                Edge.origin.in_(PRIORITY_TASK_FLOW_ORIGINS),
                Edge.type.in_(PRIORITY_TASK_FLOW_TYPES),
                flow.user_id == self._user_id,
                flow.kind != "task",
                flow.state != REJECTED_STATE,
                telegram_mtproto_active_object_predicate(flow),
                object_is_active(flow),
            )
            .order_by(Edge.created_at.asc(), Edge.id.asc())
        ).all()
        buckets: dict[UUID, list[tuple[Edge, Object]]] = {}
        for edge, flow_object in rows:
            if edge.source_id in task_id_set and edge.target_id == flow_object.id:
                task_id = edge.source_id
            elif edge.target_id in task_id_set and edge.source_id == flow_object.id:
                task_id = edge.target_id
            else:
                continue
            buckets.setdefault(task_id, []).append((edge, flow_object))
        return buckets

    def _complete_edges_among_nodes(
        self,
        edge_map: dict[UUID, Edge],
        node_map: dict[UUID, Object],
    ) -> dict[UUID, Edge]:
        """Return every non-rejected edge whose endpoints are already admitted.

        Node admission stays traversal-bounded. This query does not add nodes.
        It only fills edges the walk never inserted, including proposed edges
        that existing reads already keep when state is not rejected.
        """
        completed = self._filter_edges_for_nodes(edge_map, node_map)
        node_ids = list(node_map)
        if len(node_ids) < 2:
            return completed
        persisted = self._session.scalars(
            select(Edge).where(
                Edge.user_id == self._user_id,
                Edge.state != REJECTED_STATE,
                Edge.source_id.in_(node_ids),
                Edge.target_id.in_(node_ids),
            )
        )
        for edge in persisted:
            completed[edge.id] = edge
        return completed

    def _filter_edges_for_nodes(
        self,
        edge_map: dict[UUID, Edge],
        node_map: dict[UUID, Object],
    ) -> dict[UUID, Edge]:
        return {
            edge_id: edge
            for edge_id, edge in edge_map.items()
            if edge.source_id in node_map and edge.target_id in node_map
        }

    def _count_active_seed_tasks(self) -> int:
        return (
            self._session.scalar(
                select(func.count()).select_from(Object).where(*self._active_seed_task_filters())
            )
            or 0
        )

    def _fetch_active_seed_tasks(self, limit: int) -> list[Object]:
        state_rank = case((Object.state == CONFIRMED_STATE, 0), else_=1)
        stmt = (
            select(Object)
            .where(*self._active_seed_task_filters())
            .order_by(
                Object.due_at.asc().nulls_last(),
                state_rank,
                Object.updated_at.desc(),
                Object.id.asc(),
            )
            .limit(limit)
        )
        return list(self._session.scalars(stmt))

    def _active_seed_task_filters(self) -> list:
        non_terminal_status = or_(
            Object.status.is_(None),
            Object.status.not_in(tuple(TERMINAL_TASK_STATUSES_FOR_READS)),
        )
        return [
            Object.user_id == self._user_id,
            Object.kind == "task",
            Object.state != REJECTED_STATE,
            non_terminal_status,
            telegram_mtproto_active_object_predicate(),
        ]

    def _eligible_neighbor_object_filters(self, exclude_deleted_neighbors: bool) -> list:
        object_filters = [
            Object.user_id == self._user_id,
            Object.state != REJECTED_STATE,
            telegram_mtproto_active_object_predicate(),
        ]
        if exclude_deleted_neighbors:
            object_filters.append(object_is_active())
        return object_filters

    def _has_hidden_eligible_neighbors(
        self,
        center_ids: list[UUID],
        known_node_ids: set[UUID],
        exclude_deleted_neighbors: bool,
    ) -> bool:
        if not center_ids or not known_node_ids:
            return False

        object_filters = self._eligible_neighbor_object_filters(exclude_deleted_neighbors)
        known_list = list(known_node_ids)

        outgoing_exists = self._session.scalar(
            select(literal(1))
            .select_from(Edge)
            .join(Object, Edge.target_id == Object.id)
            .where(
                Edge.user_id == self._user_id,
                Edge.source_id.in_(center_ids),
                Edge.target_id.not_in(known_list),
                Edge.state != REJECTED_STATE,
                *object_filters,
            )
            .limit(1)
        )
        if outgoing_exists is not None:
            return True

        incoming_exists = self._session.scalar(
            select(literal(1))
            .select_from(Edge)
            .join(Object, Edge.source_id == Object.id)
            .where(
                Edge.user_id == self._user_id,
                Edge.target_id.in_(center_ids),
                Edge.source_id.not_in(known_list),
                Edge.state != REJECTED_STATE,
                *object_filters,
            )
            .limit(1)
        )
        return incoming_exists is not None

    def _admit_ordinary_neighbors(
        self,
        center_ids: list[UUID],
        node_map: dict[UUID, Object],
        edge_map: dict[UUID, Edge],
        neighbor_limit: int,
        node_limit: int,
    ) -> bool:
        """Admit ordinary neighbors one at a time.

        A newly admitted Task closes its confirmed part_of component before
        the next ordinary neighbor consumes node budget.
        """
        if not center_ids:
            return False
        if len(node_map) >= node_limit:
            return self._has_hidden_eligible_neighbors(
                center_ids,
                set(node_map.keys()),
                exclude_deleted_neighbors=True,
            )

        truncated = False
        while len(node_map) < node_limit:
            pairs, batch_truncated = self._expand_neighbors_batch(
                center_ids=center_ids,
                known_node_ids=set(node_map.keys()),
                neighbor_limit=neighbor_limit,
                new_node_budget=1,
                exclude_deleted_neighbors=True,
            )
            truncated = truncated or batch_truncated
            new_ids: list[UUID] = []
            for neighbor, edge in pairs:
                is_new = neighbor.id not in node_map
                node_map[neighbor.id] = neighbor
                edge_map[edge.id] = edge
                if is_new:
                    new_ids.append(neighbor.id)
            if not new_ids:
                break
            for new_id in new_ids:
                if node_map[new_id].kind == "task":
                    hierarchy_truncated = self._close_confirmed_part_of(
                        [new_id],
                        node_map,
                        edge_map,
                        node_limit,
                    )
                    truncated = truncated or hierarchy_truncated
        if len(node_map) >= node_limit and self._has_hidden_eligible_neighbors(
            center_ids,
            set(node_map.keys()),
            exclude_deleted_neighbors=True,
        ):
            truncated = True
        return truncated

    def _expand_neighbors_batch(
        self,
        center_ids: list[UUID],
        known_node_ids: set[UUID],
        neighbor_limit: int,
        new_node_budget: int,
        exclude_deleted_neighbors: bool,
    ) -> tuple[list[tuple[Object, Edge]], bool]:
        if not center_ids or new_node_budget <= 0:
            return [], False

        center_set = set(center_ids)

        object_filters = self._eligible_neighbor_object_filters(exclude_deleted_neighbors)

        outgoing = (
            select(
                Edge.id.label("edge_id"),
                Edge.created_at.label("created_at"),
                Edge.source_id.label("center_id"),
            )
            .select_from(Edge)
            .join(Object, Edge.target_id == Object.id)
            .where(
                Edge.user_id == self._user_id,
                Edge.source_id.in_(center_ids),
                Edge.state != REJECTED_STATE,
                or_(Edge.type != PART_OF, Edge.state != CONFIRMED_STATE),
                *object_filters,
            )
        )
        incoming = (
            select(
                Edge.id.label("edge_id"),
                Edge.created_at.label("created_at"),
                Edge.target_id.label("center_id"),
            )
            .select_from(Edge)
            .join(Object, Edge.source_id == Object.id)
            .where(
                Edge.user_id == self._user_id,
                Edge.target_id.in_(center_ids),
                Edge.state != REJECTED_STATE,
                or_(Edge.type != PART_OF, Edge.state != CONFIRMED_STATE),
                *object_filters,
            )
        )

        candidates = union_all(outgoing, incoming).subquery("neighbor_candidates")
        counts_per_center = dict(
            self._session.execute(
                select(candidates.c.center_id, func.count()).group_by(candidates.c.center_id)
            ).all()
        )
        truncated = any(
            counts_per_center.get(center_id, 0) > neighbor_limit for center_id in center_ids
        )

        row_number = func.row_number().over(
            partition_by=candidates.c.center_id,
            order_by=(candidates.c.created_at.asc(), candidates.c.edge_id.asc()),
        )
        ranked = (
            select(
                candidates.c.edge_id,
                candidates.c.created_at,
                row_number.label("row_number"),
            )
            .select_from(candidates)
            .subquery("ranked_neighbor_edges")
        )

        edge_id_rows = self._session.execute(
            select(ranked.c.edge_id)
            .where(ranked.c.row_number <= neighbor_limit)
            .order_by(ranked.c.created_at.asc(), ranked.c.edge_id.asc())
        ).all()
        edge_ids = [row[0] for row in edge_id_rows]
        if not edge_ids:
            return [], truncated

        edges = list(
            self._session.scalars(
                select(Edge)
                .where(Edge.id.in_(edge_ids), Edge.user_id == self._user_id)
                .order_by(Edge.created_at.asc(), Edge.id.asc())
            )
        )

        neighbor_ids: set[UUID] = set()
        for edge in edges:
            if edge.source_id in center_set:
                neighbor_ids.add(edge.target_id)
            if edge.target_id in center_set:
                neighbor_ids.add(edge.source_id)
        neighbor_ids -= center_set

        object_rows = self._session.scalars(
            select(Object).where(
                Object.user_id == self._user_id,
                Object.id.in_(neighbor_ids | center_set),
            )
        ).all()
        objects_by_id = {obj.id: obj for obj in object_rows}

        results: list[tuple[Object, Edge]] = []
        seen_edge_ids: set[UUID] = set()
        new_nodes_added = 0
        known_ids = set(known_node_ids)

        for edge in edges:
            if edge.id in seen_edge_ids:
                continue
            neighbor_id: UUID | None = None
            if edge.source_id in center_set:
                neighbor_id = edge.target_id
            elif edge.target_id in center_set:
                neighbor_id = edge.source_id
            if neighbor_id is None:
                continue

            neighbor = objects_by_id.get(neighbor_id)
            if neighbor is None:
                continue
            if neighbor.state == REJECTED_STATE:
                continue
            if exclude_deleted_neighbors and is_object_hidden_from_active_reads(neighbor):
                continue

            if neighbor.id in known_ids:
                seen_edge_ids.add(edge.id)
                results.append((neighbor, edge))
                continue

            if new_nodes_added >= new_node_budget:
                truncated = True
                break

            known_ids.add(neighbor.id)
            new_nodes_added += 1
            seen_edge_ids.add(edge.id)
            results.append((neighbor, edge))

        return results, truncated

    def to_response(self, result: GraphWorkspaceResult) -> dict:
        return {
            "root_id": str(result.root_id) if result.root_id is not None else None,
            "seed_ids": [str(seed_id) for seed_id in result.seed_ids],
            "nodes": [ObjectOut.from_model(node).model_dump(mode="json") for node in result.nodes],
            "edges": [EdgeOut.from_model(edge).model_dump(mode="json") for edge in result.edges],
            "truncated": result.truncated,
        }
