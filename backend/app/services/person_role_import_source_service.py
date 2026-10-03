"""Owned, already-stored sources for role-import extraction."""

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Object, Representation
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.local.errors import LocalAccessError, LocalPathError
from app.resources.constants import MAX_UPLOAD_BYTES, PROVIDER_UPLOAD, RASTER_UPLOAD_SUFFIXES
from app.resources.raster_signatures import header_matches_suffix, mime_type_for_suffix
from app.resources.upload_paths import validate_object_upload_path
from app.services.errors import NotFoundError, ValidationError
from app.services.provenance import REJECTED_STATE
from app.services.representation_service import KIND_CHUNK, KIND_FULL

ROLE_IMPORT_MAX_SOURCE_TEXT_CHARS = 24000

_IMAGE_UNAVAILABLE = "uploaded image is not available"
_IMAGE_CHECK_FAILED = "uploaded image failed content check"
_TEXT_UNAVAILABLE = "source has no stored text"


@dataclass(frozen=True)
class RoleImportSource:
    object_id: UUID
    source_kind: str
    source_revision: str
    source_truncated: bool
    image_bytes: bytes | None
    mime_type: str | None
    text: str | None


class PersonRoleImportSourceService:
    def __init__(self, session: Session, user_id: UUID, upload_root) -> None:
        self._session = session
        self._user_id = user_id
        self._upload_root = upload_root

    def load(self, object_id: UUID) -> RoleImportSource:
        obj = self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if (
            obj is None
            or is_object_hidden_from_active_reads(obj)
            or obj.state == REJECTED_STATE
        ):
            raise NotFoundError("object", object_id)
        if self._is_raster_upload(obj):
            return self._load_raster(obj)
        return self._load_text(obj)

    def _is_raster_upload(self, obj: Object) -> bool:
        if obj.provider != PROVIDER_UPLOAD:
            return False
        metadata = obj.metadata_ or {}
        filename = str(metadata.get("upload_filename") or "")
        suffix = _suffix(filename) or _suffix(str(metadata.get("upload_path") or ""))
        return suffix in RASTER_UPLOAD_SUFFIXES

    def _load_raster(self, obj: Object) -> RoleImportSource:
        metadata = obj.metadata_ or {}
        raw_path = metadata.get("upload_path")
        if not isinstance(raw_path, str):
            raise ValidationError(_IMAGE_UNAVAILABLE)
        filename = str(metadata.get("upload_filename") or raw_path)
        suffix = _suffix(filename) or _suffix(raw_path)
        if suffix not in RASTER_UPLOAD_SUFFIXES:
            raise ValidationError(_IMAGE_CHECK_FAILED)
        try:
            path = validate_object_upload_path(
                self._upload_root, self._user_id, obj.id, raw_path
            )
        except (LocalPathError, LocalAccessError) as exc:
            raise ValidationError(_IMAGE_UNAVAILABLE) from exc
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            raise ValidationError(_IMAGE_CHECK_FAILED)
        image_bytes = path.read_bytes()
        if not header_matches_suffix(suffix, image_bytes[:16]):
            raise ValidationError(_IMAGE_CHECK_FAILED)
        digest = hashlib.sha256(image_bytes).hexdigest()
        stored_hash = metadata.get("content_hash")
        if not isinstance(stored_hash, str) or stored_hash != digest:
            raise ValidationError(_IMAGE_CHECK_FAILED)
        return RoleImportSource(
            object_id=obj.id,
            source_kind="image",
            source_revision=digest,
            source_truncated=False,
            image_bytes=image_bytes,
            mime_type=mime_type_for_suffix(suffix),
            text=None,
        )

    def _load_text(self, obj: Object) -> RoleImportSource:
        text, truncated = _bounded_text(self._collect_text(obj))
        if text is None:
            raise ValidationError(_TEXT_UNAVAILABLE)
        revision = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return RoleImportSource(
            object_id=obj.id,
            source_kind="text",
            source_revision=revision,
            source_truncated=truncated,
            image_bytes=None,
            mime_type=None,
            text=text,
        )

    def _collect_text(self, obj: Object) -> str | None:
        full_rows = self._session.scalars(
            select(Representation)
            .where(Representation.object_id == obj.id, Representation.kind == KIND_FULL)
            .order_by(Representation.part_index.asc().nulls_last(), Representation.id.asc())
        ).all()
        for row in full_rows:
            if row.text:
                return row.text
        chunk_rows = self._session.scalars(
            select(Representation)
            .where(Representation.object_id == obj.id, Representation.kind == KIND_CHUNK)
            .order_by(Representation.part_index.asc().nulls_last(), Representation.id.asc())
        ).all()
        parts = [row.text for row in chunk_rows if row.text]
        if parts:
            return "\n".join(parts)
        if obj.body:
            return obj.body
        return None


def _bounded_text(text: str | None) -> tuple[str | None, bool]:
    if text is None:
        return None, False
    if len(text) <= ROLE_IMPORT_MAX_SOURCE_TEXT_CHARS:
        return text, False
    return text[:ROLE_IMPORT_MAX_SOURCE_TEXT_CHARS], True


def _suffix(name: str) -> str:
    dot = name.rfind(".")
    if dot < 0:
        return ""
    return name[dot:].lower()
