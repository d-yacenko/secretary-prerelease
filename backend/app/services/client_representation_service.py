"""Validate and persist client-extracted mechanical representations."""

from pathlib import Path
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import Representation
from app.services.client_intake_constants import (
    CLIENT_REP_METADATA_ALLOWLIST,
    CLIENT_REPRESENTATION_KINDS,
    DATASET_FILE_SUFFIXES,
    DATASET_REPRESENTATION_KINDS,
    DOCUMENT_FILE_SUFFIXES,
    DOCUMENT_REPRESENTATION_KINDS,
    LEGACY_METADATA_ONLY_SUFFIXES,
    MAX_CLIENT_REPRESENTATION_PART_BYTES,
    MAX_CLIENT_REPRESENTATION_PARTS,
    MAX_CLIENT_REPRESENTATION_TOTAL_BYTES,
    MAX_SAMPLED_ROW_INDICES,
    ALLOWED_DATASET_SAMPLING_MODES,
    UNSUPPORTED_INDEX_SUFFIXES,
)
from app.services.errors import ValidationError
from app.services.representation_service import RepresentationService


def _utf8_byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _require_non_negative_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"client representation metadata invalid type: {name}")
    if value < 0:
        raise ValidationError(f"client representation metadata invalid value: {name}")
    return value


def _require_bool(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"client representation metadata invalid type: {name}")
    return value


def _normalize_sampled_row_indices(value: object) -> list[int]:
    if not isinstance(value, list):
        raise ValidationError("client representation metadata invalid type: sampled_row_indices")
    if len(value) > MAX_SAMPLED_ROW_INDICES:
        raise ValidationError("client representation metadata exceeds sampled_row_indices limit")
    normalized: list[int] = []
    seen: set[int] = set()
    for item in value:
        index = _require_non_negative_int("sampled_row_indices", item)
        if index not in seen:
            seen.add(index)
            normalized.append(index)
    normalized.sort()
    return normalized


def _normalize_rep_metadata(metadata: dict) -> dict:
    if not metadata:
        return {}
    normalized: dict = {}
    for key, value in metadata.items():
        if key not in CLIENT_REP_METADATA_ALLOWLIST:
            raise ValidationError(f"client representation metadata not allowed: {key}")
        if key == "source_chunk_index":
            normalized[key] = _require_non_negative_int(key, value)
        elif key in {
            "truncated",
            "page_truncated",
            "compact_preview",
            "dataset_sampling_truncated",
            "stats_truncated",
        }:
            normalized[key] = _require_bool(key, value)
        elif key in {
            "page_count",
            "slide_count",
            "sheet_count",
            "dataset_row_count",
            "dataset_rows_represented",
            "row_count_in_sample",
            "row_count",
            "rows_sampled",
            "column_count",
        }:
            normalized[key] = _require_non_negative_int(key, value)
        elif key == "dataset_sampling_mode":
            mode = str(value).strip()
            if mode not in ALLOWED_DATASET_SAMPLING_MODES:
                raise ValidationError(
                    "client representation metadata invalid value: dataset_sampling_mode"
                )
            normalized[key] = mode
        elif key == "sampled_row_indices":
            normalized[key] = _normalize_sampled_row_indices(value)
        else:
            raise ValidationError(f"client representation metadata not allowed: {key}")
    return normalized


class ClientRepresentationValidator:
    def validate_payload(
        self,
        filename: str,
        representations: list[dict],
        metadata_only: bool,
    ) -> list[dict]:
        suffix = Path(filename).suffix.lower()
        if metadata_only:
            if representations:
                raise ValidationError("metadata_only intake cannot include representations")
            return []

        if suffix in LEGACY_METADATA_ONLY_SUFFIXES:
            raise ValidationError("legacy file format requires metadata_only intake")

        if suffix in UNSUPPORTED_INDEX_SUFFIXES or suffix not in (
            DOCUMENT_FILE_SUFFIXES | DATASET_FILE_SUFFIXES
        ):
            raise ValidationError("unsupported file format requires metadata_only intake")

        if len(representations) > MAX_CLIENT_REPRESENTATION_PARTS:
            raise ValidationError("client representations exceed max parts")

        allowed_kinds = (
            DOCUMENT_REPRESENTATION_KINDS
            if suffix in DOCUMENT_FILE_SUFFIXES
            else DATASET_REPRESENTATION_KINDS
        )

        seen_indices: set[int] = set()
        seen_singleton_kinds: set[str] = set()
        total_bytes = 0
        normalized: list[dict] = []

        for item in representations:
            kind = str(item.get("kind", "")).strip()
            if kind not in CLIENT_REPRESENTATION_KINDS:
                raise ValidationError(f"client representation kind not allowed: {kind}")
            if kind not in allowed_kinds:
                raise ValidationError(
                    f"client representation kind {kind} not allowed for {suffix}"
                )
            if kind in {"full", "schema", "sample", "statistics"}:
                if kind in seen_singleton_kinds:
                    raise ValidationError(f"duplicate client representation kind: {kind}")
                seen_singleton_kinds.add(kind)

            text = str(item.get("text", ""))
            part_bytes = _utf8_byte_len(text)
            if part_bytes > MAX_CLIENT_REPRESENTATION_PART_BYTES:
                raise ValidationError("client representation part exceeds size limit")
            total_bytes += part_bytes
            if total_bytes > MAX_CLIENT_REPRESENTATION_TOTAL_BYTES:
                raise ValidationError("client representation payload exceeds total size limit")

            part_index = item.get("part_index")
            if part_index is not None:
                index = int(part_index)
                if index in seen_indices:
                    raise ValidationError("duplicate client representation part_index")
                seen_indices.add(index)

            normalized.append(
                {
                    "kind": kind,
                    "text": text,
                    "part_index": part_index,
                    "metadata": _normalize_rep_metadata(dict(item.get("metadata") or {})),
                }
            )
        return normalized


class ClientRepresentationPersistence:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._representations = RepresentationService(session, user_id)
        self._validator = ClientRepresentationValidator()

    def replace_for_object(
        self,
        object_id: UUID,
        filename: str,
        representations: list[dict],
        metadata_only: bool,
    ) -> int:
        validated = self._validator.validate_payload(filename, representations, metadata_only)
        self._representations._get_object(object_id)
        reps: list[Representation] = []
        for item in validated:
            reps.append(
                Representation(
                    object_id=object_id,
                    kind=item["kind"],
                    text=item["text"],
                    part_index=item.get("part_index"),
                    metadata_=item.get("metadata") or {},
                )
            )
        self._session.execute(delete(Representation).where(Representation.object_id == object_id))
        for rep in reps:
            self._session.add(rep)
        self._session.flush()
        return len(reps)

    def delete_all_for_object(self, object_id: UUID) -> None:
        self._session.execute(delete(Representation).where(Representation.object_id == object_id))
        self._session.flush()
