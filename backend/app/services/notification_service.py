from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import Notification, Object
from app.notifications.constants import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    NOTIFICATION_FILTER_UNRESOLVED,
    NOTIFICATION_STATUS_ACCEPTED,
    NOTIFICATION_STATUS_IGNORED,
    NOTIFICATION_STATUS_NEW,
    NOTIFICATION_STATUS_READ,
    NOTIFICATION_STATUS_RESOLVED,
    NOTIFICATION_STATUSES,
)
from app.services.errors import NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.pipeline_enqueue import enqueue_embed_object


def utcnow() -> datetime:

    return datetime.now(UTC)


def _parse_optional_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


class NotificationService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._graph = GraphService(session, user_id)

    def create(
        self,
        title: str,
        body: str | None,
        priority: str,
        proposal: dict,
        source_object_id: UUID | None = None,
        related_object_id: UUID | None = None,
    ) -> Notification:
        from app.notifications.constants import NOTIFICATION_PRIORITIES

        if priority not in NOTIFICATION_PRIORITIES:
            raise ValidationError(f"invalid notification priority: {priority}")
        self._validate_object_link(source_object_id)
        self._validate_object_link(related_object_id)
        notification = Notification(
            user_id=self._user_id,
            title=title,
            body=body,
            priority=priority,
            status=NOTIFICATION_STATUS_NEW,
            source_object_id=source_object_id,
            related_object_id=related_object_id,
            proposal_=proposal,
        )
        self._session.add(notification)
        self._session.flush()
        return notification

    def _validate_object_link(self, object_id: UUID | None) -> None:
        if object_id is None:
            return
        owned = self._session.scalar(
            select(Object.id).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if owned is None:
            raise ValidationError("linked object does not belong to current user")

    def get(self, notification_id: UUID) -> Notification:
        notification = self._session.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == self._user_id,
            )
        )
        if notification is None:
            raise NotFoundError("notification", notification_id)
        return notification

    def list_notifications(
        self,
        status: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[Notification]:
        if (
            status is not None
            and status not in NOTIFICATION_STATUSES
            and status != NOTIFICATION_FILTER_UNRESOLVED
        ):
            raise ValidationError(f"invalid notification status: {status}")
        bounded_limit = max(1, min(limit, MAX_LIST_LIMIT))
        stmt = (
            select(Notification)
            .where(Notification.user_id == self._user_id)
            .order_by(
                Notification.created_at.desc(),
                Notification.id.desc(),
            )
        )
        if status == NOTIFICATION_FILTER_UNRESOLVED:
            stmt = stmt.where(
                Notification.status.in_((NOTIFICATION_STATUS_NEW, NOTIFICATION_STATUS_READ))
            )
        elif status is not None:
            stmt = stmt.where(Notification.status == status)
        stmt = stmt.limit(bounded_limit)
        return list(self._session.scalars(stmt))

    def mark_read(self, notification_id: UUID) -> Notification:
        notification = self.get(notification_id)
        if notification.status == NOTIFICATION_STATUS_NEW:
            notification.status = NOTIFICATION_STATUS_READ
        if notification.read_at is None:
            notification.read_at = utcnow()
        notification.updated_at = utcnow()
        self._session.flush()
        return notification

    def accept(self, notification_id: UUID) -> Notification:
        notification = self.get(notification_id)
        if notification.status in (
            NOTIFICATION_STATUS_IGNORED,
            NOTIFICATION_STATUS_RESOLVED,
        ):
            raise ValidationError("cannot accept ignored or resolved notification")

        proposal_type = notification.proposal_.get("type")
        if proposal_type == "task":
            return self._accept_task_proposal(notification)

        notification.status = NOTIFICATION_STATUS_ACCEPTED
        if notification.read_at is None:
            notification.read_at = utcnow()
        notification.updated_at = utcnow()
        self._session.flush()
        return notification

    def _accept_task_proposal(self, notification: Notification) -> Notification:
        if notification.result_object_id is not None:
            notification.status = NOTIFICATION_STATUS_ACCEPTED
            if notification.read_at is None:
                notification.read_at = utcnow()
            notification.updated_at = utcnow()
            self._session.flush()
            return notification

        if notification.status == NOTIFICATION_STATUS_ACCEPTED:
            pass
        elif notification.status not in (
            NOTIFICATION_STATUS_NEW,
            NOTIFICATION_STATUS_READ,
        ):
            raise ValidationError("cannot accept notification in current status")

        proposal = notification.proposal_
        title = proposal.get("title") or notification.title
        if not title:
            raise ValidationError("task proposal is missing title")

        body = proposal.get("description") or notification.body
        confidence = proposal.get("confidence")
        due_at = _parse_optional_datetime(proposal.get("due_at"))
        start_at = _parse_optional_datetime(proposal.get("start_at"))

        task = self._graph.create_object(
            ObjectCreate(
                kind="task",
                title=str(title),
                body=body,
                origin="agent",
                state="confirmed",
                due_at=due_at,
                start_at=start_at,
                confidence=confidence,
                metadata={"accepted_from_notification_id": str(notification.id)},
            )
        )

        if notification.source_object_id is not None:
            self._graph.create_edge(
                EdgeCreate(
                    source_id=task.id,
                    target_id=notification.source_object_id,
                    type="references",
                    origin="agent",
                    state="confirmed",
                    confidence=confidence,
                )
            )

        enqueue_embed_object(self._session, task.id, self._user_id)

        notification.result_object_id = task.id
        notification.status = NOTIFICATION_STATUS_ACCEPTED
        if notification.read_at is None:
            notification.read_at = utcnow()
        notification.updated_at = utcnow()
        self._session.flush()
        return notification

    def ignore(self, notification_id: UUID) -> Notification:
        notification = self.get(notification_id)
        notification.status = NOTIFICATION_STATUS_IGNORED
        if notification.read_at is None:
            notification.read_at = utcnow()
        notification.updated_at = utcnow()
        self._session.flush()
        return notification

    def resolve(self, notification_id: UUID) -> Notification:
        notification = self.get(notification_id)
        notification.status = NOTIFICATION_STATUS_RESOLVED
        if notification.read_at is None:
            notification.read_at = utcnow()
        notification.updated_at = utcnow()
        self._session.flush()
        return notification
