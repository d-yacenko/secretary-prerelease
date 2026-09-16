from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.services.errors import ValidationError

CURSOR_VERSION = 2
VALID_DIRECTIONS = frozenset({"asc", "desc"})


def canonical_feed_at(value: datetime) -> datetime:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC)


def feed_at_iso(value: datetime) -> str:
    return canonical_feed_at(value).isoformat().replace("+00:00", "Z")


def parse_feed_at(value: object) -> datetime:
    if isinstance(value, datetime):
        return canonical_feed_at(value)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("invalid inbox review cursor")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))  # noqa: FURB162
    except ValueError as exc:
        raise ValidationError("invalid inbox review cursor") from exc
    return canonical_feed_at(parsed)


def parse_object_id(value: object) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise ValidationError("invalid inbox review cursor") from exc


@dataclass(frozen=True)
class InboxReviewSnapshotCursor:
    anchor_object_id: UUID
    anchor_feed_at: datetime
    snapshot_top_object_id: UUID
    snapshot_top_feed_at: datetime
    last_object_id: UUID
    last_feed_at: datetime
    direction: str

    def encode(self) -> str:
        payload = {
            "v": CURSOR_VERSION,
            "dir": self.direction,
            "a_id": str(self.anchor_object_id),
            "a_at": feed_at_iso(self.anchor_feed_at),
            "t_id": str(self.snapshot_top_object_id),
            "t_at": feed_at_iso(self.snapshot_top_feed_at),
            "l_id": str(self.last_object_id),
            "l_at": feed_at_iso(self.last_feed_at),
        }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def frozen_matches(
        self,
        *,
        anchor_object_id: UUID,
        anchor_feed_at: datetime,
        snapshot_top_object_id: UUID,
        snapshot_top_feed_at: datetime,
    ) -> bool:
        return (
            self.anchor_object_id == anchor_object_id
            and self.snapshot_top_object_id == snapshot_top_object_id
            and feed_at_iso(self.anchor_feed_at) == feed_at_iso(anchor_feed_at)
            and feed_at_iso(self.snapshot_top_feed_at) == feed_at_iso(snapshot_top_feed_at)
        )

    def last_is_inside_window(self) -> bool:
        last_newer_than_anchor = _tuple_is_newer(
            self.last_feed_at,
            self.last_object_id,
            self.anchor_feed_at,
            self.anchor_object_id,
        )
        last_newer_than_top = _tuple_is_newer(
            self.last_feed_at,
            self.last_object_id,
            self.snapshot_top_feed_at,
            self.snapshot_top_object_id,
        )
        return last_newer_than_anchor and not last_newer_than_top


def _tuple_is_newer(
    left_feed_at: datetime,
    left_id: UUID,
    right_feed_at: datetime,
    right_id: UUID,
) -> bool:
    if left_feed_at != right_feed_at:
        return left_feed_at > right_feed_at
    return left_id > right_id


def encode_inbox_review_snapshot_cursor(
    *,
    anchor_object_id: UUID,
    anchor_feed_at: datetime,
    snapshot_top_object_id: UUID,
    snapshot_top_feed_at: datetime,
    last_object_id: UUID,
    last_feed_at: datetime,
    direction: str,
) -> str:
    if direction not in VALID_DIRECTIONS:
        raise ValidationError("invalid inbox review cursor")
    return InboxReviewSnapshotCursor(
        anchor_object_id=anchor_object_id,
        anchor_feed_at=canonical_feed_at(anchor_feed_at),
        snapshot_top_object_id=snapshot_top_object_id,
        snapshot_top_feed_at=canonical_feed_at(snapshot_top_feed_at),
        last_object_id=last_object_id,
        last_feed_at=canonical_feed_at(last_feed_at),
        direction=direction,
    ).encode()


def decode_inbox_review_snapshot_cursor(value: str) -> InboxReviewSnapshotCursor:
    if not value or not isinstance(value, str):
        raise ValidationError("invalid inbox review cursor")
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("invalid inbox review cursor") from exc
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise ValidationError("invalid inbox review cursor")
    direction = payload.get("dir")
    if direction not in VALID_DIRECTIONS:
        raise ValidationError("invalid inbox review cursor")
    try:
        cursor = InboxReviewSnapshotCursor(
            anchor_object_id=parse_object_id(payload.get("a_id")),
            anchor_feed_at=parse_feed_at(payload.get("a_at")),
            snapshot_top_object_id=parse_object_id(payload.get("t_id")),
            snapshot_top_feed_at=parse_feed_at(payload.get("t_at")),
            last_object_id=parse_object_id(payload.get("l_id")),
            last_feed_at=parse_feed_at(payload.get("l_at")),
            direction=direction,
        )
    except ValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise ValidationError("invalid inbox review cursor") from exc
    if not cursor.last_is_inside_window():
        raise ValidationError("invalid inbox review cursor")
    return cursor
