from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.ai_audit.constants import WORKLOAD_BACKGROUND_PROACTIVE_REVIEW
from app.ai_audit.context import ai_trace_session, get_current_job_id, record_if_active
from app.core.assistant_openai_config import AssistantOpenAIConfigError
from app.db.models import Edge, Notification, Object
from app.domain.labels import KIND_LABEL
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.scheduled_activity import KIND_SCHEDULED_ACTIVITY
from app.domain.task_lifecycle import TASK_STATUS_IN_PROGRESS, TASK_STATUS_OPEN
from app.jobs.constants import JOB_TYPE_PROACTIVE_REVIEW
from app.llm.openai_assistant_provider import OpenAIAssistantProvider
from app.notifications.constants import (
    NOTIFICATION_STATUS_NEW,
    NOTIFICATION_STATUS_READ,
)
from app.personal_relevance.models import (
    PERSONAL_RELEVANCE_EVIDENCE_VERSION,
    PersonalRelevanceEvidenceSnapshot,
)
from app.proactive.constants import (
    NOTIFICATION_KIND_INSIGHT,
    NOTIFICATION_KIND_TASK_PROPOSAL,
    PROACTIVE_EVENT_HORIZON,
    PROACTIVE_EVENT_KINDS,
    PROACTIVE_GATE_ORIGINS,
    PROACTIVE_INTERVAL_MINUTES_DEFAULT,
    PROACTIVE_MAX_OUTPUT_TOKENS,
    PROACTIVE_MAX_ROUNDS,
    PROACTIVE_MAX_UNRESOLVED,
    PROACTIVE_MIN_CONFIDENCE,
    PROACTIVE_PERSONAL_RELEVANCE_EVENT,
    PROACTIVE_SEED_OBJECT_LIMIT,
    PROACTIVE_SIGNATURE_COOLDOWN,
    PROACTIVE_SIGNATURE_VERSION,
    PROACTIVE_TASK_HORIZON,
    PROACTIVE_TASK_LOOKBACK,
    PROPOSAL_TYPE_PROACTIVE_INSIGHT,
    PROPOSAL_TYPE_TASK,
    STALE_FENCE_INCOMPLETE,
    STALE_FENCE_NOT_APPLICABLE,
    STALE_FENCE_STALE,
    STALE_FENCE_UNCHANGED,
)
from app.proactive.control import read_proactive_control
from app.proactive.decision import ProactiveDecision, ProactiveNotificationPayload
from app.proactive.instructions import PROACTIVE_SYSTEM_INSTRUCTIONS
from app.proactive.tool_runner import ProactiveToolRunner
from app.services.background_ai_errors import BackgroundAIConfigurationError
from app.services.domain_tool_service import DomainToolService
from app.services.effective_user_settings_service import (
    EffectiveUserSettings,
    EffectiveUserSettingsService,
)
from app.services.job_queue_service import JobQueueService, utcnow
from app.services.notification_service import NotificationService
from app.services.openai_daily_budget import OpenAIDailyBudgetGuard
from app.services.personal_relevance_evidence_service import (
    PersonalRelevanceEvidenceService,
    acquire_personal_relevance_authority,
)
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE
from app.tools.registry import PROACTIVE_TOOL_DEFINITIONS

logger = logging.getLogger(__name__)

_UNRESOLVED_STATUSES = (NOTIFICATION_STATUS_NEW, NOTIFICATION_STATUS_READ)
_REFERENCES_EDGE = "references"


def snapshot_covers_seed_ids(
    snapshot: PersonalRelevanceEvidenceSnapshot,
    seed_ids: Sequence[UUID],
) -> bool:
    expected = {str(item) for item in seed_ids}
    object_ids = [str(item.object_id) for item in snapshot.objects]
    if len(object_ids) != len(set(object_ids)):
        return False
    if snapshot.version != PERSONAL_RELEVANCE_EVIDENCE_VERSION:
        return False
    if snapshot.truncated_objects:
        return False
    signature_keys = set(snapshot.object_evidence_signatures)
    return signature_keys == expected and set(object_ids) == expected


