from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_audit.constants import WORKLOAD_BACKGROUND_TEMPORAL_SIGNAL
from app.ai_audit.context import ai_trace_session, get_active_trace
from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import Edge, Job, Object, UserSettings
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.domain.telegram_mtproto_ai import telegram_mtproto_ai_eligible
from app.domain.temporal_hint import (
    EDGE_TYPE_TEMPORAL_CONFIRMATION,
    EDGE_TYPE_TEMPORAL_EVIDENCE,
    KIND_TEMPORAL_HINT,
    LIFECYCLE_SUPERSEDED_BY_CALENDAR,
    LIFECYCLE_SUPERSEDED_BY_SOURCE_REVISION,
    LIFECYCLE_UNRESOLVED,
    PARTICIPATION_EXPECTED,
    PARTICIPATION_OTHERS_ONLY,
    PARTICIPATION_POSSIBLE,
    PARTICIPATION_UNKNOWN,
    RESULT_EXACT_TEMPORAL_SIGNAL,
    START_PRECISION_EXACT,
)
from app.jobs.constants import (
    JOB_STATUS_DONE,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL,
    JOB_TYPE_RECONCILE_TEMPORAL_HINTS,
)
from app.llm.temporal_match_judge import (
    TemporalMatchJudge,
    create_temporal_match_judge_from_effective,
)
from app.llm.temporal_signal_extractor import (
    TemporalSignalExtractor,
    create_temporal_signal_extractor_from_effective,
)
from app.services.calendar_event_query import (
    WEEK_CALENDAR_PROVIDERS,
    active_event_predicates,
    event_overlaps_window,
)
from app.services.correlation_constants import SEMANTIC_SUMMARY_METADATA_KEY
from app.services.edge_dedup import has_equivalent_relation
from app.services.effective_user_settings_service import EffectiveUserSettingsService
from app.services.graph_service import GraphService
from app.services.job_queue_service import JobQueueService
from app.services.openai_daily_budget import OpenAIDailyBudgetGuard
from app.services.personal_relevance_evidence_service import PersonalRelevanceEvidenceService
from app.services.provenance import (
    OBSERVED_STATE,
    REJECTED_STATE,
    SYSTEM_ORIGIN,
)
from app.services.temporal_signals_constants import (
    METADATA_END_PRECISION,
    METADATA_EVIDENCE_COUNT,
    METADATA_EXTRACTION_CONFIDENCE,
    METADATA_EXTRACTOR_VERSION,
    METADATA_LIFECYCLE,
    METADATA_PARTICIPATION,
    METADATA_PRIMARY_EVIDENCE_KIND,
    METADATA_PRIMARY_EVIDENCE_OBJECT_ID,
    METADATA_PRIMARY_EVIDENCE_PROVIDER,
    METADATA_SEMANTIC_SUBJECT,
    METADATA_SOURCE_REFERENCE_AT,
    METADATA_SOURCE_SIGNATURE,
    METADATA_START_PRECISION,
    METADATA_SUPERSEDED_BY_OBJECT_ID,
    METADATA_TEMPORAL_SIGNAL_VERSION,
    TEMPORAL_ELIGIBLE_KINDS,
    TEMPORAL_ELIGIBLE_ORIGINS,
    TEMPORAL_ELIGIBLE_PROVIDERS,
    TEMPORAL_SIGNAL_AUDIT_MATCH,
    TEMPORAL_SIGNAL_AUDIT_RECONCILE_MATCH,
    TEMPORAL_SIGNAL_CANDIDATE_WINDOW,
    TEMPORAL_SIGNAL_EXPECTED_MIN_CONFIDENCE,
    TEMPORAL_SIGNAL_EXTRACTOR_VERSION,
    TEMPORAL_SIGNAL_MATCH_MIN_CONFIDENCE,
    TEMPORAL_SIGNAL_MAX_BODY_CHARS,
    TEMPORAL_SIGNAL_MAX_CANDIDATES,
    TEMPORAL_SIGNAL_MAX_EVIDENCE_EDGES_SCAN,
    TEMPORAL_SIGNAL_MAX_TITLE_CHARS,
    TEMPORAL_SIGNAL_METADATA_VERSION,
    TEMPORAL_SIGNAL_POSSIBLE_MIN_CONFIDENCE,
    TEMPORAL_SIGNAL_START_PROXIMITY,
    TEMPORAL_SIGNALS_ENABLED_DEFAULT,
)
from app.services.temporal_signals_models import (
    ResolvedTemporalSignal,
    TemporalExtractionRequest,
    TemporalMatchCandidate,
)
from app.services.temporal_signals_resolution import (
    resolve_exact_signal,
    source_reference_timestamp,
)
from app.services.user_participation_evidence_service import extract_email_address
from app.services.user_serialization_gate import lock_user_serialization_row
from app.source_sync.constants import SOURCE_MATTERMOST


@dataclass(frozen=True)
class TemporalSignalJobOutcome:
    reason: str
    hint_id: UUID | None = None
    calendar_id: UUID | None = None
    stale: bool = False


def is_temporal_signals_enabled(session: Session, user_id: UUID) -> bool:
    row = session.get(UserSettings, user_id)
    if row is None:
        return TEMPORAL_SIGNALS_ENABLED_DEFAULT
    return bool(row.temporal_signals_enabled)


