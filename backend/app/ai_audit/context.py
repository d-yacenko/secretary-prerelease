"""Active trace context for in-request / in-job AI audit recording."""

import contextvars
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai_audit.constants import (
    EVENT_MODEL_ROUND,
    EVENT_MODEL_ROUND_FAILED,
    EVENT_TRACE_FINISHED,
    EVENT_TRACE_STARTED,
)
from app.ai_audit.sanitizer import bounded_json_text, sanitize_for_audit
from app.ai_audit.trace_service import AITraceService
from app.db.session import SessionLocal
from app.llm.assistant_provider_errors import audit_error_category

_active_trace: ContextVar["ActiveTrace | None"] = ContextVar("ai_audit_active_trace", default=None)
_current_job_id: ContextVar[UUID | None] = ContextVar("ai_audit_current_job_id", default=None)

_BUDGET_EVENT_TYPES = (EVENT_MODEL_ROUND, EVENT_MODEL_ROUND_FAILED)
_BUDGET_TOKEN_FIELDS = ("input_tokens", "output_tokens")


def _numeric_token(value: Any) -> int | None:
    """Actual billed tokens only. Booleans and estimates are not usage."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def budget_tokens_from_metadata(event_type: str, metadata: dict[str, Any]) -> int:
    """Sum input+output only when the event actually reported numeric usage."""
    if event_type not in _BUDGET_EVENT_TYPES:
        return 0
    charged = 0
    saw_usage = False
    for field in _BUDGET_TOKEN_FIELDS:
        token = _numeric_token(metadata.get(field))
        if token is None:
            continue
        charged += token
        saw_usage = True
    return charged if saw_usage else 0


def active_trace_in_flight_budget_tokens() -> int:
    active = get_active_trace()
    if active is None:
        return 0
    return active.in_flight_budget_tokens


@dataclass
class ActiveTrace:
    trace_id: UUID
    user_id: UUID
    workload: str
    session: Session
    sequence: int = 0
    capture_payloads: bool = False
    payload_retention_until: datetime | None = None
    in_flight_budget_tokens: int = 0

    def record_event(self, event_type: str, metadata: dict[str, Any]) -> None:
        self.sequence += 1
        service = AITraceService(self.session)
        stored_meta = dict(metadata)
        payload_expires_at = None
        if self.capture_payloads:
            payloads = stored_meta.pop("payloads", None)
            if payloads is not None:
                stored_meta["payloads"] = sanitize_for_audit(payloads)
                payload_expires_at = self.payload_retention_until
        self.in_flight_budget_tokens += budget_tokens_from_metadata(event_type, stored_meta)
        service.record_event(
            trace_id=self.trace_id,
            user_id=self.user_id,
            sequence=self.sequence,
            event_type=event_type,
            metadata=stored_meta,
            payload_expires_at=payload_expires_at,
        )

    def finish(self, *, success: bool = True, error_category: str | None = None) -> None:
        service = AITraceService(self.session)
        service.finish_trace(
            self.trace_id,
            self.user_id,
            success=success,
            error_category=error_category,
        )
        self.record_event(
            EVENT_TRACE_FINISHED,
            {"success": success, "error_category": error_category},
        )
        self.session.commit()


def get_active_trace() -> ActiveTrace | None:
    return _active_trace.get()


def get_current_job_id() -> UUID | None:
    return _current_job_id.get()


def set_current_job_id(job_id: UUID) -> contextvars.Token:
    return _current_job_id.set(job_id)


def reset_current_job_id(token: contextvars.Token) -> None:
    _current_job_id.reset(token)


@contextmanager
def ai_trace_session(
    user_id: UUID,
    workload: str,
    *,
    parent_trace_id: UUID | None = None,
    job_id: UUID | None = None,
    object_id: UUID | None = None,
    session: Session | None = None,
    commit_on_exit: bool = True,
):
    owns_session = session is None
    db = session or SessionLocal()
    token = None
    active: ActiveTrace | None = None
    try:
        service = AITraceService(db)
        capture_session = service.get_capture_session(user_id)
        capture_payloads = capture_session is not None
        payload_retention_until = (
            capture_session.payload_retention_until if capture_session is not None else None
        )
        effective_job_id = job_id or get_current_job_id()
        trace = service.start_trace(
            user_id=user_id,
            workload=workload,
            parent_trace_id=parent_trace_id,
            job_id=effective_job_id,
            object_id=object_id,
        )
        active = ActiveTrace(
            trace_id=trace.id,
            user_id=user_id,
            workload=workload,
            session=db,
            capture_payloads=capture_payloads,
            payload_retention_until=payload_retention_until,
        )
        active.record_event(
            EVENT_TRACE_STARTED,
            {
                "workload": workload,
                "parent_trace_id": str(parent_trace_id) if parent_trace_id else None,
                "job_id": str(effective_job_id) if effective_job_id else None,
                "object_id": str(object_id) if object_id else None,
            },
        )
        if commit_on_exit:
            db.commit()
        token = _active_trace.set(active)
        yield active
        if active is not None:
            active.finish(success=True)
    except Exception as exc:
        if active is not None:
            active.finish(success=False, error_category=audit_error_category(exc))
        raise
    finally:
        if token is not None:
            _active_trace.reset(token)
        if owns_session:
            db.close()


def record_if_active(event_type: str, metadata: dict[str, Any]) -> None:
    active = get_active_trace()
    if active is None:
        return
    active.record_event(event_type, metadata)


def maybe_payload_block(label: str, value: Any) -> dict[str, Any] | None:
    active = get_active_trace()
    if active is None or not active.capture_payloads:
        return None
    return {label: bounded_json_text(value)}
