from collections.abc import Sequence
from uuid import UUID

from app.assistant.reference_ids import collect_seen_object_ids_from_bounded_tool
from app.assistant.tool_output import serialize_tool_output_for_assistant
from app.proactive.constants import PROACTIVE_MAX_TOOL_CALLS, PROACTIVE_READ_TOOL_NAMES
from app.services.domain_tool_service import DomainToolService
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.results import ToolExecutionResult, ToolExecutionStatus

_ALLOWED_TOOLS = frozenset(PROACTIVE_READ_TOOL_NAMES)
_REJECTED_TOOL_ERROR = "proactive review cannot execute this tool"


class ProactiveToolRunner:
    """Read-only tool runner with a hard allowlist independent of the prompt."""

    def __init__(
        self,
        tools: DomainToolService,
        *,
        max_calls: int = PROACTIVE_MAX_TOOL_CALLS,
        initial_seen_object_ids: Sequence[UUID] | None = None,
        gateway: ToolExecutionGateway | None = None,
    ) -> None:
        self._tools = tools
        self._max_calls = max_calls
        self._calls = 0
        self._seen_object_ids: set[UUID] = set(initial_seen_object_ids or [])
        self._pending_seen_object_ids: set[UUID] = set()
        self._gateway = gateway or ToolExecutionGateway()
        self.rejected_tool_names: list[str] = []

    @property
    def calls_made(self) -> int:
        return self._calls

    @property
    def security_violation(self) -> bool:
        return bool(self.rejected_tool_names)

    @property
    def has_rejected_tool_attempt(self) -> bool:
        return self.security_violation

    @property
    def seen_object_ids(self) -> set[UUID]:
        return set(self._seen_object_ids) | set(self._pending_seen_object_ids)

    def seed_seen_object_ids(self, object_ids: Sequence[UUID]) -> None:
        self._seen_object_ids.update(object_ids)

    def commit_model_visible_outputs(self) -> None:
        self._seen_object_ids.update(self._pending_seen_object_ids)
        self._pending_seen_object_ids.clear()

    def __call__(self, tool_name: str, arguments: dict) -> ToolExecutionResult:
        if self._calls >= self._max_calls:
            if tool_name not in _ALLOWED_TOOLS:
                self.rejected_tool_names.append(tool_name)
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="tool call limit reached",
                limit_reached=True,
                status=ToolExecutionStatus.LIMIT_REACHED,
            )
        self._calls += 1
        if tool_name not in _ALLOWED_TOOLS:
            self.rejected_tool_names.append(tool_name)
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error=_REJECTED_TOOL_ERROR,
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        result = self._gateway.execute(
            self._tools,
            tool_name,
            arguments,
            context=ExecutionContext.BASELINE,
        )
        if result.success and result.output:
            model_output = serialize_tool_output_for_assistant(tool_name, result.output)
            result.model_output_json = model_output.model_output_json
            result.model_visible_payload = model_output.model_visible_payload
            self._pending_seen_object_ids.update(
                collect_seen_object_ids_from_bounded_tool(
                    tool_name, model_output.model_visible_payload
                )
            )
        return result
