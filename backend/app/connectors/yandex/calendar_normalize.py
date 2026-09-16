from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr
from typing import Any
from zoneinfo import ZoneInfo

from app.connectors.yandex.calendar_recurrence import (
    apply_duration,
    build_rruleset,
    occurrences_in_window,
    parse_rfc5545_duration,
    serialize_recurrence_id,
)
from app.connectors.yandex.constants import MAX_EVENT_BODY_CHARS
from app.connectors.yandex.errors import YandexConnectorError

ICAL_TEXT_NEWLINE_ESCAPE = frozenset({"n", "N"})


def unescape_ical_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not value:
        return value
    result: list[str] = []
    index = 0
    length = len(value)
    while index < length:
        char = value[index]
        if char == "\\" and index + 1 < length:
            escaped = value[index + 1]
            if escaped in ICAL_TEXT_NEWLINE_ESCAPE:
                result.append("\n")
                index += 2
                continue
            if escaped == "\\":
                result.append("\\")
                index += 2
                continue
            if escaped == ",":
                result.append(",")
                index += 2
                continue
            if escaped == ";":
                result.append(";")
                index += 2
                continue
        result.append(char)
        index += 1
    return "".join(result)


def _unfold_ical_lines(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _parse_ical_property(line: str) -> tuple[str, dict[str, str], str] | None:
    if ":" not in line:
        return None
    key, value = line.split(":", 1)
    parts = key.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            param_name, param_value = part.split("=", 1)
            params[param_name.upper()] = param_value
    return name, params, value.strip()


def _parse_ical_datetime_value(value: str, params: dict[str, str]) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    if params.get("VALUE") == "DATE" or (len(raw) == 8 and raw.isdigit()):
        return datetime.fromisoformat(f"{raw}T00:00:00+00:00")
    tzid = params.get("TZID")
    if tzid:
        try:
            zone = ZoneInfo(tzid)
        except (KeyError, ValueError):
            return None
        raw = raw.removesuffix("Z")
        if "T" in raw:
            date_part, time_part = raw.split("T", 1)
            year = int(date_part[0:4])
            month = int(date_part[4:6])
            day = int(date_part[6:8])
            hour = int(time_part[0:2])
            minute = int(time_part[2:4])
            second = int(time_part[4:6]) if len(time_part) >= 6 else 0
            local = datetime(year, month, day, hour, minute, second, tzinfo=zone)
            return local.astimezone(UTC)
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


MAX_ATTENDEES_IN_METADATA = 20


def _ical_email(value: str | None) -> str | None:
    if not value:
        return None
    raw = unescape_ical_text(value) or value
    raw = raw.strip()
    if raw.lower().startswith("mailto:"):
        raw = raw[7:]
    _, addr = parseaddr(raw)
    candidate = (addr or raw).strip().strip("<>").strip()
    if "@" not in candidate or any(ch.isspace() for ch in candidate):
        return None
    return candidate


def _parse_vevent_block(block: str) -> dict[str, Any]:
    fields: dict[str, str] = {}
    property_params: dict[str, dict[str, str]] = {}
    attendees: list[str] = []
    attendees_truncated = False
    nested_depth = 0
    exdates: list[tuple[dict[str, str], str]] = []
    rdates: list[tuple[dict[str, str], str]] = []
    for line in _unfold_ical_lines(block):
        upper = line.strip().upper()
        if upper.startswith("BEGIN:") and not upper.startswith("BEGIN:VEVENT"):
            nested_depth += 1
            continue
        if nested_depth:
            if upper.startswith("END:"):
                nested_depth -= 1
            continue
        parsed = _parse_ical_property(line)
        if parsed is None:
            continue
        name, params, value = parsed
        if name == "ATTENDEE":
            email = _ical_email(value)
            if email and email not in attendees:
                if len(attendees) < MAX_ATTENDEES_IN_METADATA:
                    attendees.append(email)
                else:
                    attendees_truncated = True
            continue
        if name == "EXDATE":
            exdates.append((params, value))
            continue
        if name == "RDATE":
            rdates.append((params, value))
            continue
        if name == "RRULE":
            if "RRULE" in fields:
                raise YandexConnectorError("multiple RRULE properties in one VEVENT")
            fields[name] = value
            property_params[name] = params
            continue
        if name == "DURATION":
            if "DURATION" in fields:
                raise YandexConnectorError("multiple DURATION properties in one VEVENT")
            fields[name] = value
            property_params[name] = params
            continue
        if name in {
            "UID",
            "SUMMARY",
            "DESCRIPTION",
            "DTSTART",
            "DTEND",
            "LOCATION",
            "STATUS",
            "LAST-MODIFIED",
            "RECURRENCE-ID",
            "ORGANIZER",
        }:
            fields[name] = value
            property_params[name] = params
    return {
        "fields": fields,
        "params": property_params,
        "attendees": attendees,
        "attendees_truncated": attendees_truncated,
        "exdates": exdates,
        "rdates": rdates,
    }


def extract_vevent_blocks(ical_text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    in_event = False
    for line in ical_text.splitlines():
        upper = line.upper()
        if upper.startswith("BEGIN:VEVENT"):
            in_event = True
            current = [line]
            continue
        if in_event:
            current.append(line)
            if upper.startswith("END:VEVENT"):
                blocks.append("\n".join(current))
                in_event = False
    return blocks


def build_occurrence_identity(event_uid: str, recurrence_id: str | None) -> str:
    if recurrence_id:
        return f"{event_uid}@{recurrence_id}"
    return event_uid


def build_external_id(
    calendar_href: str,
    event_uid: str,
    recurrence_id: str | None = None,
) -> str:
    calendar_key = calendar_href.rstrip("/")
    identity = build_occurrence_identity(event_uid, recurrence_id)
    return f"{calendar_key}:{identity}"


def _multi_ical_datetimes(entries: list[tuple[dict[str, str], str]]) -> list[datetime]:
    values: list[datetime] = []
    for params, raw in entries:
        for part in raw.split(","):
            parsed = _parse_ical_datetime_value(part.strip(), params)
            if parsed is None:
                raise YandexConnectorError("malformed EXDATE/RDATE")
            values.append(parsed)
    return values


def _in_window(start_at: datetime | None, time_min: datetime | None, time_max: datetime | None) -> bool:
    if time_min is None or time_max is None or start_at is None:
        return True
    return time_min <= start_at <= time_max


def _normalized_from_component(
    parsed: dict[str, Any],
    *,
    calendar_href: str,
    calendar_summary: str | None,
    etag: str | None,
    event_href: str | None,
    start_at: datetime | None,
    end_at: datetime | None,
    recurrence_id: str | None,
    expansion: str | None,
    include_rrule: bool,
) -> dict[str, Any]:
    fields = parsed["fields"]
    attendees = parsed["attendees"]
    attendees_truncated = parsed["attendees_truncated"]
    event_uid = fields["UID"]
    description = unescape_ical_text(fields.get("DESCRIPTION"))
    body = description[:MAX_EVENT_BODY_CHARS] if description else None
    title = unescape_ical_text(fields.get("SUMMARY")) or f"Calendar event {event_uid}"
    location = unescape_ical_text(fields.get("LOCATION"))
    metadata: dict[str, Any] = {
        "calendar_href": calendar_href,
        "calendar_id": calendar_href.rstrip("/"),
        "event_uid": event_uid,
        "calendar_summary": calendar_summary,
        "event_href": event_href,
        "etag": etag,
        "status": fields.get("STATUS"),
        "location": location,
        "last_modified": fields.get("LAST-MODIFIED"),
        "recurrence_id": recurrence_id,
        "rrule": fields.get("RRULE") if include_rrule else None,
    }
    if expansion:
        metadata["recurrence_expansion"] = expansion
    organizer = _ical_email(fields.get("ORGANIZER"))
    if organizer:
        metadata["organizer"] = organizer
    if attendees:
        metadata["attendees"] = [{"email": email} for email in attendees]
    if attendees_truncated:
        metadata["attendees_truncated"] = True
    dtstart_params = parsed["params"].get("DTSTART") or {}
    tzid = dtstart_params.get("TZID")
    if tzid:
        metadata["dtstart_tzid"] = tzid
    return {
        "external_id": build_external_id(calendar_href, event_uid, recurrence_id),
        "kind": "event",
        "provider": "yandex_calendar",
        "origin": "source",
        "state": "observed",
        "title": title,
        "body": body,
        "start_at": start_at,
        "due_at": end_at,
        "occurred_at": start_at,
        "metadata": metadata,
    }


def _dtstart_identity_flags(params: dict[str, str], raw: str) -> tuple[bool, str | None, bool]:
    all_day = params.get("VALUE") == "DATE" or (len(raw.strip()) == 8 and raw.strip().isdigit())
    tzid = params.get("TZID")
    utc_dtstart = (not all_day) and (not tzid) and raw.strip().endswith("Z")
    return all_day, tzid, utc_dtstart


def _align_recurrence_datetime(value: datetime, tzid: str | None) -> datetime:
    if not tzid:
        return value
    try:
        zone = ZoneInfo(tzid)
    except (KeyError, ValueError) as exc:
        raise YandexConnectorError("unsupported DTSTART TZID for recurrence") from exc
    return value.astimezone(zone)


def _master_occurrence_duration(
    *,
    master_start: datetime,
    master_end: datetime | None,
    duration_raw: str | None,
    all_day: bool,
) -> timedelta:
    has_end = master_end is not None
    has_duration = bool(duration_raw)
    if has_end and has_duration:
        raise YandexConnectorError("VEVENT must not include both DTEND and DURATION")
    if has_end:
        duration = master_end - master_start
        if duration.total_seconds() < 0:
            raise YandexConnectorError("invalid DTEND before DTSTART")
        return duration
    if has_duration:
        return parse_rfc5545_duration(duration_raw or "")
    if all_day:
        return timedelta(days=1)
    return timedelta(0)


@dataclass
class CalDavNormalizeResult:
    events: list[dict[str, Any]]
    occurrence_set_complete: bool
    recurrence_master_uid: str | None = None
    used_fallback: bool = False
    occurrence_coverage_min: datetime | None = None
    occurrence_coverage_max: datetime | None = None


def normalize_caldav_resource(
    ical_text: str,
    calendar_href: str,
    calendar_summary: str | None = None,
    etag: str | None = None,
    event_href: str | None = None,
    time_min: datetime | None = None,
    time_max: datetime | None = None,
    allow_fallback: bool = False,
    fallback_min: datetime | None = None,
    fallback_max: datetime | None = None,
) -> CalDavNormalizeResult:
    parsed_blocks = [_parse_vevent_block(block) for block in extract_vevent_blocks(ical_text)]
    masters = [
        item
        for item in parsed_blocks
        if item["fields"].get("UID")
        and item["fields"].get("RRULE")
        and not item["fields"].get("RECURRENCE-ID")
    ]
    overrides = [
        item
        for item in parsed_blocks
        if item["fields"].get("UID") and item["fields"].get("RECURRENCE-ID")
    ]
    plains = [
        item
        for item in parsed_blocks
        if item["fields"].get("UID")
        and not item["fields"].get("RRULE")
        and not item["fields"].get("RECURRENCE-ID")
    ]

    if not masters:
        events: list[dict[str, Any]] = []
        for parsed in plains + overrides:
            fields = parsed["fields"]
            params = parsed["params"]
            start_at = _parse_ical_datetime_value(fields.get("DTSTART", ""), params.get("DTSTART", {}))
            end_at = _parse_ical_datetime_value(fields.get("DTEND", ""), params.get("DTEND", {}))
            if not _in_window(start_at, time_min, time_max):
                continue
            events.append(
                _normalized_from_component(
                    parsed,
                    calendar_href=calendar_href,
                    calendar_summary=calendar_summary,
                    etag=etag,
                    event_href=event_href,
                    start_at=start_at,
                    end_at=end_at,
                    recurrence_id=fields.get("RECURRENCE-ID"),
                    expansion="provider" if fields.get("RECURRENCE-ID") else None,
                    include_rrule=False,
                )
            )
        return CalDavNormalizeResult(
            events=events,
            occurrence_set_complete=True,
            occurrence_coverage_min=time_min,
            occurrence_coverage_max=time_max,
        )

    if len(masters) > 1:
        raise YandexConnectorError("multiple RRULE masters in one calendar resource")
    expand_min = fallback_min if fallback_min is not None else time_min
    expand_max = fallback_max if fallback_max is not None else time_max
    if not allow_fallback or expand_min is None or expand_max is None:
        events = []
        for parsed in overrides + plains:
            fields = parsed["fields"]
            params = parsed["params"]
            if fields.get("RRULE") and not fields.get("RECURRENCE-ID"):
                continue
            start_at = _parse_ical_datetime_value(fields.get("DTSTART", ""), params.get("DTSTART", {}))
            end_at = _parse_ical_datetime_value(fields.get("DTEND", ""), params.get("DTEND", {}))
            if not _in_window(start_at, time_min, time_max):
                continue
            events.append(
                _normalized_from_component(
                    parsed,
                    calendar_href=calendar_href,
                    calendar_summary=calendar_summary,
                    etag=etag,
                    event_href=event_href,
                    start_at=start_at,
                    end_at=end_at,
                    recurrence_id=fields.get("RECURRENCE-ID"),
                    expansion="provider" if fields.get("RECURRENCE-ID") else None,
                    include_rrule=False,
                )
            )
        return CalDavNormalizeResult(events=events, occurrence_set_complete=False)

    master = masters[0]
    master_fields = master["fields"]
    master_params = master["params"]
    master_uid = master_fields["UID"]
    dtstart_raw = master_fields.get("DTSTART", "")
    dtstart_params = master_params.get("DTSTART") or {}
    master_start = _parse_ical_datetime_value(dtstart_raw, dtstart_params)
    master_end = _parse_ical_datetime_value(master_fields.get("DTEND", ""), master_params.get("DTEND", {}))
    if master_start is None:
        raise YandexConnectorError("recurring master DTSTART is missing or invalid")
    all_day, tzid, utc_dtstart = _dtstart_identity_flags(dtstart_params, dtstart_raw)
    duration = _master_occurrence_duration(
        master_start=master_start,
        master_end=master_end,
        duration_raw=master_fields.get("DURATION"),
        all_day=all_day,
    )
    rule_start = _align_recurrence_datetime(master_start, tzid)
    exdates = [
        _align_recurrence_datetime(item, tzid)
        for item in _multi_ical_datetimes(master.get("exdates") or [])
    ]
    rdates = [
        _align_recurrence_datetime(item, tzid)
        for item in _multi_ical_datetimes(master.get("rdates") or [])
    ]
    rule_set = build_rruleset(rule_start, master_fields["RRULE"], exdates, rdates)
    predicted_starts = occurrences_in_window(rule_set, expand_min, expand_max)

    predicted: list[tuple[str, datetime]] = []
    for start in predicted_starts:
        rid = serialize_recurrence_id(start, all_day=all_day, tzid=tzid, utc_dtstart=utc_dtstart)
        predicted.append((rid, start))

    override_by_rid: dict[str, dict[str, Any]] = {}
    for parsed in overrides:
        rid = (parsed["fields"].get("RECURRENCE-ID") or "").strip()
        if rid:
            override_by_rid[rid] = parsed

    predicted_rids = {rid for rid, _start in predicted}
    in_window_overrides = []
    for parsed in overrides:
        fields = parsed["fields"]
        params = parsed["params"]
        start_at = _parse_ical_datetime_value(fields.get("DTSTART", ""), params.get("DTSTART", {}))
        rid = (fields.get("RECURRENCE-ID") or "").strip()
        if rid in predicted_rids or _in_window(start_at, expand_min, expand_max):
            in_window_overrides.append(parsed)

    usable_provider_set = bool(predicted) and all(rid in override_by_rid for rid, _start in predicted)
    use_fallback = bool(predicted) and not usable_provider_set

    events = []
    if use_fallback:
        for rid, start in predicted:
            if rid in override_by_rid:
                parsed = override_by_rid[rid]
                fields = parsed["fields"]
                params = parsed["params"]
                start_at = _parse_ical_datetime_value(fields.get("DTSTART", ""), params.get("DTSTART", {}))
                end_at = _parse_ical_datetime_value(fields.get("DTEND", ""), params.get("DTEND", {}))
                events.append(
                    _normalized_from_component(
                        parsed,
                        calendar_href=calendar_href,
                        calendar_summary=calendar_summary,
                        etag=etag,
                        event_href=event_href,
                        start_at=start_at,
                        end_at=end_at,
                        recurrence_id=rid,
                        expansion="provider",
                        include_rrule=False,
                    )
                )
            else:
                occ_end = apply_duration(start, duration)
                generated = dict(master)
                generated_fields = dict(master_fields)
                generated_fields.pop("RRULE", None)
                generated_fields.pop("STATUS", None)
                generated["fields"] = generated_fields
                events.append(
                    _normalized_from_component(
                        generated,
                        calendar_href=calendar_href,
                        calendar_summary=calendar_summary,
                        etag=etag,
                        event_href=event_href,
                        start_at=start.astimezone(UTC),
                        end_at=occ_end.astimezone(UTC),
                        recurrence_id=rid,
                        expansion="fallback",
                        include_rrule=False,
                    )
                )
        extra_rids = {
            (item["fields"].get("RECURRENCE-ID") or "").strip()
            for item in in_window_overrides
        } - predicted_rids
        for rid in extra_rids:
            parsed = override_by_rid[rid]
            fields = parsed["fields"]
            params = parsed["params"]
            start_at = _parse_ical_datetime_value(fields.get("DTSTART", ""), params.get("DTSTART", {}))
            end_at = _parse_ical_datetime_value(fields.get("DTEND", ""), params.get("DTEND", {}))
            events.append(
                _normalized_from_component(
                    parsed,
                    calendar_href=calendar_href,
                    calendar_summary=calendar_summary,
                    etag=etag,
                    event_href=event_href,
                    start_at=start_at,
                    end_at=end_at,
                    recurrence_id=rid,
                    expansion="provider",
                    include_rrule=False,
                )
            )
    else:
        for parsed in in_window_overrides:
            fields = parsed["fields"]
            params = parsed["params"]
            start_at = _parse_ical_datetime_value(fields.get("DTSTART", ""), params.get("DTSTART", {}))
            end_at = _parse_ical_datetime_value(fields.get("DTEND", ""), params.get("DTEND", {}))
            events.append(
                _normalized_from_component(
                    parsed,
                    calendar_href=calendar_href,
                    calendar_summary=calendar_summary,
                    etag=etag,
                    event_href=event_href,
                    start_at=start_at,
                    end_at=end_at,
                    recurrence_id=fields.get("RECURRENCE-ID"),
                    expansion="provider",
                    include_rrule=False,
                )
            )
        for parsed in plains:
            fields = parsed["fields"]
            params = parsed["params"]
            start_at = _parse_ical_datetime_value(fields.get("DTSTART", ""), params.get("DTSTART", {}))
            end_at = _parse_ical_datetime_value(fields.get("DTEND", ""), params.get("DTEND", {}))
            if not _in_window(start_at, time_min, time_max):
                continue
            events.append(
                _normalized_from_component(
                    parsed,
                    calendar_href=calendar_href,
                    calendar_summary=calendar_summary,
                    etag=etag,
                    event_href=event_href,
                    start_at=start_at,
                    end_at=end_at,
                    recurrence_id=None,
                    expansion=None,
                    include_rrule=False,
                )
            )

    return CalDavNormalizeResult(
        events=events,
        occurrence_set_complete=True,
        recurrence_master_uid=master_uid,
        used_fallback=use_fallback,
        occurrence_coverage_min=expand_min,
        occurrence_coverage_max=expand_max,
    )


def normalize_caldav_events(
    ical_text: str,
    calendar_href: str,
    calendar_summary: str | None = None,
    etag: str | None = None,
    event_href: str | None = None,
    time_min: datetime | None = None,
    time_max: datetime | None = None,
    allow_fallback: bool = False,
    fallback_min: datetime | None = None,
    fallback_max: datetime | None = None,
) -> list[dict[str, Any]]:
    return normalize_caldav_resource(
        ical_text,
        calendar_href=calendar_href,
        calendar_summary=calendar_summary,
        etag=etag,
        event_href=event_href,
        time_min=time_min,
        time_max=time_max,
        allow_fallback=allow_fallback,
        fallback_min=fallback_min,
        fallback_max=fallback_max,
    ).events


def normalize_caldav_event(
    ical_text: str,
    calendar_href: str,
    calendar_summary: str | None = None,
    etag: str | None = None,
    event_href: str | None = None,
    time_min: datetime | None = None,
    time_max: datetime | None = None,
    allow_fallback: bool = False,
) -> dict[str, Any] | None:
    events = normalize_caldav_events(
        ical_text,
        calendar_href=calendar_href,
        calendar_summary=calendar_summary,
        etag=etag,
        event_href=event_href,
        time_min=time_min,
        time_max=time_max,
        allow_fallback=allow_fallback,
    )
    if not events:
        return None
    return events[0]
