"""Self-authored Telegram remains AI-eligible while the global flag is false."""

from datetime import UTC, datetime, timedelta
from inspect import getsource
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.connectors.telegram.constants import TELEGRAM_KIND, TELEGRAM_PROVIDER
from app.connectors.telegram.materialize import TelegramObjectMaterializer
from app.core.config import settings
from app.db.models import (
    Job,
    Object,
    TelegramMtprotoAccount,
    TelegramMtprotoChatSelection,
    User,
    UserSettings,
)
from app.domain.telegram_mtproto_ai import (
    telegram_mtproto_ai_eligible,
    telegram_mtproto_ai_predicate,
    telegram_mtproto_ai_sql_fragment,
)
from app.jobs.constants import (
    JOB_TYPE_AUTO_LABEL_OBJECT,
    JOB_TYPE_CORRELATE_OBJECT,
    JOB_TYPE_EMBED_OBJECT,
    JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL,
)
from app.jobs.handlers import handle_embed_object, handle_summarize_conversation_stack
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.summarizer import FakeSummarizer
from app.services.context_service import ContextService
from app.services.conversation_stack import group_inbox_conversation_items
from app.services.conversation_stack_summary import (
    ConversationStackSummaryService,
    enqueue_summarize_conversation_stack,
)
from app.services.correlation_candidate_service import CorrelationCandidateService
from app.services.errors import NotFoundError
from app.services.label_service import LabelService
from app.services.object_query_service import ObjectQueryService
from app.services.pipeline_enqueue import (
    enqueue_auto_label_object,
    enqueue_correlate_object,
    enqueue_embed_object,
)
from app.services.search_service import SearchService
from app.services.telegram_mtproto_recurring_sync_service import TelegramMtprotoRecurringSyncService
from app.services.temporal_signals_service import enqueue_extract_temporal_signal

_OWNER_ID = 424242
_PEER_ID = 10


class _SessionProxy:
    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(self._session, name)


def _user(session) -> User:
    user = User(id=uuid4(), display_name="self-authored policy")
    session.add(user)
    session.flush()
    return user


def _account(session, user: User, telegram_user_id: int = _OWNER_ID) -> TelegramMtprotoAccount:
    account = TelegramMtprotoAccount(
        user_id=user.id,
        telegram_user_id=telegram_user_id,
        session_encrypted="encrypted",
    )
    session.add(account)
    session.flush()
    return account


def _selection(session, account: TelegramMtprotoAccount, *, active: bool = True) -> None:
    session.add(
        TelegramMtprotoChatSelection(
            account_id=account.id,
            peer_id=_PEER_ID,
            peer_kind="group",
            provider_peer_reference_encrypted="encrypted",
            title="owned chat",
            manual_selected=False,
            scope_active=active,
        )
    )
    session.flush()


def _object(
    session,
    user: User,
    account: TelegramMtprotoAccount,
    *,
    direction: str | None = "outbound",
    sender: str | None = str(_OWNER_ID),
    account_id: str | None = None,
    transport: str = "mtproto",
    title: str = "self authored",
    body: str = "selfauthored lexical phrase",
    when: datetime | None = None,
) -> Object:
    metadata: dict = {
        "transport": transport,
        "account_id": account_id if account_id is not None else str(account.id),
        "peer_id": str(_PEER_ID),
    }
    if direction is not None:
        metadata["direction"] = direction
    if sender is not None:
        metadata["sender_peer_id"] = sender
    obj = Object(
        user_id=user.id,
        kind=TELEGRAM_KIND,
        provider=TELEGRAM_PROVIDER,
        external_id=f"mtproto|{uuid4()}",
        origin="source",
        state="observed",
        title=title,
        body=body,
        metadata_=metadata,
        occurred_at=when or datetime.now(UTC),
    )
    session.add(obj)
    session.flush()
    return obj


def _surfaces(session, obj: Object) -> bool:
    python_ok = telegram_mtproto_ai_eligible(session, obj)
    orm_ok = (
        session.scalar(
            select(Object.id).where(Object.id == obj.id, telegram_mtproto_ai_predicate())
        )
        is not None
    )
    raw_ok = (
        session.scalar(
            text(
                "SELECT o.id FROM objects o WHERE o.id = :object_id "
                + telegram_mtproto_ai_sql_fragment("o")
            ),
            {"object_id": obj.id},
        )
        is not None
    )
    assert python_ok is orm_ok is raw_ok
    return python_ok


