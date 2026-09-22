#!/usr/bin/env python3
"""One-shot Telegram synthetic ML rehearsal.

Process-local AI is enabled only inside this process. Long-running API and
worker flags are read, never written. Telegram transport and MTProto session
decrypt are sealed for the duration of the run. Jobs are parked running before
they become visible as pending, then executed synchronously here.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    Edge,
    Job,
    Object,
    Representation,
    TelegramMtprotoAccount,
    TelegramMtprotoChatSelection,
    User,
    UserSettings,
)
from app.domain.labels import EDGE_TYPE_LABELED_WITH
from app.domain.telegram_mtproto_ai import telegram_mtproto_ai_eligible
from app.domain.temporal_hint import KIND_TEMPORAL_HINT, RESULT_EXACT_TEMPORAL_SIGNAL
from app.jobs.constants import (
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_SYNC_TELEGRAM_MTPROTO,
)
from app.jobs.handlers import get_handler
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.summarizer import FakeSummarizer
from app.llm.temporal_match_judge import FakeTemporalMatchJudge
from app.llm.temporal_signal_extractor import FakeTemporalSignalExtractor
from app.services.auto_label_models import AutoLabelAssignment, AutoLabelClassifierResult
from app.services.context_service import ContextService
from app.services.conversation_stack import group_inbox_conversation_items
from app.services.conversation_stack_summary import enqueue_summarize_conversation_stack
from app.services.correlation_models import CorrelationDecision, CorrelationJudgeResult
from app.services.job_queue_service import JobQueueService
from app.services.label_service import LabelService
from app.services.object_query_service import ObjectQueryService
from app.services.pipeline_enqueue import enqueue_embed_object
from app.services.recent_source_service import RecentSourceService
from app.services.representation_service import KIND_CONVERSATION_STACK_SUMMARY

RUN_ID_RE = re.compile(r"^[a-z0-9]{8,32}$")
SESSION_PLACEHOLDER = "REHEARSAL_NOT_A_SESSION"
REFERENCE_PLACEHOLDER = "REHEARSAL_NOT_A_REFERENCE"
MAX_DRAIN_STEPS = 24
TRUE_FLAGS = {"1", "true", "yes", "on"}
LongRunningProbe = Callable[[], tuple[bool, bool]]


class RehearsalRefused(RuntimeError):
    pass


class RehearsalTransportBlocked(RuntimeError):
    pass


@dataclass
class _Barrier:
    calls: int = 0
    restores: list[tuple[object, str, object]] | None = None

    def block(self, *_args, **_kwargs):
        self.calls += 1
        raise RehearsalTransportBlocked("telegram_transport")


@dataclass(frozen=True)
class RehearsalMarkers:
    inbox_eligible: bool
    stack_grouped: bool
    embedding: bool
    auto_label: bool
    temporal: bool
    temporal_participation: str
    correlation: bool
    summary: bool
    context_visible: bool
    idempotent: bool
    telegram_transport_calls: int
    long_running_api_ai: bool
    long_running_worker_ai: bool
    process_local_ai: bool
    env_mutation: bool
    dangling_jobs: int
    provider_mode: str


def rehearsal_token(run_id: str) -> str:
    validate_run_id(run_id)
    return f"TG_REHEARSAL_{run_id}"


def validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or RUN_ID_RE.fullmatch(run_id) is None:
        raise RehearsalRefused("run_id")
    return run_id


def validate_synthetic_content(run_id: str, texts: tuple[str, ...]) -> None:
    token = rehearsal_token(run_id)
    if not texts or any(token not in text for text in texts):
        raise RehearsalRefused("non_synthetic_content")


def default_texts(run_id: str) -> tuple[str, str, str]:
    token = rehearsal_token(run_id)
    return (
        f"{token} Synthetic project budget meeting tomorrow at 11:00.",
        f"{token} Synthetic estimate preparation before the meeting.",
        f"{token} Prepare the synthetic estimate.",
    )


def long_running_ai_from_env(lines: list[str]) -> bool:
    found = ""
    for line in lines:
        if line.startswith("TELEGRAM_MTPROTO_AI_ENABLED="):
            found = line.split("=", 1)[1].strip().lower()
    return found in TRUE_FLAGS


def format_report(markers: RehearsalMarkers) -> str:
    if markers.temporal_participation not in {"expected", "possible", "none"}:
        raise RehearsalRefused("unsanitized_output")
    if markers.provider_mode not in {"fake", "live"}:
        raise RehearsalRefused("unsanitized_output")
    if markers.telegram_transport_calls != 0:
        raise RehearsalRefused("transport_calls")
    flags = {
        "INBOX_ELIGIBLE": markers.inbox_eligible,
        "STACK_GROUPED": markers.stack_grouped,
        "EMBEDDING": markers.embedding,
        "AUTO_LABEL": markers.auto_label,
        "TEMPORAL": markers.temporal,
        "CORRELATION": markers.correlation,
        "SUMMARY": markers.summary,
        "CONTEXT_VISIBLE": markers.context_visible,
        "IDEMPOTENT": markers.idempotent,
        "ENV_UNCHANGED": not markers.env_mutation,
    }
    lines = [f"{key}={'PASS' if value else 'FAIL'}" for key, value in flags.items()]
    lines.insert(5, f"TEMPORAL_PARTICIPATION={markers.temporal_participation}")
    lines.append(f"PROCESS_LOCAL_AI={'true' if markers.process_local_ai else 'false'}")
    lines.append(f"LONG_RUNNING_API_AI={'true' if markers.long_running_api_ai else 'false'}")
    lines.append(f"LONG_RUNNING_WORKER_AI={'true' if markers.long_running_worker_ai else 'false'}")
    lines.append("TELEGRAM_TRANSPORT_CALLS=0")
    lines.append(f"DANGLING_JOBS={markers.dangling_jobs}")
    lines.append(f"PROVIDERS={markers.provider_mode}")
    lines.append(f"LIVE_REHEARSAL_EXECUTED={0 if markers.provider_mode == 'fake' else 1}")
    text = "\n".join(lines) + "\n"
    if SESSION_PLACEHOLDER in text or "TG_REHEARSAL_" in text:
        raise RehearsalRefused("unsanitized_output")
    return text


def _synthetic_telegram_user_id(run_id: str) -> int:
    digest = int(hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12], 16)
    return 7_000_000_000_000_000 + (digest % 1_000_000_000_000)


def _run_exists(session: Session, run_id: str) -> bool:
    token = f"TG_REHEARSAL_{run_id}"
    user = session.scalar(select(User.id).where(User.display_name == token))
    marked = session.scalar(
        select(Object.id).where(Object.metadata_["rehearsal_run_id"].as_string() == run_id)
    )
    return user is not None or marked is not None


def _park_pending(session: Session, user_id: UUID) -> None:
    now = datetime.now(UTC)
    pending = list(
        session.scalars(select(Job).where(Job.user_id == user_id, Job.status == JOB_STATUS_PENDING))
    )
    for job in pending:
        if job.type == JOB_TYPE_SYNC_TELEGRAM_MTPROTO:
            raise RehearsalRefused("telegram_sync_job")
        job.status = JOB_STATUS_RUNNING
        job.locked_at = now
    session.flush()


def _dangling(session: Session, user_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.user_id == user_id,
                Job.status.in_((JOB_STATUS_PENDING, JOB_STATUS_RUNNING)),
            )
        )
        or 0
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
            raise RehearsalTransportBlocked(fullname)


@contextmanager
def _fake_providers(task_id: UUID, label_id: UUID) -> Iterator[FakeEmbeddingService]:
    from unittest.mock import patch

    extractor = FakeTemporalSignalExtractor(
        payload={
            "result_class": RESULT_EXACT_TEMPORAL_SIGNAL,
            "concise_title": "Synthetic meeting",
            "start_date_kind": "relative_day",
            "start_relative_day_offset": 1,
            "start_local_time": "11:00",
            "end_precision": "exact",
            "end_kind": "duration_minutes",
            "end_duration_minutes": 30,
            "participation": "expected",
            "extraction_confidence": 0.92,
            "semantic_subject": "synthetic meeting",
        }
    )

    class _Classifier:
        def classify(self, **_kwargs):
            return AutoLabelClassifierResult(
                assignments=(
                    AutoLabelAssignment(label_id=label_id, confidence=0.95, rationale="synthetic"),
                )
            )

    class _Judge:
        def judge(self, trigger_title, trigger_kind, trigger_summary, candidates):
            return CorrelationJudgeResult(
                decisions=(
                    CorrelationDecision(
                        target_object_id=task_id,
                        relation_type="related_to",
                        confidence=0.91,
                        rationale="synthetic",
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
            lambda _settings: _Judge(),
        ),
        patch(
            "app.llm.openai_summarizer.create_openai_conversation_stack_summarizer_from_effective",
            lambda _settings: FakeSummarizer(max_chars=80),
        ),
    ):
        yield FakeEmbeddingService()


def _drain(session: Session, user_id: UUID, embedding) -> None:
    queue = JobQueueService(session)
    for _ in range(MAX_DRAIN_STEPS):
        _park_pending(session, user_id)
        job = session.scalar(
            select(Job)
            .where(Job.user_id == user_id, Job.status == JOB_STATUS_RUNNING)
            .order_by(Job.created_at, Job.id)
            .limit(1)
        )
        if job is None:
            return
        handler = get_handler(job.type)
        if handler is None:
            raise RehearsalRefused("unknown_job")
        handler(session, embedding, dict(job.payload), user_id)
        queue.mark_done(job.id)
        session.flush()
    raise RehearsalRefused("drain_exceeded")


def _create_fixture(session: Session, run_id: str, texts: tuple[str, str, str]):
    token = f"TG_REHEARSAL_{run_id}"
    user = User(id=uuid4(), display_name=token)
    session.add(user)
    session.flush()
    session.add(
        UserSettings(
            user_id=user.id,
            timezone="Europe/Moscow",
            auto_label_enabled=True,
            temporal_signals_enabled=True,
        )
    )
    account = TelegramMtprotoAccount(
        user_id=user.id,
        telegram_user_id=_synthetic_telegram_user_id(run_id),
        session_encrypted=SESSION_PLACEHOLDER,
        display_name=token,
    )
    session.add(account)
    session.flush()
    session.add(
        TelegramMtprotoChatSelection(
            account_id=account.id,
            peer_id=910_000_000_000_001,
            peer_kind="private",
            provider_peer_reference_encrypted=REFERENCE_PLACEHOLDER,
            title=token,
            manual_selected=False,
            scope_active=True,
        )
    )
    now = datetime.now(UTC)
    messages = []
    for offset, body in enumerate(texts[:2]):
        obj = Object(
            user_id=user.id,
            kind="chat_message",
            provider="telegram",
            external_id=f"rehearsal|{run_id}|{offset}",
            origin="source",
            state="observed",
            title=body.split(".", 1)[0],
            body=body,
            metadata_={
                "transport": "mtproto",
                "account_id": str(account.id),
                "peer_id": 910_000_000_000_001,
                "peer_kind": "private",
                "peer_title": token,
                "sender_peer_id": account.telegram_user_id + 1,
                "direction": "inbound",
                "rehearsal_run_id": run_id,
            },
            occurred_at=now + timedelta(minutes=offset),
        )
        session.add(obj)
        messages.append(obj)
    task = Object(
        user_id=user.id,
        kind="task",
        origin="user",
        state="observed",
        title=texts[2].split(".", 1)[0],
        body=texts[2],
        metadata_={"rehearsal_run_id": run_id},
        occurred_at=now,
    )
    session.add(task)
    session.flush()
    label = LabelService(session, user.id).create_label(token).label
    session.flush()
    return user, messages, task, label


def run_rehearsal(
    session: Session,
    run_id: str,
    *,
    probe: LongRunningProbe,
    content: tuple[str, str, str] | None = None,
    commit: Callable[[], None] | None = None,
    providers: str = "fake",
) -> str:
    validate_run_id(run_id)
    texts = content or default_texts(run_id)
    validate_synthetic_content(run_id, texts)
    api_ai, worker_ai = probe()
    if api_ai or worker_ai:
        raise RehearsalRefused("long_running_ai")
    if providers not in {"fake", "live"}:
        raise RehearsalRefused("providers")
    if _run_exists(session, run_id):
        raise RehearsalRefused("duplicate_run_id")
    env_before = os.environ.get("TELEGRAM_MTPROTO_AI_ENABLED")
    previous_ai = settings.telegram_mtproto_ai_enabled
    commit = commit or session.commit
    with transport_barrier() as barrier:
        settings.telegram_mtproto_ai_enabled = True
        try:
            user, messages, task, label = _create_fixture(session, run_id, texts)
            if any(not telegram_mtproto_ai_eligible(session, item) for item in messages):
                raise RehearsalRefused("ineligible_synthetic_scope")
            grouped = group_inbox_conversation_items(messages)
            stack_ok = len(grouped) == 1 and grouped[0].item_type == "stack"
            if stack_ok:
                enqueue_summarize_conversation_stack(session, user.id, grouped[0].stack)
            for item in messages:
                enqueue_embed_object(session, item.id, user.id)
            _park_pending(session, user.id)
            commit()
            if providers == "fake":
                bridge = _session_bridges(session)
                paid = _fake_providers(task.id, label.id)
            else:
                from contextlib import nullcontext

                bridge = nullcontext()
                paid = nullcontext(None)
            with bridge, paid as embedding:
                _drain(session, user.id, embedding)
                hint_count = _hint_count(session, user.id)
                edge_count = _edge_count(session, user.id, messages[0].id, task.id)
                summary_count = _summary_count(session, messages[-1].id)
                enqueue_embed_object(session, messages[0].id, user.id)
                enqueue_embed_object(session, messages[1].id, user.id)
                if stack_ok:
                    enqueue_summarize_conversation_stack(session, user.id, grouped[0].stack)
                _drain(session, user.id, embedding)
            idempotent = (
                _hint_count(session, user.id) == hint_count
                and _edge_count(session, user.id, messages[0].id, task.id) == edge_count
                and _summary_count(session, messages[-1].id) == summary_count
            )
            inbox = RecentSourceService(session, user.id).get_inbox_eligible(messages[0].id)
            context = ContextService(session, user.id).build_context(object_id=messages[0].id)
            visible = messages[0] in ObjectQueryService(session, user.id, ai_only=True).query(
                kinds=["chat_message"], providers=["telegram"]
            )
            participation = _participation(session, user.id)
            commit()
            markers = RehearsalMarkers(
                inbox_eligible=inbox is not None,
                stack_grouped=stack_ok,
                embedding=_embedding_count(session, user.id) >= 2,
                auto_label=_label_edge_count(session, user.id, label.id) >= 1,
                temporal=participation == "expected",
                temporal_participation=participation,
                correlation=edge_count >= 1,
                summary=summary_count >= 1,
                context_visible=visible
                and messages[0].id in {item.object_id for item in context.items},
                idempotent=idempotent,
                telegram_transport_calls=barrier.calls,
                long_running_api_ai=api_ai,
                long_running_worker_ai=worker_ai,
                process_local_ai=settings.telegram_mtproto_ai_enabled is True,
                env_mutation=os.environ.get("TELEGRAM_MTPROTO_AI_ENABLED") != env_before,
                dangling_jobs=_dangling(session, user.id),
                provider_mode=providers,
            )
            return format_report(markers)
        finally:
            settings.telegram_mtproto_ai_enabled = previous_ai


def _hint_count(session: Session, user_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Object)
            .where(Object.user_id == user_id, Object.kind == KIND_TEMPORAL_HINT)
        )
        or 0
    )


def _participation(session: Session, user_id: UUID) -> str:
    hints = session.scalars(
        select(Object).where(Object.user_id == user_id, Object.kind == KIND_TEMPORAL_HINT)
    )
    values = {(hint.metadata_ or {}).get("participation") for hint in hints}
    if "expected" in values:
        return "expected"
    if "possible" in values:
        return "possible"
    return "none"


def _edge_count(session: Session, user_id: UUID, source_id: UUID, target_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Edge)
            .where(
                Edge.user_id == user_id,
                Edge.source_id == source_id,
                Edge.target_id == target_id,
                Edge.type == "related_to",
                Edge.state == "proposed",
            )
        )
        or 0
    )


def _label_edge_count(session: Session, user_id: UUID, label_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Edge)
            .where(
                Edge.user_id == user_id,
                Edge.target_id == label_id,
                Edge.type == EDGE_TYPE_LABELED_WITH,
            )
        )
        or 0
    )


def _summary_count(session: Session, anchor_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Representation)
            .where(
                Representation.object_id == anchor_id,
                Representation.kind == KIND_CONVERSATION_STACK_SUMMARY,
            )
        )
        or 0
    )


def _embedding_count(session: Session, user_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Object)
            .where(
                Object.user_id == user_id,
                Object.kind == "chat_message",
                Object.embedding.is_not(None),
            )
        )
        or 0
    )


def compose_long_running_probe() -> tuple[bool, bool]:
    """Read only the AI flag from the long-running api and worker containers."""
    return _compose_ai_flag("api"), _compose_ai_flag("worker")


def _compose_ai_flag(service: str) -> bool:
    import subprocess

    proc = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "/opt/secretary/.env",
            "-f",
            "infra/compose.yaml",
            "-f",
            "infra/compose.deploy.yaml",
            "exec",
            "-T",
            service,
            "printenv",
            "TELEGRAM_MTPROTO_AI_ENABLED",
        ],
        cwd="/opt/secretary",
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode not in {0, 1}:
        raise RehearsalRefused("long_running_probe")
    return long_running_ai_from_env([f"TELEGRAM_MTPROTO_AI_ENABLED={proc.stdout.strip()}"])


REHEARSAL_ABORTED = "rehearsal_aborted"


def live_long_running_probe() -> tuple[bool, bool]:
    api = os.environ.get("REHEARSAL_LONG_RUNNING_API_AI")
    worker = os.environ.get("REHEARSAL_LONG_RUNNING_WORKER_AI")
    if api is None or worker is None:
        return compose_long_running_probe()
    return (
        long_running_ai_from_env([f"TELEGRAM_MTPROTO_AI_ENABLED={api}"]),
        long_running_ai_from_env([f"TELEGRAM_MTPROTO_AI_ENABLED={worker}"]),
    )


def abort_rehearsal_jobs(session: Session, run_id: str) -> None:
    """Roll back the failed transaction, then fail leftover synthetic jobs."""
    session.rollback()
    token = f"TG_REHEARSAL_{run_id}"
    user_id = session.scalar(select(User.id).where(User.display_name == token))
    if user_id is None:
        return
    jobs = list(
        session.scalars(
            select(Job).where(
                Job.user_id == user_id,
                Job.status.in_((JOB_STATUS_PENDING, JOB_STATUS_RUNNING)),
            )
        )
    )
    queue = JobQueueService(session)
    for job in jobs:
        queue.mark_failed(job.id, REHEARSAL_ABORTED)
    session.commit()


def _cleanup_failed_rehearsal(session: Session, run_id: str) -> None:
    try:
        abort_rehearsal_jobs(session, run_id)
    except Exception:  # noqa: BLE001
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            return


def execute_live(run_id: str, *, session_factory=None) -> int:
    from app.db.session import SessionLocal

    previous_ai = settings.telegram_mtproto_ai_enabled
    env_before = os.environ.get("TELEGRAM_MTPROTO_AI_ENABLED")
    session = (session_factory or SessionLocal)()
    try:
        report = run_rehearsal(
            session,
            run_id,
            probe=live_long_running_probe,
            providers="live",
        )
    except RehearsalRefused:
        _cleanup_failed_rehearsal(session, run_id)
        sys.stdout.write("REHEARSAL_REFUSED=rehearsal_refused\n")
        return 2
    except Exception:  # noqa: BLE001
        _cleanup_failed_rehearsal(session, run_id)
        sys.stdout.write("REHEARSAL_FAILED=rehearsal_aborted\n")
        return 1
    else:
        sys.stdout.write(report)
        ready = "DANGLING_JOBS=0\n" in report and "INBOX_ELIGIBLE=PASS\n" in report
        return 0 if ready else 1
    finally:
        settings.telegram_mtproto_ai_enabled = previous_ai
        if os.environ.get("TELEGRAM_MTPROTO_AI_ENABLED") != env_before:
            if env_before is None:
                os.environ.pop("TELEGRAM_MTPROTO_AI_ENABLED", None)
            else:
                os.environ["TELEGRAM_MTPROTO_AI_ENABLED"] = env_before
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    if args.live:
        if os.environ.get("REHEARSAL_LIVE_CONFIRM") != "reviewed":
            sys.stdout.write("LIVE_REHEARSAL_BLOCKED=architect_review_required\n")
            return 2
        return execute_live(args.run_id)
    if not args.fake:
        sys.stdout.write("REHEARSAL_BLOCKED=mode_required\n")
        return 2
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        report = run_rehearsal(
            session,
            args.run_id,
            probe=lambda: (False, False),
        )
    except RehearsalRefused as exc:
        sys.stdout.write(f"REHEARSAL_REFUSED={exc}\n")
        session.rollback()
        return 2
    else:
        sys.stdout.write(report)
        return 0 if "DANGLING_JOBS=0\n" in report and "INBOX_ELIGIBLE=PASS\n" in report else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
