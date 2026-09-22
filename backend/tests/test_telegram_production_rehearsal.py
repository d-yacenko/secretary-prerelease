"""Local fake-provider proof for the production Telegram rehearsal helper."""

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.db.models import Job, User

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
