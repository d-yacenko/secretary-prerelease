from datetime import datetime
from typing import Any

from app.connectors.google.constants import CALENDAR_READONLY_SCOPE, MAX_EVENT_BODY_CHARS

MAX_ATTENDEES_IN_METADATA = 20


def _parse_event_datetime(field: dict[str, Any] | None) -> datetime | None:
    if not field:
        return None
    date_time = field.get("dateTime")
    if date_time:
        normalized = str(date_time).replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    date_only = field.get("date")
    if date_only:
        return datetime.fromisoformat(f"{date_only}T00:00:00+00:00")
    return None


def _compact_attendees(
    attendees: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, str]], bool]:
    if not attendees:
        return [], False
    truncated = len(attendees) > MAX_ATTENDEES_IN_METADATA
    compact: list[dict[str, str]] = []
    for attendee in attendees[:MAX_ATTENDEES_IN_METADATA]:
        email = attendee.get("email")
        if not email:
            continue
        entry: dict[str, str] = {"email": str(email)}
        response = attendee.get("responseStatus")
        if response:
            entry["response_status"] = str(response)
        if attendee.get("self"):
            entry["self"] = "true"
        compact.append(entry)
    return compact, truncated


def normalize_calendar_event(
    event: dict[str, Any],
    calendar_id: str,
    calendar_summary: str | None = None,
) -> dict[str, Any]:
    event_id = str(event.get("id", ""))
    start_at = _parse_event_datetime(event.get("start"))
    end_at = _parse_event_datetime(event.get("end"))
    description = event.get("description")
    body = None
    if description:
        body = str(description)[:MAX_EVENT_BODY_CHARS]

    organizer = event.get("organizer") or {}
    attendees, attendees_truncated = _compact_attendees(event.get("attendees"))
    metadata = {
        "calendar_id": calendar_id,
        "event_id": event_id,
        "calendar_summary": calendar_summary,
        "status": event.get("status"),
        "location": event.get("location"),
        "html_link": event.get("htmlLink"),
        "attendees": attendees,
        "organizer": organizer.get("email"),
        "recurring_event_id": event.get("recurringEventId"),
        "updated": event.get("updated"),
    }
    if attendees_truncated:
        metadata["attendees_truncated"] = True
    if organizer.get("self"):
        metadata["organizer_self"] = True

    title = str(event.get("summary") or f"Calendar event {event_id}")

    return {
        "external_id": f"{calendar_id}:{event_id}",
        "kind": "event",
        "provider": "google_calendar",
        "origin": "source",
        "state": "observed",
        "title": title,
        "body": body,
        "start_at": start_at,
        "due_at": end_at,
        "occurred_at": start_at,
        "metadata": metadata,
        "scopes": [CALENDAR_READONLY_SCOPE],
    }
