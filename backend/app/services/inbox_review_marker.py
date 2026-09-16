from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import InboxReviewMarker, Object
from app.services.errors import NotFoundError, ValidationError
from app.services.inbox_review_snapshot_cursor import (
    canonical_feed_at,
    decode_inbox_review_snapshot_cursor,
    encode_inbox_review_snapshot_cursor,
)
from app.services.recent_source_service import (
    RECENT_SOURCE_MAX_LIMIT,
    InboxFeedPage,
    RecentSourceService,
    inbox_feed_at,
)


def feed_tuple_is_newer(
    left_feed_at: datetime,
    left_id: UUID,
    right_feed_at: datetime,
    right_id: UUID,
) -> bool:
    """True if left appears above right in canonical Inbox order."""
    if left_feed_at != right_feed_at:
        return left_feed_at > right_feed_at
    return left_id > right_id


def item_is_at_or_above_marker(
    item_feed_at: datetime,
    item_id: UUID,
    anchor_feed_at: datetime,
    anchor_object_id: UUID,
) -> bool:
    """Items at/above the marker are newer than or equal to the persisted anchor tuple."""
    return not feed_tuple_is_newer(
        anchor_feed_at,
        anchor_object_id,
        item_feed_at,
        item_id,
    )


@dataclass(frozen=True)
class ReviewMarkerRecord:
    anchor_feed_at: datetime
    anchor_object_id: UUID
    updated_at: datetime


@dataclass(frozen=True)
class InboxSinceReviewMarkerPage:
    marker: ReviewMarkerRecord | None
    items: list[Object]
    has_more: bool
    snapshot_top_object_id: UUID | None = None
    snapshot_top_feed_at: datetime | None = None
    total_count: int = 0
    returned_count: int = 0
    remaining_count: int = 0
    next_cursor: str | None = None


@dataclass(frozen=True)
class ReviewMarkerCompletion:
    status: str
    marker: ReviewMarkerRecord | None


