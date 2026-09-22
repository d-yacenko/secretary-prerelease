"""Local fake-provider proof for the production Telegram rehearsal helper."""

import importlib.util
import os
import sys
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.db.models import Job, Object, User

HELPER_PATH = (
    Path(__file__).resolve().parents[2] / "ops" / "production" / "telegram_production_rehearsal.py"
)
spec = importlib.util.spec_from_file_location("telegram_production_rehearsal", HELPER_PATH)
helper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = helper
spec.loader.exec_module(helper)

RUN_ID = "rehearsal1"


def _probe(calls: list[tuple[bool, bool]], api: bool = False, worker: bool = False):
    def probe():
        calls.append((api, worker))
        return api, worker

    return probe


def test_refuses_non_synthetic_run_id_and_content(db_session) -> None:
    with pytest.raises(helper.RehearsalRefused, match="run_id"):
        helper.run_rehearsal(db_session, "Bad_Id", probe=lambda: (False, False))
    with pytest.raises(helper.RehearsalRefused, match="non_synthetic_content"):
        helper.run_rehearsal(
            db_session,
            RUN_ID,
            probe=lambda: (False, False),
            content=("real private text", "real private text", "real private text"),
        )
    assert (
        db_session.scalar(
            select(func.count()).select_from(User).where(User.display_name.contains("rehearsal1"))
        )
        == 0
    )


def test_transport_and_session_decrypt_are_unreachable() -> None:
    with helper.transport_barrier():
        with pytest.raises(helper.RehearsalTransportBlocked):
            importlib.import_module("telethon")
        store = importlib.import_module("app.connectors.telegram.mtproto_account_store")
        with pytest.raises(helper.RehearsalTransportBlocked):
            store.TelegramMtprotoAccountStore.decrypt_session(object(), object())
        transport = importlib.import_module("app.connectors.telegram.mtproto_transport")
        with pytest.raises(helper.RehearsalTransportBlocked):
            transport.TelethonMtprotoTransport(1, "hash")


def test_process_local_ai_does_not_mutate_env_and_requires_false_services(
    db_session, monkeypatch
) -> None:
    monkeypatch.delenv("TELEGRAM_MTPROTO_AI_ENABLED", raising=False)
    calls: list[tuple[bool, bool]] = []
    with pytest.raises(helper.RehearsalRefused, match="long_running_ai"):
        helper.run_rehearsal(db_session, RUN_ID, probe=_probe(calls, api=True))
    assert calls == [(True, False)]
    assert settings.telegram_mtproto_ai_enabled is False
    assert "TELEGRAM_MTPROTO_AI_ENABLED" not in __import__("os").environ


def test_long_running_flag_parser_treats_absent_as_false() -> None:
    assert helper.long_running_ai_from_env([]) is False
    assert helper.long_running_ai_from_env(["TELEGRAM_MTPROTO_AI_ENABLED=false"]) is False
    assert helper.long_running_ai_from_env(["TELEGRAM_MTPROTO_AI_ENABLED=true"]) is True


def test_fake_provider_rehearsal_is_synchronous_sanitized_and_closed(db_session) -> None:
    calls: list[tuple[bool, bool]] = []
    report = helper.run_rehearsal(
        db_session,
        RUN_ID,
        probe=_probe(calls),
        commit=db_session.flush,
    )
    assert calls == [(False, False)]
    assert "TG_REHEARSAL_" not in report
    assert "budget meeting" not in report
    assert helper.SESSION_PLACEHOLDER not in report
    for line in (
        "INBOX_ELIGIBLE=PASS",
        "STACK_GROUPED=PASS",
        "EMBEDDING=PASS",
        "AUTO_LABEL=PASS",
        "TEMPORAL=PASS",
        "TEMPORAL_PARTICIPATION=expected",
        "CORRELATION=PASS",
        "SUMMARY=PASS",
        "CONTEXT_VISIBLE=PASS",
        "IDEMPOTENT=PASS",
        "PROCESS_LOCAL_AI=true",
        "ENV_UNCHANGED=PASS",
        "LONG_RUNNING_API_AI=false",
        "LONG_RUNNING_WORKER_AI=false",
        "TELEGRAM_TRANSPORT_CALLS=0",
        "DANGLING_JOBS=0",
        "PROVIDERS=fake",
        "LIVE_REHEARSAL_EXECUTED=0",
    ):
        assert line in report
    user_id = db_session.scalar(
        select(User.id).where(User.display_name == f"TG_REHEARSAL_{RUN_ID}")
    )
    dangling = db_session.scalar(
        select(func.count())
        .select_from(Job)
        .where(
            Job.user_id == user_id,
            Job.status.in_(("pending", "running")),
        )
    )
    assert dangling == 0
    with pytest.raises(helper.RehearsalRefused, match="duplicate_run_id"):
        helper.run_rehearsal(
            db_session, RUN_ID, probe=lambda: (False, False), commit=db_session.flush
        )
    assert settings.telegram_mtproto_ai_enabled is False


def test_live_mode_is_not_executed_without_architect_confirmation(capsys) -> None:
    assert helper.main(["--live", "--run-id", RUN_ID]) == 2
    assert "LIVE_REHEARSAL_BLOCKED=architect_review_required" in capsys.readouterr().out


