"""Bounded Task Profile shared by the first-party UI and Assistant/MCP.

The profile reports explicit edges only. Generic related_to is not an actor role.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, aliased

from app.api.schemas import (
    ObjectOut,
    TaskActorOut,
    TaskLinkOut,
    TaskOperationalDependencyOut,
    TaskOperationalOut,
    TaskOperationalPersonOut,
    TaskProfileOut,
)
from app.db.models import Edge, Object, PersonIdentity, PersonIdentityEvidence
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.person_candidate_score import USER_REJECTED
from app.domain.task_relations import (
    DELEGATED_TO,
    DEPENDS_ON,
    INVOLVES,
    MAX_PROFILE_ITEMS,
    REFERENCES,
    REQUESTED_BY,
    WAITING_ON,
)
from app.services.errors import NotFoundError
from app.services.provenance import REJECTED_STATE
from app.services.task_operational_projection_service import TaskOperationalProjectionService


class TaskProfileService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def get_profile(self, task_id: UUID) -> TaskProfileOut:
        task = self._session.get(Object, task_id)
        if (
            task is None
            or task.user_id != self._user_id
            or task.kind != "task"
            or task.state == REJECTED_STATE
            or is_object_hidden_from_active_reads(task)
        ):
            raise NotFoundError("task", task_id)
        requested, requested_truncated = self._actors(task.id, REQUESTED_BY)
        delegated, delegated_truncated = self._actors(task.id, DELEGATED_TO)
        waiting, waiting_truncated = self._actors(task.id, WAITING_ON)
        involved, involved_truncated = self._actors(task.id, INVOLVES)
        dependencies, dependencies_truncated = self._links(task.id, DEPENDS_ON, outgoing=True, kind="task")
        dependents, dependents_truncated = self._links(task.id, DEPENDS_ON, outgoing=False, kind="task")
        evidence, evidence_truncated = self._links(task.id, REFERENCES, outgoing=True, kind=None)
        return TaskProfileOut(
            task=ObjectOut.from_model(task),
            status=task.status,
            start_at=task.start_at,
            due_at=task.due_at,
            planned_start_at=task.planned_start_at,
            planned_end_at=task.planned_end_at,
            requested_by=requested,
            delegated_to=delegated,
            waiting_on=waiting,
            involves=involved,
            depends_on=dependencies,
            dependent_tasks=dependents,
            evidence=evidence,
            operational=self._operational(task),
            requested_by_truncated=requested_truncated,
            delegated_to_truncated=delegated_truncated,
            waiting_on_truncated=waiting_truncated,
            involves_truncated=involved_truncated,
            depends_on_truncated=dependencies_truncated,
            dependent_tasks_truncated=dependents_truncated,
            evidence_truncated=evidence_truncated,
        )

    def _operational(self, task: Object) -> TaskOperationalOut:
        projection = TaskOperationalProjectionService(self._session, self._user_id).project(task)
        return TaskOperationalOut(
            operational_state=projection.operational_state,
            is_overdue=projection.is_overdue,
            is_scheduled_later=projection.is_scheduled_later,
            is_planned_now=projection.is_planned_now,
            due_at=projection.due_at,
            planned_start_at=projection.planned_start_at,
            planned_end_at=projection.planned_end_at,
            blocking_dependencies=[
                TaskOperationalDependencyOut(task_id=item.task_id, title=item.title, status=item.status)
                for item in projection.blocking_dependencies
            ],
            waiting_on=[
                TaskOperationalPersonOut(person_id=item.person_id, title=item.title)
                for item in projection.waiting_on
            ],
            delegated_to=[
                TaskOperationalPersonOut(person_id=item.person_id, title=item.title)
                for item in projection.delegated_to
            ],
            reason_codes=list(projection.reason_codes),
        )

    def _actors(self, task_id: UUID, role: str) -> tuple[list[TaskActorOut], bool]:
        other = aliased(Object)
        rows = list(
            self._session.execute(
                self._edge_query(task_id, role, other, outgoing=True).where(other.kind == "person")
                .limit(MAX_PROFILE_ITEMS + 1)
            )
        )
        truncated = len(rows) > MAX_PROFILE_ITEMS
        visible = rows[:MAX_PROFILE_ITEMS]
        cues = self._contact_cues([person.id for _edge, person in visible])
        return [
            TaskActorOut(
                edge_id=edge.id,
                person_id=person.id,
                title=person.title,
                contact_cue=cues.get(person.id),
                edge_state=edge.state,
                edge_origin=edge.origin,
                edge_confidence=edge.confidence,
            )
            for edge, person in visible
        ], truncated

    def _links(
        self,
        task_id: UUID,
        edge_type: str,
        *,
        outgoing: bool,
        kind: str | None,
    ) -> tuple[list[TaskLinkOut], bool]:
        other = aliased(Object)
        stmt = self._edge_query(task_id, edge_type, other, outgoing=outgoing)
        if kind is not None:
            stmt = stmt.where(other.kind == kind)
        rows = list(self._session.execute(stmt.limit(MAX_PROFILE_ITEMS + 1)))
        truncated = len(rows) > MAX_PROFILE_ITEMS
        visible = rows[:MAX_PROFILE_ITEMS]
        return [
            TaskLinkOut(
                edge_id=edge.id,
                object_id=obj.id,
                title=obj.title,
                kind=obj.kind,
                edge_state=edge.state,
                edge_origin=edge.origin,
                edge_confidence=edge.confidence,
            )
            for edge, obj in visible
        ], truncated

    def _edge_query(self, task_id: UUID, edge_type: str, other, *, outgoing: bool):
        if outgoing:
            linked = other.id == Edge.target_id
            anchor = Edge.source_id == task_id
        else:
            linked = other.id == Edge.source_id
            anchor = Edge.target_id == task_id
        return (
            select(Edge, other)
            .join(other, linked)
            .where(
                Edge.user_id == self._user_id,
                anchor,
                Edge.type == edge_type,
                Edge.state != REJECTED_STATE,
                other.user_id == self._user_id,
                other.state != REJECTED_STATE,
                object_is_active(other),
            )
            .order_by(func.lower(other.title), other.id)
        )

    def _contact_cues(self, person_ids: list[UUID]) -> dict[UUID, str]:
        if not person_ids:
            return {}
        rows = self._session.scalars(
            select(PersonIdentity)
            .where(
                PersonIdentity.user_id == self._user_id,
                PersonIdentity.person_object_id.in_(person_ids),
                PersonIdentity.state != REJECTED_STATE,
                ~exists(
                    select(PersonIdentityEvidence.id).where(
                        PersonIdentityEvidence.user_id == PersonIdentity.user_id,
                        PersonIdentityEvidence.person_object_id == PersonIdentity.person_object_id,
                        PersonIdentityEvidence.state == "active",
                        PersonIdentityEvidence.evidence_type == USER_REJECTED,
                        PersonIdentityEvidence.provider == PersonIdentity.provider,
                        PersonIdentityEvidence.identity_type == PersonIdentity.identity_type,
                        PersonIdentityEvidence.realm == PersonIdentity.realm,
                        PersonIdentityEvidence.canonical_value == PersonIdentity.canonical_value,
                    )
                ),
            )
            .order_by(PersonIdentity.identity_type, PersonIdentity.canonical_value)
            .limit(MAX_PROFILE_ITEMS * 4)
        )
        cues: dict[UUID, str] = {}
        for row in rows:
            cues.setdefault(row.person_object_id, row.display_value or row.canonical_value)
        return cues
