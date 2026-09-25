"""Materialize one canonical Task when a person accepts a task Notification.

Proposal ``start_at`` stays the legacy instant on ``Object.start_at``. It is not
a canonical planned execution interval and is not copied to ``planned_start_at``
or ``planned_end_at``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.schemas import ObjectCreate
from app.db.models import Notification, Object
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.domain.task_lifecycle import TASK_STATUS_OPEN
from app.notifications.constants import (
    NOTIFICATION_STATUS_ACCEPTED,
    NOTIFICATION_STATUS_NEW,
    NOTIFICATION_STATUS_READ,
)
from app.services.errors import ValidationError
from app.services.graph_service import GraphService
from app.services.pipeline_enqueue import enqueue_embed_object
from app.services.provenance import AGENT_ORIGIN, CONFIRMED_STATE, REJECTED_STATE
from app.services.task_relation_service import TaskRelationService


def utcnow() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


class TaskProposalAcceptanceService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def accept(self, notification: Notification) -> Notification:
        if notification.result_object_id is not None:
            self._require_existing_result(notification)
            return self._mark_accepted(notification)

        if notification.status not in (
            NOTIFICATION_STATUS_NEW,
            NOTIFICATION_STATUS_READ,
            NOTIFICATION_STATUS_ACCEPTED,
        ):
            raise ValidationError("cannot accept notification in current status")

        title, body, confidence, due_at, start_at = self._validated_fields(notification)
        evidence = self._validated_source(notification.source_object_id)
        with self._session.begin_nested():
            task = GraphService(self._session, self._user_id).create_object(
                ObjectCreate(
                    kind="task",
                    title=title,
                    body=body,
                    origin=AGENT_ORIGIN,
                    state=CONFIRMED_STATE,
                    status=TASK_STATUS_OPEN,
                    due_at=due_at,
                    start_at=start_at,
                    confidence=confidence,
                    metadata={"accepted_from_notification_id": str(notification.id)},
                )
            )
            if evidence is not None:
                TaskRelationService(self._session, self._user_id).attach_evidence(
                    task.id,
                    evidence.id,
                    origin=AGENT_ORIGIN,
                    state=CONFIRMED_STATE,
                    confidence=confidence,
                )
            enqueue_embed_object(self._session, task.id, self._user_id)
            notification.result_object_id = task.id
            self._mark_accepted(notification)
        return notification

    def _validated_fields(
        self, notification: Notification
    ) -> tuple[str, str | None, float | None, datetime | None, datetime | None]:
        proposal = notification.proposal_ or {}
        raw_title = proposal.get("title") or notification.title
        title = str(raw_title).strip() if raw_title is not None else ""
        if not title:
            raise ValidationError("task proposal is missing title")
        body = proposal.get("description")
        if body is None:
            body = notification.body
        confidence = _validated_confidence(proposal.get("confidence"))
        due_at = _parse_optional_datetime(proposal.get("due_at"))
        start_at = _parse_optional_datetime(proposal.get("start_at"))
        return title, body, confidence, due_at, start_at

    def _validated_source(self, object_id: UUID | None) -> Object | None:
        if object_id is None:
            return None
        evidence = self._session.get(Object, object_id)
        if (
            evidence is None
            or evidence.user_id != self._user_id
            or evidence.state == REJECTED_STATE
            or is_object_hidden_from_active_reads(evidence)
        ):
            raise ValidationError("task proposal source evidence is not available")
        if evidence.kind == "task":
            raise ValidationError("task evidence must not be another task")
        return evidence

    def _require_existing_result(self, notification: Notification) -> Object:
        result = self._session.get(Object, notification.result_object_id)
        anchor = None if result is None else (result.metadata_ or {}).get(
            "accepted_from_notification_id"
        )
        if (
            result is None
            or result.user_id != self._user_id
            or result.kind != "task"
            or anchor != str(notification.id)
        ):
            raise ValidationError("accepted task result is inconsistent")
        return result

    def _mark_accepted(self, notification: Notification) -> Notification:
        notification.status = NOTIFICATION_STATUS_ACCEPTED
        if notification.read_at is None:
            notification.read_at = utcnow()
        notification.updated_at = utcnow()
        self._session.flush()
        return notification


def _validated_confidence(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("invalid task proposal confidence")
    confidence = float(value)
    if confidence < 0.0 or confidence > 1.0:
        raise ValidationError("invalid task proposal confidence")
    return confidence


def _parse_optional_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValidationError("invalid task proposal datetime")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("invalid task proposal datetime") from exc
