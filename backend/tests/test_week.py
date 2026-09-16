import inspect
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

import app.services.week_service as week_service_module
from app.api.schemas import ObjectCreate
from app.db.models import Object, User, UserSettings
from app.services.errors import ValidationError
from app.services.graph_service import GraphService
from app.services.week_service import WeekService, parse_week_start
from app.users.bootstrap import BOOTSTRAP_USER_ID

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
WEEK_START = "2026-09-07"
WEEK_MONDAY = datetime(2026, 9, 7, 0, 0, tzinfo=AMSTERDAM)
WEEK_NEXT_MONDAY = datetime(2026, 9, 14, 0, 0, tzinfo=AMSTERDAM)


def _event(
    graph: GraphService,
    *,
    title: str,
    start_at: datetime,
    due_at: datetime | None,
    provider: str = "google_calendar",
    metadata: dict | None = None,
    kind: str = "event",
    origin: str = "source",
    state: str = "observed",
    status: str | None = None,
    external_id: str | None = None,
) -> Object:
    obj = graph.create_object(
        ObjectCreate(
            kind=kind,
            title=title,
            origin=origin,
            state=state,
            provider=provider,
            start_at=start_at,
            due_at=due_at,
            metadata=metadata or {},
            status=status,
            external_id=external_id,
        )
    )
    return obj


def _enable_temporal(session, *, enabled: bool = True) -> None:
    row = session.get(UserSettings, BOOTSTRAP_USER_ID)
    if row is None:
        row = UserSettings(
            user_id=BOOTSTRAP_USER_ID,
            temporal_signals_enabled=enabled,
            timezone="Europe/Amsterdam",
        )
        session.add(row)
    else:
        row.temporal_signals_enabled = enabled
    session.flush()


