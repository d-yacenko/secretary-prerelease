from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.connectors.teams.constants import TEAMS_KIND, TEAMS_PROVIDER
from app.connectors.teams.normalize import merge_quoted_message_provenance, normalize_teams_message
from app.db.models import Object
from app.domain.object_visibility import passive_sync_should_skip_existing
from app.services.communication_media_service import CommunicationMediaService
from app.services.pipeline_enqueue import enqueue_embed_object


@dataclass(frozen=True)
class TeamsMaterializeResult:
    obj: Object | None
    change: str
    jobs_enqueued: int


class TeamsObjectMaterializer:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_existing(self, user_id: UUID, external_id: str) -> Object | None:
        return self._session.scalar(
            select(Object).where(
                Object.user_id == user_id,
                Object.provider == TEAMS_PROVIDER,
                Object.kind == TEAMS_KIND,
                Object.external_id == external_id,
            )
        )

    def upsert_message(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
        tenant_id: str,
        microsoft_user_id: str,
        chat_id: str,
        chat_type: str,
        chat_display_title: str | None,
        message: dict[str, Any],
        skip_hidden: bool = True,
        frozen_quoted_message_id: str | None = None,
    ) -> TeamsMaterializeResult:
        normalized = normalize_teams_message(
            message=message,
            account_id=account_id,
            tenant_id=tenant_id,
            microsoft_user_id=microsoft_user_id,
            chat_id=chat_id,
            chat_type=chat_type,
            chat_display_title=chat_display_title,
            frozen_quoted_message_id=frozen_quoted_message_id,
        )
        if normalized is None:
            return TeamsMaterializeResult(obj=None, change="unchanged", jobs_enqueued=0)

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
        self._attach_media(obj)
        return TeamsMaterializeResult(obj=obj, change="created", jobs_enqueued=1)

    def _apply_existing(
        self,
        existing: Object,
        normalized: dict[str, Any],
        *,
        skip_hidden: bool,
    ) -> TeamsMaterializeResult:
        if skip_hidden and passive_sync_should_skip_existing(existing):
            return TeamsMaterializeResult(obj=existing, change="unchanged", jobs_enqueued=0)
        incoming_meta = dict(normalized["metadata"])
        existing_meta = dict(existing.metadata_ or {})
        incoming_meta["quoted_message_id"] = merge_quoted_message_provenance(
            existing_meta.get("quoted_message_id"),
            incoming_meta.get("quoted_message_id"),
        )
        semantic_changed = (
            existing.title != normalized["title"]
            or (existing.body or "") != (normalized.get("body") or "")
        )
        existing.title = normalized["title"]
        existing.body = normalized.get("body")
        existing.metadata_ = incoming_meta
        existing.occurred_at = normalized.get("occurred_at")
        self._session.flush()
        self._attach_media(existing)
        if semantic_changed:
            self._enqueue_embed(existing)
            return TeamsMaterializeResult(obj=existing, change="updated", jobs_enqueued=1)
        return TeamsMaterializeResult(obj=existing, change="unchanged", jobs_enqueued=0)

    def _attach_media(self, obj: Object) -> None:
        CommunicationMediaService(self._session, obj.user_id).materialize_stored(obj)

    def _enqueue_embed(self, obj: Object) -> None:
        enqueue_embed_object(self._session, obj.id, obj.user_id)
