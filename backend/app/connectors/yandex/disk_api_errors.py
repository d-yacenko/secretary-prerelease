"""Parse and classify Yandex Disk API HTTP error responses."""

from typing import Any

import httpx

from app.connectors.yandex.errors import YandexDiskApiError

_FORBIDDEN_ERROR_SUBSTRINGS = (
    "authorization:",
    "bearer ",
    "access_token",
    "refresh_token",
    "oauth",
    "app_password",
)


def _sanitize_message(text: str) -> str:
    cleaned = " ".join(text.split())
    lowered = cleaned.lower()
    for needle in _FORBIDDEN_ERROR_SUBSTRINGS:
        if needle in lowered:
            return "Yandex Disk API request failed"
    return cleaned[:500]


def parse_yandex_disk_error_payload(
    status_code: int,
    payload: Any,
) -> tuple[str | None, str | None]:
    message: str | None = None
    reason: str | None = None
    if not isinstance(payload, dict):
        return reason, message
    message = payload.get("message") or payload.get("description")
    reason = payload.get("error")
    error_obj = payload.get("error")
    if isinstance(error_obj, dict):
        reason = error_obj.get("name") or error_obj.get("code")
        if not message:
            message = error_obj.get("message") or error_obj.get("description")
    return reason, message


def raise_for_yandex_disk_response(response: httpx.Response, operation: str) -> None:
    if response.status_code < 400:
        return

    reason: str | None = None
    message: str | None = None
    try:
        payload = response.json()
        reason, message = parse_yandex_disk_error_payload(response.status_code, payload)
    except (ValueError, TypeError):
        payload = None

    if not message:
        message = f"HTTP {response.status_code}"
    safe_message = _sanitize_message(str(message))
    raise YandexDiskApiError(
        safe_message,
        operation=operation,
        status_code=response.status_code,
        reason=reason,
    )
