"""AH2-MR1 scripted runner. No model and no live transport."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

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
    production_contract,
    run_scripted,
    _bound_local_tool,
)
from evals.secretary_agent.safety import (
    EvalSafetyError,
    assert_disposable_database,
    assert_dry_run_transports,
    assert_no_secrets,
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


def test_database_guard_accepts_local_and_rejects_remote() -> None:
    assert assert_disposable_database("localhost", "secretary")["local"] == "true"
    with pytest.raises(EvalSafetyError):
        assert_disposable_database("web-itx.duckdns.org", "secretary")
    with pytest.raises(EvalSafetyError):
        assert_disposable_database("", "secretary")


def test_database_guard_rejects_before_the_provider(monkeypatch) -> None:
    monkeypatch.setattr(settings, "postgres_host", "web-itx.duckdns.org")
    provider = ScriptedProvider([("create_task", {"title": "Купить бумагу", "confidence": 0.7})])

    def refuse(*args, **kwargs):
        raise AssertionError("provider ran")

    provider.run = refuse
    with pytest.raises(EvalSafetyError):
        run_scripted("A2", provider, _config(), run_id="remote")


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
    run = run_scripted("A2", provider, _config(), run_id="a2-dry")
    assert provider.seen["timezone"] == REFERENCE_TIMEZONE
    assert provider.seen["reference_datetime"] == REFERENCE_DATETIME
    assert run.final_answer == "review"


def test_a2_staged_only_is_incomplete_and_unchanged() -> None:
    run = run_scripted(
        "A2",
        ScriptedProvider([("create_task", {"title": "Купить бумагу", "confidence": 0.7})]),
        _config(),
        run_id="a2-score",
    )
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


def test_t1_approved_execution_creates_one_ongoing_task() -> None:
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
    )
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
