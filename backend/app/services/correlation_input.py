"""Correlation job input signature. Semantic fields only — not Object.updated_at."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from email.utils import getaddresses, parseaddr

from app.db.models import Object
from app.services.correlation_constants import (
    CORRELATION_VERSION,
    SEMANTIC_SUMMARY_METADATA_KEY,
)

_PARTICIPANT_SCALAR_KEYS = ("sender", "from")
_PARTICIPANT_LIST_KEYS = ("recipients", "to", "cc")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def normalize_email_address(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    _, addr = parseaddr(text)
    candidate = addr.strip() if addr else text
    if "@" not in candidate:
        return None
    return candidate.lower()


def extract_correlation_participants(obj: Object) -> set[str]:
    meta = obj.metadata_ or {}
    emails: set[str] = set()
    for key in _PARTICIPANT_SCALAR_KEYS:
        value = meta.get(key)
        if isinstance(value, str):
            normalized = normalize_email_address(value)
            if normalized:
                emails.add(normalized)
    for key in _PARTICIPANT_LIST_KEYS:
        value = meta.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    normalized = normalize_email_address(item)
                    if normalized:
                        emails.add(normalized)
        elif isinstance(value, str):
            for _, addr in getaddresses([value]):
                normalized = normalize_email_address(addr or value)
                if normalized:
                    emails.add(normalized)
    return emails


def effective_trigger_summary(obj: Object) -> str:
    meta = obj.metadata_ or {}
    semantic = meta.get(SEMANTIC_SUMMARY_METADATA_KEY)
    if isinstance(semantic, str) and semantic.strip():
        return semantic.strip()[:500]
    if obj.body:
        return obj.body[:500]
    return obj.title


def correlation_input_payload(obj: Object) -> dict:
    meta = obj.metadata_ or {}
    semantic = meta.get(SEMANTIC_SUMMARY_METADATA_KEY)
    semantic_text = semantic.strip() if isinstance(semantic, str) else ""
    thread_id = meta.get("thread_id")
    return {
        "object_id": str(obj.id),
        "correlation_version": CORRELATION_VERSION,
        "kind": obj.kind,
        "provider": obj.provider or "",
        "title": obj.title or "",
        "trigger_summary": effective_trigger_summary(obj),
        "semantic_summary": semantic_text,
        "body": obj.body or "",
        "thread_id": str(thread_id) if thread_id not in (None, "") else "",
        "participants": sorted(extract_correlation_participants(obj)),
        "occurred_at": _canonical_dt(obj.occurred_at),
        "start_at": _canonical_dt(obj.start_at),
        "due_at": _canonical_dt(obj.due_at),
    }


def correlation_input_signature(obj: Object) -> str:
    return hashlib.sha256(
        _canonical_json(correlation_input_payload(obj)).encode("utf-8")
    ).hexdigest()
