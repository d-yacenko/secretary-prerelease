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


def object_primary_search_datetime(obj: Object) -> datetime | None:
    kind = obj.kind
    if kind == "task":
        candidate = obj.due_at or obj.updated_at
    elif kind == "scheduled_activity":
        candidate = obj.due_at or obj.occurred_at or obj.updated_at
    elif kind in {"event", "calendar_event"}:
        candidate = obj.start_at or obj.occurred_at or obj.updated_at
    elif kind in {"email", "message", "chat", "chat_message"}:
        candidate = obj.occurred_at or obj.updated_at
    elif kind in {"file", "document", "dataset"}:
        modified = _parse_metadata_modified_at(dict(obj.metadata_ or {}))
        candidate = modified or obj.occurred_at or obj.updated_at
    else:
        candidate = obj.occurred_at or obj.updated_at
    if candidate is None:
        return None
    return _normalize_aware_datetime(candidate)
