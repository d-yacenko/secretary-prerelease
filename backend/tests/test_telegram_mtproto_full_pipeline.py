"""Synthetic Telegram MTProto projection, correlation, and false->true pipeline proof."""

from datetime import UTC, datetime, timedelta
from inspect import getsource
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.assistant import assistant_message, assistant_transcribe
from app.core.config import settings
from app.db.models import (
    Edge,
    Job,
    Object,
    TelegramMtprotoAccount,
    TelegramMtprotoChatSelection,
    User,
    UserSettings,
)
from app.domain.labels import EDGE_TYPE_LABELED_WITH
from app.domain.temporal_hint import KIND_TEMPORAL_HINT, RESULT_EXACT_TEMPORAL_SIGNAL
from app.jobs.constants import (
    JOB_TYPE_AUTO_LABEL_OBJECT,
    JOB_TYPE_CORRELATE_OBJECT,
    JOB_TYPE_EMBED_OBJECT,
    JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL,
    JOB_TYPE_SUMMARIZE_CONVERSATION_STACK,
)
from app.jobs.handlers import handle_embed_object
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.summarizer import FakeSummarizer
from app.llm.temporal_match_judge import FakeTemporalMatchJudge
from app.llm.temporal_signal_extractor import FakeTemporalSignalExtractor
from app.services.auto_label_models import AutoLabelAssignment, AutoLabelClassifierResult
from app.services.auto_label_service import AutoLabelService
from app.services.context_service import ContextService
from app.services.conversation_projection import project_inbox_object
from app.services.conversation_stack import group_inbox_conversation_items
from app.services.conversation_stack_summary import (
    ConversationStackSummaryService,
    enqueue_summarize_conversation_stack,
)
from app.services.correlation_models import CorrelationDecision, CorrelationJudgeResult
from app.services.correlation_service import CorrelationService
from app.services.domain_tool_service import DomainToolService
from app.services.errors import NotFoundError
from app.services.label_service import LabelService
from app.services.object_query_service import ObjectQueryService
from app.services.pipeline_enqueue import enqueue_auto_label_object, enqueue_correlate_object
from app.services.recent_source_service import RecentSourceService
from app.services.telegram_mtproto_recurring_sync_service import TelegramMtprotoRecurringSyncService
from app.services.temporal_signals_service import TemporalSignalService


class _SessionProxy:
    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(self._session, name)


@pytest.fixture(autouse=True)
def _share_test_session_for_traces(db_session, monkeypatch):
    def proxy():
        return _SessionProxy(db_session)

    monkeypatch.setattr("app.ai_audit.context.SessionLocal", proxy)
    monkeypatch.setattr("app.services.representation_embedding_worker.SessionLocal", proxy)


class _Judge:
    def __init__(self, target) -> None:
        self._target = target

    def judge(self, **_kwargs):
        return CorrelationJudgeResult(
            decisions=(
                CorrelationDecision(
                    target_object_id=self._target,
                    relation_type="related_to",
                    confidence=0.91,
                    rationale="same matter",
                ),
            )
        )


class _Classifier:
    def __init__(self, label_id) -> None:
        self._label_id = label_id

    def classify(self, **_kwargs):
        return AutoLabelClassifierResult(
            assignments=(
                AutoLabelAssignment(label_id=self._label_id, confidence=0.95, rationale="topic"),
            )
        )


def _user(session, name: str) -> User:
    user = User(id=uuid4(), display_name=name)
    session.add(user)
    session.flush()
    return user


def _account(session, user: User) -> TelegramMtprotoAccount:
    account = TelegramMtprotoAccount(
        user_id=user.id,
        telegram_user_id=uuid4().int % 2_000_000_000,
        session_encrypted="encrypted",
    )
    session.add(account)
    session.flush()
    return account


def _selection(session, account, peer_id: int, *, active: bool) -> None:
    session.add(
        TelegramMtprotoChatSelection(
            account_id=account.id,
            peer_id=peer_id,
            peer_kind="group",
            provider_peer_reference_encrypted="encrypted",
            title=f"peer {peer_id}",
            manual_selected=False,
            scope_active=active,
        )
    )
    session.flush()


def _message(session, user, account, peer_id: int, *, when, topic_id=None, reply=None, direction="inbound", title="hello"):
    metadata = {
        "transport": "mtproto",
        "account_id": str(account.id),
        "peer_id": peer_id,
        "peer_title": f"Peer {peer_id}",
        "sender_peer_id": 900,
        "peer_kind": "group",
        "direction": direction,
        "reply_to_message_id": reply,
        "topic_id": topic_id,
    }
    obj = Object(
        user_id=user.id,
        kind="chat_message",
        provider="telegram",
        external_id=f"mtproto|{uuid4()}",
        origin="source",
        state="observed",
        title=title,
        body="Созвон завтра в 11",
        metadata_=metadata,
        occurred_at=when,
    )
    session.add(obj)
    session.flush()
    return obj


