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
    AITrace,
    AITraceEvent,
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
    task = _task(db_session, user)
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
    task.occurred_at = base
    selected = _pair(db_session, user, account)
    selected[0].body = f"{MARKER} Завтра в 11:00 budget11"
    selected[1].body = f"{MARKER} budget11 follow-up"
    backlog = Object(
        user_id=user.id,
        kind="note",
        origin="user",
        state="confirmed",
        title="older note",
        body="older synced note without the marker",
        occurred_at=base - timedelta(days=5),
    )
    db_session.add(backlog)
    db_session.flush()
    unrelated = Job(
        user_id=user.id,
        type="embed_object",
        payload={"object_id": str(uuid4())},
        status="pending",
        attempts=0,
        run_after=datetime.now(UTC),
    )
    db_session.add(unrelated)
    historical = AITrace(
        id=uuid4(),
        user_id=user.id,
        workload="background_auto_label",
        object_id=selected[0].id,
    )
    unrelated_trace = AITrace(
        id=uuid4(),
        user_id=user.id,
        workload="background_auto_label",
        object_id=uuid4(),
    )
    db_session.add_all([historical, unrelated_trace])
    db_session.flush()
    db_session.add_all(
        [
            AITraceEvent(
                trace_id=historical.id,
                user_id=user.id,
                sequence=1,
                event_type="auto_label_result",
                metadata_={"accepted_assignment_count": 7},
            ),
            AITraceEvent(
                trace_id=unrelated_trace.id,
                user_id=user.id,
                sequence=1,
                event_type="auto_label_result",
                metadata_={"accepted_assignment_count": 4},
            ),
        ]
    )
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
    assert "EMBEDDING=PASS" in report
    assert "TEMPORAL=PASS" in report
    assert "CORRELATION=PASS" in report
    assert "SUMMARY=PASS" in report
    assert "CONTEXT_VISIBLE=PASS" in report
    assert "RETRIEVAL_VISIBLE=PASS" in report
    assert "IDEMPOTENT=PASS" in report
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
    assert "SELF_E2E_CONFIRM=reviewed" in command


def test_malformed_marker_metadata_is_blocked(db_session) -> None:
    user, account = _user(db_session)
    base = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    _message(db_session, user, account, 4242, when=base, account_id="not-a-uuid")
    _message(
        db_session, user, account, 4242, when=base + timedelta(minutes=1), account_id="not-a-uuid"
    )
    with pytest.raises(harness.HarnessBlocked, match="identity"):
        harness.run_acceptance(db_session, probe=_probe())
    first = db_session.scalars(select(Object).where(Object.user_id == user.id)).all()
    for obj in first:
        obj.body = "cleared"
    db_session.flush()
    user2, account2 = _user(db_session)
    bad = _message(db_session, user2, account2, 4242, when=base)
    other = _message(db_session, user2, account2, 4242, when=base + timedelta(minutes=1))
    bad.metadata_ = {**bad.metadata_, "peer_id": "not-int"}
    other.metadata_ = {**other.metadata_, "peer_id": "not-int"}
    db_session.flush()
    with pytest.raises(harness.HarnessBlocked, match="identity"):
        harness.run_acceptance(db_session, probe=_probe())


def test_correlation_privacy_blocks_unapproved_telegram_before_judge(db_session) -> None:
    user, account = _user(db_session)
    task = _task(db_session, user)
    base = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    task.occurred_at = base
    messages = _pair(db_session, user, account)
    inbound = _message(
        db_session,
        user,
        account,
        4242,
        direction="inbound",
        sender=77,
        body="third party note",
        when=base + timedelta(minutes=30),
    )
    db_session.flush()
    from app.services.correlation_candidate_service import CorrelationCandidateService

    settings.telegram_mtproto_ai_enabled = True
    try:
        candidates = CorrelationCandidateService(db_session, user.id).collect_candidates(
            messages[0].id
        )
    finally:
        settings.telegram_mtproto_ai_enabled = False
    assert inbound.id in {item.object_id for item in candidates}
    calls = []

    class _Inner:
        def judge(self, trigger_title, trigger_kind, trigger_summary, candidates):
            calls.append(candidates)
            return harness.CorrelationJudgeResult(decisions=())

    approved = harness.prove_summary_cohort(
        db_session, harness.prove_cohort(db_session, harness.load_marker_objects(db_session))
    )
    judge = harness.PrivacyCorrelationJudge(_Inner(), db_session, approved)
    with pytest.raises(harness.HarnessBlocked, match="correlation_privacy"):
        judge.judge("title", "chat_message", "summary", candidates)
    assert calls == []
    task_only = [item for item in candidates if item.object_id == task.id]
    assert task_only
    judge.judge("title", "task", "summary", task_only)
    assert len(calls) == 1


