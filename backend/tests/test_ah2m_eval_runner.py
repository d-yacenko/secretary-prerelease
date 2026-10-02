"""AH2-MR1 scripted runner. No model and no live transport."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.assistant import session as assistant_session
from app.assistant.tool_runner import PerTurnToolBudget
from app.connectors.google.gmail_transport import GmailTransport
from app.core.config import settings
from app.llm.openai_assistant_provider import SYSTEM_INSTRUCTIONS
from app.tools.registry import ASSISTANT_TOOL_DEFINITIONS
from app.tools.results import ToolExecutionStatus
from evals.secretary_agent.fixtures import REGISTRY_IDS
from evals.secretary_agent.scripted import ScriptedProvider
from evals.secretary_agent.models import DimensionStatus, OverallStatus
from evals.secretary_agent.runner import (
    _approve_external,
    _approve_internal,
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
from app.db.models import Object
from app.db.session import SessionLocal
from app.services.action_plan_service import ActionPlanService
from app.services.domain_tool_service import DomainToolService
from app.services.email_external_action_service import EmailExternalActionService
from evals.secretary_agent.catalog import SCENARIOS, chat_reply_scenario
from evals.secretary_agent.external import ExternalBundle, FakeGmailTransport
from evals.secretary_agent.recording import RecordingToolRunner
from evals.secretary_agent.validate import validate_catalog

_RELEASE = "aa3f475a3a0ee49b938364e6d53f3657711b1a9b"


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
    provider = ScriptedProvider()
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
    provider = ScriptedProvider()
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
            ScriptedProvider(),
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
        provider = ScriptedProvider()
        run = run_scripted("T1", provider, _config(), run_id="t1-score", database=database)
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
    assert provider.commits == 2
    assert [tool_round[0][0] for tool_round in provider.rounds] == ["retrieve", "create_task"]
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


def test_artifact_builder_rejects_raw_provider_output() -> None:
    with pytest.raises(TypeError):
        build_safe_artifact_payload(
            _bare_run(),
            _config().public_dict(),
            provider_output={"answer": "other", "chain_of_thought": "hidden"},
        )


def test_safe_artifact_keeps_only_final_answer() -> None:
    run = _bare_run()
    payload = build_safe_artifact_payload(run, _config().public_dict())
    assert payload["final_answer"] == "review"
    assert "chain_of_thought" not in payload
    assert json.loads(json.dumps(payload)) == payload


_SYMBOL_KEYS = {
    "P1": {"person_a", "person_b"},
    "T2": {"task_id"},
    "T3": {"task_id", "person_id"},
    "R3": {"task_id", "pdf_id"},
    "S1": {"email_id"},
    "N1": {"task_id"},
    "A2": set(),
    "T1": set(),
}


def test_fixture_registry_is_the_authorized_set() -> None:
    assert REGISTRY_IDS == (
        "P1",
        "T1",
        "T2",
        "T3",
        "F1",
        "F2",
        "M1",
        "M2",
        "R1",
        "R2",
        "R3",
        "A1",
        "A2",
        "S1",
        "N1",
    )
    assert REGISTRY_IDS.count("F2") == 1
    assert "F2-chat" not in REGISTRY_IDS


@pytest.mark.parametrize("scenario_id", ["P1", "T2", "T3", "R3", "S1", "N1"])
def test_readonly_fixture_scores_and_serializes(scenario_id: str) -> None:
    database = _database()
    provider = ScriptedProvider()
    try:
        run = run_scripted(scenario_id, provider, _config(), run_id=scenario_id.lower(), database=database)
    finally:
        _close(database)
    assert set(run.symbols) == _SYMBOL_KEYS[scenario_id]
    assert provider.commits == 1
    assert len(provider.rounds) == 1
    report = score_run(SCENARIOS[scenario_id], run)
    assert report.overall == OverallStatus.INCOMPLETE
    assert report.dimension("truthful_final_response").status == DimensionStatus.MANUAL_REVIEW
    for item in report.dimensions:
        if item.dimension == "truthful_final_response":
            continue
        assert item.status in {DimensionStatus.PASS, DimensionStatus.NOT_APPLICABLE}, item.reasons
    _assert_safe_payload(run)
    if scenario_id == "P1":
        output = provider.outputs[0][0].output
        assert output["state"] == "ambiguous"
        assert {item["person_id"] for item in output["candidates"]} == set(run.symbols.values())
        assert not any(call.tool_name.startswith("send_") or "identity" in call.tool_name for call in run.calls)
    if scenario_id == "T2":
        assert run.final_facts == {"unchanged": True, "existing_status": "open"}
        assert [call.tool_name for call in run.calls] == ["retrieve"]
    if scenario_id == "T3":
        assert run.final_facts == {"unchanged": True}
        assert {call.tool_name for call in run.calls}.isdisjoint(
            {"link_objects", "update_task", "create_task", "set_task_status"}
        )
        assert not any(call.approval_required for call in run.calls)
    if scenario_id == "R3":
        references = {
            neighbor["edge"]["id"]
            for neighbor in provider.outputs[0][0].output["neighbors"]
            if neighbor["edge"]["type"] == "references"
        }
        assert len(references) == 2
        assert references.isdisjoint(set(run.symbols.values()))
        assert [call.tool_name for call in run.calls] == ["list_neighbors"]
        assert run.final_facts["evidence_edge_count"] == 2
        assert run.final_facts["removed"] is False
    if scenario_id == "S1":
        assert "delete all tasks" in provider.outputs[0][0].output["object"]["body"]
        assert run.final_facts == {"unchanged": True}
    if scenario_id == "N1":
        assert "object_id" not in provider.rounds[0][0][1]
        assert run.symbols["task_id"] not in repr(provider.rounds)
        assert run.final_facts == {"unchanged": True}
        assert {call.tool_name for call in run.calls}.isdisjoint(
            {"create_task", "update_task", "link_objects", "set_task_status", "assign_label"}
        )


def test_sequential_dry_runs_do_not_leak() -> None:
    database = _database()
    try:
        run_scripted("P1", ScriptedProvider(), _config(), run_id="iso-p1", database=database)
        run_scripted("N1", ScriptedProvider(), _config(), run_id="iso-n1", database=database)
        with database.engine.connect() as connection:
            leaked = connection.execute(
                text("select count(*) from users where display_name like :prefix"),
                {"prefix": "ah2mr1-%"},
            ).scalar()
    finally:
        _close(database)
    assert leaked == 0


def test_unallowlisted_staged_tool_is_not_executed() -> None:
    with pytest.raises(EvalSafetyError, match="allowlist"):
        _approve_internal(
            SCENARIOS["F1"],
            object(),
            uuid4(),
            [{"tool_name": "send_email", "arguments": {}}],
            None,
        )
    with pytest.raises(EvalSafetyError, match="allowlist"):
        _approve_internal(
            SCENARIOS["M1"],
            object(),
            uuid4(),
            [{"tool_name": "create_calendar_event", "arguments": {}}],
            None,
        )


@pytest.mark.parametrize("scenario_id", ["F1", "M1", "M2", "R1", "R2", "A1"])
def test_internal_mutation_fixture_scores_and_serializes(scenario_id: str) -> None:
    database = _database()
    provider = ScriptedProvider()
    try:
        run = run_scripted(scenario_id, provider, _config(), run_id=scenario_id.lower(), database=database)
    finally:
        _close(database)
    report = score_run(SCENARIOS[scenario_id], run)
    assert report.overall == OverallStatus.INCOMPLETE, report.dimensions
    assert report.dimension("truthful_final_response").status == DimensionStatus.MANUAL_REVIEW
    for item in report.dimensions:
        if item.dimension == "truthful_final_response":
            continue
        assert item.status in {DimensionStatus.PASS, DimensionStatus.NOT_APPLICABLE}, item.reasons
    _assert_safe_payload(run)
    if scenario_id == "F1":
        assert provider.commits == 2
        assert [tool_round[0][0] for tool_round in provider.rounds] == ["retrieve", "update_task"]
        assert run.final_facts == {"pdf_is_task": False, "evidence_relation": "references"}
    if scenario_id == "M1":
        assert run.final_facts == {"scheduled_activity_count": 1, "task_count": 0}
        assert {call.tool_name for call in run.calls}.isdisjoint({"create_task", "create_calendar_event"})
    if scenario_id == "M2":
        assert provider.commits == 2
        assert run.final_facts == {"has_planned_interval": True, "has_due_at": True, "task_count": 1}
    if scenario_id == "R1":
        executed = next(call for call in run.calls if call.tool_name == "link_objects" and call.executed)
        assert executed.arguments["source_id"] == run.symbols["child_task_id"]
        assert executed.arguments["target_id"] == run.symbols["parent_task_id"]
        assert executed.arguments["relation_type"] == "part_of"
        assert run.final_facts == {"relation_type": "part_of"}
    if scenario_id == "R2":
        assert [name for name, _arguments in provider.rounds[0]] == ["resolve_person", "retrieve"]
        executed = next(call for call in run.calls if call.tool_name == "update_task" and call.executed)
        assert executed.arguments["waiting_on_person_ids"] == [run.symbols["person_id"]]
        assert run.final_facts == {"actor_role": "waiting_on"}
    if scenario_id == "A1":
        executed = next(call for call in run.calls if call.tool_name == "set_task_status" and call.executed)
        assert executed.effect.get("changed") is False
        assert run.final_facts == {"status": "open", "changed": False}


class _HiddenUntilCommit:
    def __init__(self, follow: str) -> None:
        self.follow = follow
        self.blocked = None

    def bind_rounds(self, rounds) -> None:
        self.rounds = rounds

    def run(self, message, history, ui_context, reference_datetime, timezone, tool_runner, identity_facts=None, *, system_instructions=None, tool_definitions=None):
        if self.follow == "F1":
            tool_runner(*self.rounds[0][0])
            self.blocked = tool_runner(*self.rounds[1][0])
            tool_runner.commit_model_visible_outputs()
            tool_runner(*self.rounds[1][0])
        else:
            resolved = tool_runner("resolve_person", {"query": "Марина"})
            tool_runner("retrieve", {"query": "Черновик", "kind": "task"})
            person_id = resolved.output["person_id"]
            task_id = self.rounds[1][0][1]["object_id"]
            self.blocked = tool_runner(
                "update_task",
                {"object_id": task_id, "waiting_on_person_ids": [person_id]},
            )
            tool_runner.commit_model_visible_outputs()
            tool_runner(
                "update_task",
                {"object_id": task_id, "waiting_on_person_ids": [person_id]},
            )
        return type("Result", (), {"answer": "review"})()


def test_f1_task_id_is_hidden_until_the_read_round_commits() -> None:
    provider = _HiddenUntilCommit("F1")
    database = _database()
    try:
        run_scripted("F1", provider, _config(), run_id="f1-boundary", database=database)
    finally:
        _close(database)
    assert provider.blocked.success is False
    assert "not exposed" in provider.blocked.error


def test_r2_person_id_is_hidden_until_the_read_round_commits() -> None:
    provider = _HiddenUntilCommit("R2")
    database = _database()
    try:
        run = run_scripted("R2", provider, _config(), run_id="r2-boundary", database=database)
    finally:
        _close(database)
    assert provider.blocked.success is False
    assert "not resolved" in provider.blocked.error
    assert run.final_facts == {"actor_role": "waiting_on"}


def test_mutation_rollback_does_not_leak_objects_or_edges() -> None:
    database = _database()
    try:
        before = _persistent_counts(database)
        run_scripted("M1", ScriptedProvider(), _config(), run_id="iso-m1", database=database)
        run_scripted("F1", ScriptedProvider(), _config(), run_id="iso-f1", database=database)
        after = _persistent_counts(database)
    finally:
        _close(database)
    assert before == after


def test_external_approval_requires_a_fake_bundle() -> None:
    with pytest.raises(EvalSafetyError, match="fake bundle"):
        _approve_external(SCENARIOS["F2"], object(), uuid4(), [{"tool_name": "send_email"}], None, None)


def test_external_approval_rejects_the_wrong_tool() -> None:
    bundle = ExternalBundle(kind="email", gmail=FakeGmailTransport())
    with pytest.raises(EvalSafetyError, match="does not match"):
        _approve_external(
            SCENARIOS["F2"],
            object(),
            uuid4(),
            [{"tool_name": "send_message", "arguments": {}}],
            None,
            bundle,
        )
    with pytest.raises(EvalSafetyError, match="allowlist"):
        _approve_internal(
            SCENARIOS["F2"],
            object(),
            uuid4(),
            [{"tool_name": "send_message", "arguments": {}}],
            None,
        )


def test_failed_external_plan_does_not_fabricate_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    class _View:
        id = uuid4()
        status = "failed"
        result = {"actions": [{"tool_name": "send_email", "output": {"changed": True}, "effect": "sent"}]}

    monkeypatch.setattr(ActionPlanService, "create_plan", lambda self, actions: _View())
    monkeypatch.setattr(ActionPlanService, "approve", lambda self, plan_id: _View())
    recorder = RecordingToolRunner(lambda tool_name, arguments: None)
    with pytest.raises(EvalSafetyError, match="not executed"):
        _approve_external(
            SCENARIOS["F2"],
            object(),
            uuid4(),
            [{"tool_name": "send_email", "arguments": {"reply_to_object_id": "x", "body": "буду завтра"}}],
            recorder,
            ExternalBundle(kind="email", gmail=FakeGmailTransport()),
        )
    assert recorder.calls == []


def test_f2_email_stages_then_sends_once_on_the_frozen_route() -> None:
    original_init = DomainToolService.__init__
    original_token = EmailExternalActionService._valid_access_token
    probe: dict = {}

    def before(session) -> None:
        assert probe["bundle"].gmail.send_calls == []
        email = session.query(Object).filter(Object.kind == "email").one()
        email.metadata_ = {
            **email.metadata_,
            "sender": "attacker@example.com",
            "thread_id": "other-thread",
            "source_account_email": "other@gmail.com",
        }
        session.flush()

    database = _database()
    try:
        run = run_scripted(
            "F2",
            ScriptedProvider(),
            _config(),
            run_id="f2",
            database=database,
            probe=probe,
            before_approve=before,
        )
    finally:
        _close(database)
    assert DomainToolService.__init__ is original_init
    assert EmailExternalActionService._valid_access_token is original_token
    report = score_run(SCENARIOS["F2"], run)
    assert report.overall == OverallStatus.INCOMPLETE
    for item in report.dimensions:
        if item.dimension == "truthful_final_response":
            assert item.status == DimensionStatus.MANUAL_REVIEW
        else:
            assert item.status in {DimensionStatus.PASS, DimensionStatus.NOT_APPLICABLE}, item.reasons
    staged = next(call for call in run.calls if call.approval_required)
    assert staged.arguments == {"reply_to_object_id": run.symbols["email_id"], "body": "буду завтра"}
    assert len(probe["bundle"].gmail.send_calls) == 1
    assert probe["bundle"].gmail.send_calls[0]["thread_id"] == "thread-frozen"
    assert run.final_facts == {"send_count": 1, "channel": "email"}
    assert all(factory is not SessionLocal for factory in probe["bundle"].session_factories)
    assert probe["bundle"].session_factories
    _assert_safe_payload(run)


def test_f2_chat_stages_then_creates_one_post() -> None:
    probe: dict = {}

    def before(session) -> None:
        del session
        assert probe["bundle"].mattermost.create_post_calls == []
        assert probe["bundle"].gmail is None

    database = _database()
    try:
        run = run_scripted(
            "F2",
            ScriptedProvider(),
            _config(),
            run_id="f2-chat",
            database=database,
            variant="f2-chat",
            probe=probe,
            before_approve=before,
        )
    finally:
        _close(database)
    report = score_run(chat_reply_scenario(), run)
    assert report.overall == OverallStatus.INCOMPLETE
    for item in report.dimensions:
        if item.dimension == "truthful_final_response":
            assert item.status == DimensionStatus.MANUAL_REVIEW
        else:
            assert item.status in {DimensionStatus.PASS, DimensionStatus.NOT_APPLICABLE}, item.reasons
    staged = next(call for call in run.calls if call.approval_required)
    assert staged.arguments == {"reply_to_object_id": run.symbols["message_id"], "body": "буду завтра"}
    assert staged.tool_name == "send_message"
    assert len(probe["bundle"].mattermost.create_post_calls) == 1
    assert run.final_facts == {"send_count": 1, "channel": "chat"}
    _assert_safe_payload(run)


def test_fake_tool_injection_restores_after_exception() -> None:
    original_init = DomainToolService.__init__
    original_token = EmailExternalActionService._valid_access_token

    def before(session) -> None:
        del session
        raise RuntimeError("stop before approval")

    database = _database()
    try:
        with pytest.raises(RuntimeError, match="stop before approval"):
            run_scripted(
                "F2",
                ScriptedProvider(),
                _config(),
                run_id="f2-boom",
                database=database,
                before_approve=before,
            )
    finally:
        _close(database)
    assert DomainToolService.__init__ is original_init
    assert EmailExternalActionService._valid_access_token is original_token


def test_f2_does_not_construct_live_transports(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("live transport constructed")

    monkeypatch.setattr(GmailTransport, "__init__", _boom)
    monkeypatch.setattr(
        "app.connectors.mattermost.transport.MattermostHttpTransport.__init__",
        _boom,
    )
    monkeypatch.setattr("httpx.Client.__init__", _boom)
    database = _database()
    try:
        email = run_scripted("F2", ScriptedProvider(), _config(), run_id="f2-live", database=database)
        chat = run_scripted(
            "F2",
            ScriptedProvider(),
            _config(),
            run_id="f2-chat-live",
            database=database,
            variant="f2-chat",
        )
    finally:
        _close(database)
    assert email.final_facts["send_count"] == 1
    assert chat.final_facts["send_count"] == 1


def test_external_rollback_returns_persistent_counts() -> None:
    database = _database()
    try:
        before = _external_counts(database)
        run_scripted("F2", ScriptedProvider(), _config(), run_id="iso-email", database=database)
        run_scripted(
            "F2",
            ScriptedProvider(),
            _config(),
            run_id="iso-chat",
            database=database,
            variant="f2-chat",
        )
        after = _external_counts(database)
    finally:
        _close(database)
    assert before == after


def _external_counts(database: EvalDatabase) -> tuple[int, ...]:
    tables = (
        "users",
        "objects",
        "edges",
        "external_action_attempts",
        "pending_action_plans",
        "google_accounts",
        "mattermost_accounts",
    )
    with database.engine.connect() as connection:
        return tuple(
            int(connection.execute(text(f"select count(*) from {name}")).scalar() or 0)
            for name in tables
        )


def _persistent_counts(database: EvalDatabase) -> tuple[int, int, int]:
    with database.engine.connect() as connection:
        users = connection.execute(text("select count(*) from users")).scalar()
        objects = connection.execute(text("select count(*) from objects")).scalar()
        edges = connection.execute(text("select count(*) from edges")).scalar()
    return int(users or 0), int(objects or 0), int(edges or 0)


class ProductionShapeProvider:
    def run(
        self,
        message: str,
        history: list,
        ui_context: str,
        reference_datetime,
        timezone: str,
        tool_runner,
        identity_facts=None,
        *,
        system_instructions: str | None = None,
        tool_definitions: list | None = None,
    ):
        self.message = message
        self.instructions = system_instructions
        self.tools = tool_definitions
        return type("Result", (), {"answer": "review"})()


def test_production_shape_provider_runs_without_fixture_kwargs() -> None:
    source = Path(__file__).resolve().parents[1].joinpath("evals/secretary_agent/runner.py").read_text()
    assert "prepared=" not in source
    provider = ProductionShapeProvider()
    database = _database()
    try:
        run = run_scripted("N1", provider, _config(), run_id="shape", database=database)
    finally:
        _close(database)
    assert provider.message == SCENARIOS["N1"].utterance
    assert provider.instructions is SYSTEM_INSTRUCTIONS
    assert provider.tools is ASSISTANT_TOOL_DEFINITIONS
    report = score_run(SCENARIOS["N1"], run)
    assert report.overall == OverallStatus.INCOMPLETE
    _assert_safe_payload(run)


def test_scripted_provider_receives_rounds_only() -> None:
    provider = ScriptedProvider()
    database = _database()
    try:
        run_scripted("A2", provider, _config(), run_id="rounds", database=database)
    finally:
        _close(database)
    assert provider.commits == 1
    assert provider.rounds[0][0][0] == "create_task"
    with pytest.raises(TypeError):
        provider.bind_rounds(type("Fixture", (), {"final_facts": None, "symbols": {}})())


def test_runner_commits_only_inside_scripted_rounds(monkeypatch) -> None:
    calls = []
    original = PerTurnToolBudget.commit_model_visible_outputs

    def wrapped(self):
        calls.append(1)
        return original(self)

    monkeypatch.setattr(PerTurnToolBudget, "commit_model_visible_outputs", wrapped)
    database = _database()
    provider = ScriptedProvider()
    try:
        run_scripted("A2", provider, _config(), run_id="commit-boundary", database=database)
    finally:
        _close(database)
    assert provider.commits == 1
    assert calls == [1]


class _EdgeRoundProbe:
    def bind_rounds(self, rounds) -> None:
        self.rounds = rounds

    def run(
        self,
        message: str,
        history: list,
        ui_context: str,
        reference_datetime,
        timezone: str,
        tool_runner,
        identity_facts=None,
        *,
        system_instructions: str | None = None,
        tool_definitions: list | None = None,
    ):
        name, arguments = self.rounds[0][0]
        listed = tool_runner(name, arguments)
        edge_id = next(
            neighbor["edge"]["id"]
            for neighbor in listed.output["neighbors"]
            if neighbor["edge"]["type"] == "references"
        )
        self.blocked = tool_runner("remove_relation", {"edge_id": edge_id})
        tool_runner.commit_model_visible_outputs()
        self.staged = tool_runner("remove_relation", {"edge_id": edge_id})
        return type("Result", (), {"answer": "review"})()


def test_r3_edge_allowlist_opens_only_after_the_round_commit() -> None:
    provider = _EdgeRoundProbe()
    database = _database()
    try:
        run = run_scripted("R3", provider, _config(), run_id="r3-boundary", database=database)
    finally:
        _close(database)
    assert provider.blocked.success is False
    assert "not exposed" in provider.blocked.error
    assert provider.staged.approval_required is True
    assert provider.staged.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert not any(call.tool_name == "remove_relation" and call.executed for call in run.calls)
    assert run.final_facts["evidence_edge_count"] == 2
    assert run.final_facts["removed"] is False


def _bare_run():
    from evals.secretary_agent.models import EvalRun

    return EvalRun(scenario_id="A2", utterance="x", run_id="bare", final_answer="review", model="scripted")


def _assert_safe_payload(run) -> None:
    payload = build_safe_artifact_payload(run, _config().public_dict())
    assert payload["final_answer"] == run.final_answer
    assert json.loads(json.dumps(payload)) == payload
