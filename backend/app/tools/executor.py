from typing import Any

from pydantic import BaseModel

from app.services.domain_tool_service import DomainToolService
from app.tools.gateway import ToolExecutionGateway
from app.tools.results import ToolExecutionResult, ToolExecutionStatus
from app.tools.schemas import ToolError

DEFAULT_MAX_TOOL_CALLS = 5

_DEFAULT_GATEWAY = ToolExecutionGateway()


class ToolExecutor:
    def __init__(
        self,
        tools: DomainToolService,
        max_calls: int = DEFAULT_MAX_TOOL_CALLS,
        gateway: ToolExecutionGateway | None = None,
    ) -> None:
        self._tools = tools
        self._max_calls = max_calls
        self._calls = 0
        self._gateway = gateway or _DEFAULT_GATEWAY

    @property
    def calls_made(self) -> int:
        return self._calls

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        if self._calls >= self._max_calls:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="tool call limit reached",
                limit_reached=True,
                status=ToolExecutionStatus.LIMIT_REACHED,
            )
        self._calls += 1
        return self._gateway.execute(self._tools, tool_name, arguments)


def _dispatch(tools: DomainToolService, tool_name: str, arguments: dict[str, Any]) -> BaseModel:
    """Backward-compatible dispatch for tests; routes through the gateway."""
    result = _DEFAULT_GATEWAY.execute(tools, tool_name, arguments)
    if result.status == ToolExecutionStatus.UNKNOWN_TOOL:
        raise ToolError(f"unknown tool: {tool_name}")
    if not result.success:
        raise ToolError(result.error or "tool execution failed")
    if result.raw_output is None:
        raise ToolError("tool execution failed: missing output")
    return result.raw_output
