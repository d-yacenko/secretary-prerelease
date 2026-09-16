"""Parse and classify Yandex Calendar CalDAV HTTP failures."""

from typing import Literal

import httpx

from app.connectors.yandex.errors import YandexCalDavError
from app.jobs.constants import MAX_LAST_ERROR_LENGTH

CalDavFailureCategory = Literal[
    "auth",
    "permission",
    "not_found",
    "rate_limit",
    "server",
    "network",
    "request",
]

_FORBIDDEN_ERROR_SUBSTRINGS = (
    "authorization:",
    "bearer ",
    "basic ",
    "access_token",
    "refresh_token",
    "app_password",
    "app-password",
    "password=",
)


def _sanitize_message(text: str) -> str:
    cleaned = " ".join(text.split())
    lowered = cleaned.lower()
    for needle in _FORBIDDEN_ERROR_SUBSTRINGS:
        if needle in lowered:
            return "Yandex Calendar CalDAV request failed"
    return cleaned[:500]


def classify_caldav_http_status(status_code: int) -> tuple[CalDavFailureCategory, bool]:
    if status_code == 401:
        return "auth", False
    if status_code == 403:
        return "permission", False
    if status_code == 404:
        return "not_found", False
    if status_code in {408, 425, 429}:
        return "rate_limit", True
    if status_code >= 500:
        return "server", True
    return "request", False


def raise_for_caldav_http_response(
    response: httpx.Response,
    *,
    operation: str,
    path: str,
) -> None:
    if response.status_code < 400:
        return
    category, retryable = classify_caldav_http_status(response.status_code)
    raise YandexCalDavError(
        _sanitize_message(f"HTTP {response.status_code}"),
        operation=operation,
        path=path,
        status_code=response.status_code,
        category=category,
        retryable=retryable,
    )


def raise_for_caldav_request_error(
    exc: BaseException,
    *,
    operation: str,
    path: str,
) -> YandexCalDavError:
    message = _sanitize_message(str(exc).strip() or type(exc).__name__)
    return YandexCalDavError(
        message,
        operation=operation,
        path=path,
        status_code=None,
        category="network",
        retryable=True,
    )


def format_yandex_caldav_error(error: YandexCalDavError) -> str:
    category_labels = {
        "auth": "Yandex Calendar authorization rejected",
        "permission": "Yandex Calendar permission denied",
        "not_found": "Yandex Calendar endpoint not found",
        "rate_limit": "Yandex Calendar temporarily rate limited",
        "server": "Yandex Calendar temporary server error",
        "network": "Yandex Calendar network timeout",
        "request": "Yandex Calendar request failed",
    }
    label = category_labels.get(error.category or "request", "Yandex Calendar request failed")
    if error.status_code is not None:
        text = f"{label} (HTTP {error.status_code})"
    else:
        text = label
    return text[:MAX_LAST_ERROR_LENGTH]
