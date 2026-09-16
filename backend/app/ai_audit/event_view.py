"""Non-destructive AI trace event metadata exposure for API/CLI reads."""

from datetime import datetime
from typing import Any

from app.services.job_queue_service import utcnow


def event_payloads_readable(payload_expires_at: datetime | None) -> bool:
    if payload_expires_at is None:
        return False
    return payload_expires_at > utcnow()


def expose_event_metadata(
    metadata: dict[str, Any] | None,
    *,
    include_payloads: bool,
    payload_expires_at: datetime | None,
) -> dict[str, Any]:
    meta = dict(metadata or {})
    if "payloads" not in meta:
        return meta
    if not include_payloads or not event_payloads_readable(payload_expires_at):
        meta["payloads"] = "[withheld]"
    return meta