class InboxReviewMarkerService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._feed = RecentSourceService(session, user_id)

    def get_marker(self) -> ReviewMarkerRecord | None:
        row = self._session.get(InboxReviewMarker, self._user_id)
        if row is None:
            return None
        return ReviewMarkerRecord(
            anchor_feed_at=row.anchor_feed_at,
            anchor_object_id=row.anchor_object_id,
            updated_at=row.updated_at,
        )

    def set_marker(self, after_object_id: UUID) -> ReviewMarkerRecord:
        obj = self._session.scalar(
            select(Object).where(Object.id == after_object_id, Object.user_id == self._user_id)
        )
        if obj is None:
            raise NotFoundError("object", after_object_id)
        eligible = self._feed.get_inbox_eligible(after_object_id)
        if eligible is None:
            raise ValidationError("object is not eligible for the inbox feed")
        feed_at = inbox_feed_at(eligible)
        stmt = insert(InboxReviewMarker).values(
            user_id=self._user_id,
            anchor_feed_at=feed_at,
            anchor_object_id=eligible.id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[InboxReviewMarker.user_id],
            set_={
                "anchor_feed_at": stmt.excluded.anchor_feed_at,
                "anchor_object_id": stmt.excluded.anchor_object_id,
                "updated_at": func.now(),
            },
        )
        self._session.execute(stmt)
        self._session.flush()
        row = self._session.get(InboxReviewMarker, self._user_id)
        assert row is not None
        self._session.refresh(row)
        return ReviewMarkerRecord(
            anchor_feed_at=row.anchor_feed_at,
            anchor_object_id=row.anchor_object_id,
            updated_at=row.updated_at,
        )

    def clear_marker(self) -> bool:
        row = self._session.get(InboxReviewMarker, self._user_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def list_inbox_since_review_marker(
        self,
        limit: int,
        cursor: str | None = None,
        purpose: str = "inspect",
    ) -> InboxSinceReviewMarkerPage:
        direction = _direction_for_purpose(purpose)
        if cursor:
            return self._list_continuation(
                limit=limit, cursor=cursor, direction=direction
            )
        marker = self.get_marker()
        if marker is None:
            return InboxSinceReviewMarkerPage(marker=None, items=[], has_more=False)
        frozen_top = self._freeze_snapshot_top(marker)
        if frozen_top is None:
            return InboxSinceReviewMarkerPage(
                marker=marker,
                items=[],
                has_more=False,
                total_count=0,
                returned_count=0,
                remaining_count=0,
            )
        snapshot_top, snapshot_top_feed_at = frozen_top
        page = self._feed.list_review_window(
            anchor_feed_at=marker.anchor_feed_at,
            anchor_object_id=marker.anchor_object_id,
            snapshot_top_feed_at=snapshot_top_feed_at,
            snapshot_top_object_id=snapshot_top.id,
            after_feed_at=None,
            after_object_id=None,
            limit=limit,
            direction=direction,
        )
        return self._page_from_window(
            marker=marker,
            snapshot_top_object_id=snapshot_top.id,
            snapshot_top_feed_at=snapshot_top_feed_at,
            page=page,
            direction=direction,
        )

    def complete_review(
        self,
        *,
        expected_anchor_object_id: UUID,
        expected_anchor_feed_at: datetime,
        snapshot_top_object_id: UUID,
        snapshot_top_feed_at: datetime,
    ) -> ReviewMarkerCompletion:
        expected_anchor_feed_at = canonical_feed_at(expected_anchor_feed_at)
        snapshot_top_feed_at = canonical_feed_at(snapshot_top_feed_at)
        current = self.get_marker()
        snapshot_obj = self._feed.get_inbox_eligible(snapshot_top_object_id)
        if snapshot_obj is None:
            return ReviewMarkerCompletion(status="conflict", marker=current)
        if canonical_feed_at(inbox_feed_at(snapshot_obj)) != snapshot_top_feed_at:
            return ReviewMarkerCompletion(status="conflict", marker=current)
        if current is None:
            return ReviewMarkerCompletion(status="conflict", marker=None)
        current_feed_at = canonical_feed_at(current.anchor_feed_at)
        if (
            current.anchor_object_id == expected_anchor_object_id
            and current_feed_at == expected_anchor_feed_at
        ):
            record = self.set_marker(snapshot_top_object_id)
            return ReviewMarkerCompletion(status="advanced", marker=record)
        if not feed_tuple_is_newer(
            snapshot_top_feed_at,
            snapshot_top_object_id,
            current_feed_at,
            current.anchor_object_id,
        ):
            return ReviewMarkerCompletion(status="already_current", marker=current)
        return ReviewMarkerCompletion(status="conflict", marker=current)

    def _freeze_snapshot_top(
        self, marker: ReviewMarkerRecord
    ) -> tuple[Object, datetime] | None:
        newest = self._feed.list_strictly_newer_than(
            marker.anchor_feed_at,
            marker.anchor_object_id,
            limit=1,
        )
        if not newest.items:
            return None
        top = newest.items[0]
        return top, inbox_feed_at(top)

    def _page_from_window(
        self,
        *,
        marker: ReviewMarkerRecord,
        snapshot_top_object_id: UUID,
        snapshot_top_feed_at: datetime,
        page: InboxFeedPage,
        direction: str,
    ) -> InboxSinceReviewMarkerPage:
        total_count = self._feed.count_review_window(
            anchor_feed_at=marker.anchor_feed_at,
            anchor_object_id=marker.anchor_object_id,
            snapshot_top_feed_at=snapshot_top_feed_at,
            snapshot_top_object_id=snapshot_top_object_id,
        )
        if not page.items:
            return InboxSinceReviewMarkerPage(
                marker=marker,
                items=[],
                has_more=False,
                snapshot_top_object_id=snapshot_top_object_id,
                snapshot_top_feed_at=snapshot_top_feed_at,
                total_count=total_count,
                returned_count=0,
                remaining_count=0,
            )
        last = page.items[-1]
        last_feed_at = inbox_feed_at(last)
        if direction == "asc":
            remaining_count = self._feed.count_newer_in_review_window(
                anchor_feed_at=marker.anchor_feed_at,
                anchor_object_id=marker.anchor_object_id,
                snapshot_top_feed_at=snapshot_top_feed_at,
                snapshot_top_object_id=snapshot_top_object_id,
                last_feed_at=last_feed_at,
                last_object_id=last.id,
            )
        else:
            remaining_count = self._feed.count_older_in_review_window(
                anchor_feed_at=marker.anchor_feed_at,
                anchor_object_id=marker.anchor_object_id,
                snapshot_top_feed_at=snapshot_top_feed_at,
                snapshot_top_object_id=snapshot_top_object_id,
                last_feed_at=last_feed_at,
                last_object_id=last.id,
            )
        next_cursor = None
        if page.has_more:
            next_cursor = encode_inbox_review_snapshot_cursor(
                anchor_object_id=marker.anchor_object_id,
                anchor_feed_at=marker.anchor_feed_at,
                snapshot_top_object_id=snapshot_top_object_id,
                snapshot_top_feed_at=snapshot_top_feed_at,
                last_object_id=last.id,
                last_feed_at=last_feed_at,
                direction=direction,
            )
        return InboxSinceReviewMarkerPage(
            marker=marker,
            items=page.items,
            has_more=page.has_more,
            snapshot_top_object_id=snapshot_top_object_id,
            snapshot_top_feed_at=snapshot_top_feed_at,
            total_count=total_count,
            returned_count=len(page.items),
            remaining_count=remaining_count,
            next_cursor=next_cursor,
        )

    def list_frozen_window_objects(
        self,
        *,
        marker: ReviewMarkerRecord,
        snapshot_top_object_id: UUID,
        snapshot_top_feed_at: datetime,
        purpose: str,
        max_objects: int,
    ) -> list[Object] | None:
        """Load the full frozen window in purpose order, or None if it exceeds max_objects."""
        if max_objects <= 0:
            return []
        direction = _direction_for_purpose(purpose)
        collected: list[Object] = []
        after_feed_at: datetime | None = None
        after_object_id: UUID | None = None
        while len(collected) < max_objects:
            chunk_limit = min(RECENT_SOURCE_MAX_LIMIT, max_objects - len(collected))
            chunk = self._feed.list_review_window(
                anchor_feed_at=marker.anchor_feed_at,
                anchor_object_id=marker.anchor_object_id,
                snapshot_top_feed_at=snapshot_top_feed_at,
                snapshot_top_object_id=snapshot_top_object_id,
                after_feed_at=after_feed_at,
                after_object_id=after_object_id,
                limit=chunk_limit,
                direction=direction,
            )
            if not chunk.items:
                break
            collected.extend(chunk.items)
            if not chunk.has_more:
                break
            last = chunk.items[-1]
            after_feed_at = inbox_feed_at(last)
            after_object_id = last.id
        if len(collected) > max_objects:
            return None
        return collected

    def _list_continuation(
        self, *, limit: int, cursor: str, direction: str
    ) -> InboxSinceReviewMarkerPage:
        frozen = decode_inbox_review_snapshot_cursor(cursor)
        if frozen.direction != direction:
            raise ValidationError("invalid inbox review cursor")
        frozen_marker = ReviewMarkerRecord(
            anchor_feed_at=frozen.anchor_feed_at,
            anchor_object_id=frozen.anchor_object_id,
            updated_at=frozen.anchor_feed_at,
        )
        page = self._feed.list_review_window(
            anchor_feed_at=frozen.anchor_feed_at,
            anchor_object_id=frozen.anchor_object_id,
            snapshot_top_feed_at=frozen.snapshot_top_feed_at,
            snapshot_top_object_id=frozen.snapshot_top_object_id,
            after_feed_at=frozen.last_feed_at,
            after_object_id=frozen.last_object_id,
            limit=limit,
            direction=direction,
        )
        return self._page_from_window(
            marker=frozen_marker,
            snapshot_top_object_id=frozen.snapshot_top_object_id,
            snapshot_top_feed_at=frozen.snapshot_top_feed_at,
            page=page,
            direction=direction,
        )


def _direction_for_purpose(purpose: str) -> str:
    if purpose == "review":
        return "asc"
    return "desc"
