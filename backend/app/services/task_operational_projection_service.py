"""Load confirmed canonical facts and derive one Task's actionability."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.db.models import Edge, Object
from app.domain.object_visibility import object_is_active
from app.domain.task_lifecycle import TERMINAL_TASK_STATUSES_FOR_READS
from app.domain.task_operational import (
    MAX_OPERATIONAL_BATCH,
    MAX_OPERATIONAL_CHUNKED,
    OperationalDependency,
    OperationalPerson,
    TaskOperationalProjection,
    derive_task_operational_state,
)
from app.domain.task_relations import DELEGATED_TO, DEPENDS_ON, MAX_PROFILE_ITEMS, WAITING_ON
from app.services.errors import ValidationError
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE


class TaskOperationalProjectionService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def project(self, task: Object, *, now: datetime | None = None) -> TaskOperationalProjection:
        moment = now or datetime.now(UTC)
        projected = self.project_many([task], now=moment)
        return projected[task.id]

    def project_chunked(
        self,
        tasks: list[Object],
        *,
        now: datetime | None = None,
    ) -> dict[UUID, TaskOperationalProjection]:
        """Project a bounded list in batches of MAX_OPERATIONAL_BATCH. Not one query per Task."""
        if len(tasks) > MAX_OPERATIONAL_CHUNKED:
            raise ValidationError(
                f"operational projection list exceeds {MAX_OPERATIONAL_CHUNKED}"
            )
        moment = now or datetime.now(UTC)
        projected: dict[UUID, TaskOperationalProjection] = {}
        for start in range(0, len(tasks), MAX_OPERATIONAL_BATCH):
            projected.update(
                self.project_many(tasks[start : start + MAX_OPERATIONAL_BATCH], now=moment)
            )
        return projected

    def project_many(
        self,
        tasks: list[Object],
        *,
        now: datetime | None = None,
    ) -> dict[UUID, TaskOperationalProjection]:
        if len(tasks) > MAX_OPERATIONAL_BATCH:
            raise ValidationError(f"operational projection batch exceeds {MAX_OPERATIONAL_BATCH}")
        moment = now or datetime.now(UTC)
        task_ids = [task.id for task in tasks]
        blockers = self._blocking_dependencies(task_ids)
        waiting = self._people(task_ids, WAITING_ON)
        delegated = self._people(task_ids, DELEGATED_TO)
        return {
            task.id: derive_task_operational_state(
                status=task.status,
                due_at=task.due_at,
                planned_start_at=task.planned_start_at,
                planned_end_at=task.planned_end_at,
                now=moment,
                blocking_dependencies=blockers.get(task.id, ()),
                waiting_on=waiting.get(task.id, ()),
                delegated_to=delegated.get(task.id, ()),
            )
            for task in tasks
        }

    def _blocking_dependencies(self, task_ids: list[UUID]) -> dict[UUID, tuple[OperationalDependency, ...]]:
        if not task_ids:
            return {}
        other = aliased(Object)
        ranked = (
            select(
                Edge.source_id.label("source_id"),
                other.id.label("target_id"),
                other.title.label("title"),
                other.status.label("status"),
                func.row_number()
                .over(partition_by=Edge.source_id, order_by=(other.title, other.id))
                .label("rn"),
            )
            .join(other, other.id == Edge.target_id)
            .where(
                Edge.user_id == self._user_id,
                Edge.source_id.in_(task_ids),
                Edge.type == DEPENDS_ON,
                Edge.state == CONFIRMED_STATE,
                other.user_id == self._user_id,
                other.kind == "task",
                other.state != REJECTED_STATE,
                object_is_active(other),
                or_(
                    other.status.is_(None),
                    other.status.notin_(tuple(TERMINAL_TASK_STATUSES_FOR_READS)),
                ),
            )
            .subquery()
        )
        rows = self._session.execute(
            select(ranked.c.source_id, ranked.c.target_id, ranked.c.title, ranked.c.status)
            .where(ranked.c.rn <= MAX_PROFILE_ITEMS)
            .order_by(ranked.c.source_id, ranked.c.title, ranked.c.target_id)
        ).all()
        grouped: dict[UUID, list[OperationalDependency]] = {}
        for source_id, target_id, title, status in rows:
            grouped.setdefault(source_id, []).append(
                OperationalDependency(task_id=target_id, title=title, status=status)
            )
        return {source_id: tuple(items) for source_id, items in grouped.items()}

    def _people(self, task_ids: list[UUID], role: str) -> dict[UUID, tuple[OperationalPerson, ...]]:
        if not task_ids:
            return {}
        other = aliased(Object)
        ranked = (
            select(
                Edge.source_id.label("source_id"),
                other.id.label("person_id"),
                other.title.label("title"),
                func.row_number()
                .over(partition_by=Edge.source_id, order_by=(other.title, other.id))
                .label("rn"),
            )
            .join(other, other.id == Edge.target_id)
            .where(
                Edge.user_id == self._user_id,
                Edge.source_id.in_(task_ids),
                Edge.type == role,
                Edge.state == CONFIRMED_STATE,
                other.user_id == self._user_id,
                other.kind == "person",
                other.state != REJECTED_STATE,
                object_is_active(other),
            )
            .subquery()
        )
        rows = self._session.execute(
            select(ranked.c.source_id, ranked.c.person_id, ranked.c.title)
            .where(ranked.c.rn <= MAX_PROFILE_ITEMS)
            .order_by(ranked.c.source_id, ranked.c.title, ranked.c.person_id)
        ).all()
        grouped: dict[UUID, list[OperationalPerson]] = {}
        for source_id, person_id, title in rows:
            grouped.setdefault(source_id, []).append(
                OperationalPerson(person_id=person_id, title=title)
            )
        return {source_id: tuple(items) for source_id, items in grouped.items()}
