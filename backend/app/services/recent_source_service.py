from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, String, and_, case, exists, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.orm import Session, aliased

from app.db.models import Object
from app.domain.telegram_mtproto_visibility import telegram_mtproto_active_object_predicate
from app.services.inbox_feed_cursor import decode_inbox_feed_cursor, encode_inbox_feed_cursor

RECENT_SOURCE_KINDS = frozenset(
    {
        "email",
        "event",
        "calendar_event",
        "chat_message",
        "message",
        "file",
        "document",
        "dataset",
        "folder",
    }
)

RECENT_INTAKE_KINDS = frozenset(
    {
        "note",
        "web_page",
        "file",
        "document",
        "dataset",
        "folder",
    }
)

RECENT_SOURCE_DEFAULT_LIMIT = 30
RECENT_SOURCE_MAX_LIMIT = 50
RECENT_SOURCE_EXCERPT_CHARS = 160

GMAIL_NOISE_LABELS = (
    "SPAM",
    "TRASH",
    "CATEGORY_PROMOTIONS",
    "CATEGORY_SOCIAL",
    "CATEGORY_FORUMS",
)

_SOURCE_EVENT_KINDS = ("event", "calendar_event")


def _strictly_newer_than(
    feed_at: ColumnElement[datetime],
    anchor_feed_at: datetime,
    anchor_object_id: UUID,
) -> object:
    return or_(
        feed_at > anchor_feed_at,
        and_(feed_at == anchor_feed_at, Object.id > anchor_object_id),
    )


def _at_or_older_than(
    feed_at: ColumnElement[datetime],
    top_feed_at: datetime,
    top_object_id: UUID,
) -> object:
    return or_(
        feed_at < top_feed_at,
        and_(feed_at == top_feed_at, Object.id <= top_object_id),
    )


def _strictly_older_than(
    feed_at: ColumnElement[datetime],
    last_feed_at: datetime,
    last_object_id: UUID,
) -> object:
    return or_(
        feed_at < last_feed_at,
        and_(feed_at == last_feed_at, Object.id < last_object_id),
    )


def inbox_feed_at(obj: Object) -> datetime:
    if obj.origin == "source":
        if obj.kind in _SOURCE_EVENT_KINDS:
            anchor = obj.start_at or obj.occurred_at or obj.created_at
            return min(anchor, obj.created_at)
        return obj.occurred_at or obj.created_at
    return obj.created_at


def inbox_feed_at_sql() -> ColumnElement[datetime]:
    calendar_anchor = func.coalesce(
        Object.start_at,
        Object.occurred_at,
        Object.created_at,
    )
    source_event_at = func.least(calendar_anchor, Object.created_at)
    source_object_at = func.coalesce(
        Object.occurred_at,
        Object.created_at,
    )
    return case(
        (
            Object.origin == "source",
            case(
                (Object.kind.in_(_SOURCE_EVENT_KINDS), source_event_at),
                else_=source_object_at,
            ),
        ),
        (
            or_(Object.origin == "explicit", Object.origin == "user"),
            Object.created_at,
        ),
        else_=Object.created_at,
    )


def _metadata_text(model, key: str):
    return func.nullif(func.btrim(model.metadata_[key].as_string()), "")


def _future_at_materialization(model):
    return and_(model.start_at.is_not(None), model.start_at > model.created_at)


def _yandex_calendar_identity(model):
    return func.coalesce(
        _metadata_text(model, "calendar_id"),
        _metadata_text(model, "calendar_href"),
    )


def _google_series_addressable(model):
    return and_(
        model.provider == "google_calendar",
        model.kind.in_(_SOURCE_EVENT_KINDS),
        _metadata_text(model, "calendar_id").is_not(None),
        _metadata_text(model, "recurring_event_id").is_not(None),
    )


def _yandex_series_addressable(model):
    return and_(
        model.provider == "yandex_calendar",
        model.kind.in_(_SOURCE_EVENT_KINDS),
        _metadata_text(model, "event_uid").is_not(None),
        _metadata_text(model, "recurrence_id").is_not(None),
        _yandex_calendar_identity(model).is_not(None),
    )


def _is_series_addressable(model):
    return or_(_google_series_addressable(model), _yandex_series_addressable(model))


def _same_recurring_series(left, right):
    google = and_(
        _google_series_addressable(left),
        _google_series_addressable(right),
        _metadata_text(left, "calendar_id") == _metadata_text(right, "calendar_id"),
        _metadata_text(left, "recurring_event_id")
        == _metadata_text(right, "recurring_event_id"),
    )
    yandex = and_(
        _yandex_series_addressable(left),
        _yandex_series_addressable(right),
        _yandex_calendar_identity(left) == _yandex_calendar_identity(right),
        _metadata_text(left, "event_uid") == _metadata_text(right, "event_uid"),
    )
    return or_(google, yandex)


