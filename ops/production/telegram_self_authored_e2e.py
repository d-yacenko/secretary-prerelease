#!/usr/bin/env python3
"""Acceptance harness for already-synced self-authored MTProto objects.

The synthetic rehearsal is not this path. This module never inserts Telegram
messages, tasks, or labels. It only reads the marker cohort, fail-closes
unless every selected message and every Telegram message in its summary
cohort is self-authored, then enqueues the normal handlers for that cohort.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.connectors.telegram.constants import TELEGRAM_KIND, TELEGRAM_PROVIDER
from app.core.config import settings
from app.db.models import Job, Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection
from app.domain.telegram_mtproto_ai import is_canonical_telegram_mtproto_object
from app.jobs.constants import (
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_SUMMARIZE_CONVERSATION_STACK,
    JOB_TYPE_SYNC_TELEGRAM_MTPROTO,
)
from app.jobs.handlers import get_handler
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.summarizer import FakeSummarizer
from app.llm.temporal_match_judge import FakeTemporalMatchJudge
from app.llm.temporal_signal_extractor import FakeTemporalSignalExtractor
from app.services.auto_label_models import AutoLabelClassifierResult
from app.services.conversation_stack import group_inbox_conversation_items
from app.services.conversation_stack_summary import enqueue_summarize_conversation_stack
from app.services.correlation_models import CorrelationDecision, CorrelationJudgeResult
from app.services.job_queue_service import JobQueueService
from app.services.pipeline_enqueue import enqueue_embed_object

MARKER = "TG_SELF_E2E_0922A"
MIN_MESSAGES = 2
MAX_DRAIN_STEPS = 48
BURST = timedelta(minutes=15)
ABORTED = "harness_aborted"
LongRunningProbe = Callable[[], tuple[bool, bool]]


class HarnessBlocked(RuntimeError):
    pass


class HarnessTransportBlocked(RuntimeError):
    pass


@dataclass
class _Barrier:
    calls: int = 0
    restores: list[tuple[object, str, object]] | None = None

    def block(self, *_args, **_kwargs):
        self.calls += 1
        raise HarnessTransportBlocked("telegram_transport")


@dataclass(frozen=True)
class Cohort:
    user_id: UUID
    account: TelegramMtprotoAccount
    peer_id: str
    messages: tuple[Object, ...]
    task_id: UUID


def _token(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _meta(obj: Object) -> dict:
    return dict(obj.metadata_ or {})


def load_marker_objects(session: Session) -> list[Object]:
    return list(
        session.scalars(
            select(Object).where(
                Object.deleted_at.is_(None),
                or_(Object.body.contains(MARKER), Object.title.contains(MARKER)),
            )
        )
    )


def message_identity_block(obj: Object, account: TelegramMtprotoAccount | None) -> str | None:
    """Return a block code. Direction alone never proves self-authorship."""
    if not is_canonical_telegram_mtproto_object(obj):
        return "canonical"
    meta = _meta(obj)
    if account is None:
        return "identity"
    if _token(meta.get("account_id")) != str(account.id):
        return "account"
    direction = meta.get("direction")
    if direction == "inbound":
        return "direction"
    if direction != "outbound":
        return "identity"
    sender = _token(meta.get("sender_peer_id"))
    owner = _token(account.telegram_user_id)
    if sender is None or owner is None:
        return "identity"
    if sender != owner:
        return "sender"
    if MARKER not in (obj.body or "") and MARKER not in (obj.title or ""):
        return "marker"
    return None


def prove_cohort(session: Session, rows: list[Object]) -> Cohort:
    messages: list[Object] = []
    tasks: list[Object] = []
    for obj in rows:
        if obj.kind == "task" and obj.provider is None:
            tasks.append(obj)
            continue
        if obj.kind == "task" and obj.provider not in {None, ""}:
            raise HarnessBlocked("foreign_marker_object")
        if not is_canonical_telegram_mtproto_object(obj):
            raise HarnessBlocked("foreign_marker_object")
        messages.append(obj)
    if len(messages) < MIN_MESSAGES:
        raise HarnessBlocked("cohort_size")
    user_ids = {obj.user_id for obj in messages}
    if len(user_ids) != 1:
        raise HarnessBlocked("mixed_user")
    user_id = user_ids.pop()
    account_ids = {_token(_meta(obj).get("account_id")) for obj in messages}
    peer_ids = {_token(_meta(obj).get("peer_id")) for obj in messages}
    if None in account_ids or len(account_ids) != 1:
        raise HarnessBlocked("mixed_account")
    if None in peer_ids or len(peer_ids) != 1:
        raise HarnessBlocked("mixed_peer")
    raw_account = account_ids.pop()
    peer_id = peer_ids.pop()
    assert raw_account is not None and peer_id is not None
    try:
        account_id = UUID(raw_account)
        peer_int = int(peer_id)
    except (TypeError, ValueError):
        raise HarnessBlocked("identity") from None
    account = session.scalar(
        select(TelegramMtprotoAccount).where(
            TelegramMtprotoAccount.id == account_id,
            TelegramMtprotoAccount.user_id == user_id,
        )
    )
    if account is None:
        raise HarnessBlocked("identity")
    selection = session.scalar(
        select(TelegramMtprotoChatSelection).where(
            TelegramMtprotoChatSelection.account_id == account.id,
            TelegramMtprotoChatSelection.peer_id == peer_int,
        )
    )
    if selection is None or not selection.scope_active:
        raise HarnessBlocked("scope")
    for obj in messages:
        reason = message_identity_block(obj, account)
        if reason:
            raise HarnessBlocked(reason)
    if len(tasks) != 1 or tasks[0].user_id != user_id:
        raise HarnessBlocked("marker_task")
    ordered = tuple(sorted(messages, key=lambda item: (item.occurred_at, item.id)))
    return Cohort(
        user_id=user_id,
        account=account,
        peer_id=peer_id,
        messages=ordered,
        task_id=tasks[0].id,
    )


def summary_candidates(session: Session, cohort: Cohort) -> list[Object]:
    stamps = [obj.occurred_at for obj in cohort.messages if obj.occurred_at is not None]
    if len(stamps) != len(cohort.messages):
        raise HarnessBlocked("identity")
    start = min(stamps) - BURST
    end = max(stamps) + BURST
    rows = list(
        session.scalars(
            select(Object).where(
                Object.user_id == cohort.user_id,
                Object.deleted_at.is_(None),
                Object.provider == TELEGRAM_PROVIDER,
                Object.kind == TELEGRAM_KIND,
            )
        )
    )
    window: list[Object] = []
    for obj in rows:
        meta = _meta(obj)
        if _token(meta.get("account_id")) != str(cohort.account.id):
            continue
        if _token(meta.get("peer_id")) != cohort.peer_id:
            continue
        if obj.occurred_at is None or obj.occurred_at < start or obj.occurred_at > end:
            continue
        window.append(obj)
    return sorted(window, key=lambda item: (item.occurred_at, item.id))


def prove_summary_cohort(session: Session, cohort: Cohort) -> frozenset[UUID]:
    """Block before any provider call if summary text could include a stranger."""
    objects = summary_candidates(session, cohort)
    selected = {obj.id for obj in cohort.messages}
    if not selected <= {obj.id for obj in objects}:
        raise HarnessBlocked("summary_cohort")
    groups = group_inbox_conversation_items(objects)
    covered = [group for group in groups if selected.intersection(group.object_ids)]
    if not covered:
        raise HarnessBlocked("summary_cohort")
    approved: set[UUID] = set()
    for group in covered:
        members = [obj for obj in objects if obj.id in group.object_ids]
        for obj in members:
            if obj.provider == TELEGRAM_PROVIDER and message_identity_block(obj, cohort.account):
                raise HarnessBlocked("summary_cohort")
            if is_canonical_telegram_mtproto_object(obj):
                approved.add(obj.id)
    if not selected <= approved:
        raise HarnessBlocked("summary_cohort")
    return frozenset(approved)


class PrivacyCorrelationJudge:
    """Acceptance-only fence in front of the real or fake correlation judge."""

    def __init__(self, inner, session: Session, approved_telegram_ids: frozenset[UUID]) -> None:
        self._inner = inner
        self._session = session
        self._approved = approved_telegram_ids
        self.calls = 0

    def judge(self, trigger_title, trigger_kind, trigger_summary, candidates):
        for candidate in candidates:
            obj = self._session.get(Object, candidate.object_id)
            if obj is None:
                raise HarnessBlocked("correlation_privacy")
            if is_canonical_telegram_mtproto_object(obj) and obj.id not in self._approved:
                raise HarnessBlocked("correlation_privacy")
        self.calls += 1
        return self._inner.judge(
            trigger_title=trigger_title,
            trigger_kind=trigger_kind,
            trigger_summary=trigger_summary,
            candidates=candidates,
        )


def _job_object_ids(job: Job) -> set[UUID]:
    payload = job.payload or {}
    found: set[UUID] = set()
    raw = payload.get("object_id")
    if raw:
        found.add(UUID(str(raw)))
    anchor = payload.get("anchor_object_id")
    if anchor:
        found.add(UUID(str(anchor)))
    for item in payload.get("object_ids") or []:
        found.add(UUID(str(item)))
    return found


def _selected_jobs(session: Session, cohort: Cohort) -> list[Job]:
    selected = {obj.id for obj in cohort.messages}
    jobs = list(session.scalars(select(Job).where(Job.user_id == cohort.user_id)))
    return [job for job in jobs if _job_object_ids(job) & selected]


def _park_selected(session: Session, cohort: Cohort) -> None:
    now = datetime.now(UTC)
    for job in _selected_jobs(session, cohort):
        if job.type == JOB_TYPE_SYNC_TELEGRAM_MTPROTO:
            raise HarnessBlocked("telegram_sync_job")
        if job.status != JOB_STATUS_PENDING:
            continue
        job.status = JOB_STATUS_RUNNING
        job.locked_at = now
    session.flush()


def _fail_selected(session: Session, cohort: Cohort) -> None:
    selected = {obj.id for obj in cohort.messages}
    user_id = cohort.user_id
    queue = JobQueueService(session)
    for job in session.scalars(select(Job).where(Job.user_id == user_id)):
        if not _job_object_ids(job) & selected:
            continue
        if job.status in {JOB_STATUS_PENDING, JOB_STATUS_RUNNING}:
            queue.mark_failed(job.id, ABORTED)
    session.commit()


def _dangling_selected(session: Session, cohort: Cohort) -> int:
    return sum(
        1
        for job in _selected_jobs(session, cohort)
        if job.status in {JOB_STATUS_PENDING, JOB_STATUS_RUNNING}
    )


class _BoundSession:
    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def commit(self) -> None:
        self._session.flush()

    def __getattr__(self, name: str):
        return getattr(self._session, name)


@contextmanager
def _session_bridges(session: Session) -> Iterator[None]:
    proxy = lambda: _BoundSession(session)
    targets = (
        "app.ai_audit.context.SessionLocal",
        "app.jobs.handlers.SessionLocal",
        "app.services.representation_embedding_worker.SessionLocal",
    )
    from unittest.mock import patch

    with patch(targets[0], proxy), patch(targets[1], proxy), patch(targets[2], proxy):
        yield


@contextmanager
def transport_barrier() -> Iterator[_Barrier]:
    barrier = _Barrier(restores=[])
    finder = _TransportFinder(barrier)
    sys.meta_path.insert(0, finder)
    hidden = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "telethon" or name.startswith("telethon.")
    }
    transport = sys.modules.get("app.connectors.telegram.mtproto_transport")
    if transport is not None:
        client = getattr(transport, "TelethonMtprotoTransport", None)
        if client is not None:
            for name, member in list(vars(client).items()):
                if callable(member) and (not name.startswith("__") or name == "__init__"):
                    barrier.restores.append((client, name, member))
                    setattr(client, name, barrier.block)
    import app.connectors.telegram.mtproto_account_store as store

    account_store = store.TelegramMtprotoAccountStore
    barrier.restores.append((account_store, "decrypt_session", account_store.decrypt_session))
    account_store.decrypt_session = barrier.block
    try:
        yield barrier
    finally:
        for owner, name, member in reversed(barrier.restores or []):
            setattr(owner, name, member)
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)
        sys.modules.update(hidden)


class _TransportFinder:
    def __init__(self, barrier: _Barrier) -> None:
        self._barrier = barrier

    def find_spec(self, fullname, path, target=None):
        blocked = fullname == "telethon" or fullname.startswith("telethon.")
        blocked = blocked or fullname == "app.connectors.telegram.mtproto_transport"
        blocked = blocked or fullname.startswith("app.connectors.telegram.mtproto_transport.")
        if blocked and fullname not in sys.modules:
            self._barrier.calls += 1
            raise HarnessTransportBlocked(fullname)


@contextmanager
def _fake_providers(
    task_id: UUID,
    session: Session,
    approved_telegram_ids: frozenset[UUID],
) -> Iterator[FakeEmbeddingService]:
    from unittest.mock import patch

    extractor = FakeTemporalSignalExtractor(
        payload={
            "result_class": "exact_temporal_signal",
            "concise_title": "marker meeting",
            "start_date_kind": "relative_day",
            "start_relative_day_offset": 1,
            "start_local_time": "11:00",
            "end_precision": "exact",
            "end_kind": "duration_minutes",
            "end_duration_minutes": 30,
            "participation": "possible",
            "extraction_confidence": 0.92,
            "semantic_subject": "marker meeting",
        }
    )

    class _Classifier:
        def classify(self, obj, candidates, personal):
            del obj, candidates, personal
            return AutoLabelClassifierResult(assignments=(), raw_assignment_count=0)

    class _Judge:
        def judge(self, trigger_title, trigger_kind, trigger_summary, candidates):
            del trigger_title, trigger_kind, trigger_summary, candidates
            return CorrelationJudgeResult(
                decisions=(
                    CorrelationDecision(
                        target_object_id=task_id,
                        relation_type="related_to",
                        confidence=0.91,
                        rationale="marker task",
                    ),
                )
            )

    with (
        patch(
            "app.services.temporal_signals_service.create_temporal_signal_extractor_from_effective",
            lambda _settings: extractor,
        ),
        patch(
            "app.services.temporal_signals_service.create_temporal_match_judge_from_effective",
            lambda _settings: FakeTemporalMatchJudge(),
        ),
        patch(
            "app.services.auto_label_service.create_auto_label_classifier_from_effective",
            lambda _settings: _Classifier(),
        ),
        patch(
            "app.jobs.handlers.create_correlation_judge_from_effective",
            lambda _settings: PrivacyCorrelationJudge(_Judge(), session, approved_telegram_ids),
        ),
        patch(
            "app.llm.openai_summarizer.create_openai_conversation_stack_summarizer_from_effective",
            lambda _settings: FakeSummarizer(max_chars=80),
        ),
    ):
        yield FakeEmbeddingService()


def _enqueue_cohort(session: Session, cohort: Cohort) -> None:
    for obj in cohort.messages:
        enqueue_embed_object(session, obj.id, cohort.user_id)
    grouped = group_inbox_conversation_items(list(cohort.messages))
    stacks = [item.stack for item in grouped if item.stack is not None]
    if len(stacks) != 1:
        raise HarnessBlocked("summary_cohort")
    enqueue_summarize_conversation_stack(session, cohort.user_id, stacks[0])


def _drain(session: Session, cohort: Cohort, embedding) -> list[str]:
    used: list[str] = []
    queue = JobQueueService(session)
    for _ in range(MAX_DRAIN_STEPS):
        _park_selected(session, cohort)
        running = [
            item for item in _selected_jobs(session, cohort) if item.status == JOB_STATUS_RUNNING
        ]
        job = min(running, key=lambda item: (item.created_at, item.id), default=None)
        if job is None:
            return used
        handler = get_handler(job.type)
        if handler is None:
            raise HarnessBlocked("unknown_job")
        used.append(job.type)
        handler(session, embedding, dict(job.payload), cohort.user_id)
        queue.mark_done(job.id)
        session.flush()
    raise HarnessBlocked("drain_exceeded")


def format_report(
    *,
    cohort_size: int,
    handlers: list[str],
    auto_label_events: int,
    assignments: int,
    dangling: int,
    transport_calls: int,
    api_ai: bool,
    worker_ai: bool,
    env_changed: bool,
    providers: str,
    embedding: bool,
    temporal: bool,
    temporal_participation: str,
    temporal_result: str,
    correlation: bool,
    summary: bool,
    context_visible: bool,
    retrieval_visible: bool,
    idempotent: bool,
) -> str:
    if temporal_participation not in {"expected", "possible", "none"}:
        raise HarnessBlocked("unsanitized_output")
    if temporal_result not in {"temporal_hint", "none"}:
        raise HarnessBlocked("unsanitized_output")
    lines = [
        f"COHORT_SIZE={cohort_size}",
        "SELF_AUTHORED=PASS",
        "SUMMARY_COHORT_SELF_AUTHORED=PASS",
        f"HANDLERS={','.join(handlers)}",
        f"EMBEDDING={'PASS' if embedding else 'FAIL'}",
        f"AUTO_LABEL_EXECUTED={'PASS' if auto_label_events else 'FAIL'}",
        f"AUTO_LABEL_ASSIGNMENTS={assignments}",
        f"TEMPORAL={'PASS' if temporal else 'FAIL'}",
        f"TEMPORAL_PARTICIPATION={temporal_participation}",
        f"TEMPORAL_RESULT={temporal_result}",
        f"CORRELATION={'PASS' if correlation else 'FAIL'}",
        f"SUMMARY={'PASS' if summary else 'FAIL'}",
        f"CONTEXT_VISIBLE={'PASS' if context_visible else 'FAIL'}",
        f"RETRIEVAL_VISIBLE={'PASS' if retrieval_visible else 'FAIL'}",
        f"IDEMPOTENT={'PASS' if idempotent else 'FAIL'}",
        f"DANGLING_SELECTED_JOBS={dangling}",
        f"TELEGRAM_TRANSPORT_CALLS={transport_calls}",
        "PROCESS_LOCAL_AI=true",
        f"ENV_UNCHANGED={'PASS' if not env_changed else 'FAIL'}",
        f"LONG_RUNNING_API_AI={'true' if api_ai else 'false'}",
        f"LONG_RUNNING_WORKER_AI={'true' if worker_ai else 'false'}",
        f"PROVIDERS={providers}",
        "LIVE_EXECUTION=0" if providers == "fake" else "LIVE_EXECUTION=1",
    ]
    text = "\n".join(lines) + "\n"
    lowered = text.lower()
    if MARKER in text or "sk-" in lowered or "session" in lowered:
        raise HarnessBlocked("unsanitized_output")
    return text


def _auto_label_event_rows(session: Session, selected_ids: set[UUID]):
    from app.db.models import AITrace, AITraceEvent

    return list(
        session.execute(
            select(AITraceEvent.id, AITraceEvent.metadata_, AITrace.object_id)
            .join(AITrace, AITrace.id == AITraceEvent.trace_id)
            .where(
                AITraceEvent.event_type == "auto_label_result",
                AITrace.object_id.in_(selected_ids),
            )
        )
    )


def snapshot_auto_label_events(session: Session, selected_ids: set[UUID]) -> set[UUID]:
    return {row[0] for row in _auto_label_event_rows(session, selected_ids)}


def _auto_label_evidence(
    session: Session,
    selected_ids: set[UUID],
    baseline_ids: set[UUID],
) -> tuple[int, int]:
    events = 0
    assignments = 0
    for event_id, metadata, object_id in _auto_label_event_rows(session, selected_ids):
        if event_id in baseline_ids or object_id not in selected_ids:
            continue
        events += 1
        if isinstance(metadata, dict):
            assignments += int(metadata.get("accepted_assignment_count") or 0)
    return events, assignments


def _artifact_ids(session: Session, cohort: Cohort) -> frozenset[tuple[str, UUID]]:
    from app.db.models import Edge, Representation

    found: set[tuple[str, UUID]] = set()
    hints = session.scalars(
        select(Object).where(Object.user_id == cohort.user_id, Object.kind == "temporal_hint")
    )
    for hint in hints:
        found.add(("hint", hint.id))
    edges = session.scalars(select(Edge).where(Edge.user_id == cohort.user_id))
    for edge in edges:
        found.add(("edge", edge.id))
    anchors = [obj.id for obj in cohort.messages]
    reps = session.scalars(select(Representation).where(Representation.object_id.in_(anchors)))
    for rep in reps:
        found.add(("summary", rep.id))
    return frozenset(found)


def _outcome_proofs(
    session: Session, cohort: Cohort, baseline: frozenset[tuple[str, UUID]]
) -> dict:
    from app.db.models import Edge, Representation
    from app.llm.embedding_text import embedding_input_signature
    from app.services.context_service import ContextService
    from app.services.embedding_index import object_has_current_embedding_provenance
    from app.services.object_query_service import ObjectQueryService
    from app.services.search_service import SearchService

    selected = {obj.id for obj in cohort.messages}
    embedding_ok = True
    for obj in cohort.messages:
        session.refresh(obj)
        if not object_has_current_embedding_provenance(obj, embedding_input_signature(obj)):
            embedding_ok = False
    new_ids = _artifact_ids(session, cohort) - baseline
    hint_ids = {item_id for kind, item_id in new_ids if kind == "hint"}
    hints = list(session.scalars(select(Object).where(Object.id.in_(hint_ids)))) if hint_ids else []
    matched = []
    for hint in hints:
        evidence = str((hint.metadata_ or {}).get("primary_evidence_object_id") or "")
        if evidence in {str(item) for item in selected}:
            matched.append(hint)
    participation = "none"
    result = "none"
    if matched:
        participation = str((matched[0].metadata_ or {}).get("participation") or "none")
        result = "temporal_hint"
    edge_ids = {item_id for kind, item_id in new_ids if kind == "edge"}
    linked = False
    if edge_ids:
        for edge in session.scalars(select(Edge).where(Edge.id.in_(edge_ids))):
            if (
                edge.source_id in selected
                and edge.target_id == cohort.task_id
                and edge.type == "related_to"
                and edge.state == "proposed"
            ):
                linked = True
    summary_ids = {item_id for kind, item_id in new_ids if kind == "summary"}
    summary_ok = False
    if summary_ids:
        grouped = group_inbox_conversation_items(list(cohort.messages))
        stacks = [item.stack for item in grouped if item.stack is not None]
        if len(stacks) == 1:
            current = session.scalar(
                select(Representation).where(
                    Representation.id.in_(summary_ids),
                    Representation.kind == "conversation_stack_summary",
                    Representation.object_id == stacks[0].object_ids[-1],
                )
            )
            meta = (
                current.metadata_
                if current is not None and isinstance(current.metadata_, dict)
                else {}
            )
            summary_ok = bool(
                current and current.text and meta.get("stack_fingerprint") == stacks[0].fingerprint
            )
    visible = ObjectQueryService(session, cohort.user_id, ai_only=True).query(
        kinds=["chat_message"], providers=["telegram"]
    )
    context_ok = False
    try:
        context = ContextService(session, cohort.user_id).build_context(
            object_id=cohort.messages[0].id
        )
        context_ok = any(item.object_id == cohort.messages[0].id for item in context.items)
    except Exception:  # noqa: BLE001
        context_ok = False
    query = _narrow_query(cohort)
    found = SearchService(session, cohort.user_id).search(
        query=query or "x",
        kind="chat_message",
        provider="telegram",
    )
    return {
        "embedding": embedding_ok,
        "temporal": bool(matched),
        "temporal_participation": participation
        if participation in {"expected", "possible", "none"}
        else "none",
        "temporal_result": result,
        "correlation": linked,
        "summary": summary_ok,
        "context_visible": any(obj.id in selected for obj in visible) and context_ok,
        "retrieval_visible": any(item.id in selected for item in found),
    }


def _narrow_query(cohort: Cohort) -> str:
    import re

    blocked = set(re.findall(r"[A-Za-z0-9]{4,}", MARKER))
    for obj in cohort.messages:
        for token in re.findall(r"[A-Za-z0-9]{4,}", obj.body or ""):
            if token not in blocked:
                return token
    return ""


@contextmanager
def _live_correlation_guard(session: Session, approved: frozenset[UUID]) -> Iterator[None]:
    from unittest.mock import patch

    from app.llm.correlation_judge import create_correlation_judge_from_effective

    def factory(effective):
        return PrivacyCorrelationJudge(
            create_correlation_judge_from_effective(effective),
            session,
            approved,
        )

    with patch("app.jobs.handlers.create_correlation_judge_from_effective", factory):
        yield


def run_acceptance(
    session: Session,
    *,
    probe: LongRunningProbe,
    providers: str = "fake",
    commit: Callable[[], None] | None = None,
    on_ready: Callable[[], None] | None = None,
) -> str:
    if providers not in {"fake", "live"}:
        raise HarnessBlocked("providers")
    if settings.telegram_mtproto_ai_enabled:
        raise HarnessBlocked("ai_already_enabled")
    api_ai, worker_ai = probe()
    if api_ai or worker_ai:
        raise HarnessBlocked("long_running_ai")
    cohort = prove_cohort(session, load_marker_objects(session))
    approved = prove_summary_cohort(session, cohort)
    selected_ids = {obj.id for obj in cohort.messages}
    auto_label_baseline = snapshot_auto_label_events(session, selected_ids)
    artifact_baseline = _artifact_ids(session, cohort)
    if on_ready is not None:
        on_ready()
    if settings.telegram_mtproto_ai_enabled:
        raise HarnessBlocked("ai_already_enabled")
    env_before = os.environ.get("TELEGRAM_MTPROTO_AI_ENABLED")
    previous = settings.telegram_mtproto_ai_enabled
    commit = commit or session.commit
    settings.telegram_mtproto_ai_enabled = True
    try:
        with transport_barrier() as barrier:
            if providers == "fake":
                bridge = _session_bridges(session)
                paid = _fake_providers(cohort.task_id, session, approved)
            else:
                bridge = _live_correlation_guard(session, approved)
                paid = nullcontext(None)
            with bridge, paid as embedding:
                _enqueue_cohort(session, cohort)
                _park_selected(session, cohort)
                commit()
                try:
                    handlers = _drain(session, cohort, embedding)
                    before = _artifact_ids(session, cohort)
                    _enqueue_cohort(session, cohort)
                    _park_selected(session, cohort)
                    handlers.extend(_drain(session, cohort, embedding))
                    idempotent = before == _artifact_ids(session, cohort)
                except HarnessBlocked:
                    _fail_selected(session, cohort)
                    raise
                except Exception:  # noqa: BLE001
                    _fail_selected(session, cohort)
                    raise HarnessBlocked(ABORTED) from None
        events, assignments = _auto_label_evidence(session, selected_ids, auto_label_baseline)
        outcomes = _outcome_proofs(session, cohort, artifact_baseline)
        summary_jobs = [
            job
            for job in _selected_jobs(session, cohort)
            if job.type == JOB_TYPE_SUMMARIZE_CONVERSATION_STACK
        ]
        if any(job.status == JOB_STATUS_PENDING for job in summary_jobs):
            raise HarnessBlocked("summary_not_run")
        return format_report(
            cohort_size=len(cohort.messages),
            handlers=handlers,
            auto_label_events=events,
            assignments=assignments,
            dangling=_dangling_selected(session, cohort),
            transport_calls=barrier.calls,
            api_ai=api_ai,
            worker_ai=worker_ai,
            env_changed=os.environ.get("TELEGRAM_MTPROTO_AI_ENABLED") != env_before,
            providers=providers,
            idempotent=idempotent and _dangling_selected(session, cohort) == 0,
            **outcomes,
        )
    finally:
        settings.telegram_mtproto_ai_enabled = previous


def live_long_running_probe() -> tuple[bool, bool]:
    api = os.environ.get("REHEARSAL_LONG_RUNNING_API_AI")
    worker = os.environ.get("REHEARSAL_LONG_RUNNING_WORKER_AI")
    if api is None or worker is None:
        raise HarnessBlocked("long_running_probe")
    true_flags = {"1", "true", "yes", "on"}
    return (api.strip().lower() in true_flags, worker.strip().lower() in true_flags)


def _restore_process_local(previous: bool, env_before: str | None) -> None:
    settings.telegram_mtproto_ai_enabled = previous
    if os.environ.get("TELEGRAM_MTPROTO_AI_ENABLED") != env_before:
        if env_before is None:
            os.environ.pop("TELEGRAM_MTPROTO_AI_ENABLED", None)
        else:
            os.environ["TELEGRAM_MTPROTO_AI_ENABLED"] = env_before


def execute_live(*, session_factory=None) -> int:
    if os.environ.get("SELF_E2E_CONFIRM") != "reviewed":
        sys.stdout.write("SELF_E2E_BLOCKED=review_required\n")
        return 2
    from app.db.session import SessionLocal

    previous = settings.telegram_mtproto_ai_enabled
    env_before = os.environ.get("TELEGRAM_MTPROTO_AI_ENABLED")
    session = (session_factory or SessionLocal)()
    try:
        report = run_acceptance(
            session,
            probe=live_long_running_probe,
            providers="live",
        )
    except HarnessBlocked as exc:
        sys.stdout.write(f"SELF_E2E_BLOCKED={exc}\n")
        return 2
    except Exception:  # noqa: BLE001
        sys.stdout.write("SELF_E2E_FAILED=harness_aborted\n")
        return 1
    else:
        sys.stdout.write(report)
        required = (
            "EMBEDDING=PASS\n",
            "AUTO_LABEL_EXECUTED=PASS\n",
            "TEMPORAL=PASS\n",
            "CORRELATION=PASS\n",
            "SUMMARY=PASS\n",
            "CONTEXT_VISIBLE=PASS\n",
            "RETRIEVAL_VISIBLE=PASS\n",
            "IDEMPOTENT=PASS\n",
            "DANGLING_SELECTED_JOBS=0\n",
        )
        return 0 if all(line in report for line in required) else 1
    finally:
        _restore_process_local(previous, env_before)
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    if args.live:
        return execute_live()
    if not args.fake:
        sys.stdout.write("SELF_E2E_BLOCKED=mode_required\n")
        return 2
    from app.db.session import SessionLocal

    session = SessionLocal()
    previous = settings.telegram_mtproto_ai_enabled
    env_before = os.environ.get("TELEGRAM_MTPROTO_AI_ENABLED")
    try:
        report = run_acceptance(session, probe=lambda: (False, False))
    except HarnessBlocked as exc:
        sys.stdout.write(f"SELF_E2E_BLOCKED={exc}\n")
        return 2
    except Exception:  # noqa: BLE001
        sys.stdout.write("SELF_E2E_FAILED=harness_aborted\n")
        return 1
    else:
        sys.stdout.write(report)
        ready = "DANGLING_SELECTED_JOBS=0\n" in report and "EMBEDDING=PASS\n" in report
        return 0 if ready else 1
    finally:
        _restore_process_local(previous, env_before)
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