def _jobs(session, user_id, job_type: str) -> int:
    return session.scalar(
        select(func.count()).select_from(Job).where(Job.user_id == user_id, Job.type == job_type)
    )


def test_native_mtproto_projection_keeps_peer_account_and_topic_separate(db_session) -> None:
    user = _user(db_session, "projection")
    other = _user(db_session, "other account")
    account = _account(db_session, user)
    other_account = _account(db_session, other)
    now = datetime.now(UTC)
    first = _message(db_session, user, account, 10, when=now, reply=15)
    second = _message(db_session, user, account, 10, when=now + timedelta(minutes=2))
    other_peer = _message(db_session, user, account, 11, when=now)
    other_user_peer = _message(db_session, other, other_account, 10, when=now)
    topic_a = _message(db_session, user, account, 10, when=now, topic_id=1)
    topic_b = _message(db_session, user, account, 10, when=now + timedelta(minutes=1), topic_id=2)
    legacy = Object(
        user_id=user.id,
        kind="chat_message",
        provider="telegram",
        external_id=f"legacy|{uuid4()}",
        origin="source",
        state="observed",
        title="legacy",
        body="old",
        metadata_={"chat_id": "42", "from_user_id": "7", "chat_display_name": "Legacy chat", "direction": "inbound"},
        occurred_at=now,
    )
    db_session.add(legacy)
    db_session.flush()

    projected = project_inbox_object(first)
    assert projected is not None
    assert projected.grouping_seed == project_inbox_object(second).grouping_seed
    assert projected.account_scope == str(account.id)
    assert projected.sender_id == "900"
    assert projected.direction == "inbound"
    assert projected.reply_ref == "15"
    assert projected.conversation_label == "Peer 10"
    assert projected.grouping_seed != project_inbox_object(other_peer).grouping_seed
    assert projected.grouping_seed != project_inbox_object(other_user_peer).grouping_seed
    assert project_inbox_object(topic_a).grouping_seed != project_inbox_object(topic_b).grouping_seed
    assert "topic:1" in project_inbox_object(topic_a).grouping_seed
    legacy_projection = project_inbox_object(legacy)
    assert legacy_projection is not None
    assert legacy_projection.grouping_seed.endswith(":chat:42")
    assert legacy_projection.sender_id == "7"

    groups = group_inbox_conversation_items([first, second])
    assert len(groups) == 1
    assert groups[0].item_type == "stack"
    assert set(groups[0].object_ids) == {first.id, second.id}


def test_voice_reaches_assistant_message_and_inherits_ai_gate() -> None:
    message_source = getsource(assistant_message)
    transcribe_source = getsource(assistant_transcribe)
    tool_source = getsource(DomainToolService.__init__)
    assert "send_message" in message_source
    assert "ContextService" not in transcribe_source
    assert "ai_only=True" in tool_source


