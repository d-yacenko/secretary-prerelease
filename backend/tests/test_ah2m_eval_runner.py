"""AH2-MR1 scripted runner. No model and no live transport."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.assistant import session as assistant_session
from app.connectors.google.gmail_transport import GmailTransport
from app.core.config import settings
from app.llm.openai_assistant_provider import SYSTEM_INSTRUCTIONS
from app.tools.registry import ASSISTANT_TOOL_DEFINITIONS
from evals.secretary_agent.models import DimensionStatus, OverallStatus
from evals.secretary_agent.runner import (
    REFERENCE_DATETIME,
    REFERENCE_TIMEZONE,
    EvalConfig,
    EvalDatabase,
    production_contract,
    run_scripted,
    _bound_local_tool,
)
from evals.secretary_agent.safety import (
    EvalSafetyError,
    assert_dry_run_transports,
    assert_eval_database,
    assert_no_secrets,
    build_safe_artifact_payload,
)
from evals.secretary_agent.scorer import score_run
from evals.secretary_agent.catalog import SCENARIOS
from evals.secretary_agent.validate import validate_catalog

_RELEASE = "aa3f475a3a0ee49b938364e6d53f3657711b1a9b"


class ScriptedProvider:
    def __init__(self, calls: list[tuple[str, dict]]) -> None:
        self.calls = calls
        self.seen: dict = {}

    def run(self, message, history, ui_context, reference_datetime, timezone, tool_runner, identity_facts=None, **kwargs):
        self.seen = {
            "reference_datetime": reference_datetime,
            "timezone": timezone,
        }
        for name, arguments in self.calls:
            tool_runner(name, arguments)
        return type("Result", (), {"answer": "review"})()


def _config() -> EvalConfig:
    return EvalConfig(
        model="scripted",
        reasoning_effort="low",
        verbosity="low",
        max_rounds=6,
        max_output_tokens=1600,
        mode="scripted",
    )


def _database(url: str | None = None, *, disposable: bool = True) -> EvalDatabase:
    return EvalDatabase(engine=create_engine(url or settings.database_url), disposable=disposable)


def _close(database: EvalDatabase) -> None:
    database.engine.dispose()


def test_product_code_matches_production_release() -> None:
    root = Path(__file__).resolve().parents[2]
    diff = subprocess.check_output(
        ["git", "diff", "--name-only", f"{_RELEASE}..HEAD", "--", "backend/app"],
        cwd=root,
        text=True,
    )
    assert diff.strip() == ""
    assert validate_catalog() == []
    instructions, tools = production_contract()
    assert instructions is SYSTEM_INSTRUCTIONS
    assert tools is ASSISTANT_TOOL_DEFINITIONS


def test_database_guard_accepts_explicit_local_engine() -> None:
    database = _database()
    try:
        identity = assert_eval_database(database.engine, disposable=True)
    finally:
        _close(database)
    assert set(identity) == {"host", "database", "disposable"}
    assert identity["host"] in {"localhost", "127.0.0.1", "::1"}
    assert identity["database"]
    assert identity["disposable"] == "true"
    assert all("://" not in value for value in identity.values())


def test_remote_engine_is_rejected_before_connect() -> None:
    database = _database("postgresql+psycopg://eval:secret@web-itx.duckdns.org/secretary")
    try:
        with patch.object(Engine, "connect", side_effect=AssertionError("connected")):
            with pytest.raises(EvalSafetyError):
                run_scripted(
                    "A2",
                    ScriptedProvider([]),
                    _config(),
                    run_id="remote",
                    database=database,
                )
    finally:
        _close(database)


def test_local_engine_without_eval_classification_is_rejected() -> None:
    database = _database(disposable=False)
    try:
        with patch.object(Engine, "connect", side_effect=AssertionError("connected")):
            with pytest.raises(EvalSafetyError):
                run_scripted(
                    "A2",
                    ScriptedProvider([]),
                    _config(),
                    run_id="unclassified",
                    database=database,
                )
    finally:
        _close(database)


def test_settings_host_cannot_redirect_injected_engine(monkeypatch) -> None:
    database = _database()
    monkeypatch.setattr(settings, "postgres_host", "web-itx.duckdns.org")
    provider = ScriptedProvider([("create_task", {"title": "Купить бумагу", "confidence": 0.7})])
    try:
        run = run_scripted("A2", provider, _config(), run_id="settings-ignored", database=database)
    finally:
        _close(database)
    assert provider.seen["timezone"] == REFERENCE_TIMEZONE
    assert run.final_facts == {"confirmed_task_count": 0}


def test_runner_has_no_global_engine_fallback() -> None:
    source = Path(__file__).resolve().parents[1].joinpath("evals/secretary_agent/runner.py").read_text()
    assert "app.db.engine" not in source
    assert "SessionLocal" not in source


def test_injection_restores_after_success_and_failure(db_session) -> None:
    original = assistant_session.run_assistant_tool
    with _bound_local_tool(db_session):
        assert assistant_session.run_assistant_tool is not original
    assert assistant_session.run_assistant_tool is original
    with pytest.raises(RuntimeError, match="boom"):
        with _bound_local_tool(db_session):
            raise RuntimeError("boom")
    assert assistant_session.run_assistant_tool is original


def test_scripted_provider_does_not_construct_openai(monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("openai client")

    monkeypatch.setattr("openai.OpenAI", explode)
    provider = ScriptedProvider([("create_task", {"title": "Купить бумагу", "confidence": 0.7})])
    database = _database()
    try:
        run = run_scripted("A2", provider, _config(), run_id="a2-dry", database=database)
    finally:
        _close(database)
    assert provider.seen["timezone"] == REFERENCE_TIMEZONE
    assert provider.seen["reference_datetime"] == REFERENCE_DATETIME
    assert run.final_answer == "review"


def test_a2_staged_only_is_incomplete_and_unchanged() -> None:
    database = _database()
    try:
        run = run_scripted(
            "A2",
            ScriptedProvider([("create_task", {"title": "Купить бумагу", "confidence": 0.7})]),
            _config(),
            run_id="a2-score",
            database=database,
        )
    finally:
        _close(database)
    assert run.final_facts == {"confirmed_task_count": 0}
    assert run.calls[0].approval_required is True
    assert run.calls[0].executed is False
    report = score_run(SCENARIOS["A2"], run)
    assert report.overall == OverallStatus.INCOMPLETE
    assert report.dimension("truthful_final_response").status == DimensionStatus.MANUAL_REVIEW
    for item in report.dimensions:
        if item.dimension == "truthful_final_response":
            continue
        assert item.status in {DimensionStatus.PASS, DimensionStatus.NOT_APPLICABLE}, item.reasons
    _assert_safe_payload(run)


def test_t1_approved_execution_creates_one_ongoing_task() -> None:
    database = _database()
    try:
        run = run_scripted(
            "T1",
            ScriptedProvider(
                [
                    ("retrieve", {"query": "Публикации", "kind": "task"}),
                    (
                        "create_task",
                        {"title": "Публикации", "confidence": 0.8, "completion_mode": "ongoing"},
                    ),
                ]
            ),
            _config(),
            run_id="t1-score",
            database=database,
        )
    finally:
        _close(database)
    assert run.final_facts == {
        "task_count": 1,
        "title": "Публикации",
        "status": "open",
        "completion_mode": "ongoing",
    }
    staged = [call for call in run.calls if call.tool_name == "create_task" and call.approval_required]
    executed = [call for call in run.calls if call.tool_name == "create_task" and call.executed]
    assert len(staged) == 1
    assert len(executed) == 1
    assert executed[0].arguments["completion_mode"] == "ongoing"
    report = score_run(SCENARIOS["T1"], run)
    assert report.overall == OverallStatus.INCOMPLETE
    for item in report.dimensions:
        if item.dimension == "truthful_final_response":
            continue
        assert item.status in {DimensionStatus.PASS, DimensionStatus.NOT_APPLICABLE}, item.reasons
    _assert_safe_payload(run)


def test_live_transport_is_rejected() -> None:
    transport = GmailTransport()
    try:
        with pytest.raises(EvalSafetyError):
            assert_dry_run_transports((transport,))
    finally:
        transport._http.close()
    assert_dry_run_transports(())


def test_sanitizer_rejects_secret_fields() -> None:
    with pytest.raises(EvalSafetyError):
        assert_no_secrets({"OPENAI_API_KEY": "present"})
    with pytest.raises(EvalSafetyError):
        assert_no_secrets({"dsn": "postgresql://user:password@localhost/secretary"})
    assert_no_secrets(_config().public_dict())


def test_safe_artifact_rejects_secrets_reasoning_and_production_identity() -> None:
    run = _bare_run()
    public = _config().public_dict()
    for extra in (
        {"OPENAI_API_KEY": "sk-test-secret"},
        {"dsn": "postgresql://user:password@localhost/secretary"},
        {"access_token": "oauth-access"},
        {"refresh_token": "oauth-refresh"},
        {"chain_of_thought": "hidden"},
        {"reasoning_trace": "hidden"},
        {"hidden_reasoning": "hidden"},
        {"raw_response": {"id": "resp"}},
        {"provider_request": {"input": "wire"}},
        {"production_user_id": "user-1"},
    ):
        with pytest.raises(EvalSafetyError):
            build_safe_artifact_payload(run, {**public, **extra})
    with pytest.raises(EvalSafetyError):
        build_safe_artifact_payload(
            run,
            public,
            provider_output={"answer": "other", "chain_of_thought": "hidden"},
        )


def test_safe_artifact_keeps_only_final_answer() -> None:
    run = _bare_run()
    payload = build_safe_artifact_payload(
        run,
        _config().public_dict(),
        provider_output={"answer": "other", "commentary": "not stored"},
    )
    assert payload["final_answer"] == "review"
    encoded = json.dumps(payload)
    assert "commentary" not in encoded
    assert "other" not in encoded
    assert json.loads(encoded) == payload


def _bare_run():
    from evals.secretary_agent.models import EvalRun

    return EvalRun(scenario_id="A2", utterance="x", run_id="bare", final_answer="review", model="scripted")


def _assert_safe_payload(run) -> None:
    payload = build_safe_artifact_payload(run, _config().public_dict())
    assert payload["final_answer"] == run.final_answer
    assert json.loads(json.dumps(payload)) == payload
