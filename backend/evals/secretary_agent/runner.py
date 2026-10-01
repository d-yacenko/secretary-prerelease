"""Eval-only AH2-MR1 runner. Scripted providers make no model call."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.assistant.tool_args import normalize_assistant_tool_arguments
from app.assistant.tool_runner import BoundAssistantToolRunner, PerTurnToolBudget
from app.db.models import User
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.openai_assistant_provider import SYSTEM_INSTRUCTIONS
from app.services.action_plan_service import ActionPlanService
from app.services.domain_tool_service import DomainToolService
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.registry import ASSISTANT_TOOL_DEFINITIONS
from app.tools.results import ToolExecutionStatus
from evals.secretary_agent.catalog import SCENARIOS, chat_reply_scenario
from evals.secretary_agent.external import ExternalBundle, external_settings, inject_fake_tools
from evals.secretary_agent.fixtures import REGISTRY_IDS, prepare_fixture
from evals.secretary_agent.models import EvalRun, ToolCallRecord
from evals.secretary_agent.recording import RecordingToolRunner
from evals.secretary_agent.safety import (
    EvalSafetyError,
    assert_dry_run_transports,
    assert_eval_database,
)

REFERENCE_DATETIME = datetime.fromisoformat("2026-10-01T12:00:00+02:00")
REFERENCE_TIMEZONE = "Europe/Amsterdam"
_GATEWAY = ToolExecutionGateway()
_DRY_RUNS = frozenset(REGISTRY_IDS)


class EvalProvider(Protocol):
    def run(
        self,
        message: str,
        history: list,
        ui_context: str,
        reference_datetime: datetime,
        timezone: str,
        tool_runner,
        identity_facts=None,
        *,
        system_instructions: str | None = None,
        tool_definitions: list | None = None,
    ): ...


@dataclass(frozen=True)
class EvalConfig:
    model: str
    reasoning_effort: str
    verbosity: str
    max_rounds: int
    max_output_tokens: int
    reference_datetime: datetime = REFERENCE_DATETIME
    timezone: str = REFERENCE_TIMEZONE
    mode: str = "scripted"

    def public_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "verbosity": self.verbosity,
            "max_rounds": self.max_rounds,
            "max_output_tokens": self.max_output_tokens,
            "reference_datetime": self.reference_datetime.isoformat(),
            "timezone": self.timezone,
            "mode": self.mode,
            "system_instructions": "imported",
            "tool_definitions": len(ASSISTANT_TOOL_DEFINITIONS),
            "instructions_chars": len(SYSTEM_INSTRUCTIONS),
        }


def production_contract() -> tuple[str, list[dict]]:
    return SYSTEM_INSTRUCTIONS, ASSISTANT_TOOL_DEFINITIONS


@dataclass(frozen=True)
class EvalDatabase:
    engine: Engine
    disposable: bool


def run_scripted(
    scenario_id: str,
    provider: EvalProvider,
    config: EvalConfig,
    *,
    run_id: str,
    database: EvalDatabase,
    variant: str | None = None,
    probe: dict | None = None,
    before_approve: Callable[[Session], None] | None = None,
) -> EvalRun:
    if scenario_id not in _DRY_RUNS:
        raise EvalSafetyError("scripted dry runs are limited to the fixture registry")
    if variant not in {None, "f2-chat"}:
        raise EvalSafetyError("unknown eval variant")
    if variant == "f2-chat" and scenario_id != "F2":
        raise EvalSafetyError("f2-chat variant is only valid for F2")
    assert_eval_database(database.engine, disposable=database.disposable)
    assert_dry_run_transports(())
    scenario = chat_reply_scenario() if variant == "f2-chat" else SCENARIOS[scenario_id]
    fixture_id = "F2-chat" if variant == "f2-chat" else scenario_id
    connection = database.engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        user = User(id=uuid4(), display_name=f"ah2mr1-{scenario_id}-{uuid4().hex[:8]}")
        session.add(user)
        session.flush()
        settings_cm = external_settings() if scenario_id == "F2" else nullcontext()
        with settings_cm:
            prepared = prepare_fixture(fixture_id, session, user.id)
            injection = (
                inject_fake_tools(prepared.external, connection)
                if prepared.external is not None
                else nullcontext()
            )
            with injection:
                with _bound_local_tool(session):
                    budget = PerTurnToolBudget(initial_seen_object_ids=prepared.initial_object_ids)
                    recorder = RecordingToolRunner(BoundAssistantToolRunner(budget, user.id))
                    bind_rounds = getattr(provider, "bind_rounds", None)
                    if bind_rounds is not None:
                        bind_rounds(prepared.rounds)
                    result = provider.run(
                        message=scenario.utterance,
                        history=[],
                        ui_context=prepared.ui_context,
                        reference_datetime=config.reference_datetime,
                        timezone=config.timezone,
                        tool_runner=recorder,
                        identity_facts=None,
                        system_instructions=SYSTEM_INSTRUCTIONS,
                        tool_definitions=ASSISTANT_TOOL_DEFINITIONS,
                    )
                    if probe is not None:
                        probe["bundle"] = prepared.external
                    if before_approve is not None:
                        before_approve(session)
                    if prepared.external is not None:
                        _approve_external(
                            scenario,
                            session,
                            user.id,
                            budget.staged_actions,
                            recorder,
                            prepared.external,
                        )
                    else:
                        _approve_internal(scenario, session, user.id, budget.staged_actions, recorder)
                    session.expire_all()
                    facts = prepared.final_facts(session)
        return EvalRun(
            scenario_id=scenario.id,
            utterance=scenario.utterance,
            run_id=run_id,
            calls=list(recorder.calls),
            symbols=dict(prepared.symbols),
            final_facts=facts,
            final_answer=str(getattr(result, "answer", "") or ""),
            model=config.model,
        )
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


_INTERNAL_APPROVAL_TOOLS = frozenset(
    {
        "create_task",
        "update_task",
        "link_objects",
        "create_scheduled_activity",
        "set_task_status",
    }
)
_EXECUTE_MODES = frozenset({"staged_then_executed", "staged_then_executed_if_present"})


def _approve_internal(scenario, session: Session, user_id: UUID, actions: list[dict], recorder: RecordingToolRunner) -> None:
    if scenario.approval not in _EXECUTE_MODES:
        return
    if scenario.approval == "staged_then_executed_if_present" and not actions:
        return
    if len(actions) != 1:
        raise EvalSafetyError("eval approval executes exactly one staged action")
    tool_name = str(actions[0].get("tool_name"))
    if tool_name not in _INTERNAL_APPROVAL_TOOLS:
        raise EvalSafetyError("staged tool is outside the eval approval allowlist")
    plan = ActionPlanService(session, user_id).create_plan(actions)
    approved = ActionPlanService(session, user_id).approve(plan.id)
    _append_executed(recorder, approved.result or {}, actions)


_EXTERNAL_TOOLS = {"email": "send_email", "chat": "send_message"}


def _approve_external(
    scenario,
    session: Session,
    user_id: UUID,
    actions: list[dict],
    recorder: RecordingToolRunner,
    bundle: ExternalBundle | None,
) -> None:
    if scenario.id != "F2" or bundle is None or bundle.kind not in _EXTERNAL_TOOLS:
        raise EvalSafetyError("external approval requires an explicit fake bundle")
    if scenario.approval not in _EXECUTE_MODES:
        return
    if len(actions) != 1:
        raise EvalSafetyError("eval approval executes exactly one staged action")
    tool_name = str(actions[0].get("tool_name"))
    if tool_name != _EXTERNAL_TOOLS[bundle.kind]:
        raise EvalSafetyError("staged tool does not match the external eval case")
    plan = ActionPlanService(session, user_id).create_plan(actions)
    approved = ActionPlanService(session, user_id).approve(plan.id)
    if approved.status != "executed" or not approved.result:
        raise EvalSafetyError("action plan was not executed")
    _append_executed(recorder, approved.result, actions, model_arguments=True)


def _append_executed(
    recorder: RecordingToolRunner,
    result: dict,
    staged: list[dict],
    *,
    model_arguments: bool = False,
) -> None:
    arguments = {
        str(action.get("tool_name")): _jsonable(action.get("arguments") or {}) for action in staged
    }
    if model_arguments:
        arguments = {
            call.tool_name: dict(call.arguments)
            for call in recorder.calls
            if call.approval_required and not call.executed
        }
    for action in result.get("actions", []):
        tool_name = str(action.get("tool_name"))
        output = action.get("output") if isinstance(action.get("output"), dict) else {}
        effect: dict[str, Any] = {"kind": action.get("effect")} if isinstance(action.get("effect"), str) else {}
        if isinstance(action.get("effect"), dict):
            effect.update(action["effect"])
        if "changed" in output:
            effect["changed"] = output["changed"]
        recorder.calls.append(
            ToolCallRecord(
                sequence=len(recorder.calls) + 1,
                tool_name=tool_name,
                arguments=arguments.get(tool_name, {}),
                success=True,
                status="success",
                executed=True,
                effect=effect,
            )
        )


class _LocalTool:
    def __init__(self, session: Session) -> None:
        self._session = session

    def __enter__(self) -> None:
        import app.assistant.session as assistant_session

        self._module = assistant_session
        self._original = assistant_session.run_assistant_tool

        def run(user_id: UUID, tool_name: str, arguments: dict):
            tools = DomainToolService(
                self._session,
                user_id,
                FakeEmbeddingService(),
                defer_write_embeddings=True,
            )
            nested = self._session.begin_nested()
            try:
                result = _GATEWAY.execute(
                    tools,
                    tool_name,
                    normalize_assistant_tool_arguments(tool_name, arguments),
                    context=ExecutionContext.INTERACTIVE_ASSISTANT,
                )
                if result.success or result.status == ToolExecutionStatus.APPROVAL_REQUIRED:
                    nested.commit()
                else:
                    nested.rollback()
                return result
            except Exception:
                nested.rollback()
                raise

        assistant_session.run_assistant_tool = run

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._module.run_assistant_tool = self._original


def _bound_local_tool(session: Session) -> _LocalTool:
    return _LocalTool(session)


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
