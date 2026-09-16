"""Deterministic wall-clock recurrence and DST helpers (no DB)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_SET = frozenset(WEEKDAYS)
SCHEDULE_KIND_DAILY = "daily"
SCHEDULE_KIND_WEEKLY = "weekly"
RECURRING_SCHEDULE_KINDS = frozenset({SCHEDULE_KIND_DAILY, SCHEDULE_KIND_WEEKLY})
_FIXED_OFFSET_TIMEZONE = frozenset({"+", "-"})


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def instant_to_iso(value: datetime) -> str:
    return as_utc(value).isoformat()


def parse_instant(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return as_utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return as_utc(parsed)


def same_instant(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return False
    return as_utc(left) == as_utc(right)


def parse_local_time(value: str) -> tuple[int, int]:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise ValueError("local_time must be HH:MM")
    hour_text, minute_text = value[:2], value[3:]
    if not hour_text.isdigit() or not minute_text.isdigit():
        raise ValueError("local_time must be HH:MM")
    hour = int(hour_text)
    minute = int(minute_text)
    if hour > 23 or minute > 59:
        raise ValueError("local_time must be HH:MM")
    if hour_text != f"{hour:02d}" or minute_text != f"{minute:02d}":
        raise ValueError("local_time must be HH:MM")
    return hour, minute


def looks_like_fixed_offset_timezone(name: str) -> bool:
    text = name.strip()
    if not text:
        return False
    return text[0] in _FIXED_OFFSET_TIMEZONE


def require_iana_timezone(name: str) -> str:
    text = name.strip()
    if not text:
        raise ValueError("invalid timezone")
    if looks_like_fixed_offset_timezone(text):
        raise ValueError("invalid timezone")
    try:
        ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("invalid timezone") from exc
    return text


def resolve_iana_timezone(explicit: str | None, fallback: str) -> str:
    if explicit is not None and explicit.strip():
        return require_iana_timezone(explicit)
    return require_iana_timezone(fallback)


def canonicalize_weekdays(values: list[str] | None, *, required: bool) -> tuple[str, ...]:
    if not values:
        if required:
            raise ValueError("weekdays are required for weekly schedule")
        return ()
    if not required:
        raise ValueError("weekdays must be empty for daily schedule")
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise TypeError("invalid weekday")
        token = raw.strip().lower()
        if token not in WEEKDAY_SET:
            raise ValueError("invalid weekday")
        if token in seen:
            raise ValueError("duplicate weekday")
        seen.add(token)
    return tuple(day for day in WEEKDAYS if day in seen)


def weekday_token(day: date) -> str:
    return WEEKDAYS[day.weekday()]


def local_wall_instant(zone: ZoneInfo, day: date, hour: int, minute: int) -> datetime:
    """Map local wall time to UTC using fold=0 (earlier / gap-forward)."""
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone, fold=0)
    return as_utc(local)


@dataclass(frozen=True)
class RecurrenceSpec:
    schedule_kind: str
    timezone: str
    local_time: str
    weekdays: tuple[str, ...] = ()

    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def hour_minute(self) -> tuple[int, int]:
        return parse_local_time(self.local_time)


def spec_from_metadata(metadata: dict) -> RecurrenceSpec | None:
    kind = metadata.get("schedule_kind")
    timezone = metadata.get("timezone")
    local_time = metadata.get("local_time")
    if kind not in RECURRING_SCHEDULE_KINDS:
        return None
    if not isinstance(timezone, str) or not isinstance(local_time, str):
        return None
    try:
        require_iana_timezone(timezone)
        parse_local_time(local_time)
        weekdays = canonicalize_weekdays(
            metadata.get("weekdays"),
            required=kind == SCHEDULE_KIND_WEEKLY,
        )
    except (TypeError, ValueError):
        return None
    return RecurrenceSpec(
        schedule_kind=kind,
        timezone=timezone,
        local_time=local_time,
        weekdays=weekdays,
    )


def next_occurrence(spec: RecurrenceSpec, after_instant: datetime) -> datetime:
    after = as_utc(after_instant)
    zone = spec.zone()
    hour, minute = spec.hour_minute()
    start = after.astimezone(zone).date()
    selected = set(spec.weekdays) if spec.schedule_kind == SCHEDULE_KIND_WEEKLY else None
    for offset in range(400):
        day = start + timedelta(days=offset)
        if selected is not None and weekday_token(day) not in selected:
            continue
        instant = local_wall_instant(zone, day, hour, minute)
        if instant > after:
            return instant
    raise ValueError("could not compute next occurrence")