def _earlier_series_representative(candidate, current):
    return or_(
        candidate.start_at < current.start_at,
        and_(
            candidate.start_at == current.start_at,
            candidate.created_at < current.created_at,
        ),
        and_(
            candidate.start_at == current.start_at,
            candidate.created_at == current.created_at,
            candidate.id < current.id,
        ),
    )


@dataclass(frozen=True)
class InboxFeedPage:
    items: list[Object]
    next_cursor: str | None
    has_more: bool


class RecentSourceService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    @staticmethod
    def _gmail_feed_eligible_clause(model=Object) -> object:
        labels = model.metadata_["labels"]
        noise_any = labels.op("?|")(
            array(GMAIL_NOISE_LABELS, type_=ARRAY(String)),
        )
        return or_(
            model.provider != "gmail",
            labels.is_(None),
            ~noise_any,
        )

    @staticmethod
    def _not_child_email_attachment_clause(model=Object) -> object:
        parent_email_id = model.metadata_["parent_email_id"].as_string()
        return ~and_(
            model.origin == "source",
            model.kind == "file",
            parent_email_id.is_not(None),
            parent_email_id != "",
        )

    def _source_feed_clause(self, model=Object) -> object:
        return and_(
            model.origin == "source",
            model.kind.in_(tuple(RECENT_SOURCE_KINDS)),
        )

    def _intake_feed_clause(self, model=Object) -> object:
        return and_(
            or_(model.origin == "explicit", model.origin == "user"),
            model.kind.in_(tuple(RECENT_INTAKE_KINDS)),
            model.kind != "task",
        )

    def _not_outbound_chat_clause(self, model=Object) -> object:
        direction = model.metadata_["direction"].as_string()
        return ~and_(
            model.provider.in_(("telegram", "teams")),
            model.kind == "chat_message",
            direction == "outbound",
        )

    def _base_eligible_filters(self, model=Object) -> object:
        return and_(
            model.user_id == self._user_id,
            or_(self._source_feed_clause(model), self._intake_feed_clause(model)),
            model.state != "rejected",
            model.deleted_at.is_(None),
            or_(model.status.is_(None), model.status != "deleted"),
            self._gmail_feed_eligible_clause(model),
            self._not_child_email_attachment_clause(model),
            self._not_outbound_chat_clause(model),
            telegram_mtproto_active_object_predicate(model),
        )

    def _not_suppressed_future_recurrence_sibling(self) -> object:
        sibling = aliased(Object)
        earlier_sibling = exists(
            select(sibling.id).where(
                self._base_eligible_filters(sibling),
                sibling.id != Object.id,
                _is_series_addressable(sibling),
                _future_at_materialization(sibling),
                _same_recurring_series(Object, sibling),
                _earlier_series_representative(sibling, Object),
            )
        )
        return ~and_(
            _is_series_addressable(Object),
            _future_at_materialization(Object),
            earlier_sibling,
        )

    def _eligible_filters(self) -> object:
        return and_(
            self._base_eligible_filters(),
            self._not_suppressed_future_recurrence_sibling(),
        )

    def get_inbox_eligible(self, object_id: UUID) -> Object | None:
        return self._session.scalar(
            select(Object).where(Object.id == object_id, self._eligible_filters())
        )

    def list_strictly_newer_than(
        self,
        anchor_feed_at: datetime,
        anchor_object_id: UUID,
        limit: int = RECENT_SOURCE_DEFAULT_LIMIT,
    ) -> InboxFeedPage:
        """Inbox-eligible objects strictly newer than the persisted review-marker tuple.

        Canonical order is feed_at DESC, id DESC. The anchor itself is excluded.
        """
        bounded_limit = min(max(limit, 1), RECENT_SOURCE_MAX_LIMIT)
        feed_at = inbox_feed_at_sql()
        stmt = (
            select(Object)
            .where(self._eligible_filters())
            .where(
                or_(
                    feed_at > anchor_feed_at,
                    and_(feed_at == anchor_feed_at, Object.id > anchor_object_id),
                )
            )
            .order_by(feed_at.desc(), Object.id.desc())
        )
        rows = list(self._session.scalars(stmt.limit(bounded_limit + 1)))
        has_more = len(rows) > bounded_limit
        items = rows[:bounded_limit]
        return InboxFeedPage(items=items, next_cursor=None, has_more=has_more)

    def count_review_window(
        self,
        *,
        anchor_feed_at: datetime,
        anchor_object_id: UUID,
        snapshot_top_feed_at: datetime,
        snapshot_top_object_id: UUID,
    ) -> int:
        feed_at = inbox_feed_at_sql()
        stmt = (
            select(func.count())
            .select_from(Object)
            .where(self._eligible_filters())
            .where(_strictly_newer_than(feed_at, anchor_feed_at, anchor_object_id))
            .where(
                _at_or_older_than(feed_at, snapshot_top_feed_at, snapshot_top_object_id)
            )
        )
        return int(self._session.scalar(stmt) or 0)

    def count_older_in_review_window(
        self,
        *,
        anchor_feed_at: datetime,
        anchor_object_id: UUID,
        snapshot_top_feed_at: datetime,
        snapshot_top_object_id: UUID,
        last_feed_at: datetime,
        last_object_id: UUID,
    ) -> int:
        feed_at = inbox_feed_at_sql()
        stmt = (
            select(func.count())
            .select_from(Object)
            .where(self._eligible_filters())
            .where(_strictly_newer_than(feed_at, anchor_feed_at, anchor_object_id))
            .where(
                _at_or_older_than(feed_at, snapshot_top_feed_at, snapshot_top_object_id)
            )
            .where(_strictly_older_than(feed_at, last_feed_at, last_object_id))
        )
        return int(self._session.scalar(stmt) or 0)

    def count_newer_in_review_window(
        self,
        *,
        anchor_feed_at: datetime,
        anchor_object_id: UUID,
        snapshot_top_feed_at: datetime,
        snapshot_top_object_id: UUID,
        last_feed_at: datetime,
        last_object_id: UUID,
    ) -> int:
        feed_at = inbox_feed_at_sql()
        stmt = (
            select(func.count())
            .select_from(Object)
            .where(self._eligible_filters())
            .where(_strictly_newer_than(feed_at, anchor_feed_at, anchor_object_id))
            .where(
                _at_or_older_than(feed_at, snapshot_top_feed_at, snapshot_top_object_id)
            )
            .where(_strictly_newer_than(feed_at, last_feed_at, last_object_id))
        )
        return int(self._session.scalar(stmt) or 0)

    def list_review_window(
        self,
        *,
        anchor_feed_at: datetime,
        anchor_object_id: UUID,
        snapshot_top_feed_at: datetime | None,
        snapshot_top_object_id: UUID | None,
        after_feed_at: datetime | None,
        after_object_id: UUID | None,
        limit: int,
        direction: str = "desc",
    ) -> InboxFeedPage:
        bounded_limit = min(max(limit, 1), RECENT_SOURCE_MAX_LIMIT)
        feed_at = inbox_feed_at_sql()
        stmt = (
            select(Object)
            .where(self._eligible_filters())
            .where(_strictly_newer_than(feed_at, anchor_feed_at, anchor_object_id))
        )
        if snapshot_top_feed_at is not None and snapshot_top_object_id is not None:
            stmt = stmt.where(
                _at_or_older_than(feed_at, snapshot_top_feed_at, snapshot_top_object_id)
            )
        if after_feed_at is not None and after_object_id is not None:
            if direction == "asc":
                stmt = stmt.where(
                    _strictly_newer_than(feed_at, after_feed_at, after_object_id)
                )
            else:
                stmt = stmt.where(
                    _strictly_older_than(feed_at, after_feed_at, after_object_id)
                )
        if direction == "asc":
            stmt = stmt.order_by(feed_at.asc(), Object.id.asc())
        else:
            stmt = stmt.order_by(feed_at.desc(), Object.id.desc())
        rows = list(self._session.scalars(stmt.limit(bounded_limit + 1)))
        has_more = len(rows) > bounded_limit
        items = rows[:bounded_limit]
        return InboxFeedPage(items=items, next_cursor=None, has_more=has_more)

    def list_page(
        self,
        limit: int = RECENT_SOURCE_DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> InboxFeedPage:
        bounded_limit = min(max(limit, 1), RECENT_SOURCE_MAX_LIMIT)
        feed_at = inbox_feed_at_sql()
        stmt = (
            select(Object)
            .where(self._eligible_filters())
            .order_by(feed_at.desc(), Object.id.desc())
        )
        if cursor is not None:
            cursor_feed_at, cursor_id = decode_inbox_feed_cursor(cursor)
            stmt = stmt.where(
                or_(
                    feed_at < cursor_feed_at,
                    and_(feed_at == cursor_feed_at, Object.id < cursor_id),
                )
            )
        rows = list(self._session.scalars(stmt.limit(bounded_limit + 1)))
        has_more = len(rows) > bounded_limit
        items = rows[:bounded_limit]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_inbox_feed_cursor(inbox_feed_at(last), last.id)
        return InboxFeedPage(items=items, next_cursor=next_cursor, has_more=has_more)

    def list_recent(self, limit: int = RECENT_SOURCE_DEFAULT_LIMIT) -> list[Object]:
        return self.list_page(limit=limit).items

    @staticmethod
    def excerpt(body: str | None) -> str | None:
        if not body:
            return None
        normalized = body.replace("\\n", " ").replace("\n", " ")
        text = " ".join(normalized.split())
        if len(text) <= RECENT_SOURCE_EXCERPT_CHARS:
            return text
        return text[:RECENT_SOURCE_EXCERPT_CHARS].rstrip() + "…"