def personal_relevance_evidence_is_stale(
    initial: PersonalRelevanceEvidenceSnapshot,
    fresh: PersonalRelevanceEvidenceSnapshot,
    seed_ids: Sequence[UUID],
) -> bool:
    if not snapshot_covers_seed_ids(initial, seed_ids):
        return True
    if not snapshot_covers_seed_ids(fresh, seed_ids):
        return True
    if initial.version != fresh.version:
        return True
    if initial.user_context_signature != fresh.user_context_signature:
        return True
    if dict(initial.object_evidence_signatures) != dict(fresh.object_evidence_signatures):
        return True
    if initial.truncated_objects != fresh.truncated_objects:
        return True
    return initial.user_context.truncated != fresh.user_context.truncated


def seed_context_from_evidence(
    seed_objects: list[Object],
    snapshot: PersonalRelevanceEvidenceSnapshot,
) -> dict:
    seed_ids = [obj.id for obj in seed_objects]
    if not snapshot_covers_seed_ids(snapshot, seed_ids):
        raise ValueError("personal relevance snapshot does not cover the Proactive seed set")
    evidence_by_id = {item.object_id: item for item in snapshot.objects}
    seed_payload = []
    for obj in seed_objects:
        evidence = evidence_by_id[obj.id]
        payload = evidence.to_payload()
        seed_payload.append(
            {
                "id": str(obj.id),
                "kind": obj.kind,
                "title": obj.title,
                "status": obj.status,
                "origin": obj.origin,
                "updated_at": parse_aware_datetime(obj.updated_at).isoformat()
                if parse_aware_datetime(obj.updated_at)
                else None,
                "due_at": parse_aware_datetime(obj.due_at).isoformat()
                if parse_aware_datetime(obj.due_at)
                else None,
                "start_at": parse_aware_datetime(obj.start_at).isoformat()
                if parse_aware_datetime(obj.start_at)
                else None,
                "object_id": payload["object_id"],
                "provider": payload["provider"],
                "state": payload["state"],
                "occurred_at": payload["occurred_at"],
                "user_participation_roles": payload["user_participation_roles"],
                "participation_truncated": payload["participation_truncated"],
                "assigned_labels": payload["assigned_labels"],
                "labels_truncated": payload["labels_truncated"],
                "object_evidence_signature": snapshot.object_evidence_signatures[str(obj.id)],
            }
        )
    return {
        "user_context": snapshot.user_context.to_payload(),
        "user_context_signature": snapshot.user_context_signature,
        "evidence_version": snapshot.version,
        "truncated_objects": snapshot.truncated_objects,
        "seed_objects": seed_payload,
    }


def create_proactive_provider(effective: EffectiveUserSettings) -> OpenAIAssistantProvider:
    if not effective.openai_api_key:
        raise BackgroundAIConfigurationError("OpenAI API key is not configured")
    return OpenAIAssistantProvider(
        api_key=effective.openai_api_key,
        model=effective.assistant_model,
        reasoning_effort=effective.assistant_reasoning_effort,
        verbosity=effective.assistant_verbosity,
        max_output_tokens=PROACTIVE_MAX_OUTPUT_TOKENS,
        max_rounds=PROACTIVE_MAX_ROUNDS,
    )


def parse_aware_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            return value.replace(tzinfo=UTC)
        return value
    text = str(value).strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))  # noqa: FURB162
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def is_proactive_proposal(proposal: dict | None) -> bool:
    if not isinstance(proposal, dict):
        return False
    if proposal.get("proactive") is True:
        return True
    if proposal.get("type") == PROPOSAL_TYPE_PROACTIVE_INSIGHT:
        return True
    return bool(proposal.get("proactive_signature"))


def compute_proactive_signature(
    *,
    kind: str,
    source: Object,
    related: Object | None,
    task_due_at: datetime | None,
    task_start_at: datetime | None,
) -> str:
    updated = parse_aware_datetime(source.updated_at) or utcnow()
    parts = [
        f"v{PROACTIVE_SIGNATURE_VERSION}",
        kind,
        str(source.id),
        updated.isoformat(),
        str(related.id) if related is not None else "",
        task_due_at.isoformat() if task_due_at is not None else "",
        task_start_at.isoformat() if task_start_at is not None else "",
    ]
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest


def _proactive_proposal_sql():
    proposal = Notification.proposal_
    signature = proposal["proactive_signature"].as_string()
    return or_(
        proposal["proactive"].as_boolean().is_(True),
        proposal["type"].as_string() == PROPOSAL_TYPE_PROACTIVE_INSIGHT,
        and_(signature.is_not(None), signature != ""),
    )