def test_false_to_true_pipeline_uses_existing_catchup(db_session, monkeypatch) -> None:
    user = _user(db_session, "pipeline")
    db_session.add(
        UserSettings(
            user_id=user.id,
            timezone="Europe/Moscow",
            auto_label_enabled=True,
            temporal_signals_enabled=True,
        )
    )
    account = _account(db_session, user)
    _selection(db_session, account, 10, active=True)
    _selection(db_session, account, 99, active=False)
    now = datetime.now(UTC)
    active = _message(db_session, user, account, 10, when=now, title="active")
    partner = _message(db_session, user, account, 10, when=now + timedelta(minutes=1), title="partner")
    inactive = _message(db_session, user, account, 99, when=now, title="inactive")
    label = LabelService(db_session, user.id).create_label("Follow up").label
    task = Object(
        user_id=user.id,
        kind="task",
        origin="user",
        state="observed",
        title="Follow the call",
        body="task",
        occurred_at=now,
    )
    db_session.add(task)
    teams = Object(
        user_id=user.id,
        kind="chat_message",
        provider="teams",
        external_id=f"teams|{uuid4()}",
        origin="source",
        state="observed",
        title="teams",
        body="hello",
        metadata_={"chat_id": "chat", "direction": "inbound"},
        occurred_at=now,
    )
    db_session.add(teams)
    db_session.flush()
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)

    assert RecentSourceService(db_session, user.id).get_inbox_eligible(active.id) is active
    assert group_inbox_conversation_items([active, partner])[0].item_type == "stack"
    enqueue_correlate_object(db_session, active.id, user.id, active.kind)
    enqueue_auto_label_object(db_session, active.id, user.id)
    enqueue_correlate_object(db_session, teams.id, user.id, teams.kind)
    stack = group_inbox_conversation_items([active, partner])[0].stack
    assert enqueue_summarize_conversation_stack(db_session, user.id, stack) is None
    sync = TelegramMtprotoRecurringSyncService.__new__(TelegramMtprotoRecurringSyncService)
    sync._session = db_session
    assert sync._enqueue_embedding_catchup(user.id, account.id) == 0
    assert _jobs(db_session, user.id, JOB_TYPE_EMBED_OBJECT) == 0
    assert _jobs(db_session, user.id, JOB_TYPE_CORRELATE_OBJECT) == 0
    assert _jobs(db_session, user.id, JOB_TYPE_AUTO_LABEL_OBJECT) == 0
    assert _jobs(db_session, user.id, JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL) == 0
    assert _jobs(db_session, user.id, JOB_TYPE_SUMMARIZE_CONVERSATION_STACK) == 0
    assert active not in ObjectQueryService(db_session, user.id, ai_only=True).query(
        kinds=["chat_message"], providers=["telegram"]
    )
    with pytest.raises(NotFoundError):
        ContextService(db_session, user.id).build_context(object_id=active.id)
    assert CorrelationService(db_session, user.id, _Judge(task.id)).run_correlation(active.id) == 0
    assert CorrelationService(db_session, user.id, _Judge(task.id)).run_correlation(teams.id) == 0

    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    db_session.refresh(active)
    from app.domain.telegram_mtproto_ai import telegram_mtproto_ai_eligible

    assert telegram_mtproto_ai_eligible(db_session, active)
    assert not telegram_mtproto_ai_eligible(db_session, inactive)
    assert sync._enqueue_embedding_catchup(user.id, account.id) == 2
    assert sync._enqueue_embedding_catchup(user.id, account.id) == 0
    assert _jobs(db_session, user.id, JOB_TYPE_EMBED_OBJECT) == 2
    embed_job = db_session.scalar(
        select(Job).where(
            Job.user_id == user.id,
            Job.type == JOB_TYPE_EMBED_OBJECT,
            Job.payload["object_id"].as_string() == str(active.id),
        )
    )
    handle_embed_object(db_session, FakeEmbeddingService(), dict(embed_job.payload), user.id)
    assert sync._enqueue_embedding_catchup(user.id, account.id) == 0
    assert _jobs(db_session, user.id, JOB_TYPE_CORRELATE_OBJECT) == 1
    assert _jobs(db_session, user.id, JOB_TYPE_AUTO_LABEL_OBJECT) == 1
    assert _jobs(db_session, user.id, JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL) == 1

    label_job = db_session.scalar(
        select(Job).where(Job.user_id == user.id, Job.type == JOB_TYPE_AUTO_LABEL_OBJECT)
    )
    AutoLabelService(db_session, user.id, classifier=_Classifier(label.id)).run_job(dict(label_job.payload))
    assert db_session.scalar(
        select(Edge.id).where(
            Edge.user_id == user.id,
            Edge.source_id == active.id,
            Edge.target_id == label.id,
            Edge.type == EDGE_TYPE_LABELED_WITH,
        )
    ) is not None

    temporal_job = db_session.scalar(
        select(Job).where(Job.user_id == user.id, Job.type == JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL)
    )
    outcome = TemporalSignalService(
        db_session,
        user.id,
        extractor=FakeTemporalSignalExtractor(
            payload={
                "result_class": RESULT_EXACT_TEMPORAL_SIGNAL,
                "concise_title": "Созвон",
                "start_date_kind": "relative_day",
                "start_relative_day_offset": 1,
                "start_local_time": "11:00",
                "end_precision": "exact",
                "end_kind": "duration_minutes",
                "end_duration_minutes": 30,
                "participation": "expected",
                "extraction_confidence": 0.92,
                "semantic_subject": "созвон",
            }
        ),
        match_judge=FakeTemporalMatchJudge(),
    ).run_extract_job(dict(temporal_job.payload))
    assert outcome.hint_id is not None, outcome
    hint = db_session.get(Object, outcome.hint_id)
    assert hint is not None
    assert hint.metadata_["participation"] == "possible"
    assert db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.user_id == user.id, Object.kind == KIND_TEMPORAL_HINT
        )
    ) == 1

    assert CorrelationService(db_session, user.id, _Judge(task.id)).run_correlation(active.id) == 1
    assert db_session.scalar(
        select(Edge.id).where(
            Edge.user_id == user.id,
            Edge.source_id == active.id,
            Edge.target_id == task.id,
            Edge.type == "related_to",
            Edge.state == "proposed",
        )
    ) is not None

    summary_job = enqueue_summarize_conversation_stack(db_session, user.id, stack)
    assert summary_job is not None
    text = ConversationStackSummaryService(
        db_session, user.id, summarizer=FakeSummarizer(max_chars=200)
    ).generate_for_payload(dict(summary_job.payload))
    assert text
    context = ContextService(db_session, user.id).build_context(object_id=active.id)
    assert active.id in {item.object_id for item in context.items}
    assert active in ObjectQueryService(db_session, user.id, ai_only=True).query(
        kinds=["chat_message"], providers=["telegram"]
    )