def test_live_entrypoint_is_sanitized_and_uses_real_boundary(monkeypatch, capsys) -> None:
    monkeypatch.delenv("SELF_E2E_CONFIRM", raising=False)
    assert harness.main(["--live"]) == 2
    assert capsys.readouterr().out == "SELF_E2E_BLOCKED=review_required\n"
    monkeypatch.setenv("SELF_E2E_CONFIRM", "reviewed")
    monkeypatch.setenv("REHEARSAL_LONG_RUNNING_API_AI", "false")
    monkeypatch.setenv("REHEARSAL_LONG_RUNNING_WORKER_AI", "false")

    def explode(*_args, **_kwargs):
        raise RuntimeError("sk-secret payload")

    monkeypatch.setattr(harness, "run_acceptance", explode)
    monkeypatch.setattr(harness, "SessionLocal", lambda: object(), raising=False)
    code = harness.execute_live(
        session_factory=lambda: type("S", (), {"close": lambda self: None})()
    )
    captured = capsys.readouterr().out
    assert code == 1
    assert captured == "SELF_E2E_FAILED=harness_aborted\n"
    assert "sk-secret" not in captured
    assert "Traceback" not in captured


_FAKE_SUBPROCESS = """
import subprocess
import sys
from pathlib import Path

RELEASE = sys.argv[2]
ORIGIN = sys.argv[3]
MODE = sys.argv[4]


class Proc:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def fake_run(cmd, **_kwargs):
    if MODE == "raise":
        raise RuntimeError("sk-secret NameError TRUE_FLAGS")
    if cmd and cmd[0] == "git":
        answers = {
            ("rev-parse", "HEAD"): RELEASE,
            ("status", "--porcelain"): "",
            ("remote", "get-url", "origin"): ORIGIN,
        }
        return Proc(0, answers[tuple(cmd[1:])] + "\\n")
    if "exec" in cmd:
        return Proc(0, "false\\n")
    if "run" in cmd:
        if MODE == "oneshot":
            return Proc(1, "Traceback sk-secret ModuleNotFoundError")
        return Proc(0, "EMBEDDING=PASS\\n")
    raise AssertionError(cmd)


subprocess.run = fake_run
program = Path(sys.argv[1]).read_text(encoding="utf-8")
try:
    exec(compile(program, "remote_program.py", "exec"), {"__name__": "__main__"})
except SystemExit as exc:
    raise SystemExit(0 if exc.code is None else exc.code)
"""


def _run_generated(program: str, *, mode: str):
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        script = root / "remote.py"
        runner = root / "runner.py"
        script.write_text(program, encoding="utf-8")
        runner.write_text(_FAKE_SUBPROCESS, encoding="utf-8")
        return __import__("subprocess").run(
            [
                sys.executable,
                str(runner),
                str(script),
                remote.PRODUCTION_RELEASE,
                remote.CANONICAL_ORIGIN,
                mode,
            ],
            text=True,
            capture_output=True,
            check=False,
        )


def test_generated_remote_program_reaches_oneshot_and_sanitizes_failure() -> None:
    written = Path("/tmp/telegram_self_authored_e2e.py")
    program = remote.build_remote_program("print('helper')\n")
    try:
        ok = _run_generated(program, mode="ok")
        failed = _run_generated(program, mode="oneshot")
        raised = _run_generated(program, mode="raise")
    finally:
        written.unlink(missing_ok=True)
    assert ok.returncode == 0
    assert ok.stdout == "EMBEDDING=PASS\n"
    assert "NameError" not in ok.stderr
    assert failed.returncode == 1
    assert failed.stdout == "SELF_E2E_REMOTE_BLOCKED=oneshot_failed\n"
    assert "sk-secret" not in failed.stdout
    assert raised.returncode == 1
    assert raised.stdout == "SELF_E2E_REMOTE_BLOCKED=remote_program\n"
    assert "sk-secret" not in raised.stdout
    assert "TELEGRAM_MTPROTO_AI_ENABLED=true" not in program
