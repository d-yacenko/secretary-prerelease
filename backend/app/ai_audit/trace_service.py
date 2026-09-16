"""Persisted AI trace storage, queries, and capture sessions."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai_audit.constants import (
    DEFAULT_CAPTURE_DURATION,
    MAX_EVENTS_PER_TRACE,
    MAX_SUMMARY_RANGE_DAYS,
    MAX_TRACE_LIST,
    METADATA_RETENTION,
    PAYLOAD_RETENTION_AFTER_CAPTURE,
    WORKLOAD_ASSISTANT_INTERACTIVE,
)
from app.ai_audit.event_view import expose_event_metadata
from app.ai_audit.sanitizer import sanitize_for_audit
from app.db.models import AIAuditCaptureSession, AITrace, AITraceEvent
from app.services.job_queue_service import utcnow


class AITraceService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def start_trace(
        self,
        user_id: UUID,
        workload: str,
        *,
        parent_trace_id: UUID | None = None,
        job_id: UUID | None = None,
        object_id: UUID | None = None,
    ) -> AITrace:
        now = utcnow()
        trace = AITrace(
            user_id=user_id,
            workload=workload,
            parent_trace_id=parent_trace_id,
            job_id=job_id,
            object_id=object_id,
            started_at=now,
            success=True,
        )
        self._session.add(trace)
        self._session.flush()
        return trace

    def record_event(
        self,
        trace_id: UUID,
        user_id: UUID,
        sequence: int,
        event_type: str,
        metadata: dict[str, Any],
        *,
        payload_expires_at: datetime | None = None,
    ) -> AITraceEvent:
        event = AITraceEvent(
            trace_id=trace_id,
            user_id=user_id,
            sequence=sequence,
            event_type=event_type,
            metadata_=sanitize_for_audit(metadata),
            payload_expires_at=payload_expires_at,
        )
        self._session.add(event)
        self._session.flush()
        return event

    def finish_trace(
        self,
        trace_id: UUID,
        user_id: UUID,
        *,
        success: bool,
        error_category: str | None = None,
    ) -> None:
        trace = self._require_trace(trace_id, user_id)
        trace.finished_at = utcnow()
        trace.success = success
        trace.error_category = error_category

    def get_trace(self, trace_id: UUID, user_id: UUID) -> AITrace | None:
        return self._session.scalar(
            select(AITrace).where(AITrace.id == trace_id, AITrace.user_id == user_id)
        )

    def list_trace_events(
        self,
        trace_id: UUID,
        user_id: UUID,
        *,
        include_payloads: bool = False,
    ) -> list[dict[str, Any]]:
        trace = self.get_trace(trace_id, user_id)
        if trace is None:
            return []
        events = list(
            self._session.scalars(
                select(AITraceEvent)
                .where(
                    AITraceEvent.trace_id == trace_id,
                    AITraceEvent.user_id == user_id,
                )
                .order_by(AITraceEvent.sequence)
                .limit(MAX_EVENTS_PER_TRACE)
            )
        )
        return [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "created_at": event.created_at,
                "metadata": expose_event_metadata(
                    event.metadata_,
                    include_payloads=include_payloads,
                    payload_expires_at=event.payload_expires_at,
                ),
            }
            for event in events
        ]

    def list_traces(
        self,
        user_id: UUID,
        started_after: datetime,
        started_before: datetime,
        *,
        workload: str | None = None,
        limit: int = MAX_TRACE_LIST,
    ) -> list[dict[str, Any]]:
        if started_before <= started_after:
            raise ValueError("invalid time range")
        limit = min(max(limit, 1), MAX_TRACE_LIST)
        query = (
            select(AITrace)
            .where(
                AITrace.user_id == user_id,
                AITrace.started_at >= started_after,
                AITrace.started_at < started_before,
            )
            .order_by(AITrace.started_at.desc())
            .limit(limit)
        )
        if workload is not None:
            query = query.where(AITrace.workload == workload)
        traces = list(self._session.scalars(query))
        if not traces:
            return []

        trace_ids = [trace.id for trace in traces]
        events = list(
            self._session.scalars(
                select(AITraceEvent).where(
                    AITraceEvent.user_id == user_id,
                    AITraceEvent.trace_id.in_(trace_ids),
                )
            )
        )
        per_trace_model_calls: dict[UUID, int] = {}
        per_trace_usage: dict[UUID, dict[str, int]] = {}

        for event in events:
            meta = event.metadata_ or {}
            if event.event_type in ("model_round", "model_round_failed"):
                per_trace_model_calls[event.trace_id] = per_trace_model_calls.get(event.trace_id, 0) + 1
                usage = per_trace_usage.setdefault(
                    event.trace_id,
                    {
                        "input_tokens": 0,
                        "cached_input_tokens": 0,
                        "output_tokens": 0,
                        "reasoning_tokens": 0,
                        "cache_write_tokens": 0,
                    },
                )
                for key in usage:
                    value = meta.get(key)
                    if isinstance(value, int):
                        usage[key] += value

        rows: list[dict[str, Any]] = []
        for trace in traces:
            usage = per_trace_usage.get(trace.id, {})
            rows.append(
                {
                    "trace_id": trace.id,
                    "workload": trace.workload,
                    "started_at": trace.started_at,
                    "finished_at": trace.finished_at,
                    "success": trace.success,
                    "error_category": trace.error_category,
                    "model_call_count": per_trace_model_calls.get(trace.id, 0),
                    "input_tokens": usage.get("input_tokens", 0),
                    "cached_input_tokens": usage.get("cached_input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "reasoning_tokens": usage.get("reasoning_tokens", 0),
                    "cache_write_tokens": usage.get("cache_write_tokens", 0),
                    "job_id": trace.job_id,
                    "object_id": trace.object_id,
                    "parent_trace_id": trace.parent_trace_id,
                }
            )
        return rows

    def build_summary(
        self,
        user_id: UUID,
        started_after: datetime,
        started_before: datetime,
    ) -> dict[str, Any]:
        if started_before <= started_after:
            raise ValueError("invalid time range")
        if (started_before - started_after).days > MAX_SUMMARY_RANGE_DAYS:
            raise ValueError("time range too large")

        traces = list(
            self._session.scalars(
                select(AITrace).where(
                    AITrace.user_id == user_id,
                    AITrace.started_at >= started_after,
                    AITrace.started_at < started_before,
                )
            )
        )
        trace_map = {trace.id: trace for trace in traces}
        trace_ids = list(trace_map.keys())
        events: list[AITraceEvent] = []
        if trace_ids:
            events = list(
                self._session.scalars(
                    select(AITraceEvent).where(
                        AITraceEvent.user_id == user_id,
                        AITraceEvent.trace_id.in_(trace_ids),
                    )
                )
            )

        traces_by_workload: dict[str, int] = {}
        model_calls_by_workload: dict[str, int] = {}
        model_calls_by_model: dict[str, int] = {}
        token_totals_by_workload: dict[str, dict[str, int]] = {}
        totals = {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "cache_write_tokens": 0,
        }
        model_call_count = 0
        tool_call_count = 0
        failures = 0
        assistant_turn_count = 0
        assistant_rounds: list[int] = []
        assistant_tool_counts: list[int] = []
        background_counts: dict[str, int] = {}

        assistant_trace_ids = {
            trace.id for trace in traces if trace.workload == WORKLOAD_ASSISTANT_INTERACTIVE
        }
        per_assistant_rounds: dict[UUID, int] = {}
        per_assistant_tools: dict[UUID, int] = {}

        for trace in traces:
            traces_by_workload[trace.workload] = traces_by_workload.get(trace.workload, 0) + 1
            if trace.workload == WORKLOAD_ASSISTANT_INTERACTIVE:
                assistant_turn_count += 1
            if trace.workload.startswith("background_") or trace.workload == "embedding":
                background_counts[trace.workload] = background_counts.get(trace.workload, 0) + 1
            if not trace.success:
                failures += 1

        for event in events:
            meta = event.metadata_ or {}
            trace = trace_map.get(event.trace_id)
            if trace is None:
                continue
            workload = trace.workload

            if event.event_type in ("model_round", "model_round_failed"):
                model_call_count += 1
                model_calls_by_workload[workload] = model_calls_by_workload.get(workload, 0) + 1
                model = meta.get("model")
                if model:
                    model_calls_by_model[str(model)] = model_calls_by_model.get(str(model), 0) + 1
                workload_totals = token_totals_by_workload.setdefault(
                    workload,
                    {
                        "input_tokens": 0,
                        "cached_input_tokens": 0,
                        "output_tokens": 0,
                        "reasoning_tokens": 0,
                        "cache_write_tokens": 0,
                    },
                )
                for key in totals:
                    value = meta.get(key)
                    if isinstance(value, int):
                        totals[key] += value
                        workload_totals[key] += value
                if trace.id in assistant_trace_ids:
                    per_assistant_rounds[trace.id] = per_assistant_rounds.get(trace.id, 0) + 1

            if event.event_type == "tool_call":
                tool_call_count += 1
                if trace.id in assistant_trace_ids:
                    per_assistant_tools[trace.id] = per_assistant_tools.get(trace.id, 0) + 1

        for trace_id in assistant_trace_ids:
            assistant_rounds.append(per_assistant_rounds.get(trace_id, 0))
            assistant_tool_counts.append(per_assistant_tools.get(trace_id, 0))

        def _avg(values: list[int]) -> float | None:
            return sum(values) / len(values) if values else None

        def _max(values: list[int]) -> int | None:
            return max(values) if values else None

        return {
            "trace_count": len(traces),
            "traces_by_workload": traces_by_workload,
            "calls_by_workload": traces_by_workload,
            "model_call_count": model_call_count,
            "model_calls_by_workload": model_calls_by_workload,
            "calls_by_model": model_calls_by_model,
            "model_calls_by_model": model_calls_by_model,
            "total_input_tokens": totals["input_tokens"],
            "total_cached_input_tokens": totals["cached_input_tokens"],
            "total_output_tokens": totals["output_tokens"],
            "total_reasoning_tokens": totals["reasoning_tokens"],
            "total_cache_write_tokens": totals["cache_write_tokens"],
            "token_totals_by_workload": token_totals_by_workload,
            "model_round_count": model_call_count,
            "tool_call_count": tool_call_count,
            "failure_count": failures,
            "assistant_turn_count": assistant_turn_count,
            "assistant_avg_rounds": _avg(assistant_rounds),
            "assistant_max_rounds": _max(assistant_rounds),
            "assistant_avg_tool_calls": _avg(assistant_tool_counts),
            "assistant_max_tool_calls": _max(assistant_tool_counts),
            "background_call_counts": background_counts,
            "started_after": started_after.isoformat(),
            "started_before": started_before.isoformat(),
        }

    def get_payload_retention_until(self, user_id: UUID) -> datetime | None:
        row = self._session.get(AIAuditCaptureSession, user_id)
        if row is None:
            return None
        return row.payload_retention_until

    def enable_capture(
        self,
        user_id: UUID,
        duration: timedelta = DEFAULT_CAPTURE_DURATION,
    ) -> AIAuditCaptureSession:
        now = utcnow()
        session_row = AIAuditCaptureSession(
            user_id=user_id,
            enabled_at=now,
            expires_at=now + duration,
            payload_retention_until=now + duration + PAYLOAD_RETENTION_AFTER_CAPTURE,
        )
        self._session.merge(session_row)
        self._session.flush()
        return session_row

    def disable_capture(self, user_id: UUID) -> None:
        row = self._session.get(AIAuditCaptureSession, user_id)
        if row is not None:
            self._session.delete(row)

    def get_capture_session(self, user_id: UUID) -> AIAuditCaptureSession | None:
        row = self._session.get(AIAuditCaptureSession, user_id)
        if row is None:
            return None
        if row.expires_at <= utcnow():
            return None
        return row

    def is_payload_capture_active(self, user_id: UUID) -> bool:
        return self.get_capture_session(user_id) is not None

    def cleanup_expired(self) -> dict[str, int]:
        now = utcnow()
        metadata_cutoff = now - METADATA_RETENTION

        expired_payload_events = list(
            self._session.scalars(
                select(AITraceEvent).where(
                    AITraceEvent.payload_expires_at.is_not(None),
                    AITraceEvent.payload_expires_at <= now,
                )
            )
        )
        scrubbed = 0
        for event in expired_payload_events:
            meta = dict(event.metadata_ or {})
            if "payloads" in meta:
                meta.pop("payloads", None)
                event.metadata_ = meta
                event.payload_expires_at = None
                scrubbed += 1

        capture_rows = list(self._session.scalars(select(AIAuditCaptureSession)))
        expired_capture_users = [
            row.user_id for row in capture_rows if row.payload_retention_until <= now
        ]
        if expired_capture_users:
            self._session.execute(
                delete(AIAuditCaptureSession).where(
                    AIAuditCaptureSession.user_id.in_(expired_capture_users)
                )
            )

        old_trace_ids = list(
            self._session.scalars(
                select(AITrace.id).where(AITrace.started_at < metadata_cutoff)
            )
        )
        deleted_events = 0
        deleted_traces = 0
        if old_trace_ids:
            result = self._session.execute(
                delete(AITraceEvent).where(AITraceEvent.trace_id.in_(old_trace_ids))
            )
            deleted_events = result.rowcount or 0
            result = self._session.execute(
                delete(AITrace).where(AITrace.id.in_(old_trace_ids))
            )
            deleted_traces = result.rowcount or 0
        return {
            "scrubbed_payload_events": scrubbed,
            "deleted_events": deleted_events,
            "deleted_traces": deleted_traces,
        }

    def _require_trace(self, trace_id: UUID, user_id: UUID) -> AITrace:
        trace = self.get_trace(trace_id, user_id)
        if trace is None:
            raise ValueError("trace not found")
        return trace
