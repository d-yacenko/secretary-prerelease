from __future__ import annotations

import base64
from datetime import UTC, datetime
from uuid import UUID

from app.services.errors import ValidationError

CURSOR_VERSION = "1"


def encode_inbox_feed_cursor(feed_at: datetime, object_id: UUID) -> str:
    aware = feed_at if feed_at.tzinfo is not None else feed_at.replace(tzinfo=UTC)
    canonical = aware.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raw = f"{CURSOR_VERSION}|{canonical}|{object_id}".encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_inbox_feed_cursor(value: str) -> tuple[datetime, UUID]:
    if not value or not isinstance(value, str):
        raise ValidationError("invalid inbox cursor")
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("invalid inbox cursor") from exc
    parts = decoded.split("|")
    if len(parts) != 3 or parts[0] != CURSOR_VERSION:
        raise ValidationError("invalid inbox cursor")
    try:
        feed_at = datetime.fromisoformat(parts[1])
        object_id = UUID(parts[2])
    except ValueError as exc:
        raise ValidationError("invalid inbox cursor") from exc
    if feed_at.tzinfo is None:
        raise ValidationError("invalid inbox cursor")
    return feed_at.astimezone(UTC), object_id