def test_week_merges_google_and_yandex_chronologically(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    yandex = _event(
        graph,
        title="Yandex standup",
        provider="yandex_calendar",
        start_at=WEEK_MONDAY + timedelta(hours=9),
        due_at=WEEK_MONDAY + timedelta(hours=9, minutes=30),
        external_id="yandex-1",
    )
    google = _event(
        graph,
        title="Google review",
        provider="google_calendar",
        start_at=WEEK_MONDAY + timedelta(hours=10),
        due_at=WEEK_MONDAY + timedelta(hours=11),
        external_id="google-1",
    )
    earlier_google = _event(
        graph,
        title="Google breakfast",
        provider="google_calendar",
        start_at=WEEK_MONDAY + timedelta(hours=8),
        due_at=WEEK_MONDAY + timedelta(hours=8, minutes=30),
        external_id="google-0",
    )

    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    monday_events = snapshot["days"][0]["events"]
    titles = [obj.title for obj in monday_events]
    assert titles == ["Google breakfast", "Yandex standup", "Google review"]
    providers = [obj.provider for obj in monday_events]
    assert providers == ["google_calendar", "yandex_calendar", "google_calendar"]
    assert [obj.id for obj in monday_events] == [earlier_google.id, yandex.id, google.id]


def test_week_monday_boundary_included_next_monday_excluded(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    _event(
        graph,
        title="Monday open",
        start_at=WEEK_MONDAY,
        due_at=WEEK_MONDAY + timedelta(hours=1),
        external_id="mon-open",
    )
    _event(
        graph,
        title="Next Monday open",
        start_at=WEEK_NEXT_MONDAY,
        due_at=WEEK_NEXT_MONDAY + timedelta(hours=1),
        external_id="next-mon-open",
    )

    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    titles = [obj.title for day in snapshot["days"] for obj in day["events"]]
    assert "Monday open" in titles
    assert "Next Monday open" not in titles
    assert snapshot["window_start"] == WEEK_MONDAY
    assert snapshot["window_end"] == WEEK_NEXT_MONDAY


def test_week_previous_and_next_week_isolation(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    _event(
        graph,
        title="Previous Sunday",
        start_at=WEEK_MONDAY - timedelta(hours=2),
        due_at=WEEK_MONDAY - timedelta(hours=1),
        external_id="prev-sun",
    )
    _event(
        graph,
        title="This Tuesday",
        start_at=WEEK_MONDAY + timedelta(days=1, hours=11),
        due_at=WEEK_MONDAY + timedelta(days=1, hours=12),
        external_id="tue",
    )
    _event(
        graph,
        title="Following Tuesday",
        start_at=WEEK_NEXT_MONDAY + timedelta(days=1, hours=11),
        due_at=WEEK_NEXT_MONDAY + timedelta(days=1, hours=12),
        external_id="next-tue",
    )

    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    titles = [obj.title for day in snapshot["days"] for obj in day["events"]]
    assert titles == ["This Tuesday"]

    previous = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start="2026-08-31",
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    previous_titles = [obj.title for day in previous["days"] for obj in day["events"]]
    assert previous_titles == ["Previous Sunday"]


def test_week_returns_materialized_occurrence_without_rrule_expansion(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    _event(
        graph,
        title="Weekly master",
        start_at=datetime(2025, 1, 6, 10, 0, tzinfo=AMSTERDAM),
        due_at=datetime(2025, 1, 6, 11, 0, tzinfo=AMSTERDAM),
        metadata={"rrule": "FREQ=WEEKLY;BYDAY=MO", "recurrence_id": None},
        external_id="master-weekly",
    )
    occurrence = _event(
        graph,
        title="Weekly occurrence",
        start_at=WEEK_MONDAY + timedelta(hours=10),
        due_at=WEEK_MONDAY + timedelta(hours=11),
        metadata={"recurrence_id": "20260907T080000Z", "rrule": None},
        external_id="master-weekly:20260907T080000Z",
    )

    source = inspect.getsource(week_service_module)
    assert "calendar_recurrence" not in source
    assert "occurrences_in_window" not in source
    assert "build_rruleset" not in source

    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    events = [obj for day in snapshot["days"] for obj in day["events"]]
    assert [obj.id for obj in events] == [occurrence.id]
    assert events[0].metadata_["recurrence_id"] == "20260907T080000Z"


def test_week_includes_cross_midnight_and_multiday_overlap(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    _event(
        graph,
        title="Cross midnight",
        start_at=WEEK_MONDAY + timedelta(hours=23),
        due_at=WEEK_MONDAY + timedelta(days=1, hours=1),
        external_id="cross",
    )
    _event(
        graph,
        title="Trip",
        start_at=WEEK_MONDAY + timedelta(days=2, hours=18),
        due_at=WEEK_MONDAY + timedelta(days=4, hours=10),
        external_id="trip",
    )
    _event(
        graph,
        title="All-day conference",
        start_at=datetime(2026, 9, 9, tzinfo=UTC),
        due_at=datetime(2026, 9, 11, tzinfo=UTC),
        metadata={"all_day": True},
        external_id="all-day-conf",
    )

    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    by_date = {day["date"]: [obj.title for obj in day["events"]] for day in snapshot["days"]}
    assert "Cross midnight" in by_date["2026-09-07"]
    assert "Cross midnight" in by_date["2026-09-08"]
    assert "Trip" in by_date["2026-09-09"]
    assert "Trip" in by_date["2026-09-10"]
    assert "Trip" in by_date["2026-09-11"]
    assert "Trip" not in by_date["2026-09-12"]
    assert by_date["2026-09-09"][0] == "All-day conference"
    assert by_date["2026-09-10"][0] == "All-day conference"
    assert "All-day conference" not in by_date["2026-09-11"]


def test_week_excludes_non_calendar_objects(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    graph.create_object(
        ObjectCreate(
            kind="task",
            title="Task due this week",
            origin="user",
            state="confirmed",
            due_at=WEEK_MONDAY + timedelta(hours=12),
        )
    )
    graph.create_object(
        ObjectCreate(
            kind="email",
            title="Email",
            origin="source",
            state="observed",
            provider="gmail",
            start_at=WEEK_MONDAY + timedelta(hours=9),
            due_at=WEEK_MONDAY + timedelta(hours=10),
        )
    )
    graph.create_object(
        ObjectCreate(
            kind="message",
            title="Telegram hint",
            origin="source",
            state="observed",
            start_at=WEEK_MONDAY + timedelta(hours=9),
        )
    )
    _event(
        graph,
        title="Note pretending",
        kind="note",
        provider="google_calendar",
        start_at=WEEK_MONDAY + timedelta(hours=9),
        due_at=WEEK_MONDAY + timedelta(hours=10),
        origin="user",
        state="confirmed",
        external_id="note-cal",
    )
    _event(
        graph,
        title="Kept meeting",
        start_at=WEEK_MONDAY + timedelta(hours=15),
        due_at=WEEK_MONDAY + timedelta(hours=16),
        external_id="kept",
    )

    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    titles = [obj.title for day in snapshot["days"] for obj in day["events"]]
    assert titles == ["Kept meeting"]


def test_week_user_scope(db_session) -> None:
    other_id = uuid.uuid4()
    db_session.add(User(id=other_id, display_name="User B"))
    db_session.flush()
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID)
    graph_b = GraphService(db_session, other_id)
    _event(
        graph_a,
        title="Mine",
        start_at=WEEK_MONDAY + timedelta(hours=10),
        due_at=WEEK_MONDAY + timedelta(hours=11),
        external_id="mine",
    )
    _event(
        graph_b,
        title="Theirs",
        start_at=WEEK_MONDAY + timedelta(hours=10),
        due_at=WEEK_MONDAY + timedelta(hours=11),
        external_id="theirs",
    )

    snapshot_a = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    snapshot_b = WeekService(db_session, other_id).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    assert [obj.title for day in snapshot_a["days"] for obj in day["events"]] == ["Mine"]
    assert [obj.title for day in snapshot_b["days"] for obj in day["events"]] == ["Theirs"]


def test_week_empty_response(db_session) -> None:
    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    assert snapshot["week_start"] == WEEK_START
    assert snapshot["week_end"] == "2026-09-14"
    assert len(snapshot["days"]) == 7
    assert all(day["events"] == [] for day in snapshot["days"])
    assert all(day["temporal_hints"] == [] for day in snapshot["days"])
    assert [day["date"] for day in snapshot["days"]] == [
        "2026-09-07",
        "2026-09-08",
        "2026-09-09",
        "2026-09-10",
        "2026-09-11",
        "2026-09-12",
        "2026-09-13",
    ]


def test_week_dst_local_midnight_boundaries(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    dst_week_start = datetime(2026, 3, 23, 0, 0, tzinfo=AMSTERDAM)
    dst_week_end = datetime(2026, 3, 30, 0, 0, tzinfo=AMSTERDAM)
    assert dst_week_start.utcoffset() != dst_week_end.utcoffset()
    _event(
        graph,
        title="Monday midnight",
        start_at=dst_week_start,
        due_at=dst_week_start + timedelta(hours=1),
        external_id="dst-open",
    )
    _event(
        graph,
        title="After spring forward",
        start_at=datetime(2026, 3, 29, 3, 30, tzinfo=AMSTERDAM),
        due_at=datetime(2026, 3, 29, 4, 30, tzinfo=AMSTERDAM),
        external_id="dst-after",
    )
    _event(
        graph,
        title="Next Monday midnight",
        start_at=dst_week_end,
        due_at=dst_week_end + timedelta(hours=1),
        external_id="dst-close",
    )

    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start="2026-03-23",
        timezone="Europe/Amsterdam",
        reference_at=datetime(2026, 3, 26, 12, 0, tzinfo=AMSTERDAM),
    )
    assert snapshot["window_start"] == dst_week_start
    assert snapshot["window_end"] == dst_week_end
    titles = [obj.title for day in snapshot["days"] for obj in day["events"]]
    assert "Monday midnight" in titles
    assert "After spring forward" in titles
    assert "Next Monday midnight" not in titles


def test_week_all_day_orders_before_timed_and_tie_breaks_by_id(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    later = _event(
        graph,
        title="Later timed",
        start_at=WEEK_MONDAY + timedelta(hours=11),
        due_at=WEEK_MONDAY + timedelta(hours=12),
        external_id="timed-late",
    )
    earlier = _event(
        graph,
        title="Earlier timed",
        start_at=WEEK_MONDAY + timedelta(hours=9),
        due_at=WEEK_MONDAY + timedelta(hours=10),
        external_id="timed-early",
    )
    all_day_b = _event(
        graph,
        title="All day B",
        start_at=datetime(2026, 9, 7, tzinfo=UTC),
        due_at=datetime(2026, 9, 8, tzinfo=UTC),
        external_id="all-b",
    )
    all_day_a = _event(
        graph,
        title="All day A",
        start_at=datetime(2026, 9, 7, tzinfo=UTC),
        due_at=datetime(2026, 9, 8, tzinfo=UTC),
        external_id="all-a",
    )
    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    monday = snapshot["days"][0]["events"]
    assert [obj.title for obj in monday[:2]] == (
        ["All day A", "All day B"]
        if all_day_a.id < all_day_b.id
        else ["All day B", "All day A"]
    )
    assert [obj.title for obj in monday[2:]] == ["Earlier timed", "Later timed"]
    assert earlier.id != later.id


def test_week_overlapping_events_both_visible(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    _event(
        graph,
        title="Google overlap",
        provider="google_calendar",
        start_at=WEEK_MONDAY + timedelta(hours=14),
        due_at=WEEK_MONDAY + timedelta(hours=16),
        external_id="g-overlap",
    )
    _event(
        graph,
        title="Yandex overlap",
        provider="yandex_calendar",
        start_at=WEEK_MONDAY + timedelta(hours=15),
        due_at=WEEK_MONDAY + timedelta(hours=17),
        external_id="y-overlap",
    )
    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    titles = [obj.title for obj in snapshot["days"][0]["events"]]
    assert titles == ["Google overlap", "Yandex overlap"]


def test_parse_week_start_rejects_non_monday_and_invalid() -> None:
    try:
        parse_week_start("2026-09-08", AMSTERDAM)
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        assert "Monday" in exc.message
    try:
        parse_week_start("not-a-date", AMSTERDAM)
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        assert "invalid week_start" in exc.message


def test_http_week_empty_and_validation(auth_client) -> None:
    empty = auth_client.get(
        "/week",
        params={
            "week_start": WEEK_START,
            "client_timezone_id": "Europe/Amsterdam",
        },
    )
    assert empty.status_code == 200
    payload = empty.json()
    assert payload["week_start"] == WEEK_START
    assert payload["week_end"] == "2026-09-14"
    assert payload["timezone"] == "Europe/Amsterdam"
    assert len(payload["days"]) == 7
    assert all(day["events"] == [] for day in payload["days"])
    assert all(day["temporal_hints"] == [] for day in payload["days"])

    invalid = auth_client.get(
        "/week",
        params={"week_start": "2026-09-08", "client_timezone_id": "Europe/Amsterdam"},
    )
    assert invalid.status_code == 422

    bad_tz = auth_client.get(
        "/week",
        params={"week_start": WEEK_START, "client_timezone_id": "Not/AZone"},
    )
    assert bad_tz.status_code == 422


def test_http_week_returns_object_ids_and_all_day(db_session, auth_client) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    timed = _event(
        graph,
        title="Office",
        provider="yandex_calendar",
        start_at=WEEK_MONDAY + timedelta(hours=10),
        due_at=WEEK_MONDAY + timedelta(hours=11),
        external_id="http-timed",
    )
    all_day = _event(
        graph,
        title="Holiday",
        start_at=datetime(2026, 9, 7, tzinfo=UTC),
        due_at=datetime(2026, 9, 8, tzinfo=UTC),
        external_id="http-all-day",
    )
    db_session.flush()

    response = auth_client.get(
        "/week",
        params={
            "week_start": WEEK_START,
            "client_timezone_id": "Europe/Amsterdam",
        },
    )
    assert response.status_code == 200
    monday = response.json()["days"][0]["events"]
    assert [row["title"] for row in monday] == ["Holiday", "Office"]
    assert monday[0]["id"] == str(all_day.id)
    assert monday[0]["all_day"] is True
    assert monday[0]["provider"] == "google_calendar"
    assert monday[1]["id"] == str(timed.id)
    assert monday[1]["all_day"] is False
    assert monday[1]["provider"] == "yandex_calendar"
    assert "calendar_events" not in response.json()
    assert "tasks" not in response.json()
    assert "notifications" not in response.json()


def test_week_does_not_use_inbox_feed_fields(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    _event(
        graph,
        title="Created this week but starts later",
        start_at=WEEK_NEXT_MONDAY + timedelta(hours=10),
        due_at=WEEK_NEXT_MONDAY + timedelta(hours=11),
        metadata={"feed_at": WEEK_MONDAY.isoformat()},
        external_id="feed-trap",
    )
    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    titles = [obj.title for day in snapshot["days"] for obj in day["events"]]
    assert titles == []
    leftover = db_session.scalar(select(Object).where(Object.title == "Created this week but starts later"))
    assert leftover is not None


def _hint(graph: GraphService, *, title: str, start_at: datetime, due_at: datetime | None, metadata: dict | None = None) -> Object:
    from app.domain.temporal_hint import KIND_TEMPORAL_HINT, LIFECYCLE_UNRESOLVED
    from app.services.temporal_signals_constants import (
        METADATA_END_PRECISION,
        METADATA_EVIDENCE_COUNT,
        METADATA_LIFECYCLE,
        METADATA_PARTICIPATION,
        METADATA_PRIMARY_EVIDENCE_KIND,
        METADATA_PRIMARY_EVIDENCE_PROVIDER,
    )

    meta = {
        METADATA_LIFECYCLE: LIFECYCLE_UNRESOLVED,
        METADATA_END_PRECISION: "exact" if due_at is not None else "unknown",
        METADATA_PARTICIPATION: "expected",
        METADATA_PRIMARY_EVIDENCE_PROVIDER: "gmail",
        METADATA_PRIMARY_EVIDENCE_KIND: "email",
        METADATA_EVIDENCE_COUNT: 1,
    }
    if metadata:
        meta.update(metadata)
    return graph.create_object(
        ObjectCreate(
            kind=KIND_TEMPORAL_HINT,
            title=title,
            origin="system",
            state="observed",
            start_at=start_at,
            due_at=due_at,
            metadata=meta,
            confidence=0.9,
        )
    )


def test_week_temporal_hints_are_additive_and_not_events(db_session) -> None:
    from app.domain.temporal_hint import KIND_TEMPORAL_HINT, LIFECYCLE_SUPERSEDED_BY_CALENDAR
    from app.services.calendar_event_query import WEEK_CALENDAR_PROVIDERS, active_event_predicates
    from app.services.temporal_signals_constants import METADATA_LIFECYCLE

    _enable_temporal(db_session)

    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    google = _event(
        graph,
        title="Google review",
        start_at=WEEK_MONDAY + timedelta(hours=10),
        due_at=WEEK_MONDAY + timedelta(hours=11),
        external_id="g-hint-week",
    )
    yandex = _event(
        graph,
        title="Yandex standup",
        provider="yandex_calendar",
        start_at=WEEK_MONDAY + timedelta(hours=9),
        due_at=WEEK_MONDAY + timedelta(hours=9, minutes=30),
        external_id="y-hint-week",
    )
    known = _hint(
        graph,
        title="Known duration hint",
        start_at=WEEK_MONDAY + timedelta(hours=14),
        due_at=WEEK_MONDAY + timedelta(hours=15),
    )
    unknown = _hint(
        graph,
        title="Unknown duration hint",
        start_at=WEEK_MONDAY + timedelta(hours=16),
        due_at=None,
    )
    _hint(
        graph,
        title="Superseded hint",
        start_at=WEEK_MONDAY + timedelta(hours=11),
        due_at=WEEK_MONDAY + timedelta(hours=12),
        metadata={METADATA_LIFECYCLE: LIFECYCLE_SUPERSEDED_BY_CALENDAR},
    )

    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    monday_events = [obj.title for obj in snapshot["days"][0]["events"]]
    monday_hints = snapshot["days"][0]["temporal_hints"]
    assert monday_events == ["Yandex standup", "Google review"]
    assert [obj.title for obj in monday_hints] == ["Known duration hint", "Unknown duration hint"]
    assert google.kind == "event" and yandex.kind == "event"
    assert known.kind == KIND_TEMPORAL_HINT and unknown.due_at is None
    calendar_rows = list(
        db_session.scalars(select(Object).where(*active_event_predicates(BOOTSTRAP_USER_ID)))
    )
    assert known not in calendar_rows
    assert unknown not in calendar_rows
    assert "gmail" not in WEEK_CALENDAR_PROVIDERS


def test_http_week_temporal_hints_omit_source_body(db_session, auth_client) -> None:
    _enable_temporal(db_session)
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    _event(
        graph,
        title="Office",
        start_at=WEEK_MONDAY + timedelta(hours=10),
        due_at=WEEK_MONDAY + timedelta(hours=11),
        external_id="http-hint-cal",
    )
    hint = _hint(
        graph,
        title="Call",
        start_at=WEEK_MONDAY + timedelta(hours=16),
        due_at=None,
    )
    response = auth_client.get(
        "/week",
        params={"week_start": WEEK_START, "client_timezone_id": "Europe/Amsterdam"},
    )
    assert response.status_code == 200
    monday = response.json()["days"][0]
    assert [row["title"] for row in monday["events"]] == ["Office"]
    assert "body" not in monday["temporal_hints"][0]
    assert monday["temporal_hints"][0]["id"] == str(hint.id)
    assert monday["temporal_hints"][0]["due_at"] is None
    assert monday["temporal_hints"][0]["end_precision"] == "unknown"
    assert monday["temporal_hints"][0]["primary_provider"] == "gmail"
    assert "gmail" not in {row.get("provider") for row in monday["events"]}


def test_week_does_not_project_hints_when_temporal_signals_disabled(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    _event(
        graph,
        title="Office",
        start_at=WEEK_MONDAY + timedelta(hours=10),
        due_at=WEEK_MONDAY + timedelta(hours=11),
        external_id="disabled-hint-cal",
    )
    hint = _hint(
        graph,
        title="Hidden when disabled",
        start_at=WEEK_MONDAY + timedelta(hours=16),
        due_at=None,
    )
    _enable_temporal(db_session, enabled=False)
    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )
    monday = snapshot["days"][0]
    assert [obj.title for obj in monday["events"]] == ["Office"]
    assert monday["temporal_hints"] == []
    leftover = db_session.get(Object, hint.id)
    assert leftover is not None
    assert leftover.deleted_at is None

