"""Parse and classify Google API HTTP error responses."""

from typing import Any

import httpx

from app.connectors.google.errors import GoogleApiError
from app.jobs.constants import MAX_LAST_ERROR_LENGTH

_RETRYABLE_REASONS = frozenset(
    {
        "rateLimitExceeded",
        "userRateLimitExceeded",
        "backendError",
        "internalError",
    }
)

_NON_RETRYABLE_REASONS = frozenset(
    {
        "insufficientPermissions",
        "accessNotConfigured",
        "forbidden",
        "authError",
        "dailyLimitExceeded",
        "domainPolicy",
        "notConfigured",
        "serviceDisabled",
    }
)

_FORBIDDEN_ERROR_SUBSTRINGS = (
    "authorization:",
    "bearer ",
    "access_token",
    "refresh_token",
    "ya29.",
)


def _sanitize_message(text: str) -> str:
    cleaned = " ".join(text.split())
    lowered = cleaned.lower()
    for needle in _FORBIDDEN_ERROR_SUBSTRINGS:
        if needle in lowered:
            return "Google API request failed"
    return cleaned[:500]


def is_google_error_retryable(
    status_code: int,
    reason: str | None,
    api_status: str | None = None,
) -> bool:
    normalized_reason = (reason or "").strip()
    if normalized_reason in _RETRYABLE_REASONS:
        return True
    if normalized_reason in _NON_RETRYABLE_REASONS:
        return False
    if api_status in {"PERMISSION_DENIED", "UNAUTHENTICATED"}:
        return False
    if status_code == 429:
        return True
    if status_code >= 500:
        return True
    if status_code in (401, 403):
        return False
    return status_code >= 500


def parse_google_api_error_payload(
    status_code: int,
    payload: Any,
) -> tuple[str | None, str | None, str | None]:
    reason: str | None = None
    message: str | None = None
    api_status: str | None = None
    if not isinstance(payload, dict):
        return reason, message, api_status
    error = payload.get("error")
    if not isinstance(error, dict):
        return reason, message, api_status
    message = error.get("message")
    api_status = error.get("status")
    errors = error.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            reason = first.get("reason")
            if not message:
                message = first.get("message")
    return reason, message, api_status


def raise_for_google_response(response: httpx.Response, operation: str) -> None:
    if response.status_code < 400:
        return

    reason: str | None = None
    message: str | None = None
    api_status: str | None = None
    try:
        payload = response.json()
        reason, message, api_status = parse_google_api_error_payload(
            response.status_code,
            payload,
        )
    except (ValueError, TypeError):
        payload = None

    if not message:
        message = f"HTTP {response.status_code}"
    safe_message = _sanitize_message(str(message))
    retryable = is_google_error_retryable(response.status_code, reason, api_status)
    raise GoogleApiError(
        safe_message,
        operation=operation,
        status_code=response.status_code,
        reason=reason,
        api_status=api_status,
        retryable=retryable,
    )


def format_google_api_error(error: GoogleApiError) -> str:
    parts: list[str] = []
    if error.operation:
        parts.append(error.operation)
    if error.status_code is not None:
        parts.append(str(error.status_code))
    if error.reason:
        parts.append(error.reason)
    if error.message:
        parts.append(_sanitize_message(error.message))
    text = ": ".join(parts) if parts else "Google API error"
    return text[:MAX_LAST_ERROR_LENGTH]
