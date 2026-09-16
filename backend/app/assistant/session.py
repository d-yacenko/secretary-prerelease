from typing import Any
from uuid import UUID

from app.assistant.execution_effects import (
    classify_tool_execution_effect,
    describe_execution_effect,
)
from app.assistant.tool_args import normalize_assistant_tool_arguments
from app.db.session import SessionLocal
from app.services.domain_tool_service import DomainToolService
from app.services.user_embedding_resolver import (
    EMBEDDING_PROVIDER_UNAVAILABLE,
    resolve_embedding_service_for_user,
)
from app.services.user_openai_credential_errors import UserOpenAICredentialConfigurationError
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.results import ToolExecutionResult, ToolExecutionStatus
from app.tools.schemas import ToolError

_GATEWAY = ToolExecutionGateway()


def run_assistant_tool(user_id: UUID, tool_name: str, arguments: dict) -> ToolExecutionResult:
    """One interactive Assistant tool call: short session, commit on success, rollback on failure."""
    session = SessionLocal()
    try:
        embedding_service = resolve_embedding_service_for_user(session, user_id)
    except UserOpenAICredentialConfigurationError:
        session.close()
        return ToolExecutionResult(
            success=False,
            tool_name=tool_name,
            error=EMBEDDING_PROVIDER_UNAVAILABLE,
            status=ToolExecutionStatus.EXECUTION_FAILED,
        )
    tools = DomainToolService(
        session,
        user_id,
        embedding_service,
        defer_write_embeddings=True,
    )
    try:
        normalized_arguments = normalize_assistant_tool_arguments(tool_name, arguments)
        result = _GATEWAY.execute(
            tools,
            tool_name,
            normalized_arguments,
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        if result.success:
            session.commit()
        elif result.status != ToolExecutionStatus.APPROVAL_REQUIRED:
            session.rollback()
        return result
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return ToolExecutionResult(
            success=False,
            tool_name=tool_name,
            error=f"tool execution failed: {type(exc).__name__}",
            status=ToolExecutionStatus.EXECUTION_FAILED,
        )
    finally:
        session.close()


def execute_approved_actions_with_tools(
    tools: DomainToolService,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Execute frozen plan actions using the caller's DB session (no commit)."""
    action_results: list[dict[str, Any]] = []
    for action in actions:
        tool_name = action["tool_name"]
        arguments = action["arguments"]
        result = _GATEWAY.execute(
            tools,
            tool_name,
            arguments,
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        if not result.success:
            raise ToolError(result.error or "action plan execution failed")
        action_results.append(
            {
                "tool_name": tool_name,
                "success": True,
                "output": result.output,
                "effect": classify_tool_execution_effect(tool_name, result.output),
                "effect_description": describe_execution_effect(tool_name, result.output),
            }
        )
    return {"actions": action_results}
