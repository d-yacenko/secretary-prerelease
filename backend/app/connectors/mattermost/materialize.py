from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.connectors.mattermost.normalize import (
    MattermostChannelContext,
    normalize_mattermost_post,
)
from app.db.models import Object
from app.domain.object_visibility import passive_sync_should_skip_existing
from app.services.pipeline_enqueue import enqueue_embed_object


@dataclass(frozen=True)
class MattermostMaterializeResult:
    obj: Object | None
    change: str
    jobs_enqueued: int


class MattermostObjectMaterializer:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_post(
        self,
        *,
        user_id: UUID,
        normalized_server_url: str,
        account_id: UUID,
        channel: MattermostChannelContext,
        post: dict[str, Any],
        author: dict[str, Any] | None,
        skip_hidden: bool = True,
    ) -> MattermostMaterializeResult:
        normalized = normalize_mattermost_post(
            post=post,
            normalized_server_url=normalized_server_url,
            account_id=account_id,
            channel=channel,
            author=author,
        )
        if normalized is None:
            return MattermostMaterializeResult(obj=None, change="unchanged", jobs_enqueued=0)

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
        return MattermostMaterializeResult(obj=obj, change="created", jobs_enqueued=1)

    def find_existing(self, user_id: UUID, external_id: str) -> Object | None:
        return self._session.scalar(
            select(Object).where(
                Object.user_id == user_id,
                Object.provider == "mattermost",
                Object.kind == "chat_message",
                Object.external_id == external_id,
            )
        )

    def find_by_pending_post_id(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
        channel_id: str,
        pending_post_id: str,
    ) -> Object | None:
        matches: list[Object] = []
        rows = self._session.scalars(
            select(Object).where(
                Object.user_id == user_id,
                Object.provider == "mattermost",
                Object.kind == "chat_message",
                Object.metadata_["pending_post_id"].as_string() == pending_post_id,
            )
        )
        for obj in rows:
            meta = dict(obj.metadata_ or {})
            if str(meta.get("channel_id") or "") != channel_id:
                continue
            if str(meta.get("account_id") or "") != str(account_id):
                continue
            matches.append(obj)
        if len(matches) != 1:
            return None
        return matches[0]

    def _apply_existing(
        self,
        existing: Object,
        normalized: dict[str, Any],
        *,
        skip_hidden: bool,
    ) -> MattermostMaterializeResult:
        if skip_hidden and passive_sync_should_skip_existing(existing):
            return MattermostMaterializeResult(obj=existing, change="unchanged", jobs_enqueued=0)
        object_changed = self._object_changed(existing, normalized)
        if not object_changed:
            return MattermostMaterializeResult(obj=existing, change="unchanged", jobs_enqueued=0)
        semantic_changed = self._semantic_content_changed(existing, normalized)
        self._apply_normalized(existing, normalized)
        if semantic_changed:
            self._enqueue_embed(existing)
            return MattermostMaterializeResult(obj=existing, change="updated", jobs_enqueued=1)
        return MattermostMaterializeResult(obj=existing, change="metadata_updated", jobs_enqueued=0)

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