def acquire_temporal_signals_user_gate(session: Session, user_id: UUID) -> UserSettings | None:
    user = lock_user_serialization_row(session, user_id)
    if user is None:
        return None
    return session.scalar(
        select(UserSettings)
        .where(UserSettings.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def object_is_temporal_source_eligible(obj: Object) -> bool:
    if is_object_hidden_from_active_reads(obj) or obj.state == REJECTED_STATE:
        return False
    if obj.kind not in TEMPORAL_ELIGIBLE_KINDS:
        return False
    if obj.provider not in TEMPORAL_ELIGIBLE_PROVIDERS:
        return False
    if obj.origin not in TEMPORAL_ELIGIBLE_ORIGINS:
        return False
    if obj.kind == KIND_TEMPORAL_HINT:
        return False
    return not _is_self_only_outgoing(obj)


def object_is_calendar_reconcile_eligible(obj: Object) -> bool:
    if is_object_hidden_from_active_reads(obj) or obj.state == REJECTED_STATE:
        return False
    return obj.kind == "event" and obj.provider in WEEK_CALENDAR_PROVIDERS and obj.start_at is not None


def _is_self_only_outgoing(obj: Object) -> bool:
    metadata = obj.metadata_ or {}
    if obj.provider in {"gmail", "yandex_mail"}:
        sender = extract_email_address(metadata.get("sender"))
        recipients = _string_values(metadata.get("recipients"))
        copied = _string_values(metadata.get("cc"))
        others = [
            extract_email_address(item)
            for item in (*recipients, *copied)
        ]
        other_emails = {item for item in others if item and item != sender}
        return bool(sender) and not other_emails
    return False


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bounded_source_text(obj: Object) -> tuple[str, str]:
    title = (obj.title or "")[:TEMPORAL_SIGNAL_MAX_TITLE_CHARS]
    body = (obj.body or "").strip()[:TEMPORAL_SIGNAL_MAX_BODY_CHARS]
    return title, body


def bounded_semantic_summary(obj: Object) -> str | None:
    summary = (obj.metadata_ or {}).get(SEMANTIC_SUMMARY_METADATA_KEY)
    if isinstance(summary, str) and summary.strip():
        return summary.strip()[:TEMPORAL_SIGNAL_MAX_BODY_CHARS]
    return None


def source_extraction_signature(obj: Object) -> str:
    title, body = bounded_source_text(obj)
    metadata = obj.metadata_ or {}
    reference = source_reference_timestamp(obj.occurred_at, metadata)
    reference_iso = reference.astimezone(UTC).isoformat() if reference is not None else None
    participants = {
        "sender": metadata.get("sender"),
        "recipients": metadata.get("recipients"),
        "cc": metadata.get("cc"),
        "author_user_id": metadata.get("author_user_id"),
        "author_username": metadata.get("author_username"),
        "mentioned_user_ids": metadata.get("mentioned_user_ids"),
        "mentioned_usernames": metadata.get("mentioned_usernames"),
    }
    if obj.provider == "telegram":
        participants.update(
            {
                "business_user_id": metadata.get("business_user_id"),
                "from_user_id": metadata.get("from_user_id"),
                "direction": metadata.get("direction"),
            }
        )
        if metadata.get("transport") == "mtproto":
            participants["sender_peer_id"] = metadata.get("sender_peer_id")
            participants["peer_kind"] = metadata.get("peer_kind")
    elif obj.provider == "teams":
        participants.update(
            {
                "teams_user_id": metadata.get("teams_user_id"),
                "sender_id": metadata.get("sender_id"),
                "direction": metadata.get("direction"),
            }
        )
    return _sha256_text(
        _canonical_json(
            {
                "object_id": str(obj.id),
                "kind": obj.kind,
                "provider": obj.provider,
                "title": title,
                "body": body,
                "occurred_at": reference_iso,
                "participants": participants,
                "extractor_version": TEMPORAL_SIGNAL_EXTRACTOR_VERSION,
            }
        )
    )


def _canonical_instant(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).isoformat()
    return value.isoformat()


def calendar_event_signature(obj: Object) -> str:
    return _sha256_text(
        _canonical_json(
            {
                "object_id": str(obj.id),
                "title": obj.title,
                "start_at": _canonical_instant(obj.start_at),
                "due_at": _canonical_instant(obj.due_at),
                "provider": obj.provider,
            }
        )
    )


def hint_is_unresolved(obj: Object) -> bool:
    if obj.kind != KIND_TEMPORAL_HINT:
        return False
    if is_object_hidden_from_active_reads(obj) or obj.state == REJECTED_STATE:
        return False
    lifecycle = (obj.metadata_ or {}).get(METADATA_LIFECYCLE, LIFECYCLE_UNRESOLVED)
    return lifecycle == LIFECYCLE_UNRESOLVED


def evidence_edge_is_active(edge: Edge) -> bool:
    if edge.state == REJECTED_STATE:
        return False
    lifecycle = (edge.metadata_ or {}).get(METADATA_LIFECYCLE)
    return lifecycle not in {LIFECYCLE_SUPERSEDED_BY_SOURCE_REVISION}


def enqueue_extract_temporal_signal(
    session: Session,
    object_id: UUID,
    user_id: UUID,
    *,
    parent_trace_id: UUID | str | None = None,
    already_gated: bool = False,
) -> None:
    if not already_gated:
        settings = acquire_temporal_signals_user_gate(session, user_id)
        if settings is None or not bool(settings.temporal_signals_enabled):
            return
    elif not is_temporal_signals_enabled(session, user_id):
        return
    obj = session.scalar(select(Object).where(Object.id == object_id, Object.user_id == user_id))
    if obj is None or not object_is_temporal_source_eligible(obj):
        return
    signature = source_extraction_signature(obj)
    extra = {
        "source_signature": signature,
        "extractor_version": TEMPORAL_SIGNAL_EXTRACTOR_VERSION,
    }
    if _has_signature_job(
        session, user_id, JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL, object_id, extra
    ):
        return
    payload: dict = {
        "object_id": str(object_id),
        "source_signature": signature,
        "extractor_version": TEMPORAL_SIGNAL_EXTRACTOR_VERSION,
    }
    parent = _parent_trace_id(parent_trace_id)
    if parent is not None:
        payload["parent_trace_id"] = parent
    JobQueueService(session).enqueue(
        JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL,
        payload,
        user_id=user_id,
    )


def enqueue_reconcile_temporal_hints(
    session: Session,
    object_id: UUID,
    user_id: UUID,
    *,
    parent_trace_id: UUID | str | None = None,
    already_gated: bool = False,
) -> None:
    if not already_gated:
        settings = acquire_temporal_signals_user_gate(session, user_id)
        if settings is None or not bool(settings.temporal_signals_enabled):
            return
    elif not is_temporal_signals_enabled(session, user_id):
        return
    obj = session.scalar(select(Object).where(Object.id == object_id, Object.user_id == user_id))
    if obj is None or not object_is_calendar_reconcile_eligible(obj):
        return
    signature = calendar_event_signature(obj)
    extra = {"event_signature": signature}
    if _has_signature_job(
        session, user_id, JOB_TYPE_RECONCILE_TEMPORAL_HINTS, object_id, extra
    ):
        return
    payload: dict = {"object_id": str(object_id), "event_signature": signature}
    parent = _parent_trace_id(parent_trace_id)
    if parent is not None:
        payload["parent_trace_id"] = parent
    JobQueueService(session).enqueue(
        JOB_TYPE_RECONCILE_TEMPORAL_HINTS,
        payload,
        user_id=user_id,
    )


def _parent_trace_id(parent_trace_id: UUID | str | None) -> str | None:
    if parent_trace_id is not None:
        return str(parent_trace_id)
    active = get_active_trace()
    if active is None:
        return None
    return str(active.trace_id)


def _has_signature_job(
    session: Session,
    user_id: UUID,
    job_type: str,
    object_id: UUID,
    extra: dict,
) -> bool:
    jobs = session.scalars(
        select(Job).where(
            Job.user_id == user_id,
            Job.type == job_type,
            Job.status.in_((JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_STATUS_DONE)),
        )
    )
    object_key = str(object_id)
    for job in jobs:
        payload = job.payload or {}
        if payload.get("object_id") != object_key:
            continue
        for key, value in extra.items():
            if payload.get(key) != value:
                break
        else:
            return True
    return False


class TemporalSignalService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        *,
        extractor: TemporalSignalExtractor | None = None,
        match_judge: TemporalMatchJudge | None = None,
        after_extract: Callable[[], None] | None = None,
        after_judge: Callable[[], None] | None = None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._extractor = extractor
        self._match_judge = match_judge
        self._after_extract = after_extract
        self._after_judge = after_judge
        self._graph = GraphService(session, user_id)

    def _paid_extractor(self) -> TemporalSignalExtractor:
        if self._extractor is not None:
            return self._extractor
        return OpenAIDailyBudgetGuard.build(
            self._session, self._user_id
        ).guard_temporal_signal_extractor(
            create_temporal_signal_extractor_from_effective(
                EffectiveUserSettingsService.build(self._session).get_effective_settings(
                    self._user_id
                )
            )
        )

    def _paid_match_judge(self) -> TemporalMatchJudge:
        if self._match_judge is not None:
            return self._match_judge
        return OpenAIDailyBudgetGuard.build(
            self._session, self._user_id
        ).guard_temporal_match_judge(
            create_temporal_match_judge_from_effective(
                EffectiveUserSettingsService.build(self._session).get_effective_settings(
                    self._user_id
                )
            )
        )

    def run_extract_job(self, payload: dict) -> TemporalSignalJobOutcome:
        object_id = UUID(str(payload["object_id"]))
        payload_sig = str(payload.get("source_signature") or "")
        if not is_temporal_signals_enabled(self._session, self._user_id):
            return TemporalSignalJobOutcome(reason="disabled")
        source = self._load_source(object_id)
        if source is None or not object_is_temporal_source_eligible(source):
            return TemporalSignalJobOutcome(reason="ineligible")
        live_sig = source_extraction_signature(source)
        if live_sig != payload_sig:
            enqueue_extract_temporal_signal(self._session, object_id, self._user_id)
            return TemporalSignalJobOutcome(reason="stale_before_model", stale=True)
        parent_raw = payload.get("parent_trace_id")
        parent_trace_id = UUID(str(parent_raw)) if parent_raw else None
        with ai_trace_session(
            self._user_id,
            WORKLOAD_BACKGROUND_TEMPORAL_SIGNAL,
            object_id=object_id,
            parent_trace_id=parent_trace_id,
        ):
            outcome = self._extract_and_persist(source, payload_sig)
            self._record_result(source.id, outcome)
            return outcome

    def run_reconcile_job(self, payload: dict) -> TemporalSignalJobOutcome:
        object_id = UUID(str(payload["object_id"]))
        payload_sig = str(payload.get("event_signature") or "")
        if not is_temporal_signals_enabled(self._session, self._user_id):
            return TemporalSignalJobOutcome(reason="disabled")
        event = self._load_source(object_id)
        if event is None or not object_is_calendar_reconcile_eligible(event):
            return TemporalSignalJobOutcome(reason="ineligible")
        live_sig = calendar_event_signature(event)
        if not payload_sig or live_sig != payload_sig:
            enqueue_reconcile_temporal_hints(self._session, object_id, self._user_id)
            return TemporalSignalJobOutcome(reason="stale_before_model", stale=True)
        parent_raw = payload.get("parent_trace_id")
        parent_trace_id = UUID(str(parent_raw)) if parent_raw else None
        with ai_trace_session(
            self._user_id,
            WORKLOAD_BACKGROUND_TEMPORAL_SIGNAL,
            object_id=object_id,
            parent_trace_id=parent_trace_id,
        ):
            outcome = self._reconcile_calendar_event(event, payload_sig)
            self._record_result(event.id, outcome)
            return outcome

    def _extract_and_persist(self, source: Object, payload_sig: str) -> TemporalSignalJobOutcome:
        request = self._build_request(source)
        extractor = self._paid_extractor()
        extraction = extractor.extract(request)
        if self._after_extract is not None:
            self._after_extract()
        fenced = self._post_model_fence(source.id, payload_sig)
        if fenced is None:
            return TemporalSignalJobOutcome(reason="stale_after_model", stale=True)
        source = fenced
        if not self._signature_still_current(source, payload_sig):
            return TemporalSignalJobOutcome(reason="stale_after_model", stale=True)
        if extraction.result_class != RESULT_EXACT_TEMPORAL_SIGNAL or extraction.exact is None:
            return self._retire_source_revision(
                source,
                payload_sig,
                reason=extraction.reject_reason or extraction.result_class,
            )
        timezone = EffectiveUserSettingsService.build(self._session).get_settings_view(
            self._user_id
        ).timezone
        reference = source_reference_timestamp(source.occurred_at, source.metadata_ or {})
        resolved, reason = resolve_exact_signal(
            extraction.exact,
            timezone_name=timezone,
            source_reference_at=reference,
        )
        if resolved is None:
            return self._retire_source_revision(
                source,
                payload_sig,
                reason=reason or "unresolved_datetime",
            )
        participation = self._effective_participation(
            resolved.participation,
            resolved.extraction_confidence,
            request.participation_roles,
            request.is_channel_message,
            request.has_other_participants,
        )
        if participation in {PARTICIPATION_OTHERS_ONLY, PARTICIPATION_UNKNOWN}:
            return self._retire_source_revision(
                source,
                payload_sig,
                reason=f"participation_{participation}",
            )
        resolved = ResolvedTemporalSignal(
            title=resolved.title,
            start_at=resolved.start_at,
            due_at=resolved.due_at,
            end_precision=resolved.end_precision,
            participation=participation,
            extraction_confidence=resolved.extraction_confidence,
            semantic_subject=resolved.semantic_subject,
            source_reference_at=resolved.source_reference_at,
        )
        same_revision = self._active_same_revision_anchor(source.id, payload_sig)
        if same_revision is not None:
            return TemporalSignalJobOutcome(
                reason="already_evidenced",
                hint_id=same_revision.id if same_revision.kind == KIND_TEMPORAL_HINT else None,
                calendar_id=same_revision.id if same_revision.kind == "event" else None,
            )
        matched = self._match_existing_anchor(resolved)
        if matched is not None:
            if not self._commit_source_revision(source, payload_sig, matched, resolved):
                return TemporalSignalJobOutcome(reason="stale_after_model", stale=True)
            if matched.kind == "event":
                return TemporalSignalJobOutcome(
                    reason="calendar_first_match",
                    calendar_id=matched.id,
                )
            return TemporalSignalJobOutcome(reason="hint_merged", hint_id=matched.id)
        created = self._create_hint(resolved, source, payload_sig)
        if not self._commit_source_revision(source, payload_sig, created, resolved):
            self._refresh_hint_after_evidence_change(created)
            return TemporalSignalJobOutcome(reason="stale_after_model", stale=True)
        return TemporalSignalJobOutcome(reason="hint_created", hint_id=created.id)

    def _reconcile_calendar_event(
        self, event: Object, payload_sig: str
    ) -> TemporalSignalJobOutcome:
        unresolved = self._unresolved_hints_near(event.start_at, event.due_at)
        if not unresolved:
            return TemporalSignalJobOutcome(reason="no_hints", calendar_id=event.id)
        candidates = [self._candidate_from_object(item) for item in unresolved]
        judge = self._paid_match_judge()
        result = judge.judge(
            trigger_title=event.title or "",
            trigger_subject=self._content_summary(event),
            trigger_kind="event",
            candidates=candidates,
            operation=TEMPORAL_SIGNAL_AUDIT_RECONCILE_MATCH,
        )
        if self._after_judge is not None:
            self._after_judge()
        fenced = self._post_reconcile_fence(event.id, payload_sig)
        if fenced is None:
            return TemporalSignalJobOutcome(reason="stale_after_model", stale=True)
        event = fenced
        allowed = {item.object_id for item in candidates}
        decision = result.decision
        if (
            decision is None
            or decision.target_object_id not in allowed
            or decision.confidence < TEMPORAL_SIGNAL_MATCH_MIN_CONFIDENCE
            or not _finite_score(decision.confidence)
        ):
            return TemporalSignalJobOutcome(reason="no_semantic_match", calendar_id=event.id)
        hint = self._load_source(decision.target_object_id)
        if hint is None or not hint_is_unresolved(hint):
            return TemporalSignalJobOutcome(reason="hint_gone", calendar_id=event.id)
        self._suppress_hint(hint, event)
        for edge in self._active_evidence_edges(anchor_id=hint.id):
            source = self._load_source(edge.target_id)
            if source is None:
                continue
            self._upsert_evidence(
                event,
                source,
                decision.confidence,
                self._edge_source_signature(edge),
                extractor_version=self._edge_extractor_version(edge),
            )
        return TemporalSignalJobOutcome(
            reason="hint_superseded",
            hint_id=hint.id,
            calendar_id=event.id,
        )

    def _match_existing_anchor(self, resolved: ResolvedTemporalSignal) -> Object | None:
        events = self._calendar_candidates(resolved.start_at, resolved.due_at)
        hints = self._unresolved_hints_near(resolved.start_at, resolved.due_at)
        combined: list[Object] = []
        seen: set[UUID] = set()
        for item in [*events, *hints]:
            if item.id in seen:
                continue
            seen.add(item.id)
            combined.append(item)
            if len(combined) >= TEMPORAL_SIGNAL_MAX_CANDIDATES:
                break
        return self._judge_match(
            resolved,
            combined,
            trigger_kind=KIND_TEMPORAL_HINT,
            operation=TEMPORAL_SIGNAL_AUDIT_MATCH,
        )

    def _judge_match(
        self,
        resolved: ResolvedTemporalSignal,
        objects: list[Object],
        *,
        trigger_kind: str,
        operation: str,
    ) -> Object | None:
        if not objects:
            return None
        candidates = [self._candidate_from_object(item) for item in objects]
        judge = self._paid_match_judge()
        result = judge.judge(
            trigger_title=resolved.title,
            trigger_subject=resolved.semantic_subject,
            trigger_kind=trigger_kind,
            candidates=candidates,
            operation=operation,
        )
        allowed = {item.object_id for item in candidates}
        decision = result.decision
        if (
            decision is None
            or decision.target_object_id not in allowed
            or decision.confidence < TEMPORAL_SIGNAL_MATCH_MIN_CONFIDENCE
            or not _finite_score(decision.confidence)
        ):
            return None
        return next(item for item in objects if item.id == decision.target_object_id)

    def _calendar_candidates(self, start_at: datetime, due_at: datetime | None) -> list[Object]:
        window_start = start_at - TEMPORAL_SIGNAL_CANDIDATE_WINDOW
        window_end = (due_at or start_at) + TEMPORAL_SIGNAL_CANDIDATE_WINDOW
        rows = list(
            self._session.scalars(
                select(Object)
                .where(
                    *active_event_predicates(self._user_id),
                    Object.provider.in_(WEEK_CALENDAR_PROVIDERS),
                    event_overlaps_window(window_start, window_end),
                )
                .order_by(Object.start_at.asc(), Object.id.asc())
                .limit(TEMPORAL_SIGNAL_MAX_CANDIDATES)
            )
        )
        return [row for row in rows if _temporally_compatible(start_at, due_at, row.start_at, row.due_at)]

    def _unresolved_hints_near(self, start_at: datetime | None, due_at: datetime | None) -> list[Object]:
        if start_at is None:
            return []
        window_start = start_at - TEMPORAL_SIGNAL_CANDIDATE_WINDOW
        window_end = (due_at or start_at) + TEMPORAL_SIGNAL_CANDIDATE_WINDOW
        rows = list(
            self._session.scalars(
                select(Object)
                .where(
                    Object.user_id == self._user_id,
                    Object.kind == KIND_TEMPORAL_HINT,
                    Object.state != REJECTED_STATE,
                    Object.deleted_at.is_(None),
                    Object.start_at.is_not(None),
                    event_overlaps_window(window_start, window_end),
                )
                .order_by(Object.start_at.asc(), Object.id.asc())
                .limit(TEMPORAL_SIGNAL_MAX_CANDIDATES)
            )
        )
        return [
            row
            for row in rows
            if hint_is_unresolved(row)
            and _temporally_compatible(start_at, due_at, row.start_at, row.due_at)
        ]

    def _create_hint(
        self,
        resolved: ResolvedTemporalSignal,
        source: Object,
        source_signature: str,
    ) -> Object:
        metadata = {
            METADATA_TEMPORAL_SIGNAL_VERSION: TEMPORAL_SIGNAL_METADATA_VERSION,
            METADATA_START_PRECISION: START_PRECISION_EXACT,
            METADATA_END_PRECISION: resolved.end_precision,
            METADATA_PARTICIPATION: resolved.participation,
            METADATA_PRIMARY_EVIDENCE_OBJECT_ID: str(source.id),
            METADATA_PRIMARY_EVIDENCE_PROVIDER: source.provider,
            METADATA_PRIMARY_EVIDENCE_KIND: source.kind,
            METADATA_EVIDENCE_COUNT: 1,
            METADATA_EXTRACTION_CONFIDENCE: resolved.extraction_confidence,
            METADATA_SOURCE_REFERENCE_AT: resolved.source_reference_at.isoformat(),
            METADATA_SOURCE_SIGNATURE: source_signature,
            METADATA_EXTRACTOR_VERSION: TEMPORAL_SIGNAL_EXTRACTOR_VERSION,
            METADATA_LIFECYCLE: LIFECYCLE_UNRESOLVED,
        }
        if resolved.semantic_subject:
            metadata[METADATA_SEMANTIC_SUBJECT] = resolved.semantic_subject
        hint = self._graph.create_object(
            ObjectCreate(
                kind=KIND_TEMPORAL_HINT,
                title=resolved.title,
                origin=SYSTEM_ORIGIN,
                state=OBSERVED_STATE,
                start_at=resolved.start_at,
                due_at=resolved.due_at,
                metadata=metadata,
                confidence=resolved.extraction_confidence,
            )
        )
        return hint

    def _signature_still_current(self, source: Object, payload_sig: str) -> bool:
        return source_extraction_signature(source) == payload_sig

    def _edge_source_signature(self, edge: Edge) -> str:
        return str((edge.metadata_ or {}).get(METADATA_SOURCE_SIGNATURE) or "")

    def _evidence_edges_for_source(self, source_id: UUID) -> list[Edge]:
        return list(
            self._session.scalars(
                select(Edge)
                .where(
                    Edge.user_id == self._user_id,
                    Edge.target_id == source_id,
                    Edge.type == EDGE_TYPE_TEMPORAL_EVIDENCE,
                )
                .order_by(Edge.created_at.asc(), Edge.id.asc())
                .limit(TEMPORAL_SIGNAL_MAX_EVIDENCE_EDGES_SCAN)
            )
        )

    def _active_evidence_edges(self, *, anchor_id: UUID | None = None, source_id: UUID | None = None) -> list[Edge]:
        stmt = select(Edge).where(
            Edge.user_id == self._user_id,
            Edge.type == EDGE_TYPE_TEMPORAL_EVIDENCE,
        )
        if anchor_id is not None:
            stmt = stmt.where(Edge.source_id == anchor_id)
        if source_id is not None:
            stmt = stmt.where(Edge.target_id == source_id)
        rows = list(
            self._session.scalars(
                stmt.order_by(Edge.created_at.asc(), Edge.id.asc()).limit(
                    TEMPORAL_SIGNAL_MAX_EVIDENCE_EDGES_SCAN
                )
            )
        )
        return [edge for edge in rows if evidence_edge_is_active(edge)]

    def _find_evidence_edge(self, anchor_id: UUID, source_id: UUID) -> Edge | None:
        return self._session.scalar(
            select(Edge)
            .where(
                Edge.user_id == self._user_id,
                Edge.source_id == anchor_id,
                Edge.target_id == source_id,
                Edge.type == EDGE_TYPE_TEMPORAL_EVIDENCE,
            )
            .order_by(Edge.created_at.asc(), Edge.id.asc())
            .limit(1)
        )

    def _edge_extractor_version(self, edge: Edge) -> int:
        raw = (edge.metadata_ or {}).get(METADATA_EXTRACTOR_VERSION)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def _active_same_revision_anchor(self, source_id: UUID, payload_sig: str) -> Object | None:
        active = self._active_evidence_edges(source_id=source_id)
        matching = [
            edge
            for edge in active
            if self._edge_source_signature(edge) == payload_sig
            and self._edge_extractor_version(edge) == TEMPORAL_SIGNAL_EXTRACTOR_VERSION
        ]
        if not matching or len(matching) != len(active):
            return None
        return self._load_source(matching[0].source_id)

    def _retire_evidence_edge(self, edge: Edge, payload_sig: str) -> None:
        metadata = dict(edge.metadata_ or {})
        metadata[METADATA_LIFECYCLE] = LIFECYCLE_SUPERSEDED_BY_SOURCE_REVISION
        if payload_sig:
            metadata["retired_by_source_signature"] = payload_sig
        edge.metadata_ = metadata
        self._session.flush()

    def _write_evidence_revision(
        self,
        edge: Edge,
        signature: str,
        confidence: float,
        *,
        extractor_version: int | None = None,
    ) -> None:
        metadata = dict(edge.metadata_ or {})
        metadata.pop(METADATA_LIFECYCLE, None)
        metadata.pop("retired_by_source_signature", None)
        metadata[METADATA_SOURCE_SIGNATURE] = signature
        metadata[METADATA_EXTRACTOR_VERSION] = (
            TEMPORAL_SIGNAL_EXTRACTOR_VERSION if extractor_version is None else extractor_version
        )
        edge.metadata_ = metadata
        edge.confidence = confidence
        self._session.flush()

    def _upsert_evidence(
        self,
        anchor: Object,
        source: Object,
        confidence: float,
        signature: str,
        *,
        extractor_version: int | None = None,
    ) -> None:
        version = (
            TEMPORAL_SIGNAL_EXTRACTOR_VERSION if extractor_version is None else extractor_version
        )
        edge = self._find_evidence_edge(anchor.id, source.id)
        if edge is not None:
            self._write_evidence_revision(
                edge,
                signature,
                confidence,
                extractor_version=version,
            )
            return
        self._graph.create_edge(
            EdgeCreate(
                source_id=anchor.id,
                target_id=source.id,
                type=EDGE_TYPE_TEMPORAL_EVIDENCE,
                origin=SYSTEM_ORIGIN,
                state=OBSERVED_STATE,
                confidence=confidence,
                metadata={
                    METADATA_EXTRACTOR_VERSION: version,
                    METADATA_SOURCE_SIGNATURE: signature,
                },
            )
        )

    def _commit_source_revision(
        self,
        source: Object,
        payload_sig: str,
        anchor: Object,
        resolved: ResolvedTemporalSignal,
    ) -> bool:
        if not self._signature_still_current(source, payload_sig):
            enqueue_extract_temporal_signal(self._session, source.id, self._user_id)
            return False
        affected: list[UUID] = []
        for edge in self._evidence_edges_for_source(source.id):
            if not evidence_edge_is_active(edge):
                continue
            if edge.source_id == anchor.id:
                self._write_evidence_revision(edge, payload_sig, resolved.extraction_confidence)
                continue
            self._retire_evidence_edge(edge, payload_sig)
            affected.append(edge.source_id)
        self._upsert_evidence(anchor, source, resolved.extraction_confidence, payload_sig)
        for object_id in dict.fromkeys([*affected, anchor.id]):
            obj = self._load_source(object_id)
            if obj is not None:
                self._refresh_hint_after_evidence_change(obj)
        return True

    def _retire_source_revision(
        self,
        source: Object,
        payload_sig: str,
        *,
        reason: str,
    ) -> TemporalSignalJobOutcome:
        if not self._signature_still_current(source, payload_sig):
            enqueue_extract_temporal_signal(self._session, source.id, self._user_id)
            return TemporalSignalJobOutcome(reason="stale_after_model", stale=True)
        affected: list[UUID] = []
        for edge in self._evidence_edges_for_source(source.id):
            if not evidence_edge_is_active(edge):
                continue
            if self._edge_source_signature(edge) == payload_sig:
                continue
            self._retire_evidence_edge(edge, payload_sig)
            affected.append(edge.source_id)
        for object_id in dict.fromkeys(affected):
            obj = self._load_source(object_id)
            if obj is not None:
                self._refresh_hint_after_evidence_change(obj)
        return TemporalSignalJobOutcome(reason=reason)

    def _refresh_hint_after_evidence_change(self, obj: Object) -> None:
        if obj.kind != KIND_TEMPORAL_HINT:
            return
        active = self._active_evidence_edges(anchor_id=obj.id)
        metadata = dict(obj.metadata_ or {})
        metadata[METADATA_EVIDENCE_COUNT] = len(active)
        if not active:
            if metadata.get(METADATA_LIFECYCLE, LIFECYCLE_UNRESOLVED) == LIFECYCLE_UNRESOLVED:
                metadata[METADATA_LIFECYCLE] = LIFECYCLE_SUPERSEDED_BY_SOURCE_REVISION
            metadata.pop(METADATA_SOURCE_SIGNATURE, None)
            obj.metadata_ = metadata
            self._session.flush()
            return
        primary_id = None
        raw_primary = metadata.get(METADATA_PRIMARY_EVIDENCE_OBJECT_ID)
        if raw_primary:
            try:
                primary_id = UUID(str(raw_primary))
            except ValueError:
                primary_id = None
        active_source_ids = {edge.target_id for edge in active}
        if primary_id not in active_source_ids:
            chosen = min(active, key=lambda edge: (edge.created_at, str(edge.id)))
            primary_id = chosen.target_id
        primary = self._load_source(primary_id) if primary_id is not None else None
        if primary is not None:
            metadata[METADATA_PRIMARY_EVIDENCE_OBJECT_ID] = str(primary.id)
            metadata[METADATA_PRIMARY_EVIDENCE_PROVIDER] = primary.provider
            metadata[METADATA_PRIMARY_EVIDENCE_KIND] = primary.kind
            metadata[METADATA_SOURCE_SIGNATURE] = source_extraction_signature(primary)
        obj.metadata_ = metadata
        self._session.flush()

    def _suppress_hint(self, hint: Object, calendar: Object) -> None:
        if not has_equivalent_relation(
            self._session,
            self._user_id,
            hint.id,
            calendar.id,
            EDGE_TYPE_TEMPORAL_CONFIRMATION,
        ):
            self._graph.create_edge(
                EdgeCreate(
                    source_id=hint.id,
                    target_id=calendar.id,
                    type=EDGE_TYPE_TEMPORAL_CONFIRMATION,
                    origin=SYSTEM_ORIGIN,
                    state=OBSERVED_STATE,
                    metadata={
                        METADATA_LIFECYCLE: LIFECYCLE_SUPERSEDED_BY_CALENDAR,
                    },
                )
            )
        metadata = dict(hint.metadata_ or {})
        metadata[METADATA_LIFECYCLE] = LIFECYCLE_SUPERSEDED_BY_CALENDAR
        metadata[METADATA_SUPERSEDED_BY_OBJECT_ID] = str(calendar.id)
        hint.metadata_ = metadata
        self._session.flush()

    def _evidence_sources(self, hint: Object) -> list[Object]:
        edges = self._active_evidence_edges(anchor_id=hint.id)
        if not edges:
            return []
        ids = [edge.target_id for edge in edges]
        return list(
            self._session.scalars(
                select(Object).where(Object.user_id == self._user_id, Object.id.in_(ids))
            )
        )

    def _build_request(self, source: Object) -> TemporalExtractionRequest:
        title, body = bounded_source_text(source)
        snapshot = PersonalRelevanceEvidenceService.build(self._session).build_snapshot(
            self._user_id,
            [source.id],
        )
        roles: tuple[str, ...] = ()
        if snapshot.objects:
            roles = snapshot.objects[0].user_participation_roles
        metadata = source.metadata_ or {}
        is_channel = source.provider == SOURCE_MATTERMOST and bool(metadata.get("channel_id"))
        if (
            source.provider == "telegram"
            and metadata.get("transport") == "mtproto"
            and metadata.get("peer_kind") in {"group", "supergroup"}
        ):
            is_channel = True
        has_others = _has_other_participants(source, roles)
        return TemporalExtractionRequest(
            object_id=source.id,
            kind=source.kind,
            provider=source.provider,
            title=title,
            body=body,
            source_reference_at=source_reference_timestamp(source.occurred_at, metadata),
            timezone=EffectiveUserSettingsService.build(self._session).get_settings_view(
                self._user_id
            ).timezone,
            participation_roles=roles,
            is_channel_message=is_channel,
            has_other_participants=has_others,
            semantic_summary=bounded_semantic_summary(source),
        )

    def _effective_participation(
        self,
        llm_value: str,
        confidence: float,
        roles: tuple[str, ...],
        is_channel: bool,
        has_others: bool,
    ) -> str:
        directed = bool(
            set(roles)
            & {
                "direct_recipient",
                "copied_recipient",
                "mentioned",
                "organizer",
                "attendee",
                "sender",
                "author",
            }
        )
        if llm_value == PARTICIPATION_OTHERS_ONLY:
            return PARTICIPATION_OTHERS_ONLY
        if not directed and not is_channel:
            return PARTICIPATION_OTHERS_ONLY
        if llm_value == PARTICIPATION_UNKNOWN:
            return PARTICIPATION_UNKNOWN
        if llm_value == PARTICIPATION_POSSIBLE:
            if confidence < TEMPORAL_SIGNAL_POSSIBLE_MIN_CONFIDENCE:
                return PARTICIPATION_UNKNOWN
            return PARTICIPATION_POSSIBLE
        if confidence < TEMPORAL_SIGNAL_EXPECTED_MIN_CONFIDENCE:
            return PARTICIPATION_UNKNOWN
        if directed:
            return PARTICIPATION_EXPECTED
        if is_channel or has_others:
            if confidence >= TEMPORAL_SIGNAL_POSSIBLE_MIN_CONFIDENCE:
                return PARTICIPATION_POSSIBLE
            return PARTICIPATION_UNKNOWN
        return PARTICIPATION_OTHERS_ONLY

    def _post_model_fence(self, object_id: UUID, payload_sig: str) -> Object | None:
        self._session.expire_all()
        settings = acquire_temporal_signals_user_gate(self._session, self._user_id)
        if settings is None or not bool(settings.temporal_signals_enabled):
            return None
        source = self._load_source(object_id)
        if source is None or not object_is_temporal_source_eligible(source):
            return None
        if source_extraction_signature(source) != payload_sig:
            enqueue_extract_temporal_signal(
                self._session,
                object_id,
                self._user_id,
                already_gated=True,
            )
            return None
        return source

    def _post_reconcile_fence(self, object_id: UUID, payload_sig: str) -> Object | None:
        self._session.expire_all()
        settings = acquire_temporal_signals_user_gate(self._session, self._user_id)
        if settings is None or not bool(settings.temporal_signals_enabled):
            return None
        event = self._load_source(object_id)
        if event is None or not object_is_calendar_reconcile_eligible(event):
            return None
        if calendar_event_signature(event) != payload_sig:
            enqueue_reconcile_temporal_hints(
                self._session,
                object_id,
                self._user_id,
                already_gated=True,
            )
            return None
        return event

    def _load_source(self, object_id: UUID) -> Object | None:
        obj = self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if obj is None or not telegram_mtproto_ai_eligible(self._session, obj):
            return None
        return obj

    def _candidate_from_object(self, obj: Object) -> TemporalMatchCandidate:
        return TemporalMatchCandidate(
            object_id=obj.id,
            kind=obj.kind,
            title=obj.title or "",
            start_at=obj.start_at,
            due_at=obj.due_at,
            summary=self._content_summary(obj),
            provider=obj.provider,
        )

    def _content_summary(self, obj: Object) -> str:
        summary = (obj.metadata_ or {}).get(SEMANTIC_SUMMARY_METADATA_KEY)
        if isinstance(summary, str) and summary.strip():
            return summary.strip()[:500]
        if obj.body and obj.body.strip():
            return obj.body.strip()[:500]
        return (obj.title or "")[:500]

    def _record_result(self, source_id: UUID, outcome: TemporalSignalJobOutcome) -> None:
        active = get_active_trace()
        if active is None:
            return
        active.record_event(
            "temporal_signal_result",
            {
                "source_object_id": str(source_id),
                "extractor_version": TEMPORAL_SIGNAL_EXTRACTOR_VERSION,
                "result_class": outcome.reason,
                "accepted_rejected_reason": outcome.reason,
                "chosen_calendar_id": str(outcome.calendar_id) if outcome.calendar_id else None,
                "chosen_hint_id": str(outcome.hint_id) if outcome.hint_id else None,
                "stale": outcome.stale,
            },
        )


def _finite_score(value: float) -> bool:
    return math.isfinite(value) and 0.0 <= value <= 1.0


def _temporally_compatible(
    left_start: datetime | None,
    left_end: datetime | None,
    right_start: datetime | None,
    right_end: datetime | None,
) -> bool:
    if left_start is None or right_start is None:
        return False
    if abs(left_start - right_start) <= TEMPORAL_SIGNAL_START_PROXIMITY:
        return True
    if left_end is None and right_end is not None:
        return right_start <= left_start < right_end
    if right_end is None and left_end is not None:
        return left_start <= right_start < left_end
    if left_end is not None and right_end is not None:
        return left_start < right_end and right_start < left_end
    return False


def _has_other_participants(obj: Object, roles: tuple[str, ...]) -> bool:
    metadata = obj.metadata_ or {}
    if _string_values(metadata.get("recipients")) or _string_values(metadata.get("cc")):
        return True
    if metadata.get("mentioned_user_ids") or metadata.get("mentioned_usernames"):
        return True
    author = metadata.get("author_user_id") or metadata.get("author_username")
    if author and "author" not in roles:
        return True
    sender = extract_email_address(metadata.get("sender"))
    return bool(sender) and "sender" not in roles
