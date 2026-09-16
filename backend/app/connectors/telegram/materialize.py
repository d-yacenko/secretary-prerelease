from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.connectors.telegram.constants import TELEGRAM_KIND, TELEGRAM_PROVIDER
from app.connectors.telegram.normalize import (
    build_external_id,
    normalize_telegram_business_message,
)
from app.db.models import Object
from app.domain.object_visibility import passive_sync_should_skip_existing, tombstone_object
from app.services.pipeline_enqueue import enqueue_embed_object


@dataclass(frozen=True)
class TelegramMaterializeResult:
    obj: Object | None
    change: str
    jobs_enqueued: int


class TelegramObjectMaterializer:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_business_message(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
        business_connection_id: str,
        business_user_id: str,
        message: dict[str, Any],
        skip_hidden: bool = True,
    ) -> TelegramMaterializeResult:
        normalized = normalize_telegram_business_message(
            message=message,
            account_id=account_id,
            business_connection_id=business_connection_id,
            business_user_id=business_user_id,
        )
        if normalized is None:
            return TelegramMaterializeResult(obj=None, change="unchanged", jobs_enqueued=0)

        existing = self.find_existing(user_id, normalized["external_id"])
        if existing is not None:
            return self._apply_existing(existing, normalized, skip_hidden=skip_hidden)

        nested = self._session.begin_nested()
        try:
            obj = Object(
                user_id=user_id,
                kind=normalized["kind"],
                provider=normalized["provider"],
                external_id=normalized["external_id"],
                origin=normalized["origin"],
                state=normalized["state"],
                title=normalized["title"],
                body=normalized.get("body"),
                metadata_=normalized["metadata"],
                occurred_at=normalized.get("occurred_at"),
            )
            self._session.add(obj)
            self._session.flush()
            nested.commit()
        except IntegrityError:
            nested.rollback()
            existing = self.find_existing(user_id, normalized["external_id"])
            if existing is None:
                raise
            return self._apply_existing(existing, normalized, skip_hidden=skip_hidden)

        self._enqueue_embed(obj)
        return TelegramMaterializeResult(obj=obj, change="created", jobs_enqueued=1)

    def hide_deleted_messages(
        self,
        *,
        user_id: UUID,
        business_connection_id: str,
        chat_id: str,
        message_ids: list[str],
    ) -> int:
        hidden = 0
        for message_id in message_ids:
            existing = self.find_existing(
                user_id,
                build_external_id(business_connection_id, chat_id, message_id),
            )
            if existing is None:
                continue
            if tombstone_object(existing):
                hidden += 1
        if hidden:
            self._session.flush()
        return hidden

    def find_existing(self, user_id: UUID, external_id: str) -> Object | None:
        return self._session.scalar(
            select(Object).where(
                Object.user_id == user_id,
                Object.provider == TELEGRAM_PROVIDER,
                Object.kind == TELEGRAM_KIND,
                Object.external_id == external_id,
            )
        )

    def _apply_existing(
        self,
        existing: Object,
        normalized: dict[str, Any],
        *,
        skip_hidden: bool,
    ) -> TelegramMaterializeResult:
        if skip_hidden and passive_sync_should_skip_existing(existing):
            return TelegramMaterializeResult(obj=existing, change="unchanged", jobs_enqueued=0)
        object_changed = self._object_changed(existing, normalized)
        if not object_changed:
            return TelegramMaterializeResult(obj=existing, change="unchanged", jobs_enqueued=0)
        semantic_changed = self._semantic_content_changed(existing, normalized)
        self._apply_normalized(existing, normalized)
        self._session.flush()
        if semantic_changed:
            self._enqueue_embed(existing)
            return TelegramMaterializeResult(obj=existing, change="updated", jobs_enqueued=1)
        return TelegramMaterializeResult(obj=existing, change="metadata_updated", jobs_enqueued=0)

    @staticmethod
    def _object_changed(obj: Object, normalized: dict[str, Any]) -> bool:
        if obj.title != normalized["title"]:
            return True
        if obj.body != normalized.get("body"):
            return True
        if obj.occurred_at != normalized.get("occurred_at"):
            return True
        return obj.metadata_ != normalized["metadata"]

    @staticmethod
    def _semantic_content_changed(obj: Object, normalized: dict[str, Any]) -> bool:
        if obj.title != normalized["title"]:
            return True
        return obj.body != normalized.get("body")

    @staticmethod
    def _apply_normalized(obj: Object, normalized: dict[str, Any]) -> None:
        obj.title = normalized["title"]
        obj.body = normalized.get("body")
        obj.metadata_ = normalized["metadata"]
        obj.occurred_at = normalized.get("occurred_at")

    def _enqueue_embed(self, obj: Object) -> None:
        enqueue_embed_object(self._session, obj.id, obj.user_id)
