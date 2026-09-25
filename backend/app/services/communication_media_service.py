"""Materialize provider-neutral media child Objects for a communication parent."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import EdgeCreate
from app.db.models import Object
from app.domain.communication_media import (
    CommunicationMediaDescriptor,
    parse_stored_descriptor,
    safe_descriptor,
)
from app.services.correlation_constants import EDGE_TYPE_CONTAINS
from app.services.edge_dedup import has_equivalent_relation
from app.services.errors import NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.provenance import OBSERVED_STATE, SOURCE_ORIGIN


def build_media_external_id(provider: str, parent_external_id: str, descriptor_key: str) -> str:
    return f"{provider}:media:{parent_external_id}:{descriptor_key}"


class CommunicationMediaService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._graph = GraphService(session, user_id)

    def materialize_stored(self, parent: Object) -> list[Object]:
        raw = (parent.metadata_ or {}).get("media_descriptors")
        if not isinstance(raw, list):
            return []
        descriptors = [
            parsed
            for item in raw
            if (parsed := parse_stored_descriptor(parent.provider or "", item)) is not None
        ]
        if not descriptors:
            return []
        return self.materialize(parent, descriptors)

    def materialize(
        self,
        parent: Object,
        descriptors: list[CommunicationMediaDescriptor],
    ) -> list[Object]:
        if parent.user_id != self._user_id:
            raise NotFoundError("object", parent.id)
        if not parent.external_id:
            raise ValidationError("communication media parent has no external id")
        children: list[Object] = []
        seen: set[str] = set()
        for descriptor in descriptors:
            safe = safe_descriptor(descriptor)
            if safe is None or safe.provider != parent.provider or safe.descriptor_key in seen:
                continue
            seen.add(safe.descriptor_key)
            children.append(self._upsert_child(parent, safe))
        return children

    def _upsert_child(self, parent: Object, descriptor: CommunicationMediaDescriptor) -> Object:
        external_id = build_media_external_id(
            parent.provider or descriptor.provider,
            parent.external_id or "",
            descriptor.descriptor_key,
        )
        metadata = {
            "parent_communication_id": str(parent.id),
            "provider": parent.provider,
            "descriptor_key": descriptor.descriptor_key,
            "media_kind": descriptor.media_kind,
            "provider_media_id": descriptor.provider_media_id,
            "filename": descriptor.filename,
            "mime_type": descriptor.mime_type,
            "size": descriptor.size,
            "duration_seconds": descriptor.duration_seconds,
            "provenance": descriptor.provenance or {},
        }
        existing = self._session.scalar(
            select(Object).where(
                Object.user_id == self._user_id,
                Object.provider == parent.provider,
                Object.kind == "file",
                Object.external_id == external_id,
            )
        )
        title = descriptor.filename or descriptor.media_kind
        if existing is None:
            child = Object(
                user_id=self._user_id,
                kind="file",
                title=title,
                body=None,
                origin=SOURCE_ORIGIN,
                state=OBSERVED_STATE,
                provider=parent.provider,
                external_id=external_id,
                metadata_=metadata,
                occurred_at=parent.occurred_at,
            )
            self._session.add(child)
            self._session.flush()
        else:
            child = existing
            child.title = title
            child.body = None
            child.metadata_ = metadata
            child.occurred_at = parent.occurred_at
            self._session.flush()
        self._link_contains(parent.id, child.id)
        from app.services.communication_media_jobs import maybe_enqueue_media_transcription

        maybe_enqueue_media_transcription(self._session, parent, child)
        return child

    def _link_contains(self, parent_id: UUID, child_id: UUID) -> None:
        if has_equivalent_relation(
            self._session, self._user_id, parent_id, child_id, EDGE_TYPE_CONTAINS
        ):
            return
        self._graph.create_edge(
            EdgeCreate(
                source_id=parent_id,
                target_id=child_id,
                type=EDGE_TYPE_CONTAINS,
                origin=SOURCE_ORIGIN,
                state=OBSERVED_STATE,
                metadata={"source_fact": "communication_media"},
            )
        )
