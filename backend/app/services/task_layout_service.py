"""User-scoped canonical Task world-space persistence.

Coordinates are presentation state. This service does not place Tasks and does
not observe relation mutations.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Edge, Object, TaskLayoutPosition, TaskLayoutState
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.task_map_topology import TASK_MAP_HIDDEN_RELATION_TYPES
from app.domain.task_relations import PART_OF
from app.services.errors import ConflictError, ValidationError
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE

_ALGORITHM_VERSION_LIMIT = 128
TASK_LAYOUT_TOPOLOGY_TASK_CAP = 500
TASK_LAYOUT_TOPOLOGY_EDGE_CAP = 2000


@dataclass(frozen=True)
class TaskLayoutCenter:
    task_id: uuid.UUID
    world_x: float
    world_y: float


@dataclass(frozen=True)
class TaskLayoutView:
    user_id: uuid.UUID
    topology_revision: int
    snapshot_revision: int | None
    algorithm_version: str | None
    usable: bool
    positions: tuple[TaskLayoutCenter, ...]


@dataclass(frozen=True)
class TaskLayoutTopology:
    topology_revision: int
    tasks: tuple[Object, ...]
    edges: tuple[Edge, ...]


class TaskLayoutService:
    def __init__(self, session: Session, user_id: uuid.UUID) -> None:
        self.session = session
        self.user_id = user_id

    def read(self) -> TaskLayoutView:
        state = self._locked_state(create=True)
        return self._view(state)

    def replace_snapshot(
        self,
        *,
        expected_topology_revision: int,
        algorithm_version: str,
        positions: list[TaskLayoutCenter],
    ) -> TaskLayoutView:
        state = self._locked_state(create=False)
        current_revision = 1 if state is None else state.topology_revision
        if current_revision != expected_topology_revision:
            raise ConflictError("stale task layout topology revision")
        centers = self._validated_centers(positions)
        version = self._validated_version(algorithm_version)
        if state is None:
            state = TaskLayoutState(user_id=self.user_id, topology_revision=1)
            self.session.add(state)
            self.session.flush()
        with self.session.begin_nested():
            self.session.execute(
                delete(TaskLayoutPosition).where(
                    TaskLayoutPosition.user_id == self.user_id,
                    TaskLayoutPosition.snapshot_revision == expected_topology_revision,
                )
            )
            for center in centers:
                self.session.add(
                    TaskLayoutPosition(
                        user_id=self.user_id,
                        task_id=center.task_id,
                        snapshot_revision=expected_topology_revision,
                        world_x=center.world_x,
                        world_y=center.world_y,
                    )
                )
            state.snapshot_revision = expected_topology_revision
            state.algorithm_version = version
            state.updated_at = datetime.now(UTC)
            self.session.flush()
        return self._view(state)

    def invalidate_topology(self) -> TaskLayoutView:
        state = self._locked_state(create=True)
        state.topology_revision += 1
        state.updated_at = datetime.now(UTC)
        self.session.flush()
        return self._view(state)

    def read_topology(self) -> TaskLayoutTopology:
        state = self.session.get(TaskLayoutState, self.user_id)
        revision = 1 if state is None else state.topology_revision
        filters = _eligible_filters(self.user_id)
        task_count = self.session.scalar(select(func.count()).select_from(Object).where(*filters))
        if task_count is not None and task_count > TASK_LAYOUT_TOPOLOGY_TASK_CAP:
            raise ValidationError("task layout topology exceeds the task cap")
        tasks = tuple(
            self.session.scalars(select(Object).where(*filters).order_by(Object.id)).all()
        )
        task_ids = [task.id for task in tasks]
        if not task_ids:
            return TaskLayoutTopology(topology_revision=revision, tasks=(), edges=())
        edge_filters = (
            Edge.user_id == self.user_id,
            Edge.source_id.in_(task_ids),
            Edge.target_id.in_(task_ids),
            Edge.state != REJECTED_STATE,
            Edge.type.notin_(tuple(TASK_MAP_HIDDEN_RELATION_TYPES)),
            or_(Edge.type != PART_OF, Edge.state == CONFIRMED_STATE),
        )
        edge_count = self.session.scalar(
            select(func.count()).select_from(Edge).where(*edge_filters)
        )
        if edge_count is not None and edge_count > TASK_LAYOUT_TOPOLOGY_EDGE_CAP:
            raise ValidationError("task layout topology exceeds the edge cap")
        edges = tuple(
            self.session.scalars(select(Edge).where(*edge_filters).order_by(Edge.id)).all()
        )
        return TaskLayoutTopology(
            topology_revision=revision,
            tasks=tasks,
            edges=edges,
        )

    def _locked_state(self, *, create: bool) -> TaskLayoutState | None:
        state = self.session.scalar(
            select(TaskLayoutState)
            .where(TaskLayoutState.user_id == self.user_id)
            .with_for_update()
        )
        if state is None and create:
            state = TaskLayoutState(user_id=self.user_id, topology_revision=1)
            self.session.add(state)
            self.session.flush()
        return state

    def _view(self, state: TaskLayoutState) -> TaskLayoutView:
        positions: tuple[TaskLayoutCenter, ...] = ()
        if state.snapshot_revision is not None:
            rows = self.session.scalars(
                select(TaskLayoutPosition)
                .where(
                    TaskLayoutPosition.user_id == self.user_id,
                    TaskLayoutPosition.snapshot_revision == state.snapshot_revision,
                )
                .order_by(TaskLayoutPosition.task_id)
            ).all()
            positions = tuple(
                TaskLayoutCenter(task_id=row.task_id, world_x=row.world_x, world_y=row.world_y)
                for row in rows
            )
        covered = {position.task_id for position in positions}
        usable = (
            state.snapshot_revision is not None
            and state.snapshot_revision == state.topology_revision
            and self._eligible_ids() <= covered
        )
        return TaskLayoutView(
            user_id=self.user_id,
            topology_revision=state.topology_revision,
            snapshot_revision=state.snapshot_revision,
            algorithm_version=state.algorithm_version,
            usable=usable,
            positions=positions,
        )

    def _validated_centers(self, positions: list[TaskLayoutCenter]) -> tuple[TaskLayoutCenter, ...]:
        seen: set[uuid.UUID] = set()
        centers: list[TaskLayoutCenter] = []
        for position in positions:
            if position.task_id in seen:
                raise ValidationError("duplicate task id in layout snapshot")
            seen.add(position.task_id)
            centers.append(
                TaskLayoutCenter(
                    task_id=position.task_id,
                    world_x=_finite_coordinate(position.world_x, "world_x"),
                    world_y=_finite_coordinate(position.world_y, "world_y"),
                )
            )
        if centers:
            rows = self.session.scalars(select(Object).where(Object.id.in_(seen))).all()
            by_id = {row.id: row for row in rows}
        else:
            by_id = {}
        for center in centers:
            obj = by_id.get(center.task_id)
            if obj is None:
                raise ValidationError("task layout id was not found")
            if obj.user_id != self.user_id:
                raise ValidationError("task layout id is owned by another user")
            if obj.kind != "task":
                raise ValidationError("task layout id is not a task")
            if obj.state == REJECTED_STATE or is_object_hidden_from_active_reads(obj):
                raise ValidationError("task layout id is not a current task")
        if seen != self._eligible_ids():
            raise ValidationError("task layout snapshot must match the current task set")
        return tuple(centers)

    def _eligible_ids(self) -> set[uuid.UUID]:
        return set(
            self.session.scalars(
                select(Object.id).where(*_eligible_filters(self.user_id))
            ).all()
        )

    def _validated_version(self, algorithm_version: str) -> str:
        if not isinstance(algorithm_version, str) or not algorithm_version.strip():
            raise ValidationError("algorithm version is required")
        if len(algorithm_version) > _ALGORITHM_VERSION_LIMIT:
            raise ValidationError("algorithm version is too long")
        return algorithm_version


def _eligible_filters(user_id: uuid.UUID) -> tuple:
    return (
        Object.user_id == user_id,
        Object.kind == "task",
        Object.state != REJECTED_STATE,
        object_is_active(),
    )


def _finite_coordinate(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{name} must be a finite coordinate")
    number = float(value)
    if not math.isfinite(number):
        raise ValidationError(f"{name} must be a finite coordinate")
    return number