class _SessionProxy:
    def __init__(self, session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(self._session, name)


def test_live_exit_code_propagates(monkeypatch, capsys) -> None:
    monkeypatch.setenv("REHEARSAL_LIVE_CONFIRM", "reviewed")
    monkeypatch.setattr(helper, "execute_live", lambda _run_id: 0)
    assert helper.main(["--live", "--run-id", RUN_ID]) == 0
    monkeypatch.setattr(helper, "execute_live", lambda _run_id: 2)
    assert helper.main(["--live", "--run-id", RUN_ID]) == 2
    assert capsys.readouterr().out == ""


def test_execute_live_success_returns_zero(db_session, monkeypatch, capsys) -> None:
    report = "INBOX_ELIGIBLE=PASS\nDANGLING_JOBS=0\n"

    def succeed(*_args, **_kwargs):
        return report

    monkeypatch.setattr(helper, "run_rehearsal", succeed)
    code = helper.execute_live(RUN_ID, session_factory=lambda: _SessionProxy(db_session))
    assert code == 0
    assert capsys.readouterr().out == report


def test_provider_failure_is_sanitized_and_clears_dangling_jobs(
    db_session, monkeypatch, capsys
) -> None:
    monkeypatch.delenv("TELEGRAM_MTPROTO_AI_ENABLED", raising=False)
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)

    def explode(session, run_id, **_kwargs):
        user = User(id=uuid4(), display_name=f"TG_REHEARSAL_{run_id}")
        session.add(user)
        session.flush()
        session.add(
            Object(
                user_id=user.id,
                kind="task",
                origin="user",
                state="observed",
                title="synthetic artifact",
            )
        )
        now = datetime.now(UTC)
        for status in ("pending", "running"):
            session.add(
                Job(
                    user_id=user.id,
                    type="embed_object",
                    payload={},
                    status=status,
                    attempts=0,
                    run_after=now,
                )
            )
        session.commit()
        settings.telegram_mtproto_ai_enabled = True
        raise RuntimeError("sk-secret provider payload")

    monkeypatch.setattr(helper, "run_rehearsal", explode)
    code = helper.execute_live("failure01", session_factory=lambda: _SessionProxy(db_session))
    captured = capsys.readouterr().out
    assert code == 1
    assert captured == "REHEARSAL_FAILED=rehearsal_aborted\n"
    assert "sk-secret" not in captured
    assert "Traceback" not in captured
    user_id = db_session.scalar(
        select(User.id).where(User.display_name == "TG_REHEARSAL_failure01")
    )
    rows = list(db_session.scalars(select(Job).where(Job.user_id == user_id)))
    assert rows
    assert {row.status for row in rows} == {"failed"}
    assert {row.last_error for row in rows} == {"rehearsal_aborted"}
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(Object)
            .where(Object.user_id == user_id, Object.kind == "task")
        )
        == 1
    )
    assert settings.telegram_mtproto_ai_enabled is False
    assert "TELEGRAM_MTPROTO_AI_ENABLED" not in os.environ


def test_execute_live_refusal_returns_nonzero(db_session, monkeypatch, capsys) -> None:
    def refuse(*_args, **_kwargs):
        raise helper.RehearsalRefused("long_running_ai sk-secret")

    monkeypatch.setattr(helper, "run_rehearsal", refuse)
    code = helper.execute_live(RUN_ID, session_factory=lambda: _SessionProxy(db_session))
    captured = capsys.readouterr().out
    assert code == 2
    assert captured == "REHEARSAL_REFUSED=rehearsal_refused\n"
    assert "sk-secret" not in captured


def test_live_path_does_not_enter_fake_providers(db_session, monkeypatch, capsys) -> None:
    monkeypatch.setenv("REHEARSAL_LIVE_CONFIRM", "reviewed")
    monkeypatch.setenv("REHEARSAL_LONG_RUNNING_API_AI", "false")
    monkeypatch.setenv("REHEARSAL_LONG_RUNNING_WORKER_AI", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "present-not-a-real-call")
    calls = []
    seen = {}

    def fake_providers(*_args, **_kwargs):
        calls.append("fake")
        return nullcontext(object())

    def drain(_session, _user_id, embedding):
        seen["embedding"] = embedding
        raise RuntimeError("stop")

    monkeypatch.setattr(helper, "_fake_providers", fake_providers)
    monkeypatch.setattr(helper, "_drain", drain)
    with pytest.raises(RuntimeError, match="stop"):
        helper.run_rehearsal(
            db_session,
            "livepath1",
            probe=lambda: (False, False),
            commit=db_session.flush,
            providers="live",
        )
    assert calls == []
    assert seen["embedding"] is None
    assert settings.telegram_mtproto_ai_enabled is False
    captured = capsys.readouterr().out
    assert captured == "REHEARSAL_STARTUP=PASS\n"
    assert "present-not-a-real-call" not in captured


def test_missing_openai_fallback_blocks_before_fixture(db_session, monkeypatch, capsys) -> None:
    monkeypatch.setenv("REHEARSAL_LIVE_CONFIRM", "reviewed")
    monkeypatch.setenv("REHEARSAL_LONG_RUNNING_API_AI", "false")
    monkeypatch.setenv("REHEARSAL_LONG_RUNNING_WORKER_AI", "false")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    code = helper.execute_live("noprovkey", session_factory=lambda: _SessionProxy(db_session))
    captured = capsys.readouterr().out
    assert code == 2
    assert captured == "REHEARSAL_STARTUP=PASS\nREHEARSAL_REMOTE_BLOCKED=provider_config\n"
    assert "sk-" not in captured
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.display_name == "TG_REHEARSAL_noprovkey")
        )
        == 0
    )
