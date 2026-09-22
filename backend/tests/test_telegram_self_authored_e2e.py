"""Local fake-provider checks for the self-authored MTProto acceptance harness."""

import importlib.util
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.db.models import (
    Job,
    Object,
    TelegramMtprotoAccount,
    TelegramMtprotoChatSelection,
    User,
    UserSettings,
)
from app.jobs.handlers import HANDLERS
from app.services.label_service import LabelService

HELPER_PATH = (
    Path(__file__).resolve().parents[2] / "ops" / "production" / "telegram_self_authored_e2e.py"
)
REMOTE_PATH = HELPER_PATH.with_name("telegram_self_authored_e2e_remote.py")
spec = importlib.util.spec_from_file_location("telegram_self_authored_e2e", HELPER_PATH)
harness = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = harness
spec.loader.exec_module(harness)
remote_spec = importlib.util.spec_from_file_location(
    "telegram_self_authored_e2e_remote", REMOTE_PATH
)
remote = importlib.util.module_from_spec(remote_spec)
sys.modules[remote_spec.name] = remote
remote_spec.loader.exec_module(remote)

MARKER = harness.MARKER


def _probe(api: bool = False, worker: bool = False):
    return lambda: (api, worker)


def _account(session, user, telegram_user_id: int) -> TelegramMtprotoAccount:
    account = TelegramMtprotoAccount(
        id=uuid4(),
        user_id=user.id,
        telegram_user_id=telegram_user_id,
        session_encrypted="SEALED",
    )
    session.add(account)
    session.flush()
    return account


def _selection(session, account, peer_id: int, *, active: bool = True) -> None:
    session.add(
        TelegramMtprotoChatSelection(
            account_id=account.id,
            peer_id=peer_id,
            peer_kind="group",
            provider_peer_reference_encrypted="SEALED",
            title="solo",
            scope_active=active,
        )
    )
    session.flush()


def _message(
    session,
    user,
    account,
    peer_id: int,
    *,
    direction: str = "outbound",
    sender: int | None = None,
    body: str | None = None,
    when: datetime | None = None,
    account_id: str | None = None,
) -> Object:
    text = body if body is not None else f"{MARKER} self authored note"
    obj = Object(
        user_id=user.id,
        kind="chat_message",
        origin="source",
        state="observed",
        provider="telegram",
        title="solo",
        body=text,
        occurred_at=when or datetime.now(UTC),
        metadata_={
            "transport": "mtproto",
            "account_id": account_id if account_id is not None else str(account.id),
            "peer_id": peer_id,
            "peer_kind": "group",
            "direction": direction,
            "sender_peer_id": account.telegram_user_id if sender is None else sender,
        },
    )
    if sender is None and "sender_peer_id" in obj.metadata_ and direction == "outbound":
        pass
    session.add(obj)
    session.flush()
    return obj


def _user(session) -> tuple[User, TelegramMtprotoAccount]:
    user = User(id=uuid4(), display_name=f"user-{uuid4().hex[:8]}")
    session.add(user)
    session.flush()
    account = _account(session, user, telegram_user_id=int(uuid4().int % 1_000_000_000_000) + 10)
    _selection(session, account, 4242)
    return user, account


def _task(session, user) -> Object:
    task = Object(
        user_id=user.id,
        kind="task",
        origin="user",
        state="confirmed",
        title=f"{MARKER} prepare the estimate",
        body="existing secretary task",
    )
    session.add(task)
    session.flush()
    return task


def _pair(session, user, account, **overrides) -> list[Object]:
    base = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    first = _message(session, user, account, 4242, when=base, **overrides)
    second = _message(
        session,
        user,
        account,
        4242,
        when=base + timedelta(minutes=1),
        body=f"{MARKER} second self authored note",
    )
    return [first, second]


def test_inbound_is_rejected(db_session) -> None:
    user, account = _user(db_session)
    _message(db_session, user, account, 4242, direction="inbound", sender=99)
    _message(db_session, user, account, 4242, direction="inbound", sender=99)
    with pytest.raises(harness.HarnessBlocked, match="direction"):
        harness.run_acceptance(db_session, probe=_probe())
    assert settings.telegram_mtproto_ai_enabled is False


