from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def normalize_tool_datetime(
    value: datetime | None,
    timezone_name: str | None = None,
) -> datetime | None:
    if value is None:
        return None
    tz = ZoneInfo(timezone_name or settings.secretary_timezone)
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)
