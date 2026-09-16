from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote, urljoin

from app.connectors.yandex.caldav_transport import CalDavCalendar
from app.connectors.yandex.calendar_normalize import normalize_caldav_event
from app.tools.schemas import CreateCalendarEventCanonicalInput, ToolError

VEVENT_COMPONENT = "VEVENT"
MAX_TARGET_CALENDARS = 10


def compact_operation_id(operation_id: str) -> str:
    compact = operation_id.replace("-", "").lower()
    if len(compact) < 5 or len(compact) > 1024:
        raise ToolError("invalid operation_id")
    return compact


def caldav_uid_from_operation_id(operation_id: str) -> str:
    return f"secretary-{compact_operation_id(operation_id)}@secretary"


def caldav_resource_name(operation_id: str) -> str:
    return quote(caldav_uid_from_operation_id(operation_id), safe="") + ".ics"


def join_calendar_href(calendar_href: str, resource_name: str) -> str:
    base = calendar_href if calendar_href.endswith("/") else f"{calendar_href}/"
    joined = urljoin(base, resource_name)
    if ".." in joined or not joined.startswith("/"):
        raise ToolError("invalid calendar target")
    return joined


def event_href_from_operation_id(calendar_href: str, operation_id: str) -> str:
    return join_calendar_href(calendar_href, caldav_resource_name(operation_id))


def select_unique_vevent_calendar(calendars: list[CalDavCalendar]) -> CalDavCalendar:
    if len(calendars) > MAX_TARGET_CALENDARS:
        raise ToolError("cannot identify default Yandex calendar")
    if not calendars:
        raise ToolError("Yandex calendar is not available")
    vevent_calendars = [
        calendar
        for calendar in calendars
        if VEVENT_COMPONENT in calendar.supported_components
    ]
    if len(vevent_calendars) == 1:
        return vevent_calendars[0]
    raise ToolError("cannot identify default Yandex calendar")


def resolve_unique_vevent_calendar(transport) -> CalDavCalendar:
    return select_unique_vevent_calendar(
        transport.discover_calendars(MAX_TARGET_CALENDARS + 1)
    )


def _escape_ical_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ToolError("calendar event times must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def build_vevent_ics(payload: CreateCalendarEventCanonicalInput) -> str:
    uid = caldav_uid_from_operation_id(payload.operation_id)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Secretary//EN",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{_format_utc(payload.start_at)}",
        f"DTEND:{_format_utc(payload.end_at)}",
        f"SUMMARY:{_escape_ical_text(payload.summary)}",
    ]
    if payload.description:
        lines.append(f"DESCRIPTION:{_escape_ical_text(payload.description)}")
    if payload.location:
        lines.append(f"LOCATION:{_escape_ical_text(payload.location)}")
    lines.extend(["END:VEVENT", "END:VCALENDAR", ""])
    return "\r\n".join(lines)


def ics_has_disallowed_write_fields(ics_text: str) -> bool:
    for line in ics_text.splitlines():
        name = line.split(";", 1)[0].split(":", 1)[0].strip().upper()
        if name in {"ATTENDEE", "RRULE"}:
            return True
    return False


def event_matches_frozen_payload(
    payload: CreateCalendarEventCanonicalInput,
    ics_text: str,
    calendar_href: str,
    event_href: str,
) -> bool:
    if ics_has_disallowed_write_fields(ics_text):
        return False
    parsed = normalize_caldav_event(
        ics_text,
        calendar_href=calendar_href,
        event_href=event_href,
    )
    if parsed is None:
        return False
    metadata = parsed.get("metadata") or {}
    expected_uid = caldav_uid_from_operation_id(payload.operation_id)
    if metadata.get("event_uid") != expected_uid:
        return False
    if parsed.get("title") != payload.summary:
        return False
    start = parsed.get("start_at")
    end = parsed.get("due_at")
    if start is None or end is None:
        return False
    if start.astimezone(UTC) != payload.start_at.astimezone(UTC):
        return False
    if end.astimezone(UTC) != payload.end_at.astimezone(UTC):
        return False
    body = parsed.get("body")
    if (payload.description or None) != (body or None):
        return False
    location = metadata.get("location")
    return (payload.location or None) == (location or None)
