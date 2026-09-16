"""Resolve trusted client timezone for calendar-day semantics."""

from contextvars import ContextVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings
from app.services.errors import ValidationError

_request_timezone: ContextVar[str | None] = ContextVar("request_timezone", default=None)


def set_request_timezone(timezone: str) -> None:
    _request_timezone.set(timezone)


def clear_request_timezone() -> None:
    _request_timezone.set(None)


def get_request_timezone() -> str:
    active = _request_timezone.get()
    return active if active is not None else settings.secretary_timezone


def resolve_assistant_request_timezone(
    zone_id: str | None,
    utc_offset_minutes: int | None,
    user_timezone: str,
) -> str:
    """Resolve timezone for Assistant requests: client IANA → user preference → server default."""
    if zone_id is not None:
        text = zone_id.strip()
        if text:
            try:
                ZoneInfo(text)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValidationError(f"invalid client timezone: {zone_id}") from exc
            return text
    if user_timezone:
        return user_timezone
    return settings.secretary_timezone


def resolve_client_timezone(
    zone_id: str | None,
    utc_offset_minutes: int | None = None,
) -> str:
    """Return an IANA timezone name for the current client request.

    ``utc_offset_minutes`` is accepted for diagnostics/fallback compatibility but
    does not override a valid IANA ``zone_id``.
    """
    if zone_id is not None:
        text = zone_id.strip()
        if not text:
            return settings.secretary_timezone
        try:
            ZoneInfo(text)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValidationError(f"invalid client timezone: {zone_id}") from exc
        return text
    # offset-only requests fall back to server default for backward compatibility
    return settings.secretary_timezone
