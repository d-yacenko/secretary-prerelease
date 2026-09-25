"""Explicit Task actor roles, dependencies, and evidence references.

A confirmed active edge is the current fact. A later proposal does not add
another active row. An explicit confirmed write supersedes active proposals
by rejecting them and creating a new confirmed edge. Removal rejects the
edge and leaves the historical row in place.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import EdgeCreate
from app.db.models import Edge, Object
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.domain.task_relations import (
    DEPENDS_ON,
    REFERENCES,
    TASK_ACTOR_ROLES,
)
from app.services.errors import NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE, USER_ORIGIN


class TaskRelationService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._graph = GraphService(session, user_id)

    def add_actor(
        self,
        task_id: UUID,
        person_id: UUID,
        role: str,
        *,
        origin: str = USER_ORIGIN,
        state: str = CONFIRMED_STATE,
        confidence: float | None = None,
    ) -> tuple[Edge, bool]:
        if role not in TASK_ACTOR_ROLES:
            raise ValidationError("task actor role is unknown")
        task = self._require_active(task_id, kind="task")
        person = self._require_active(person_id, kind="person")
        return self._add_edge(task.id, person.id, role, origin=origin, state=state, confidence=confidence)

    def remove_actor(self, task_id: UUID, edge_id: UUID) -> tuple[Edge, bool]:
        return self._reject(task_id, edge_id, TASK_ACTOR_ROLES)

    def add_dependency(
        self,
        task_id: UUID,
        depends_on_task_id: UUID,
        *,
        origin: str = USER_ORIGIN,
        state: str = CONFIRMED_STATE,
        confidence: float | None = None,
    ) -> tuple[Edge, bool]:
        if task_id == depends_on_task_id:
            raise ValidationError("task cannot depend on itself")
        task = self._require_active(task_id, kind="task")
        dependency = self._require_active(depends_on_task_id, kind="task")
        return self._add_edge(
            task.id,
            dependency.id,
            DEPENDS_ON,
            origin=origin,
            state=state,
            confidence=confidence,
        )

    def remove_dependency(self, task_id: UUID, edge_id: UUID) -> tuple[Edge, bool]:
        return self._reject(task_id, edge_id, frozenset({DEPENDS_ON}))

    def attach_evidence(
        self,
        task_id: UUID,
        evidence_id: UUID,
        *,
        origin: str = USER_ORIGIN,
        state: str = CONFIRMED_STATE,
        confidence: float | None = None,
    ) -> tuple[Edge, bool]:
        if task_id == evidence_id:
            raise ValidationError("task cannot reference itself as evidence")
        task = self._require_active(task_id, kind="task")
        evidence = self._require_active_object(evidence_id)
        if evidence.kind == "task":
            raise ValidationError("task evidence must not be another task")
        return self._add_edge(
            task.id,
            evidence.id,
            REFERENCES,
            origin=origin,
            state=state,
            confidence=confidence,
        )

    def _add_edge(
        self,
        source_id: UUID,
        target_id: UUID,
        edge_type: str,
        *,
        origin: str,
        state: str,
        confidence: float | None,
    ) -> tuple[Edge, bool]:
        active = list(
            self._session.scalars(
                select(Edge)
                .where(
                    Edge.user_id == self._user_id,
                    Edge.source_id == source_id,
                    Edge.target_id == target_id,
                    Edge.type == edge_type,
                    Edge.state != REJECTED_STATE,
                )
                .order_by(Edge.id)
            )
        )
        confirmed = next((edge for edge in active if edge.state == CONFIRMED_STATE), None)
        if confirmed is not None:
            return confirmed, False
        if state != CONFIRMED_STATE and active:
            return active[0], False
        if state == CONFIRMED_STATE and active:
            for edge in active:
                edge.state = REJECTED_STATE
            self._session.flush()
        edge = self._graph.create_edge(
            EdgeCreate(
                source_id=source_id,
                target_id=target_id,
                type=edge_type,
                origin=origin,
                state=state,
                confidence=confidence,
            )
        )
        return edge, True

    def _reject(self, task_id: UUID, edge_id: UUID, allowed: frozenset[str]) -> tuple[Edge, bool]:
        self._require_active(task_id, kind="task")
        edge = self._session.scalar(
            select(Edge).where(Edge.id == edge_id, Edge.user_id == self._user_id)
        )
        if edge is None or edge.source_id != task_id or edge.type not in allowed:
            raise NotFoundError("edge", edge_id)
        if edge.state == REJECTED_STATE:
            return edge, False
        edge.state = REJECTED_STATE
        self._session.flush()
        return edge, True

    def ensure_active(self, object_id: UUID, *, kind: str) -> Object:
        return self._require_active(object_id, kind=kind)

    def _require_active(self, object_id: UUID, *, kind: str) -> Object:
        obj = self._require_active_object(object_id)
        if obj.kind != kind:
            raise ValidationError(f"task relation endpoint must be a {kind}")
        return obj

    def _require_active_object(self, object_id: UUID) -> Object:
        obj = self._session.get(Object, object_id)
        if (
            obj is None
            or obj.user_id != self._user_id
            or obj.state == REJECTED_STATE
            or is_object_hidden_from_active_reads(obj)
        ):
            raise NotFoundError("object", object_id)
        return obj
