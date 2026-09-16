from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.connectors.google.api_errors import raise_for_google_response
from app.connectors.google.constants import CALENDAR_API_BASE
from app.connectors.google.errors import GoogleApiError


@dataclass(frozen=True)
class CalendarEventPage:
    events: list[dict[str, Any]]
    next_page_token: str | None


class CalendarTransport:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._http = http_client or httpx.Client(timeout=30.0)

    def list_calendars(
        self,
        access_token: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        response = self._http.get(
            f"{CALENDAR_API_BASE}/users/me/calendarList",
            params={"maxResults": max_results},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        raise_for_google_response(response, "list_calendars")
        payload = response.json()
        return list(payload.get("items", []))

    def list_events_page(
        self,
        access_token: str,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
        max_results: int,
        page_token: str | None = None,
        show_deleted: bool = False,
    ) -> CalendarEventPage:
        encoded_calendar_id = quote(calendar_id, safe="")
        params: dict[str, object] = {
            "timeMin": _format_rfc3339(time_min),
            "timeMax": _format_rfc3339(time_max),
            "maxResults": max_results,
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        if show_deleted:
            params["showDeleted"] = "true"
        if page_token is not None:
            params["pageToken"] = page_token
        response = self._http.get(
            f"{CALENDAR_API_BASE}/calendars/{encoded_calendar_id}/events",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        raise_for_google_response(response, "list_events")
        payload = response.json()
        events = list(payload.get("items", []))
        next_token = payload.get("nextPageToken")
        return CalendarEventPage(
            events=events,
            next_page_token=str(next_token) if next_token else None,
        )

    def list_events(
        self,
        access_token: str,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
        max_results: int,
    ) -> list[dict[str, Any]]:
        return self.list_events_page(
            access_token=access_token,
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
        ).events

    def insert_event(
        self,
        access_token: str,
        calendar_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        encoded_calendar_id = quote(calendar_id, safe="")
        response = self._http.post(
            f"{CALENDAR_API_BASE}/calendars/{encoded_calendar_id}/events",
            json=body,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        raise_for_google_response(response, "insert_event")
        return _json_object_payload(response, "insert_event")

    def get_event(
        self,
        access_token: str,
        calendar_id: str,
        event_id: str,
    ) -> dict[str, Any]:
        encoded_calendar_id = quote(calendar_id, safe="")
        encoded_event_id = quote(event_id, safe="")
        response = self._http.get(
            f"{CALENDAR_API_BASE}/calendars/{encoded_calendar_id}/events/{encoded_event_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        raise_for_google_response(response, "get_event")
        return _json_object_payload(response, "get_event")


def _json_object_payload(response: httpx.Response, operation: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = None
    if not isinstance(payload, dict):
        raise GoogleApiError(
            f"{operation} returned a malformed response",
            operation=operation,
            status_code=response.status_code,
            retryable=True,
        )
    return payload


def _format_rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        return value.isoformat() + "Z"
    return value.isoformat().replace("+00:00", "Z")
