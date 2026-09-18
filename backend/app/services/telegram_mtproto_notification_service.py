"""Deterministic notifications for canonical Telegram MTProto events."""

from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import Notification, Object
from app.notifications.constants import NOTIFICATION_STATUS_NEW

TELEGRAM_MTPROTO_NOTIFICATION_NAMESPACE = UUID("8e0f28f1-2e15-4dd4-8e0f-7f7f5cf0e31f")
_PREVIEW_LIMIT = 500


class TelegramMtprotoNotificationPersistenceError(RuntimeError):
    """A local deterministic-event write failed and must abort the source path."""


class TelegramMtprotoTransportNotificationService:
    def __init__(self, session) -> None:
        self._session = session

    def message_created(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
        peer_id: int,
        message_id: int,
        obj: Object,
        occurred_at: datetime,
        conversation_title: str,
    ) -> Notification:
        return self._create(
            user_id=user_id,
            account_id=account_id,
            peer_id=peer_id,
            event_type="message_created",
            event_key=_event_key(account_id, peer_id, message_id, "created"),
            title=f"Telegram · {conversation_title}",
            body=_preview(obj.body),
            source_object_id=obj.id,
            payload={
                "message_id": message_id,
                "object_id": str(obj.id),
                "occurred_at": occurred_at.isoformat(),
                "conversation_title": conversation_title,
            },
        )

    def message_edited(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
        peer_id: int,
        message_id: int,
        obj: Object,
        occurred_at: datetime,
        edited_at: datetime,
        conversation_title: str,
    ) -> Notification:
        return self._create(
            user_id=user_id,
            account_id=account_id,
            peer_id=peer_id,
            event_type="message_edited",
            event_key=_event_key(
                account_id, peer_id, message_id, f"edited:{edited_at.isoformat()}"
            ),
            title=f"Telegram · message edited · {conversation_title}",
            body=_preview(obj.body),
            source_object_id=obj.id,
            payload={
                "message_id": message_id,
                "object_id": str(obj.id),
                "occurred_at": occurred_at.isoformat(),
                "edited_at": edited_at.isoformat(),
                "conversation_title": conversation_title,
            },
        )

    def message_deleted(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
        peer_id: int,
        message_id: int,
        obj: Object,
        occurred_at: datetime,
        conversation_title: str,
    ) -> Notification:
        return self._create(
            user_id=user_id,
            account_id=account_id,
            peer_id=peer_id,
            event_type="message_deleted",
            event_key=_event_key(account_id, peer_id, message_id, "deleted"),
            title=f"Telegram · message deleted · {conversation_title}",
            body="Message deleted",
            source_object_id=obj.id,
            payload={
                "message_id": message_id,
                "object_id": str(obj.id),
                "occurred_at": occurred_at.isoformat(),
                "conversation_title": conversation_title,
            },
        )

    def _create(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
        peer_id: int,
        event_type: str,
        event_key: str,
        title: str,
        body: str | None,
        source_object_id: UUID | None,
        payload: dict,
    ) -> Notification:
        notification_id = uuid5(
            TELEGRAM_MTPROTO_NOTIFICATION_NAMESPACE, f"{user_id}:{event_key}"
        )
        try:
            existing = self._session.scalar(
                select(Notification).where(
                    Notification.id == notification_id,
                    Notification.user_id == user_id,
                )
            )
        except Exception as exc:
            raise TelegramMtprotoNotificationPersistenceError(
                "Telegram transport notification persistence failed"
            ) from exc
        if existing is not None:
            return existing
        proposal = {
            "type": "transport_event",
            "provider": "telegram",
            "transport": "mtproto",
            "event_type": event_type,
            "event_key": event_key,
            "account_id": str(account_id),
            "peer_id": peer_id,
            "message_id": payload["message_id"],
            "object_id": payload["object_id"],
            "occurred_at": payload["occurred_at"],
            "conversation_title": payload["conversation_title"],
        }
        if "edited_at" in payload:
            proposal["edited_at"] = payload["edited_at"]
        notification = Notification(
            id=notification_id,
            user_id=user_id,
            title=title[:500],
            body=body[:_PREVIEW_LIMIT] if body else body,
            priority="normal",
            status=NOTIFICATION_STATUS_NEW,
            source_object_id=source_object_id,
            related_object_id=None,
            result_object_id=None,
            proposal_=proposal,
        )
        nested = self._session.begin_nested()
        try:
            self._session.add(notification)
            self._session.flush()
            nested.commit()
        except IntegrityError:
            nested.rollback()
            try:
                existing = self._session.get(Notification, notification_id)
            except Exception as exc:
                raise TelegramMtprotoNotificationPersistenceError(
                    "Telegram transport notification persistence failed"
                ) from exc
            if existing is None:
                raise TelegramMtprotoNotificationPersistenceError(
                    "Telegram transport notification conflict could not be recovered"
                )
            return existing
        except Exception as exc:
            nested.rollback()
            raise TelegramMtprotoNotificationPersistenceError(
                "Telegram transport notification persistence failed"
            ) from exc
        return notification


def _event_key(account_id: UUID, peer_id: int, message_id: int, suffix: str) -> str:
    return f"telegram:mtproto:{account_id}:{peer_id}:{message_id}:{suffix}"


def _preview(body: str | None) -> str | None:
    if body is None:
        return None
    return body[:_PREVIEW_LIMIT]