def test_outbound_sender_mismatch_is_rejected(db_session) -> None:
    user, account = _user(db_session)
    _pair(db_session, user, account, sender=account.telegram_user_id + 1)
    with pytest.raises(harness.HarnessBlocked, match="sender"):
        harness.run_acceptance(db_session, probe=_probe())
    assert settings.telegram_mtproto_ai_enabled is False


def test_missing_sender_and_account_identity_are_rejected(db_session) -> None:
    user, account = _user(db_session)
    base = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    first = _message(db_session, user, account, 4242, when=base)
    second = _message(db_session, user, account, 4242, when=base + timedelta(minutes=1))
    first.metadata_ = {**first.metadata_, "sender_peer_id": None}
    second.metadata_ = {**second.metadata_, "sender_peer_id": None}
    db_session.flush()
    with pytest.raises(harness.HarnessBlocked, match="identity"):
        harness.run_acceptance(db_session, probe=_probe())
    first.body = "cleared"
    second.body = "cleared"
    db_session.flush()

    other, other_account = _user(db_session)
    _message(
        db_session,
        other,
        other_account,
        4242,
        account_id=str(uuid4()),
    )
    _message(
        db_session,
        other,
        other_account,
        4242,
        account_id=str(uuid4()),
    )
    with pytest.raises(harness.HarnessBlocked, match="mixed_account|identity"):
        harness.run_acceptance(db_session, probe=_probe())


def test_mixed_account_and_peer_are_rejected(db_session) -> None:
    user, account = _user(db_session)
    base = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    first = _message(db_session, user, account, 4242, when=base)
    second = _message(
        db_session,
        user,
        account,
        4242,
        when=base + timedelta(minutes=1),
        account_id=str(uuid4()),
    )
    with pytest.raises(harness.HarnessBlocked, match="mixed_account"):
        harness.run_acceptance(db_session, probe=_probe())
    first.body = "cleared"
    second.body = "cleared"
    db_session.flush()

    user2, account2 = _user(db_session)
    _selection(db_session, account2, 777)
    _message(db_session, user2, account2, 4242, when=base)
    _message(db_session, user2, account2, 777, when=base + timedelta(minutes=1))
    with pytest.raises(harness.HarnessBlocked, match="mixed_peer"):
        harness.run_acceptance(db_session, probe=_probe())


def test_inactive_scope_is_rejected(db_session) -> None:
    user = User(id=uuid4(), display_name=f"user-{uuid4().hex[:8]}")
    db_session.add(user)
    db_session.flush()
    account = _account(db_session, user, telegram_user_id=int(uuid4().int % 1_000_000_000) + 3)
    _selection(db_session, account, 4242, active=False)
    _pair(db_session, user, account)
    with pytest.raises(harness.HarnessBlocked, match="scope"):
        harness.run_acceptance(db_session, probe=_probe())
    assert settings.telegram_mtproto_ai_enabled is False


def test_third_party_summary_message_blocks_before_provider_call(db_session, monkeypatch) -> None:
    user, account = _user(db_session)
    _task(db_session, user)
    base = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    _pair(db_session, user, account)
    _message(
        db_session,
        user,
        account,
        4242,
        direction="inbound",
        sender=55,
        body="someone else wrote this",
        when=base + timedelta(minutes=2),
    )
    calls = []
    monkeypatch.setattr(
        harness.FakeEmbeddingService,
        "embed",
        lambda self, text: calls.append(text),
    )
    with pytest.raises(harness.HarnessBlocked, match="summary_cohort"):
        harness.run_acceptance(db_session, probe=_probe())
    assert calls == []
    assert settings.telegram_mtproto_ai_enabled is False
    assert (
        db_session.scalar(select(func.count()).select_from(Job).where(Job.user_id == user.id)) == 0
    )


