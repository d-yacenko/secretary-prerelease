"""Primary search/sort date for objects (aligned with Flutter object_dates)."""

from datetime import UTC, datetime

from app.db.models import Object


def _normalize_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_metadata_modified_at(metadata: dict) -> datetime | None:
    raw = metadata.get("modified_at")
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    try:
        if "+" in text or text.endswith(("Z", "-00:00")):
            parsed = datetime.fromisoformat(text)
        else:
            # Timezone-less metadata dates are unreliable for ordering; fall back.
            return None
        return _normalize_aware_datetime(parsed)
    except ValueError:
        return None


def _coerce_datetime(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def primary_search_datetime_from_fields(
    *,
    kind: str,
    due_at: datetime | None,
    start_at: datetime | None,
    occurred_at: datetime | None,
    updated_at: datetime | None,
    metadata: dict | None,
) -> datetime | None:
    if kind == "task":
        candidate = due_at or updated_at
    elif kind == "scheduled_activity":
        candidate = due_at or occurred_at or updated_at
    elif kind in {"event", "calendar_event"}:
        candidate = start_at or occurred_at or updated_at
    elif kind in {"email", "message", "chat", "chat_message"}:
        candidate = occurred_at or updated_at
    elif kind in {"file", "document", "dataset"}:
        modified = _parse_metadata_modified_at(dict(metadata or {}))
        candidate = modified or occurred_at or updated_at
    else:
        candidate = occurred_at or updated_at
    if candidate is None:
        return None
    return _normalize_aware_datetime(candidate)


def object_primary_search_datetime(obj: Object) -> datetime | None:
    return primary_search_datetime_from_fields(
        kind=obj.kind,
        due_at=obj.due_at,
        start_at=obj.start_at,
        occurred_at=obj.occurred_at,
        updated_at=obj.updated_at,
        metadata=dict(obj.metadata_ or {}),
    )


def primary_search_datetime_from_object_snapshot(payload: dict) -> datetime | None:
    metadata = payload.get("metadata")
    return primary_search_datetime_from_fields(
        kind=str(payload.get("kind") or ""),
        due_at=_coerce_datetime(payload.get("due_at")),
        start_at=_coerce_datetime(payload.get("start_at")),
        occurred_at=_coerce_datetime(payload.get("occurred_at")),
        updated_at=_coerce_datetime(payload.get("updated_at")),
        metadata=metadata if isinstance(metadata, dict) else {},
    )