class ProactiveReviewService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        *,
        after_llm=None,
        after_authority=None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._queue = JobQueueService(session)
        self._notifications = NotificationService(session, user_id)
        self._settings_service = EffectiveUserSettingsService.build(session)
        self._after_llm = after_llm
        self._after_authority = after_authority

    def run(self, payload: dict) -> None:
        control = read_proactive_control(self._session, self._user_id, for_update=False)
        if not control.enabled:
            return
        now = utcnow()
        window_start = parse_aware_datetime(payload.get("window_start"))
        if window_start is None:
            window_start = now - timedelta(minutes=control.interval_minutes)
        window_end = now
        if self._unresolved_proactive_count() >= PROACTIVE_MAX_UNRESOLVED:
            self._commit_quiet_successor(window_end)
            return
        seed_objects = self._gate_seed_objects(window_start, window_end, now)
        if not seed_objects:
            self._commit_quiet_successor(window_end)
            return
        if not read_proactive_control(self._session, self._user_id, for_update=False).enabled:
            return
        effective = self._load_effective()
        outcome = self._run_llm(effective, seed_objects, window_start, window_end)
        if outcome["incomplete"]:
            self._commit_quiet_successor(window_end)
            return
        decision = outcome["decision"]
        runner = outcome["runner"]
        if runner is not None and runner.has_rejected_tool_attempt:
            decision = None
        if outcome["authority_held"]:
            if outcome["enabled"]:
                if runner is None or not runner.has_rejected_tool_attempt:
                    self._maybe_notify(decision)
                self._enqueue_successor(window_end, outcome["interval_minutes"])
            return
        locked = read_proactive_control(self._session, self._user_id, for_update=True)
        if not locked.enabled:
            return
        self._maybe_notify(decision)
        self._enqueue_successor(window_end, locked.interval_minutes)

    def _commit_quiet_successor(self, window_end: datetime) -> None:
        locked = read_proactive_control(self._session, self._user_id, for_update=True)
        if not locked.enabled:
            return
        self._enqueue_successor(window_end, locked.interval_minutes)

    def _load_effective(self) -> EffectiveUserSettings:
        try:
            return self._settings_service.get_effective_settings(self._user_id)
        except AssistantOpenAIConfigError as exc:
            raise BackgroundAIConfigurationError(str(exc)) from exc

    def _enqueue_successor(self, window_end: datetime, interval_minutes: int) -> None:
        self._queue.enqueue(
            JOB_TYPE_PROACTIVE_REVIEW,
            {"window_start": window_end.isoformat()},
            self._user_id,
            run_after=window_end + timedelta(minutes=interval_minutes),
        )

    def _unresolved_proactive_count(self) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == self._user_id,
                    Notification.status.in_(_UNRESOLVED_STATUSES),
                    _proactive_proposal_sql(),
                )
            )
            or 0
        )

    def _gate_seed_objects(
        self,
        window_start: datetime,
        window_end: datetime,
        now: datetime,
    ) -> list[Object]:
        found: dict[UUID, Object] = {}
        for obj in self._recent_activity(window_start, window_end):
            found[obj.id] = obj
        for obj in self._attention_tasks(now):
            found[obj.id] = obj
        for obj in self._upcoming_events(now):
            found[obj.id] = obj
        objects = list(found.values())
        objects.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        return objects[:PROACTIVE_SEED_OBJECT_LIMIT]

    def _visible_owned(self) -> list:
        return [
            Object.user_id == self._user_id,
            object_is_active(),
            Object.state != REJECTED_STATE,
        ]

    def _recent_activity(self, window_start: datetime, window_end: datetime) -> list[Object]:
        parent_email_id = Object.metadata_["parent_email_id"].as_string()
        child_email_attachment = and_(
            Object.origin == "source",
            Object.kind == "file",
            parent_email_id.is_not(None),
            parent_email_id != "",
        )
        stmt = (
            select(Object)
            .where(
                *self._visible_owned(),
                Object.origin.in_(tuple(PROACTIVE_GATE_ORIGINS)),
                Object.kind != KIND_SCHEDULED_ACTIVITY,
                Object.kind != KIND_LABEL,
                Object.updated_at > window_start,
                Object.updated_at <= window_end,
                ~child_email_attachment,
            )
            .order_by(Object.updated_at.desc(), Object.id.desc())
            .limit(PROACTIVE_SEED_OBJECT_LIMIT)
        )
        return list(self._session.scalars(stmt))

    def _attention_tasks(self, now: datetime) -> list[Object]:
        start = now - PROACTIVE_TASK_LOOKBACK
        end = now + PROACTIVE_TASK_HORIZON
        stmt = (
            select(Object)
            .where(
                *self._visible_owned(),
                Object.kind == "task",
                Object.status.in_((TASK_STATUS_OPEN, TASK_STATUS_IN_PROGRESS)),
                Object.due_at.is_not(None),
                Object.due_at >= start,
                Object.due_at <= end,
            )
            .order_by(Object.due_at.asc(), Object.id.asc())
            .limit(PROACTIVE_SEED_OBJECT_LIMIT)
        )
        return list(self._session.scalars(stmt))

    def _upcoming_events(self, now: datetime) -> list[Object]:
        end = now + PROACTIVE_EVENT_HORIZON
        stmt = (
            select(Object)
            .where(
                *self._visible_owned(),
                Object.kind.in_(PROACTIVE_EVENT_KINDS),
                Object.start_at.is_not(None),
                Object.start_at > now,
                Object.start_at <= end,
            )
            .order_by(Object.start_at.asc(), Object.id.asc())
            .limit(PROACTIVE_SEED_OBJECT_LIMIT)
        )
        return list(self._session.scalars(stmt))

    def _run_llm(
        self,
        effective: EffectiveUserSettings,
        seed_objects: list[Object],
        window_start: datetime,
        window_end: datetime,
    ) -> dict:
        tools = DomainToolService(
            self._session,
            self._user_id,
            None,
            defer_write_embeddings=True,
            client_timezone=effective.timezone,
        )
        seed_ids = [obj.id for obj in seed_objects]
        seed_id_set = set(seed_ids)
        runner = ProactiveToolRunner(
            tools,
            initial_seen_object_ids=seed_ids,
        )
        empty = {
            "decision": None,
            "runner": runner,
            "incomplete": False,
            "authority_held": False,
            "enabled": False,
            "interval_minutes": PROACTIVE_INTERVAL_MINUTES_DEFAULT,
        }
        if not read_proactive_control(self._session, self._user_id, for_update=False).enabled:
            return empty
        evidence_service = PersonalRelevanceEvidenceService.build(self._session)
        snapshot = evidence_service.build_snapshot(self._user_id, seed_ids)
        if not snapshot_covers_seed_ids(snapshot, seed_ids):
            logger.info("proactive seed personal-relevance evidence incomplete")
            empty["incomplete"] = True
            return empty
        provider = OpenAIDailyBudgetGuard.build(
            self._session, self._user_id
        ).guard_assistant_provider(create_proactive_provider(effective))
        message = (
            "Perform a bounded proactive attention review. "
            f"window_start={window_start.isoformat()} "
            f"window_end={window_end.isoformat()}. "
            "Return exact JSON for ProactiveDecision."
        )
        seed_context = json.dumps(
            seed_context_from_evidence(seed_objects, snapshot),
            ensure_ascii=False,
        )
        job_id = get_current_job_id()
        parsed = None
        fence_result = STALE_FENCE_NOT_APPLICABLE
        authority_held = False
        enabled = False
        interval_minutes = PROACTIVE_INTERVAL_MINUTES_DEFAULT
        with ai_trace_session(
            self._user_id,
            WORKLOAD_BACKGROUND_PROACTIVE_REVIEW,
            job_id=job_id,
        ):
            result = provider.run(
                message,
                [],
                seed_context,
                window_end,
                effective.timezone,
                runner,
                system_instructions=PROACTIVE_SYSTEM_INSTRUCTIONS,
                tool_definitions=PROACTIVE_TOOL_DEFINITIONS,
            )
            runner.commit_model_visible_outputs()
            pre_fence = None
            if not runner.has_rejected_tool_attempt:
                parsed = self._parse_decision(result.answer)
                if parsed is not None:
                    parsed = self._bind_seen_ids(
                        parsed,
                        seed_ids=seed_id_set,
                        seen_ids=runner.seen_object_ids | seed_id_set,
                    )
                pre_fence = parsed
                if (
                    parsed is not None
                    and parsed.decision == "notify"
                    and parsed.notification is not None
                ):
                    if self._after_llm is not None:
                        self._after_llm()
                    self._session.expire_all()
                    settings = acquire_personal_relevance_authority(
                        self._session, self._user_id, seed_ids
                    )
                    authority_held = True
                    if settings is None:
                        parsed = None
                    else:
                        locked = read_proactive_control(
                            self._session, self._user_id, for_update=False
                        )
                        enabled = locked.enabled
                        interval_minutes = locked.interval_minutes
                        if not enabled:
                            parsed = None
                        else:
                            fresh = evidence_service.build_snapshot(self._user_id, seed_ids)
                            if not snapshot_covers_seed_ids(fresh, seed_ids):
                                parsed = None
                                fence_result = STALE_FENCE_INCOMPLETE
                            elif personal_relevance_evidence_is_stale(
                                snapshot, fresh, seed_ids
                            ):
                                parsed = None
                                fence_result = STALE_FENCE_STALE
                            else:
                                fence_result = STALE_FENCE_UNCHANGED
                                if self._after_authority is not None:
                                    self._after_authority()
            record_if_active(
                PROACTIVE_PERSONAL_RELEVANCE_EVENT,
                self._personal_relevance_audit_metadata(
                    snapshot=snapshot,
                    seed_count=len(seed_objects),
                    pre_fence=pre_fence,
                    decision=parsed,
                    fence_result=fence_result,
                ),
            )
        return {
            "decision": parsed,
            "runner": runner,
            "incomplete": False,
            "authority_held": authority_held,
            "enabled": enabled,
            "interval_minutes": interval_minutes,
        }

    def _personal_relevance_audit_metadata(
        self,
        *,
        snapshot: PersonalRelevanceEvidenceSnapshot,
        seed_count: int,
        pre_fence: ProactiveDecision | None,
        decision: ProactiveDecision | None,
        fence_result: str,
    ) -> dict:
        source_signature = None
        source_participation_truncated = None
        source_labels_truncated = None
        kind = None
        relationship = None
        dependency = None
        outcome = "none" if decision is None else decision.decision
        judgment_source = decision if decision is not None else pre_fence
        if judgment_source is not None and judgment_source.personal_relevance is not None:
            relationship = judgment_source.personal_relevance.relationship.value
            dependency = judgment_source.personal_relevance.dependency.value
        notification = None
        if decision is not None and decision.notification is not None:
            notification = decision.notification
        elif pre_fence is not None and pre_fence.notification is not None:
            notification = pre_fence.notification
        if notification is not None:
            source_id = str(notification.source_object_id)
            source_signature = snapshot.object_evidence_signatures.get(source_id)
            evidence_by_id = {str(item.object_id): item for item in snapshot.objects}
            source_evidence = evidence_by_id.get(source_id)
            if source_evidence is not None:
                source_participation_truncated = source_evidence.participation_truncated
                source_labels_truncated = source_evidence.labels_truncated
            if outcome == "notify":
                kind = notification.kind
        return {
            "evidence_version": PERSONAL_RELEVANCE_EVIDENCE_VERSION,
            "seed_count": seed_count,
            "user_context_signature": snapshot.user_context_signature,
            "source_object_evidence_signature": source_signature,
            "relationship": relationship,
            "dependency": dependency,
            "user_context_truncated": snapshot.user_context.truncated,
            "source_participation_truncated": source_participation_truncated,
            "source_labels_truncated": source_labels_truncated,
            "stale_fence": fence_result,
            "decision": outcome,
            "notification_kind": kind,
        }

    def _parse_decision(self, raw: str | None) -> ProactiveDecision | None:
        if not raw or not raw.strip():
            return None
        try:
            payload = json.loads(raw.strip())
            return ProactiveDecision.model_validate(payload)
        except (json.JSONDecodeError, ValueError):
            logger.info("proactive review returned unusable structured output")
            return None

    def _bind_seen_ids(
        self,
        decision: ProactiveDecision,
        *,
        seed_ids: set[UUID],
        seen_ids: set[UUID],
    ) -> ProactiveDecision | None:
        if decision.decision == "none" or decision.notification is None:
            return decision
        notification = decision.notification
        if notification.confidence < PROACTIVE_MIN_CONFIDENCE:
            return None
        source = self._load_visible_object(notification.source_object_id)
        if source is None or source.id not in seed_ids:
            return None
        if notification.related_object_id is not None:
            related = self._load_visible_object(notification.related_object_id)
            if related is None or related.id not in seen_ids:
                return None
        if notification.kind == NOTIFICATION_KIND_TASK_PROPOSAL:
            if source.kind == "task":
                return None
            if self._active_task_references(source.id):
                return None
        return decision

    def _load_visible_object(self, object_id: UUID) -> Object | None:
        obj = self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if obj is None:
            return None
        if is_object_hidden_from_active_reads(obj) or obj.state == REJECTED_STATE:
            return None
        return obj

    def _active_task_references(self, source_object_id: UUID) -> bool:
        stmt = select(
            exists(
                select(Object.id)
                .join(Edge, Edge.source_id == Object.id)
                .where(
                    Object.user_id == self._user_id,
                    Object.kind == "task",
                    object_is_active(),
                    Object.state == CONFIRMED_STATE,
                    Object.status.in_((TASK_STATUS_OPEN, TASK_STATUS_IN_PROGRESS)),
                    Edge.user_id == self._user_id,
                    Edge.type == _REFERENCES_EDGE,
                    Edge.state == CONFIRMED_STATE,
                    Edge.target_id == source_object_id,
                )
            )
        )
        return bool(self._session.scalar(stmt))

    def _maybe_notify(self, decision: ProactiveDecision | None) -> None:
        if decision is None or decision.decision != "notify" or decision.notification is None:
            return
        payload = decision.notification
        source = self._load_visible_object(payload.source_object_id)
        if source is None:
            return
        related = None
        if payload.related_object_id is not None:
            related = self._load_visible_object(payload.related_object_id)
            if related is None:
                return
        if self._has_unresolved_same_source(source.id):
            return
        task_due = payload.task.due_at if payload.task is not None else None
        task_start = payload.task.start_at if payload.task is not None else None
        signature = compute_proactive_signature(
            kind=payload.kind,
            source=source,
            related=related,
            task_due_at=task_due,
            task_start_at=task_start,
        )
        if self._has_recent_signature(signature):
            return
        proposal = self._build_proposal(payload, signature)
        self._notifications.create(
            title=payload.title,
            body=payload.body,
            priority=payload.priority,
            proposal=proposal,
            source_object_id=source.id,
            related_object_id=related.id if related is not None else None,
        )

    def _has_unresolved_same_source(self, source_object_id: UUID) -> bool:
        stmt = select(
            exists(
                select(Notification.id).where(
                    Notification.user_id == self._user_id,
                    Notification.source_object_id == source_object_id,
                    Notification.status.in_(_UNRESOLVED_STATUSES),
                    _proactive_proposal_sql(),
                )
            )
        )
        return bool(self._session.scalar(stmt))

    def _has_recent_signature(self, signature: str) -> bool:
        cutoff = utcnow() - PROACTIVE_SIGNATURE_COOLDOWN
        stmt = select(
            exists(
                select(Notification.id).where(
                    Notification.user_id == self._user_id,
                    Notification.created_at >= cutoff,
                    Notification.proposal_["proactive_signature"].as_string() == signature,
                )
            )
        )
        return bool(self._session.scalar(stmt))

    def _build_proposal(
        self,
        payload: ProactiveNotificationPayload,
        signature: str,
    ) -> dict:
        if payload.kind == NOTIFICATION_KIND_INSIGHT:
            return {
                "type": PROPOSAL_TYPE_PROACTIVE_INSIGHT,
                "version": PROACTIVE_SIGNATURE_VERSION,
                "confidence": payload.confidence,
                "proactive": True,
                "proactive_signature": signature,
            }
        task = payload.task
        assert task is not None
        proposal: dict = {
            "type": PROPOSAL_TYPE_TASK,
            "title": task.title,
            "description": task.description,
            "confidence": payload.confidence,
            "proactive": True,
            "proactive_signature": signature,
            "version": PROACTIVE_SIGNATURE_VERSION,
        }
        if task.due_at is not None:
            proposal["due_at"] = task.due_at.isoformat()
        if task.start_at is not None:
            proposal["start_at"] = task.start_at.isoformat()
        return proposal
