"""Canonical object embedding input. Semantic fields only — not Object.updated_at."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.config import settings
from app.db.models import Object

EMBEDDING_DIMENSION = 1536
EMBEDDING_INPUT_VERSION = "cost_guard_b"

# Ordered allowlist: searchable semantics only. Provider housekeeping is excluded.
EMBEDDING_SEMANTIC_METADATA_KEYS = (
    "semantic_summary",
    "sender",
    "from",
    "recipients",
    "to",
    "cc",
    "tags",
    "category",
    "author",
    "source",
    "location",
    "organizer",
    "attendees",
    "participants",
)


def embedding_input_version() -> str:
    return EMBEDDING_INPUT_VERSION


def effective_embedding_model() -> str:
    return settings.openai_embedding_model


def canonical_embedding_text(obj: Object) -> str:
    parts: list[str] = [obj.title or ""]
    if obj.body:
        parts.append(obj.body)
    meta = obj.metadata_ or {}
    for key in EMBEDDING_SEMANTIC_METADATA_KEYS:
        rendered = _stringify_semantic_value(meta.get(key))
        if rendered:
            parts.append(f"{key}: {rendered}")
    return "\n".join(parts)


def build_embedding_text(obj: Object) -> str:
    return canonical_embedding_text(obj)


def embedding_input_signature(obj: Object, model: str | None = None) -> str:
    payload = {
        "embedding_input_version": embedding_input_version(),
        "embedding_model": model or effective_embedding_model(),
        "text": canonical_embedding_text(obj),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def embed_job_payload(obj: Object, *, parent_trace_id: str | None = None) -> dict:
    payload: dict = {
        "object_id": str(obj.id),
        "embedding_input_signature": embedding_input_signature(obj),
    }
    if parent_trace_id is not None:
        payload["parent_trace_id"] = parent_trace_id
    return payload


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stringify_semantic_value(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, list):
        parts = [_item_semantic_text(item) for item in value]
        rendered = [part for part in parts if part]
        if not rendered:
            return None
        return ", ".join(sorted(set(rendered)))
    if isinstance(value, dict):
        return _item_semantic_text(value)
    return None


def _item_semantic_text(item: Any) -> str | None:
    if isinstance(item, str):
        text = item.strip()
        return text or None
    if not isinstance(item, dict):
        return None
    email = item.get("email") or item.get("address")
    if isinstance(email, str) and email.strip():
        return email.strip()
    name = item.get("displayName") or item.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None
