"""Availability A — deterministic free/busy from confirmed calendar commitments."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.api.schemas import ObjectCreate
from app.core.client_timezone import resolve_client_timezone
from app.db.models import Object, UserSettings
from app.domain.object_visibility import tombstone_object
from app.domain.temporal_hint import KIND_TEMPORAL_HINT, LIFECYCLE_UNRESOLVED
from app.services.availability_service import AvailabilityService
from app.services.calendar_event_query import WEEK_CALENDAR_PROVIDERS
from app.services.graph_service import GraphService
from app.services.temporal_signals_constants import (
    METADATA_END_PRECISION,
    METADATA_EVIDENCE_COUNT,
    METADATA_LIFECYCLE,
    METADATA_PARTICIPATION,
    METADATA_PRIMARY_EVIDENCE_KIND,
    METADATA_PRIMARY_EVIDENCE_PROVIDER,
    METADATA_START_PRECISION,
)
from app.services.week_service import WeekService
from app.users.bootstrap import BOOTSTRAP_USER_ID

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
DAY = datetime(2026, 9, 7, 0, 0, tzinfo=AMSTERDAM)
WINDOW_START = DAY + timedelta(hours=9)
WINDOW_END = DAY + timedelta(hours=18)
WEEK_START = "2026-09-07"


def _graph(session) -> GraphService:
    return GraphService(session, BOOTSTRAP_USER_ID)


def _availability(session) -> AvailabilityService:
    return AvailabilityService(session, BOOTSTRAP_USER_ID)


def _query(session, **kwargs):
    params = {
        "start_at": WINDOW_START,
        "end_at": WINDOW_END,
        "timezone": "Europe/Amsterdam",
        "min_duration_minutes": 30,
    }
    params.update(kwargs)
    return _availability(session).query(**params)


def _event(
    graph: GraphService,
    *,
    title: str,
    start_at: datetime,
    due_at: datetime | None,
    provider: str = "google_calendar",
    state: str = "observed",
    status: str | None = None,
    kind: str = "event",
    metadata: dict | None = None,
) -> Object:
    return graph.create_object(
        ObjectCreate(
            kind=kind,
            title=title,
            origin="source",
            state=state,
            provider=provider,
            start_at=start_at,
            due_at=due_at,
            status=status,
            metadata=metadata or {},
            external_id=f"ext-{title}",
        )
    )


def _task(graph: GraphService, *, title: str, start_at: datetime, end_at: datetime) -> Object:
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin="user",
            status="open",
            planned_start_at=start_at,
            planned_end_at=end_at,
        )
    )


def _hint(graph: GraphService, *, title: str, start_at: datetime) -> Object:
    return graph.create_object(
        ObjectCreate(
            kind=KIND_TEMPORAL_HINT,
            title=title,
            origin="system",
            state="observed",
            start_at=start_at,
            metadata={
                METADATA_LIFECYCLE: LIFECYCLE_UNRESOLVED,
                METADATA_START_PRECISION: "exact",
                METADATA_END_PRECISION: "unknown",
                METADATA_PARTICIPATION: "expected",
                METADATA_PRIMARY_EVIDENCE_PROVIDER: "gmail",
                METADATA_PRIMARY_EVIDENCE_KIND: "email",
                METADATA_EVIDENCE_COUNT: 1,
            },
            confidence=0.9,
        )
    )


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


def _iso(value: datetime) -> str:
    return value.isoformat()


def test_empty_calendar_entire_window_free(db_session) -> None:
    result = _query(db_session)
    assert result["availability_complete"] is True
    assert result["busy_intervals"] == []
    assert result["unknown_end_event_ids"] == []
    assert len(result["free_intervals"]) == 1
    free = result["free_intervals"][0]
    assert free["start_at"] == WINDOW_START
    assert free["end_at"] == WINDOW_END
    assert free["duration_minutes"] == 9 * 60


def test_one_hard_event_free_before_and_after(db_session) -> None:
    graph = _graph(db_session)
    event = _event(
        graph,
        title="Office",
        start_at=DAY + timedelta(hours=11),
        due_at=DAY + timedelta(hours=12),
    )
    result = _query(db_session)
    assert result["availability_complete"] is True
    assert len(result["busy_intervals"]) == 1
    busy = result["busy_intervals"][0]
    assert busy["start_at"] == DAY + timedelta(hours=11)
    assert busy["end_at"] == DAY + timedelta(hours=12)
    assert busy["event_ids"] == [event.id]
    free = [(row["start_at"], row["end_at"], row["duration_minutes"]) for row in result["free_intervals"]]
    assert free == [
        (WINDOW_START, DAY + timedelta(hours=11), 120),
        (DAY + timedelta(hours=12), WINDOW_END, 6 * 60),
    ]


def test_event_clipped_at_query_start(db_session) -> None:
    graph = _graph(db_session)
    _event(
        graph,
        title="Early",
        start_at=DAY + timedelta(hours=8),
        due_at=DAY + timedelta(hours=10),
    )
    result = _query(db_session)
    busy = result["busy_intervals"][0]
    assert busy["start_at"] == WINDOW_START
    assert busy["end_at"] == DAY + timedelta(hours=10)
    assert result["free_intervals"][0]["start_at"] == DAY + timedelta(hours=10)


def test_event_clipped_at_query_end(db_session) -> None:
    graph = _graph(db_session)
    _event(
        graph,
        title="Late",
        start_at=DAY + timedelta(hours=17),
        due_at=DAY + timedelta(hours=19),
    )
    result = _query(db_session)
    busy = result["busy_intervals"][0]
    assert busy["start_at"] == DAY + timedelta(hours=17)
    assert busy["end_at"] == WINDOW_END
    assert result["free_intervals"][-1]["end_at"] == DAY + timedelta(hours=17)


def test_overlapping_google_and_yandex_events_merge(db_session) -> None:
    graph = _graph(db_session)
    google = _event(
        graph,
        title="Google overlap",
        start_at=DAY + timedelta(hours=10),
        due_at=DAY + timedelta(hours=11, minutes=30),
        provider="google_calendar",
    )
    yandex = _event(
        graph,
        title="Yandex overlap",
        start_at=DAY + timedelta(hours=11),
        due_at=DAY + timedelta(hours=12),
        provider="yandex_calendar",
    )
    result = _query(db_session)
    assert len(result["busy_intervals"]) == 1
    busy = result["busy_intervals"][0]
    assert busy["start_at"] == DAY + timedelta(hours=10)
    assert busy["end_at"] == DAY + timedelta(hours=12)
    assert set(busy["event_ids"]) == {google.id, yandex.id}
    google_row = db_session.get(Object, google.id)
    yandex_row = db_session.get(Object, yandex.id)
    assert google_row is not None and yandex_row is not None
    assert google_row.id != yandex_row.id


def test_directly_adjacent_hard_events_merge(db_session) -> None:
    graph = _graph(db_session)
    first = _event(
        graph,
        title="First",
        start_at=DAY + timedelta(hours=10),
        due_at=DAY + timedelta(hours=11),
    )
    second = _event(
        graph,
        title="Second",
        start_at=DAY + timedelta(hours=11),
        due_at=DAY + timedelta(hours=12),
        provider="yandex_calendar",
    )
    result = _query(db_session)
    assert len(result["busy_intervals"]) == 1
    busy = result["busy_intervals"][0]
    assert busy["start_at"] == DAY + timedelta(hours=10)
    assert busy["end_at"] == DAY + timedelta(hours=12)
    assert set(busy["event_ids"]) == {first.id, second.id}
    free_starts = [row["start_at"] for row in result["free_intervals"]]
    assert DAY + timedelta(hours=11) not in free_starts


def test_merged_interval_retains_contributing_event_ids(db_session) -> None:
    graph = _graph(db_session)
    a = _event(
        graph,
        title="A",
        start_at=DAY + timedelta(hours=10),
        due_at=DAY + timedelta(hours=12),
    )
    b = _event(
        graph,
        title="B",
        start_at=DAY + timedelta(hours=11),
        due_at=DAY + timedelta(hours=13),
        provider="yandex_calendar",
    )
    c = _event(
        graph,
        title="C",
        start_at=DAY + timedelta(hours=12, minutes=30),
        due_at=DAY + timedelta(hours=13),
    )
    result = _query(db_session)
    assert len(result["busy_intervals"]) == 1
    assert set(result["busy_intervals"][0]["event_ids"]) == {a.id, b.id, c.id}
    assert result["busy_intervals"][0]["event_ids"] == sorted({a.id, b.id, c.id}, key=str)


def test_free_intervals_shorter_than_min_duration_filtered(db_session) -> None:
    graph = _graph(db_session)
    _event(
        graph,
        title="Morning",
        start_at=DAY + timedelta(hours=9),
        due_at=DAY + timedelta(hours=10),
    )
    _event(
        graph,
        title="Late morning",
        start_at=DAY + timedelta(hours=10, minutes=20),
        due_at=DAY + timedelta(hours=18),
    )
    result = _query(db_session, min_duration_minutes=30)
    assert result["free_intervals"] == []


def test_exact_boundary_free_interval_accepted(db_session) -> None:
    graph = _graph(db_session)
    _event(
        graph,
        title="Morning",
        start_at=DAY + timedelta(hours=9),
        due_at=DAY + timedelta(hours=10),
    )
    _event(
        graph,
        title="Afternoon",
        start_at=DAY + timedelta(hours=10, minutes=30),
        due_at=DAY + timedelta(hours=18),
    )
    result = _query(db_session, min_duration_minutes=30)
    assert len(result["free_intervals"]) == 1
    free = result["free_intervals"][0]
    assert free["start_at"] == DAY + timedelta(hours=10)
    assert free["end_at"] == DAY + timedelta(hours=10, minutes=30)
    assert free["duration_minutes"] == 30


def test_google_calendar_event_blocks(db_session) -> None:
    graph = _graph(db_session)
    _event(
        graph,
        title="Google block",
        provider="google_calendar",
        start_at=DAY + timedelta(hours=10),
        due_at=DAY + timedelta(hours=11),
    )
    result = _query(db_session)
    assert result["busy_intervals"][0]["start_at"] == DAY + timedelta(hours=10)
    assert result["busy_intervals"][0]["end_at"] == DAY + timedelta(hours=11)


def test_yandex_calendar_event_blocks(db_session) -> None:
    graph = _graph(db_session)
    _event(
        graph,
        title="Yandex block",
        provider="yandex_calendar",
        start_at=DAY + timedelta(hours=14),
        due_at=DAY + timedelta(hours=15),
    )
    result = _query(db_session)
    assert result["busy_intervals"][0]["start_at"] == DAY + timedelta(hours=14)
    assert result["busy_intervals"][0]["end_at"] == DAY + timedelta(hours=15)


def test_scheduled_work_does_not_block(db_session) -> None:
    graph = _graph(db_session)
    _task(
        graph,
        title="Planned desk work",
        start_at=DAY + timedelta(hours=10),
        end_at=DAY + timedelta(hours=11),
    )
    result = _query(db_session)
    assert result["busy_intervals"] == []
    assert result["free_intervals"][0]["start_at"] == WINDOW_START
    assert result["free_intervals"][0]["end_at"] == WINDOW_END
    occupied = [
        row
        for row in result["free_intervals"]
        if row["start_at"] <= DAY + timedelta(hours=10)
        and row["end_at"] >= DAY + timedelta(hours=11)
    ]
    assert occupied


def test_temporal_hint_does_not_block(db_session) -> None:
    _enable_temporal(db_session)
    graph = _graph(db_session)
    _hint(graph, title="Possible call", start_at=DAY + timedelta(hours=10))
    result = _query(db_session)
    assert result["busy_intervals"] == []
    assert result["free_intervals"][0]["duration_minutes"] == 9 * 60


def test_non_calendar_event_provider_does_not_block(db_session) -> None:
    graph = _graph(db_session)
    _event(
        graph,
        title="Mail shaped event",
        provider="gmail",
        start_at=DAY + timedelta(hours=10),
        due_at=DAY + timedelta(hours=11),
    )
    assert "gmail" not in WEEK_CALENDAR_PROVIDERS
    result = _query(db_session)
    assert result["busy_intervals"] == []


def test_rejected_event_does_not_block(db_session) -> None:
    graph = _graph(db_session)
    _event(
        graph,
        title="Rejected meeting",
        start_at=DAY + timedelta(hours=10),
        due_at=DAY + timedelta(hours=11),
        state="rejected",
    )
    result = _query(db_session)
    assert result["busy_intervals"] == []


def test_deleted_event_does_not_block(db_session) -> None:
    graph = _graph(db_session)
    deleted = _event(
        graph,
        title="Deleted meeting",
        start_at=DAY + timedelta(hours=10),
        due_at=DAY + timedelta(hours=11),
    )
    tombstone_object(deleted)
    db_session.flush()
    result = _query(db_session)
    assert result["busy_intervals"] == []
    leftover = db_session.get(Object, deleted.id)
    assert leftover is not None
    assert leftover.deleted_at is not None


def test_all_day_event_blocks_intersected_range(db_session) -> None:
    graph = _graph(db_session)
    _event(
        graph,
        title="Holiday",
        start_at=datetime(2026, 9, 7, tzinfo=UTC),
        due_at=datetime(2026, 9, 8, tzinfo=UTC),
        metadata={"all_day": True},
    )
    result = _query(db_session)
    assert len(result["busy_intervals"]) == 1
    busy = result["busy_intervals"][0]
    assert busy["start_at"] == WINDOW_START
    assert busy["end_at"] == WINDOW_END
    assert result["free_intervals"] == []


def test_unknown_end_hard_event_fails_closed(db_session) -> None:
    graph = _graph(db_session)
    known = _event(
        graph,
        title="Known end",
        start_at=DAY + timedelta(hours=10),
        due_at=DAY + timedelta(hours=11),
    )
    unknown = _event(
        graph,
        title="Unknown end",
        start_at=DAY + timedelta(hours=14),
        due_at=None,
    )
    result = _query(db_session)
    assert result["availability_complete"] is False
    assert result["unknown_end_event_ids"] == [unknown.id]
    assert result["free_intervals"] == []
    assert len(result["busy_intervals"]) == 1
    assert result["busy_intervals"][0]["event_ids"] == [known.id]
    stored = db_session.get(Object, unknown.id)
    assert stored is not None
    assert stored.due_at is None


def test_unknown_end_hard_event_starting_before_window_fails_closed(db_session) -> None:
    graph = _graph(db_session)
    unknown = _event(
        graph,
        title="Unknown before window",
        start_at=DAY + timedelta(hours=8),
        due_at=None,
    )
    result = _query(db_session)
    assert result["availability_complete"] is False
    assert result["unknown_end_event_ids"] == [unknown.id]
    assert result["free_intervals"] == []
    stored = db_session.get(Object, unknown.id)
    assert stored is not None
    assert stored.due_at is None
    assert stored.start_at == DAY + timedelta(hours=8)


def test_unknown_end_hard_event_at_or_after_window_end_is_irrelevant(db_session) -> None:
    graph = _graph(db_session)
    at_end = _event(
        graph,
        title="Unknown at window end",
        start_at=WINDOW_END,
        due_at=None,
    )
    after_end = _event(
        graph,
        title="Unknown after window end",
        start_at=WINDOW_END + timedelta(hours=1),
        due_at=None,
    )
    result = _query(db_session)
    assert result["availability_complete"] is True
    assert result["unknown_end_event_ids"] == []
    assert result["free_intervals"][0]["start_at"] == WINDOW_START
    assert result["free_intervals"][0]["end_at"] == WINDOW_END
    leftover_at = db_session.get(Object, at_end.id)
    leftover_after = db_session.get(Object, after_end.id)
    assert leftover_at is not None and leftover_at.due_at is None
    assert leftover_after is not None and leftover_after.due_at is None


def test_known_end_event_starting_before_window_clips_and_blocks(db_session) -> None:
    graph = _graph(db_session)
    event = _event(
        graph,
        title="Starts before window",
        start_at=DAY + timedelta(hours=8),
        due_at=DAY + timedelta(hours=10, minutes=30),
    )
    result = _query(db_session)
    assert result["availability_complete"] is True
    busy = result["busy_intervals"][0]
    assert busy["start_at"] == WINDOW_START
    assert busy["end_at"] == DAY + timedelta(hours=10, minutes=30)
    assert busy["event_ids"] == [event.id]
    assert result["free_intervals"][0]["start_at"] == DAY + timedelta(hours=10, minutes=30)


def test_more_than_five_hundred_hard_events_cannot_cause_false_free(db_session) -> None:
    late_start = DAY + timedelta(hours=17)
    late_end = DAY + timedelta(hours=18)
    fillers = [
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="event",
            title=f"Filler {index}",
            origin="source",
            state="observed",
            provider="google_calendar",
            start_at=DAY + timedelta(hours=9, seconds=index),
            due_at=DAY + timedelta(hours=9, seconds=index + 1),
            external_id=f"filler-{index}",
            metadata_={},
        )
        for index in range(500)
    ]
    late = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="event",
        title="Late blocker",
        origin="source",
        state="observed",
        provider="google_calendar",
        start_at=late_start,
        due_at=late_end,
        external_id="late-blocker",
        metadata_={},
    )
    db_session.add_all([*fillers, late])
    db_session.flush()

    result = _query(db_session)
    assert result["availability_complete"] is True
    late_utc_start = late_start.astimezone(UTC)
    late_utc_end = late_end.astimezone(UTC)
    covering = [
        row
        for row in result["busy_intervals"]
        if late.id in row["event_ids"]
        and row["start_at"] == late_utc_start
        and row["end_at"] == late_utc_end
    ]
    assert covering, "event beyond the former 500-cap must occupy 17:00–18:00"
    for row in result["free_intervals"]:
        overlaps_late = row["start_at"] < late_utc_end and row["end_at"] > late_utc_start
        assert not overlaps_late


def test_week_unknown_end_hard_events_remain_start_in_window(db_session) -> None:
    graph = _graph(db_session)
    before_week = _event(
        graph,
        title="Unknown before week",
        start_at=DAY - timedelta(hours=4),
        due_at=None,
    )
    inside_week = _event(
        graph,
        title="Unknown inside week",
        start_at=DAY + timedelta(hours=10),
        due_at=None,
    )
    after_week = _event(
        graph,
        title="Unknown after week",
        start_at=DAY + timedelta(days=7),
        due_at=None,
    )
    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=DAY + timedelta(hours=12),
    )
    week_ids = [obj.id for day in snapshot["days"] for obj in day["events"]]
    assert inside_week.id in week_ids
    assert before_week.id not in week_ids
    assert after_week.id not in week_ids
    leftover = db_session.get(Object, before_week.id)
    assert leftover is not None
    assert leftover.due_at is None


def test_http_naive_start_rejected(auth_client) -> None:
    response = auth_client.get(
        "/availability",
        params={
            "start_at": "2026-09-07T09:00:00",
            "end_at": _iso(WINDOW_END),
            "client_timezone_id": "Europe/Amsterdam",
        },
    )
    assert response.status_code == 422


def test_http_naive_end_rejected(auth_client) -> None:
    response = auth_client.get(
        "/availability",
        params={
            "start_at": _iso(WINDOW_START),
            "end_at": "2026-09-07T18:00:00",
            "client_timezone_id": "Europe/Amsterdam",
        },
    )
    assert response.status_code == 422


def test_http_end_not_after_start_rejected(auth_client) -> None:
    equal = auth_client.get(
        "/availability",
        params={
            "start_at": _iso(WINDOW_START),
            "end_at": _iso(WINDOW_START),
            "client_timezone_id": "Europe/Amsterdam",
        },
    )
    assert equal.status_code == 422
    before = auth_client.get(
        "/availability",
        params={
            "start_at": _iso(WINDOW_END),
            "end_at": _iso(WINDOW_START),
            "client_timezone_id": "Europe/Amsterdam",
        },
    )
    assert before.status_code == 422


def test_http_window_larger_than_seven_days_rejected(auth_client) -> None:
    response = auth_client.get(
        "/availability",
        params={
            "start_at": _iso(WINDOW_START),
            "end_at": _iso(WINDOW_START + timedelta(days=7, seconds=1)),
            "client_timezone_id": "Europe/Amsterdam",
        },
    )
    assert response.status_code == 422


def test_http_invalid_min_duration_rejected(auth_client) -> None:
    too_small = auth_client.get(
        "/availability",
        params={
            "start_at": _iso(WINDOW_START),
            "end_at": _iso(WINDOW_END),
            "min_duration_minutes": 4,
            "client_timezone_id": "Europe/Amsterdam",
        },
    )
    assert too_small.status_code == 422
    too_large = auth_client.get(
        "/availability",
        params={
            "start_at": _iso(WINDOW_START),
            "end_at": _iso(WINDOW_END),
            "min_duration_minutes": 1441,
            "client_timezone_id": "Europe/Amsterdam",
        },
    )
    assert too_large.status_code == 422


def test_timezone_resolution_matches_week(db_session, auth_client, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_timezone", "Europe/Moscow")
    assert resolve_client_timezone("Europe/Amsterdam") == "Europe/Amsterdam"
    week = auth_client.get(
        "/week",
        params={"week_start": WEEK_START, "client_timezone_id": "Europe/Amsterdam"},
    )
    availability = auth_client.get(
        "/availability",
        params={
            "start_at": _iso(WINDOW_START),
            "end_at": _iso(WINDOW_END),
            "client_timezone_id": "Europe/Amsterdam",
        },
    )
    assert week.status_code == 200
    assert availability.status_code == 200
    assert week.json()["timezone"] == "Europe/Amsterdam"
    assert availability.json()["timezone"] == "Europe/Amsterdam"
    bad = auth_client.get(
        "/availability",
        params={
            "start_at": _iso(WINDOW_START),
            "end_at": _iso(WINDOW_END),
            "client_timezone_id": "Not/AZone",
        },
    )
    assert bad.status_code == 422
    week_bad = auth_client.get(
        "/week",
        params={"week_start": WEEK_START, "client_timezone_id": "Not/AZone"},
    )
    assert week_bad.status_code == 422


def test_dst_aware_absolute_interval_europe_amsterdam(db_session) -> None:
    tz = ZoneInfo("Europe/Amsterdam")
    day_start = datetime(2026, 3, 29, 0, 0, tzinfo=tz)
    day_end = datetime(2026, 3, 30, 0, 0, tzinfo=tz)
    assert day_end.astimezone(UTC) - day_start.astimezone(UTC) == timedelta(hours=23)
    busy_span = datetime(2026, 3, 29, 4, 0, tzinfo=tz).astimezone(UTC) - datetime(
        2026, 3, 29, 1, 0, tzinfo=tz
    ).astimezone(UTC)
    assert busy_span == timedelta(hours=2)
    empty = _query(
        db_session,
        start_at=day_start,
        end_at=day_end,
        timezone="Europe/Amsterdam",
        min_duration_minutes=30,
    )
    assert empty["availability_complete"] is True
    assert empty["free_intervals"][0]["duration_minutes"] == 23 * 60
    graph = _graph(db_session)
    _event(
        graph,
        title="Across spring forward",
        start_at=datetime(2026, 3, 29, 1, 0, tzinfo=tz),
        due_at=datetime(2026, 3, 29, 4, 0, tzinfo=tz),
    )
    result = _query(
        db_session,
        start_at=day_start,
        end_at=day_end,
        timezone="Europe/Amsterdam",
        min_duration_minutes=30,
    )
    busy = result["busy_intervals"][0]
    assert busy["end_at"].astimezone(UTC) - busy["start_at"].astimezone(UTC) == timedelta(
        hours=2
    )
    assert result["free_intervals"][0]["duration_minutes"] == 60
    assert result["free_intervals"][1]["duration_minutes"] == 20 * 60


def test_http_endpoint_does_not_mutate_db(db_session, auth_client) -> None:
    graph = _graph(db_session)
    event = _event(
        graph,
        title="Office",
        start_at=DAY + timedelta(hours=10),
        due_at=DAY + timedelta(hours=11),
    )
    db_session.flush()
    before = db_session.execute(
        select(
            Object.id,
            Object.updated_at,
            Object.title,
            Object.start_at,
            Object.due_at,
            Object.deleted_at,
            Object.state,
        ).order_by(Object.id)
    ).all()
    count_before = db_session.scalar(select(func.count()).select_from(Object))
    response = auth_client.get(
        "/availability",
        params={
            "start_at": _iso(WINDOW_START),
            "end_at": _iso(WINDOW_END),
            "min_duration_minutes": 30,
            "client_timezone_id": "Europe/Amsterdam",
            "client_utc_offset_minutes": 120,
        },
    )
    assert response.status_code == 200
    db_session.expire_all()
    after = db_session.execute(
        select(
            Object.id,
            Object.updated_at,
            Object.title,
            Object.start_at,
            Object.due_at,
            Object.deleted_at,
            Object.state,
        ).order_by(Object.id)
    ).all()
    count_after = db_session.scalar(select(func.count()).select_from(Object))
    assert before == after
    assert count_before == count_after
    stored = db_session.get(Object, event.id)
    assert stored is not None
    assert stored.title == "Office"


def test_week_layers_unchanged_and_only_hard_blocks_availability(db_session) -> None:
    _enable_temporal(db_session)
    graph = _graph(db_session)
    event = _event(
        graph,
        title="Google review",
        start_at=DAY + timedelta(hours=10),
        due_at=DAY + timedelta(hours=11),
    )
    task = _task(
        graph,
        title="Desk work",
        start_at=DAY + timedelta(hours=12),
        end_at=DAY + timedelta(hours=13),
    )
    hint = _hint(graph, title="Possible call", start_at=DAY + timedelta(hours=14))
    snapshot = WeekService(db_session, BOOTSTRAP_USER_ID).snapshot(
        week_start=WEEK_START,
        timezone="Europe/Amsterdam",
        reference_at=DAY + timedelta(hours=12),
    )
    monday = snapshot["days"][0]
    assert [obj.id for obj in monday["events"]] == [event.id]
    assert [obj.id for obj in monday["scheduled_work"]] == [task.id]
    assert [obj.id for obj in monday["temporal_hints"]] == [hint.id]
    result = _query(db_session)
    assert result["availability_complete"] is True
    assert [row["event_ids"] for row in result["busy_intervals"]] == [[event.id]]
    free_spans = [(row["start_at"], row["end_at"]) for row in result["free_intervals"]]
    assert (DAY + timedelta(hours=12), DAY + timedelta(hours=13)) not in [
        (row["start_at"], row["end_at"]) for row in result["busy_intervals"]
    ]
    assert any(
        start <= DAY + timedelta(hours=12) and end >= DAY + timedelta(hours=13)
        for start, end in free_spans
    )
    assert any(
        start <= DAY + timedelta(hours=14) < end for start, end in free_spans
    )


def test_http_availability_compact_response_and_defaults(db_session, auth_client) -> None:
    graph = _graph(db_session)
    event = _event(
        graph,
        title="Office",
        start_at=DAY + timedelta(hours=10),
        due_at=DAY + timedelta(hours=11),
    )
    db_session.flush()
    response = auth_client.get(
        "/availability",
        params={
            "start_at": _iso(WINDOW_START),
            "end_at": _iso(WINDOW_END),
            "client_timezone_id": "Europe/Amsterdam",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["timezone"] == "Europe/Amsterdam"
    assert payload["min_duration_minutes"] == 30
    assert payload["availability_complete"] is True
    assert payload["unknown_end_event_ids"] == []
    assert payload["busy_intervals"][0]["event_ids"] == [str(event.id)]
    assert "title" not in payload["busy_intervals"][0]
    assert "body" not in payload["busy_intervals"][0]
    assert "metadata" not in payload["busy_intervals"][0]
    assert "description" not in payload["busy_intervals"][0]
    assert all("duration_minutes" in row for row in payload["free_intervals"])


def test_http_accepts_utc_z_suffix(auth_client) -> None:
    response = auth_client.get(
        "/availability",
        params={
            "start_at": "2026-09-07T07:00:00Z",
            "end_at": "2026-09-07T16:00:00Z",
            "client_timezone_id": "Europe/Amsterdam",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["availability_complete"] is True
    assert payload["min_duration_minutes"] == 30

