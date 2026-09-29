"""User-scoped canonical Task world-space persistence.

Coordinates are presentation state. This service does not place Tasks and does
not observe relation mutations.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Object, TaskLayoutPosition, TaskLayoutState
from app.services.errors import ConflictError, ValidationError

_ALGORITHM_VERSION_LIMIT = 128


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
        usable = (
            state.snapshot_revision is not None
            and state.snapshot_revision == state.topology_revision
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
        if not centers:
            return ()
        rows = self.session.scalars(select(Object).where(Object.id.in_(seen))).all()
        by_id = {row.id: row for row in rows}
        for center in centers:
            obj = by_id.get(center.task_id)
            if obj is None:
                raise ValidationError("task layout id was not found")
            if obj.user_id != self.user_id:
                raise ValidationError("task layout id is owned by another user")
            if obj.kind != "task":
                raise ValidationError("task layout id is not a task")
        return tuple(centers)

    def _validated_version(self, algorithm_version: str) -> str:
        if not isinstance(algorithm_version, str) or not algorithm_version.strip():
            raise ValidationError("algorithm version is required")
        if len(algorithm_version) > _ALGORITHM_VERSION_LIMIT:
            raise ValidationError("algorithm version is too long")
        return algorithm_version


def _finite_coordinate(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{name} must be a finite coordinate")
    number = float(value)
    if not math.isfinite(number):
        raise ValidationError(f"{name} must be a finite coordinate")
    return number
