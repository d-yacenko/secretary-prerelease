from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.services.errors import ValidationError
from app.services.inbox_review_snapshot_cursor import canonical_feed_at, parse_feed_at


@dataclass(frozen=True)
class InboxReviewReceipt:
    anchor_before_object_id: UUID
    anchor_before_feed_at: datetime
    snapshot_top_object_id: UUID
    snapshot_top_feed_at: datetime
    total_count: int


class InboxReviewTurnProgress:
    """Turn-local review completeness from successful tool executions, not LLM prose."""

    def __init__(self) -> None:
        self._invalid = False
        self._limit_hit = False
        self._failed = False
        self._purpose: str | None = None
        self._anchor_object_id: UUID | None = None
        self._anchor_feed_at: datetime | None = None
        self._snapshot_top_object_id: UUID | None = None
        self._snapshot_top_feed_at: datetime | None = None
        self._total_count: int | None = None
        self._expected_cursor: str | None = None
        self._pages = 0
        self._credited_object_ids: set[UUID] = set()
        self._complete = False

    def mark_limit_reached(self) -> None:
        self._limit_hit = True
        self._complete = False

    def mark_failed(self) -> None:
        self._failed = True
        self._complete = False

    def observe(self, *, arguments: dict[str, Any] | None, payload: dict[str, Any]) -> None:
        if self._invalid or self._limit_hit or self._failed:
            return
        purpose = _purpose_from(arguments, payload)
        cursor = _cursor_from(arguments)
        if purpose == "inspect":
            if self._purpose == "review":
                self._invalid = True
                self._complete = False
            return
        if purpose != "review":
            self._invalid = True
            self._complete = False
            return
        if self._complete:
            if self._same_frozen_snapshot(payload):
                return
            self._invalid = True
            self._complete = False
            return
        if payload.get("marker_not_set") or not payload.get("marker_present"):
            self._invalid = True
            self._complete = False
            return
        total_count = payload.get("total_count")
        if not isinstance(total_count, int) or total_count <= 0:
            self._complete = False
            if cursor or self._pages:
                self._invalid = True
            else:
                self._purpose = "review"
                self._pages += 1
            return
        try:
            anchor_object_id = UUID(str(payload.get("anchor_object_id")))
            anchor_feed_at = parse_feed_at(payload.get("anchor_feed_at"))
            snapshot_top_object_id = UUID(str(payload.get("snapshot_top_object_id")))
            snapshot_top_feed_at = parse_feed_at(payload.get("snapshot_top_feed_at"))
        except (TypeError, ValueError, ValidationError):
            self._invalid = True
            self._complete = False
            return
        has_more = bool(payload.get("has_more"))
        next_cursor = payload.get("next_cursor")
        if has_more and (not isinstance(next_cursor, str) or not next_cursor):
            self._invalid = True
            self._complete = False
            return
        if cursor is None:
            if self._pages or self._expected_cursor is not None:
                self._invalid = True
                self._complete = False
                return
            self._purpose = "review"
            self._anchor_object_id = anchor_object_id
            self._anchor_feed_at = canonical_feed_at(anchor_feed_at)
            self._snapshot_top_object_id = snapshot_top_object_id
            self._snapshot_top_feed_at = canonical_feed_at(snapshot_top_feed_at)
            self._total_count = total_count
            self._pages += 1
            self._credited_object_ids.update(credited_object_ids_from_review_payload(payload))
            if has_more:
                self._expected_cursor = next_cursor
                self._complete = False
            else:
                self._expected_cursor = None
                self._complete = self._coverage_complete()
            return
        if (
            self._purpose != "review"
            or self._anchor_object_id != anchor_object_id
            or self._snapshot_top_object_id != snapshot_top_object_id
            or self._total_count != total_count
            or self._anchor_feed_at != canonical_feed_at(anchor_feed_at)
            or self._snapshot_top_feed_at != canonical_feed_at(snapshot_top_feed_at)
        ):
            self._invalid = True
            self._complete = False
            return
        if cursor != self._expected_cursor:
            self._invalid = True
            self._complete = False
            return
        self._pages += 1
        self._credited_object_ids.update(credited_object_ids_from_review_payload(payload))
        if has_more:
            self._expected_cursor = next_cursor
            self._complete = False
        else:
            self._expected_cursor = None
            self._complete = self._coverage_complete()

    def verified_receipt(self) -> InboxReviewReceipt | None:
        if (
            self._invalid
            or self._limit_hit
            or self._failed
            or not self._complete
            or self._expected_cursor is not None
            or self._purpose != "review"
            or self._anchor_object_id is None
            or self._anchor_feed_at is None
            or self._snapshot_top_object_id is None
            or self._snapshot_top_feed_at is None
            or not self._total_count
        ):
            return None
        return InboxReviewReceipt(
            anchor_before_object_id=self._anchor_object_id,
            anchor_before_feed_at=self._anchor_feed_at,
            snapshot_top_object_id=self._snapshot_top_object_id,
            snapshot_top_feed_at=self._snapshot_top_feed_at,
            total_count=self._total_count,
        )

    def _coverage_complete(self) -> bool:
        return self._total_count is not None and len(self._credited_object_ids) == self._total_count

    def _same_frozen_snapshot(self, payload: dict[str, Any]) -> bool:
        try:
            snapshot_top_object_id = UUID(str(payload.get("snapshot_top_object_id")))
            snapshot_top_feed_at = canonical_feed_at(parse_feed_at(payload.get("snapshot_top_feed_at")))
            anchor_object_id = UUID(str(payload.get("anchor_object_id")))
            anchor_feed_at = canonical_feed_at(parse_feed_at(payload.get("anchor_feed_at")))
            total_count = payload.get("total_count")
        except (TypeError, ValueError, ValidationError):
            return False
        return (
            self._purpose == "review"
            and self._anchor_object_id == anchor_object_id
            and self._anchor_feed_at == anchor_feed_at
            and self._snapshot_top_object_id == snapshot_top_object_id
            and self._snapshot_top_feed_at == snapshot_top_feed_at
            and self._total_count == total_count
        )


def credited_object_ids_from_review_payload(payload: dict[str, Any]) -> set[UUID]:
    credited: set[UUID] = set()
    compact = payload.get("compact_items")
    sources: list[object] = []
    if isinstance(compact, list) and compact:
        for item in compact:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "stack":
                stack = item.get("stack") or {}
                sources.extend(stack.get("object_ids") or [])
            else:
                sources.append(item.get("object_id"))
    else:
        for item in payload.get("items") or []:
            if isinstance(item, dict):
                sources.append(item.get("object_id"))
    for raw in sources:
        try:
            credited.add(UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    return credited


def _purpose_from(arguments: dict[str, Any] | None, payload: dict[str, Any]) -> str:
    raw = None
    if arguments:
        raw = arguments.get("purpose")
    if raw is None:
        raw = payload.get("purpose")
    if raw is None:
        return "inspect"
    return str(raw)


def _cursor_from(arguments: dict[str, Any] | None) -> str | None:
    if not arguments:
        return None
    cursor = arguments.get("cursor")
    if not isinstance(cursor, str):
        return None
    stripped = cursor.strip()
    return stripped or None
