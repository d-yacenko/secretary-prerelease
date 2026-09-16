"""Bounded RFC5545 occurrence expansion via python-dateutil."""

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rruleset, rrulestr

from app.connectors.yandex.constants import (
    MAX_YANDEX_FALLBACK_RECURRENCE_CANDIDATES,
    MAX_YANDEX_FALLBACK_RECURRENCE_SCAN,
)
from app.connectors.yandex.errors import YandexConnectorError


def serialize_recurrence_id(
    value: datetime,
    *,
    all_day: bool,
    tzid: str | None,
    utc_dtstart: bool,
) -> str:
    if all_day:
        as_utc = value if value.tzinfo is None else value.astimezone(UTC)
        return as_utc.strftime("%Y%m%d")
    if tzid:
        try:
            zone = ZoneInfo(tzid)
        except (KeyError, ValueError) as exc:
            raise YandexConnectorError("unsupported DTSTART TZID for recurrence identity") from exc
        return value.astimezone(zone).strftime("%Y%m%dT%H%M%S")
    as_utc = value if value.tzinfo is None else value.astimezone(UTC)
    if utc_dtstart:
        return as_utc.strftime("%Y%m%dT%H%M%SZ")
    return as_utc.strftime("%Y%m%dT%H%M%S")


def build_rruleset(
    dtstart: datetime,
    rrule_value: str,
    exdates: list[datetime],
    rdates: list[datetime],
) -> rruleset:
    raw = rrule_value.strip()
    if not raw:
        raise YandexConnectorError("malformed RRULE")
    if not raw.upper().startswith("RRULE:"):
        raw = f"RRULE:{raw}"
    try:
        rule = rrulestr(raw, dtstart=dtstart)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise YandexConnectorError("unsupported or malformed RRULE") from exc
    collected = rruleset()
    collected.rrule(rule)
    for excluded in exdates:
        collected.exdate(excluded)
    for added in rdates:
        collected.rdate(added)
    return collected


def occurrences_in_window(
    rule_set: rruleset,
    time_min: datetime,
    time_max: datetime,
    *,
    candidate_cap: int = MAX_YANDEX_FALLBACK_RECURRENCE_CANDIDATES,
    scan_cap: int = MAX_YANDEX_FALLBACK_RECURRENCE_SCAN,
) -> list[datetime]:
    found: list[datetime] = []
    scanned = 0
    for raw in rule_set:
        scanned += 1
        if scanned > scan_cap:
            raise YandexConnectorError("fallback recurrence scan exceeded bound")
        occ = raw
        if occ.tzinfo is None:
            occ = occ.replace(tzinfo=UTC)
        else:
            occ = occ.astimezone(UTC)
        if occ > time_max:
            break
        if occ < time_min:
            continue
        if len(found) >= candidate_cap:
            raise YandexConnectorError(
                "fallback recurrence exceeded MAX_YANDEX_FALLBACK_RECURRENCE_CANDIDATES"
            )
        found.append(occ)
    return found


def apply_duration(start: datetime, duration: timedelta) -> datetime:
    return start + duration


_DURATION_WEEK = re.compile(r"^\+?P(\d+)W$")
_DURATION_DATE_TIME = re.compile(
    r"^\+?P(?:(\d+)D)?(?:T(?=\d)(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$"
)


def parse_rfc5545_duration(raw: str) -> timedelta:
    value = (raw or "").strip().upper()
    if not value or value.startswith("-"):
        raise YandexConnectorError("malformed DURATION")
    week_match = _DURATION_WEEK.fullmatch(value)
    if week_match:
        weeks = int(week_match.group(1))
        try:
            return timedelta(weeks=weeks)
        except OverflowError as exc:
            raise YandexConnectorError("malformed DURATION") from exc
    match = _DURATION_DATE_TIME.fullmatch(value)
    if match is None:
        raise YandexConnectorError("malformed DURATION")
    days, hours, minutes, seconds = match.groups()
    if days is None and hours is None and minutes is None and seconds is None:
        raise YandexConnectorError("malformed DURATION")
    try:
        return timedelta(
            days=int(days or 0),
            hours=int(hours or 0),
            minutes=int(minutes or 0),
            seconds=int(seconds or 0),
        )
    except OverflowError as exc:
        raise YandexConnectorError("malformed DURATION") from exc
