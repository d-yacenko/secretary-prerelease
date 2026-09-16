"""Bounded read-only graph workspace for Flutter Graph UI."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import case, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from app.api.schemas import EdgeOut, ObjectOut
from app.db.models import Edge, Object
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.task_lifecycle import TERMINAL_TASK_STATUSES_FOR_READS
from app.services.errors import NotFoundError
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE

DEFAULT_SEED_LIMIT = 12
MAX_SEED_LIMIT = 24
DEFAULT_NEIGHBOR_LIMIT = 12
MAX_NEIGHBOR_LIMIT = 24
DEFAULT_NODE_LIMIT = 80
MAX_NODE_LIMIT = 120


@dataclass(frozen=True)
class GraphWorkspaceResult:
    root_id: UUID | None
    seed_ids: list[UUID]
    nodes: list[Object]
    edges: list[Edge]
    truncated: bool


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
    ) -> GraphWorkspaceResult:
        seed_limit = min(max(1, seed_limit), MAX_SEED_LIMIT)
        neighbor_limit = min(max(1, neighbor_limit), MAX_NEIGHBOR_LIMIT)
        node_limit = min(max(1, node_limit), MAX_NODE_LIMIT)

        if root_id is not None:
            return self._rooted_workspace(root_id, neighbor_limit, node_limit)
        return self._overview_workspace(seed_limit, neighbor_limit, node_limit)

    def _rooted_workspace(
        self,
        root_id: UUID,
        neighbor_limit: int,
        node_limit: int,
    ) -> GraphWorkspaceResult:
        root = self._graph.get_object(root_id)
        node_map: dict[UUID, Object] = {root.id: root}
        edge_map: dict[UUID, Edge] = {}
        truncated = False

        new_node_budget = max(0, node_limit - len(node_map))
        if new_node_budget > 0:
            pairs, neighbor_truncated = self._expand_neighbors_batch(
                center_ids=[root_id],
                known_node_ids=set(node_map.keys()),
                neighbor_limit=neighbor_limit,
                new_node_budget=new_node_budget,
                exclude_deleted_neighbors=True,
            )
            truncated = truncated or neighbor_truncated
            for neighbor, edge in pairs:
                node_map[neighbor.id] = neighbor
                edge_map[edge.id] = edge
        elif self._has_hidden_eligible_neighbors(
            [root_id],
            set(node_map.keys()),
            exclude_deleted_neighbors=True,
        ):
            truncated = True

        edge_map = self._filter_edges_for_nodes(edge_map, node_map)
        return GraphWorkspaceResult(
            root_id=root_id,
            seed_ids=[],
            nodes=list(node_map.values()),
            edges=list(edge_map.values()),
            truncated=truncated,
        )

    def _overview_workspace(
        self,
        seed_limit: int,
        neighbor_limit: int,
        node_limit: int,
    ) -> GraphWorkspaceResult:
        actual_seed_limit = min(seed_limit, node_limit)
        total_seeds = self._count_active_seed_tasks()
        seeds = self._fetch_active_seed_tasks(actual_seed_limit)
        truncated = total_seeds > actual_seed_limit

        node_map: dict[UUID, Object] = {seed.id: seed for seed in seeds}
        edge_map: dict[UUID, Edge] = {}
        seed_ids = [seed.id for seed in seeds]

        new_node_budget = node_limit - len(node_map)
        if new_node_budget > 0 and seed_ids:
            pairs, neighbor_truncated = self._expand_neighbors_batch(
                center_ids=seed_ids,
                known_node_ids=set(node_map.keys()),
                neighbor_limit=neighbor_limit,
                new_node_budget=new_node_budget,
                exclude_deleted_neighbors=True,
            )
            truncated = truncated or neighbor_truncated
            for neighbor, edge in pairs:
                node_map[neighbor.id] = neighbor
                edge_map[edge.id] = edge
        elif seed_ids and self._has_hidden_eligible_neighbors(
            seed_ids,
            set(node_map.keys()),
            exclude_deleted_neighbors=True,
        ):
            truncated = True

        if len(node_map) > node_limit:
            truncated = True
            node_map = self._trim_nodes_deterministically(node_map, node_limit, seed_ids)

        edge_map = self._filter_edges_for_nodes(edge_map, node_map)
        return GraphWorkspaceResult(
            root_id=None,
            seed_ids=seed_ids,
            nodes=list(node_map.values()),
            edges=list(edge_map.values()),
            truncated=truncated,
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
        return self._session.scalar(
            select(func.count())
            .select_from(Object)
            .where(*self._active_seed_task_filters())
        ) or 0

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
        ]

    def _eligible_neighbor_object_filters(self, exclude_deleted_neighbors: bool) -> list:
        object_filters = [
            Object.user_id == self._user_id,
            Object.state != REJECTED_STATE,
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
                Edge.source_id.label("center_id"),
            )
            .select_from(Edge)
            .join(Object, Edge.target_id == Object.id)
            .where(
                Edge.user_id == self._user_id,
                Edge.source_id.in_(center_ids),
                Edge.state != REJECTED_STATE,
                *object_filters,
            )
        )
        incoming = (
            select(
                Edge.id.label("edge_id"),
                Edge.target_id.label("center_id"),
            )
            .select_from(Edge)
            .join(Object, Edge.source_id == Object.id)
            .where(
                Edge.user_id == self._user_id,
                Edge.target_id.in_(center_ids),
                Edge.state != REJECTED_STATE,
                *object_filters,
            )
        )

        candidates = union_all(outgoing, incoming).subquery("neighbor_candidates")
        counts_per_center = dict(
            self._session.execute(
                select(candidates.c.center_id, func.count())
                .group_by(candidates.c.center_id)
            ).all()
        )
        truncated = any(
            counts_per_center.get(center_id, 0) > neighbor_limit for center_id in center_ids
        )

        row_number = func.row_number().over(
            partition_by=candidates.c.center_id,
            order_by=candidates.c.edge_id,
        )
        ranked = (
            select(candidates.c.edge_id, row_number.label("row_number"))
            .select_from(candidates)
            .subquery("ranked_neighbor_edges")
        )

        edge_id_rows = self._session.execute(
            select(ranked.c.edge_id)
            .where(ranked.c.row_number <= neighbor_limit)
            .order_by(ranked.c.edge_id)
        ).all()
        edge_ids = [row[0] for row in edge_id_rows]
        if not edge_ids:
            return [], truncated

        edges = list(
            self._session.scalars(
                select(Edge)
                .where(Edge.id.in_(edge_ids), Edge.user_id == self._user_id)
                .order_by(Edge.id)
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
