"""Deterministic extraction source baseline for worker authority checks."""

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content_extraction.constants import EXTRACTION_VERSION
from app.content_extraction.revision import (
    derive_web_remote_content_revision,
    metadata_extraction_version,
)
from app.db.models import Object
from app.resources.constants import PROVIDER_WEB

EXTRACTION_BASELINE_METADATA_KEY = "extraction_baseline"
WEB_REVALIDATION_GENERATION_METADATA_KEY = "web_revalidation_generation"


@dataclass(frozen=True)
class WorkerFinalAuthority:
    obj: Object
    metadata: dict[str, Any]


def derive_web_extraction_baseline(metadata: dict[str, Any]) -> str:
    remote = derive_web_remote_content_revision(metadata)
    parts = [
        str(metadata.get("final_url") or ""),
        str(metadata.get("detected_suffix") or ""),
        str(metadata.get("content_length") if metadata.get("content_length") is not None else ""),
        str(metadata.get("content_format") or ""),
        remote or "no-remote-rev",
    ]
    if remote is None:
        parts.append(str(metadata.get(WEB_REVALIDATION_GENERATION_METADATA_KEY) or "0"))
    parts.append(EXTRACTION_VERSION)
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]
    return f"web:baseline:{digest}"


def derive_extraction_baseline(provider: str, metadata: dict[str, Any]) -> str | None:
    if provider in {PROVIDER_WEB, "web"}:
        return derive_web_extraction_baseline(metadata)
    return None


def worker_extraction_authoritative(
    *,
    provider: str,
    metadata: dict[str, Any],
    expected_revision: str | None,
    expected_baseline: str | None,
    extraction_version: str | None = None,
) -> bool:
    if expected_revision is not None and metadata.get("content_revision") != expected_revision:
        return False
    if extraction_version is not None and metadata_extraction_version(metadata) != extraction_version:
        return False
    if expected_baseline is not None and provider in {PROVIDER_WEB, "web"}:
        current = derive_web_extraction_baseline(metadata)
        if current != expected_baseline:
            return False
    return True


def acquire_worker_final_authority(
    session: Session,
    *,
    user_id: UUID,
    object_id: UUID,
    provider: str,
    expected_revision: str | None,
    expected_baseline: str | None,
    extraction_version: str | None,
) -> WorkerFinalAuthority | None:
    obj = session.scalar(
        select(Object)
        .where(Object.id == object_id, Object.user_id == user_id)
        .with_for_update()
    )
    if obj is None:
        raise ValueError(f"object ownership mismatch: {object_id}")
    session.refresh(obj)
    metadata = dict(obj.metadata_ or {})
    if not worker_extraction_authoritative(
        provider=provider,
        metadata=metadata,
        expected_revision=expected_revision,
        expected_baseline=expected_baseline,
        extraction_version=extraction_version,
    ):
        return None
    return WorkerFinalAuthority(obj=obj, metadata=metadata)


def resolve_web_revalidation_generation(
    *,
    prior_metadata: dict[str, Any],
    created: bool,
    requires_revalidation: bool,
    has_remote_revision: bool,
) -> int | None:
    if has_remote_revision:
        existing = prior_metadata.get(WEB_REVALIDATION_GENERATION_METADATA_KEY)
        return int(existing) if existing is not None else None
    if created:
        return 1
    if requires_revalidation:
        return int(prior_metadata.get(WEB_REVALIDATION_GENERATION_METADATA_KEY) or 0) + 1
    existing = prior_metadata.get(WEB_REVALIDATION_GENERATION_METADATA_KEY)
    return int(existing) if existing is not None else None
