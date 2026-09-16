"""Pure recurrence / DST tests for Proactive Secretary Pass B."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.domain.recurrence import RecurrenceSpec, next_occurrence

NY = "America/New_York"
MSK = "Europe/Moscow"


def _spec(kind: str, local_time: str, timezone: str = NY, weekdays: tuple[str, ...] = ()) -> RecurrenceSpec:
    return RecurrenceSpec(
        schedule_kind=kind,
        timezone=timezone,
        local_time=local_time,
        weekdays=weekdays,
    )


def test_spring_forward_2026_shifts_gap_forward_once() -> None:
    spec = _spec("daily", "02:30")
    after = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
    first = next_occurrence(spec, after)
    assert first == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    local = first.astimezone(ZoneInfo(NY))
    assert local.hour == 3
    assert local.minute == 30
    nxt = next_occurrence(spec, first)
    assert nxt == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)
    nxt_local = nxt.astimezone(ZoneInfo(NY))
    assert (nxt_local.hour, nxt_local.minute) == (2, 30)


def test_fall_back_2026_uses_first_fold_only() -> None:
    spec = _spec("daily", "01:30")
    after = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    first = next_occurrence(spec, after)
    assert first == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    local = first.astimezone(ZoneInfo(NY))
    assert (local.hour, local.minute) == (1, 30)
    second_fold = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    nxt = next_occurrence(spec, first)
    assert nxt != second_fold
    assert nxt == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
    between_folds = datetime(2026, 11, 1, 5, 45, tzinfo=UTC)
    skipped_repeat = next_occurrence(spec, between_folds)
    assert skipped_repeat == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)


def test_weekly_crossing_dst_keeps_wall_clock() -> None:
    spec = _spec("weekly", "09:30", weekdays=("sun",))
    before_dst = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    first = next_occurrence(spec, before_dst)
    first_local = first.astimezone(ZoneInfo(NY))
    assert first_local.date().isoformat() == "2026-03-01"
    assert (first_local.hour, first_local.minute) == (9, 30)
    after_transition = datetime(2026, 3, 8, 18, 0, tzinfo=UTC)
    nxt = next_occurrence(spec, after_transition)
    nxt_local = nxt.astimezone(ZoneInfo(NY))
    assert nxt_local.date().isoformat() == "2026-03-15"
    assert nxt_local.weekday() == 6
    assert (nxt_local.hour, nxt_local.minute) == (9, 30)


def test_moscow_non_dst_zone_is_stable() -> None:
    spec = _spec("daily", "09:30", timezone=MSK)
    after = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
    first = next_occurrence(spec, after)
    assert first == datetime(2026, 3, 8, 6, 30, tzinfo=UTC)
    nxt = next_occurrence(spec, first)
    assert nxt == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)
    local = first.astimezone(ZoneInfo(MSK))
    assert (local.hour, local.minute) == (9, 30)