def test_only_marker_cohort_is_enqueued_without_backlog(db_session) -> None:
    user, account = _user(db_session)
    _task(db_session, user)
    db_session.add(
        UserSettings(
            user_id=user.id,
            timezone="Europe/Moscow",
            auto_label_enabled=True,
            temporal_signals_enabled=True,
        )
    )
    LabelService(db_session, user.id).create_label("Existing")
    base = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    selected = _pair(db_session, user, account)
    backlog = _message(
        db_session,
        user,
        account,
        4242,
        body="older synced note without the marker",
        when=base - timedelta(hours=3),
    )
    unrelated = Job(
        user_id=user.id,
        type="embed_object",
        payload={"object_id": str(uuid4())},
        status="pending",
        attempts=0,
        run_after=datetime.now(UTC),
    )
    db_session.add(unrelated)
    db_session.flush()
    seen = {}

    def on_ready() -> None:
        seen["before"] = settings.telegram_mtproto_ai_enabled

    report = harness.run_acceptance(db_session, probe=_probe(), on_ready=on_ready)
    assert seen["before"] is False
    assert "SELF_AUTHORED=PASS" in report
    assert "embed_object" in report
    assert "auto_label_object" in report
    assert "AUTO_LABEL_EXECUTED=PASS" in report
    assert "AUTO_LABEL_ASSIGNMENTS=0" in report
    assert "DANGLING_SELECTED_JOBS=0" in report
    assert "LIVE_EXECUTION=0" in report
    assert MARKER not in report
    assert "бюджет" not in report
    payloads = [
        job.payload for job in db_session.scalars(select(Job).where(Job.user_id == user.id))
    ]
    assert all(str(backlog.id) not in str(payload) for payload in payloads)
    assert all(str(item.id) in str(payloads) for item in selected)
    assert unrelated.status == "pending"
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.user_id == user.id, Job.type == "sync_telegram_mtproto")
        )
        == 0
    )
    assert settings.telegram_mtproto_ai_enabled is False
    assert "TELEGRAM_MTPROTO_AI_ENABLED" not in os.environ


def test_normal_handlers_and_failure_clears_selected_jobs(db_session, monkeypatch) -> None:
    user, account = _user(db_session)
    _task(db_session, user)
    _pair(db_session, user, account)
    used = []

    def explode(session, embedding, payload, user_id):
        del session, embedding, payload, user_id
        raise RuntimeError("sk-secret provider payload")

    def spy(job_type: str):
        handler = HANDLERS[job_type]
        used.append(handler)
        return explode

    monkeypatch.setattr(harness, "get_handler", spy)
    with pytest.raises(harness.HarnessBlocked, match="harness_aborted"):
        harness.run_acceptance(db_session, probe=_probe())
    assert used
    assert used[0] in HANDLERS.values()
    jobs = list(db_session.scalars(select(Job).where(Job.user_id == user.id)))
    assert jobs
    assert {job.status for job in jobs} == {"failed"}
    assert {job.last_error for job in jobs} == {"harness_aborted"}
    assert "sk-secret" not in "".join(job.last_error or "" for job in jobs)
    assert settings.telegram_mtproto_ai_enabled is False


def test_long_running_flag_blocks_and_output_stays_sanitized(db_session, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_MTPROTO_AI_ENABLED", raising=False)
    user, account = _user(db_session)
    _task(db_session, user)
    _pair(db_session, user, account)
    with pytest.raises(harness.HarnessBlocked, match="long_running_ai"):
        harness.run_acceptance(db_session, probe=_probe(api=True))
    assert settings.telegram_mtproto_ai_enabled is False
    assert "TELEGRAM_MTPROTO_AI_ENABLED" not in os.environ


def test_transport_and_session_decrypt_are_unreachable() -> None:
    with harness.transport_barrier():
        with pytest.raises(harness.HarnessTransportBlocked):
            importlib.import_module("telethon")
        store = importlib.import_module("app.connectors.telegram.mtproto_account_store")
        with pytest.raises(harness.HarnessTransportBlocked):
            store.TelegramMtprotoAccountStore.decrypt_session(object(), object())


def test_oneshot_does_not_enable_global_ai_or_synthetic_helper() -> None:
    command = remote.oneshot_compose_command()
    joined = " ".join(command)
    assert remote.ONESHOT_HELPER_DEST == "/app/telegram_self_authored_e2e.py"
    assert command[command.index("python3") :] == [
        "python3",
        "/app/telegram_self_authored_e2e.py",
        "--live",
    ]
    assert ":ro" in joined
    assert "TELEGRAM_MTPROTO_AI_ENABLED=true" not in command
    assert "telegram_production_rehearsal.py" not in joined
    assert "--no-deps" in command
    assert "up" not in command
    assert "docker.sock" not in joined