def _normalized(account: TelegramMtprotoAccount, *, direction: str, sender: str, body: str) -> dict:
    return {
        "provider": TELEGRAM_PROVIDER,
        "kind": TELEGRAM_KIND,
        "external_id": f"mtproto|{uuid4()}",
        "origin": "source",
        "state": "observed",
        "title": "materialized",
        "body": body,
        "occurred_at": datetime.now(UTC),
        "metadata": {
            "transport": "mtproto",
            "account_id": str(account.id),
            "peer_id": str(_PEER_ID),
            "direction": direction,
            "sender_peer_id": sender,
        },
    }


def test_global_false_allows_only_proven_self_authored_messages(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    user = _user(db_session)
    account = _account(db_session, user)
    _selection(db_session, account, active=True)
    other = _user(db_session)
    other_account = _account(db_session, other, telegram_user_id=_OWNER_ID + 7)
    owned = _object(db_session, user, account)
    inbound = _object(db_session, user, account, direction="inbound", title="inbound")
    foreign = _object(db_session, user, account, sender="999", title="foreign")
    missing_direction = _object(db_session, user, account, direction=None, title="no direction")
    unknown_direction = _object(db_session, user, account, direction="sideways", title="sideways")
    missing_sender = _object(db_session, user, account, sender=None, title="no sender")
    empty_sender = _object(db_session, user, account, sender="", title="empty sender")
    malformed = _object(db_session, user, account, account_id="not-a-uuid", title="malformed")
    wrong_account = _object(
        db_session, user, account, account_id=str(other_account.id), title="wrong account"
    )
    inactive_user = _user(db_session)
    inactive_account = _account(db_session, inactive_user, telegram_user_id=_OWNER_ID + 9)
    _selection(db_session, inactive_account, active=False)
    inactive = _object(db_session, inactive_user, inactive_account, title="inactive")
    legacy = Object(
        user_id=user.id,
        kind=TELEGRAM_KIND,
        provider=TELEGRAM_PROVIDER,
        external_id=f"bot|{uuid4()}",
        origin="source",
        state="observed",
        title="legacy bot",
        body="bot body",
        metadata_={"transport": "bot"},
        occurred_at=datetime.now(UTC),
    )
    unknown = Object(
        user_id=user.id,
        kind=TELEGRAM_KIND,
        provider=TELEGRAM_PROVIDER,
        external_id=f"unknown|{uuid4()}",
        origin="source",
        state="observed",
        title="unknown transport",
        body="unknown body",
        metadata_={"transport": "webhook"},
        occurred_at=datetime.now(UTC),
    )
    other_kind = Object(
        user_id=user.id,
        kind="note",
        provider=TELEGRAM_PROVIDER,
        external_id=f"telegram-note|{uuid4()}",
        origin="source",
        state="observed",
        title="telegram note",
        body="telegram note body",
        metadata_={"transport": "mtproto"},
        occurred_at=datetime.now(UTC),
    )
    note = Object(
        user_id=user.id,
        kind="note",
        origin="user",
        state="observed",
        title="ordinary note",
        body="note body",
        occurred_at=datetime.now(UTC),
    )
    db_session.add_all([legacy, unknown, other_kind, note])
    db_session.flush()

    assert _surfaces(db_session, owned) is True
    assert _surfaces(db_session, inbound) is False
    assert _surfaces(db_session, foreign) is False
    assert _surfaces(db_session, missing_direction) is False
    assert _surfaces(db_session, unknown_direction) is False
    assert _surfaces(db_session, missing_sender) is False
    assert _surfaces(db_session, empty_sender) is False
    assert _surfaces(db_session, malformed) is False
    assert _surfaces(db_session, wrong_account) is False
    assert _surfaces(db_session, inactive) is False
    assert _surfaces(db_session, legacy) is False
    assert _surfaces(db_session, unknown) is False
    assert _surfaces(db_session, other_kind) is False
    assert _surfaces(db_session, note) is True


def test_global_true_keeps_active_scope_eligibility_for_both_directions(
    db_session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    user = _user(db_session)
    account = _account(db_session, user)
    _selection(db_session, account, active=True)
    outbound = _object(db_session, user, account, direction="outbound")
    inbound = _object(db_session, user, account, direction="inbound", sender="900")
    inactive_user = _user(db_session)
    inactive_account = _account(db_session, inactive_user, telegram_user_id=_OWNER_ID + 11)
    _selection(db_session, inactive_account, active=False)
    inactive = _object(db_session, inactive_user, inactive_account, direction="inbound", sender="1")

    assert _surfaces(db_session, outbound) is True
    assert _surfaces(db_session, inbound) is True
    assert _surfaces(db_session, inactive) is False


def test_materializer_enqueues_only_self_authored_embedding(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    user = _user(db_session)
    account = _account(db_session, user)
    _selection(db_session, account, active=True)
    materializer = TelegramObjectMaterializer(db_session)
    created = materializer.upsert_mtproto_message(
        user_id=user.id,
        normalized=_normalized(account, direction="outbound", sender=str(_OWNER_ID), body="mine"),
    )
    blocked = materializer.upsert_mtproto_message(
        user_id=user.id,
        normalized=_normalized(account, direction="inbound", sender="900", body="theirs"),
    )
    foreign = materializer.upsert_mtproto_message(
        user_id=user.id,
        normalized=_normalized(account, direction="outbound", sender="900", body="other"),
    )

    assert created.change == "created"
    assert created.jobs_enqueued == 1
    assert blocked.jobs_enqueued == 0
    assert foreign.jobs_enqueued == 0
    jobs = list(db_session.scalars(select(Job).where(Job.user_id == user.id)))
    assert [job.type for job in jobs] == [JOB_TYPE_EMBED_OBJECT]
    assert jobs[0].payload["object_id"] == str(created.obj.id)


def test_embedding_handler_enqueues_downstream_for_self_authored(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    monkeypatch.setattr("app.ai_audit.context.SessionLocal", lambda: _SessionProxy(db_session))
    monkeypatch.setattr(
        "app.services.representation_embedding_worker.SessionLocal",
        lambda: _SessionProxy(db_session),
    )
    user = _user(db_session)
    db_session.add(
        UserSettings(
            user_id=user.id,
            timezone="Europe/Moscow",
            auto_label_enabled=True,
            temporal_signals_enabled=True,
        )
    )
    account = _account(db_session, user)
    _selection(db_session, account, active=True)
    LabelService(db_session, user.id).create_label("Topic")
    obj = _object(db_session, user, account)
    enqueue_embed_object(db_session, obj.id, user.id)
    job = db_session.scalar(
        select(Job).where(Job.user_id == user.id, Job.type == JOB_TYPE_EMBED_OBJECT)
    )
    handle_embed_object(db_session, FakeEmbeddingService(), dict(job.payload), user.id)
    kinds = set(db_session.scalars(select(Job.type).where(Job.user_id == user.id)).all())
    assert JOB_TYPE_CORRELATE_OBJECT in kinds
    assert JOB_TYPE_AUTO_LABEL_OBJECT in kinds
    assert JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL in kinds


def test_downstream_helpers_reject_inbound_and_foreign(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    user = _user(db_session)
    db_session.add(
        UserSettings(
            user_id=user.id,
            timezone="Europe/Moscow",
            auto_label_enabled=True,
            temporal_signals_enabled=True,
        )
    )
    account = _account(db_session, user)
    _selection(db_session, account, active=True)
    LabelService(db_session, user.id).create_label("Topic")
    inbound = _object(db_session, user, account, direction="inbound", sender="900")
    foreign = _object(db_session, user, account, sender="900")
    enqueue_embed_object(db_session, inbound.id, user.id)
    enqueue_correlate_object(db_session, inbound.id, user.id, inbound.kind)
    enqueue_auto_label_object(db_session, inbound.id, user.id)
    enqueue_extract_temporal_signal(db_session, inbound.id, user.id)
    enqueue_embed_object(db_session, foreign.id, user.id)
    enqueue_correlate_object(db_session, foreign.id, user.id, foreign.kind)
    enqueue_auto_label_object(db_session, foreign.id, user.id)
    enqueue_extract_temporal_signal(db_session, foreign.id, user.id)
    assert db_session.scalar(select(Job.id).where(Job.user_id == user.id)) is None


def test_ai_surfaces_expose_self_authored_and_hide_inbound(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    user = _user(db_session)
    account = _account(db_session, user)
    _selection(db_session, account, active=True)
    now = datetime.now(UTC)
    owned = _object(
        db_session,
        user,
        account,
        title="selfauthored lexical phrase",
        body="selfauthored lexical phrase",
        when=now,
    )
    inbound = _object(
        db_session,
        user,
        account,
        direction="inbound",
        sender="900",
        title="inbound foreign lexical phrase",
        body="inbound foreign lexical phrase",
        when=now,
    )
    legacy = Object(
        user_id=user.id,
        kind=TELEGRAM_KIND,
        provider=TELEGRAM_PROVIDER,
        external_id=f"bot|{uuid4()}",
        origin="source",
        state="observed",
        title="legacy bot lexical phrase",
        body="legacy bot lexical phrase",
        metadata_={"transport": "bot"},
        occurred_at=now,
    )
    note = Object(
        user_id=user.id,
        kind="note",
        origin="user",
        state="observed",
        title="anchor",
        body="selfauthored lexical phrase inbound foreign lexical phrase",
        occurred_at=now,
    )
    db_session.add_all([legacy, note])
    db_session.flush()

    visible = ObjectQueryService(db_session, user.id, ai_only=True).query(
        kinds=[TELEGRAM_KIND], providers=[TELEGRAM_PROVIDER]
    )
    assert owned in visible
    assert inbound not in visible
    assert legacy not in visible
    context = ContextService(db_session, user.id).build_context(object_id=owned.id)
    assert owned.id in {item.object_id for item in context.items}
    with pytest.raises(NotFoundError):
        ContextService(db_session, user.id).build_context(object_id=inbound.id)
    with pytest.raises(NotFoundError):
        ContextService(db_session, user.id).build_context(object_id=legacy.id)
    hits = SearchService(db_session, user.id).search("selfauthored lexical phrase")
    assert owned.id in {item.id for item in hits}
    hidden = SearchService(db_session, user.id).search("inbound foreign lexical phrase")
    assert inbound.id not in {item.id for item in hidden}
    legacy_hits = SearchService(db_session, user.id).search("legacy bot lexical phrase")
    assert legacy.id not in {item.id for item in legacy_hits}
    candidate_ids = {
        item.object_id
        for item in CorrelationCandidateService(db_session, user.id).collect_candidates(note.id)
    }
    assert owned.id in candidate_ids
    assert inbound.id not in candidate_ids
    assert legacy.id not in candidate_ids


def test_summary_handler_accepts_self_authored_stack_and_refuses_mixed(
    db_session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    user = _user(db_session)
    account = _account(db_session, user)
    _selection(db_session, account, active=True)
    now = datetime.now(UTC)
    first = _object(db_session, user, account, when=now, title="one")
    second = _object(db_session, user, account, when=now + timedelta(minutes=1), title="two")
    inbound = _object(
        db_session,
        user,
        account,
        direction="inbound",
        sender="900",
        when=now + timedelta(minutes=2),
        title="three",
    )
    stack = group_inbox_conversation_items([first, second])[0].stack
    summary_job = enqueue_summarize_conversation_stack(db_session, user.id, stack)
    assert summary_job is not None
    text = ConversationStackSummaryService(
        db_session, user.id, summarizer=FakeSummarizer(max_chars=200)
    ).generate_for_payload(dict(summary_job.payload))
    assert text
    entered: list[str] = []

    def _past_gate():
        entered.append("entered")
        raise RuntimeError("past eligibility")

    monkeypatch.setattr("app.ai_audit.context.SessionLocal", lambda: _SessionProxy(db_session))
    monkeypatch.setattr("app.jobs.handlers.SessionLocal", _past_gate)
    with pytest.raises(RuntimeError, match="past eligibility"):
        handle_summarize_conversation_stack(
            db_session,
            None,
            {"object_ids": [str(first.id), str(second.id)]},
            user.id,
        )
    assert entered == ["entered"]
    entered.clear()
    handle_summarize_conversation_stack(
        db_session,
        None,
        {"object_ids": [str(first.id), str(inbound.id)]},
        user.id,
    )
    assert entered == []
    mixed = group_inbox_conversation_items([first, inbound])[0].stack
    assert enqueue_summarize_conversation_stack(db_session, user.id, mixed) is None


def test_false_catchup_stays_zero_and_true_catchup_still_runs(db_session, monkeypatch) -> None:
    user = _user(db_session)
    account = _account(db_session, user)
    _selection(db_session, account, active=True)
    _object(db_session, user, account)
    sync = TelegramMtprotoRecurringSyncService.__new__(TelegramMtprotoRecurringSyncService)
    sync._session = db_session
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    assert sync._enqueue_embedding_catchup(user.id, account.id) == 0
    assert db_session.scalar(select(Job.id).where(Job.user_id == user.id)) is None
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    assert sync._enqueue_embedding_catchup(user.id, account.id) == 1
    assert sync._enqueue_embedding_catchup(user.id, account.id) == 0


def test_production_policy_has_no_marker_harness_or_transport() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app" / "domain" / "telegram_mtproto_ai.py"
    ).read_text(encoding="utf-8")
    folded = source.lower()
    assert "tg_self_e2e" not in folded
    assert "telegram_self_authored_e2e" not in folded
    assert "telethon" not in folded
    assert "decrypt" not in folded
    assert "session_encrypted" not in folded
    catchup = getsource(TelegramMtprotoRecurringSyncService._enqueue_embedding_catchup)
    assert "if not settings.telegram_mtproto_ai_enabled" in catchup
