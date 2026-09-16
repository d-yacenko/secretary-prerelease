"""Merge provider metadata with pipeline-owned extraction state."""

from typing import Any

from app.content_extraction.constants import EXTRACTION_VERSION
from app.content_extraction.extract_service import apply_intake_content_metadata
from app.content_extraction.metadata_keys import (
    CONTENT_EXTRACTED_AT,
    CONTENT_EXTRACTED_CHARS,
    CONTENT_EXTRACTION_ERROR,
    CONTENT_EXTRACTION_STATUS,
    CONTENT_EXTRACTION_VERSION,
    CONTENT_FORMAT,
    CONTENT_SOURCE_BYTES,
    CONTENT_TRUNCATED,
    MECHANICAL_REPRESENTATION_COUNT,
    STATUS_READY,
)
from app.content_extraction.revision import metadata_extraction_version
from app.services.correlation_constants import (
    SEMANTIC_SUMMARY_METADATA_KEY,
    SEMANTIC_SUMMARY_REVISION_KEY,
)

PIPELINE_OWNED_METADATA_KEYS = frozenset(
    {
        "content_revision",
        CONTENT_EXTRACTION_STATUS,
        CONTENT_EXTRACTION_VERSION,
        CONTENT_EXTRACTED_AT,
        CONTENT_FORMAT,
        CONTENT_TRUNCATED,
        CONTENT_SOURCE_BYTES,
        CONTENT_EXTRACTED_CHARS,
        MECHANICAL_REPRESENTATION_COUNT,
        CONTENT_EXTRACTION_ERROR,
        SEMANTIC_SUMMARY_METADATA_KEY,
        SEMANTIC_SUMMARY_REVISION_KEY,
    }
)


def provider_metadata_changed(prior: dict[str, Any], incoming_provider: dict[str, Any]) -> bool:
    keys = set(prior.keys()) | set(incoming_provider.keys())
    for key in keys:
        if key in PIPELINE_OWNED_METADATA_KEYS:
            continue
        if prior.get(key) != incoming_provider.get(key):
            return True
    return False


def content_revision_changed(prior_meta: dict[str, Any], incoming_meta: dict[str, Any]) -> bool:
    incoming_revision = incoming_meta.get("content_revision")
    if incoming_revision is None:
        return False
    return prior_meta.get("content_revision") != incoming_revision


def is_ready_content_unchanged(
    prior_meta: dict[str, Any],
    incoming_meta: dict[str, Any],
    had_mechanical_reps: bool,
) -> bool:
    if not had_mechanical_reps:
        return False
    if prior_meta.get(CONTENT_EXTRACTION_STATUS) != STATUS_READY:
        return False
    if metadata_extraction_version(prior_meta) != EXTRACTION_VERSION:
        return False
    return prior_meta.get("content_revision") == incoming_meta.get("content_revision")


def merge_intake_metadata(
    prior_meta: dict[str, Any],
    incoming_provider_meta: dict[str, Any],
    provider: str,
    kind: str,
    title: str | None,
    had_mechanical_reps: bool,
) -> dict[str, Any]:
    derived = apply_intake_content_metadata(
        dict(incoming_provider_meta),
        provider,
        kind,
        title,
    )
    if is_ready_content_unchanged(prior_meta, derived, had_mechanical_reps):
        merged = dict(prior_meta)
        for key, value in incoming_provider_meta.items():
            if key not in PIPELINE_OWNED_METADATA_KEYS:
                merged[key] = value
        if derived.get("content_revision") is not None:
            merged["content_revision"] = derived["content_revision"]
        return merged

    merged = dict(prior_meta)
    for key, value in incoming_provider_meta.items():
        if key not in PIPELINE_OWNED_METADATA_KEYS:
            merged[key] = value
    for key in (
        "content_revision",
        CONTENT_EXTRACTION_STATUS,
        CONTENT_EXTRACTION_VERSION,
        CONTENT_FORMAT,
    ):
        if key in derived:
            merged[key] = derived[key]
    return merged
