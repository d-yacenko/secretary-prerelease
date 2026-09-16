"""Execute MCP tools through the canonical ToolExecutionGateway."""

from pydantic import BaseModel

from app.mcp.session import tool_session
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import ToolError


def execute_mcp_tool(tool_name: str, arguments: dict) -> BaseModel:
    with tool_session() as tools:
        gateway = ToolExecutionGateway()
        result = gateway.execute(
            tools,
            tool_name,
            arguments,
            context=ExecutionContext.MCP,
        )
        if result.status == ToolExecutionStatus.APPROVAL_REQUIRED:
            raise ToolError("tool execution requires approval")
        if result.status == ToolExecutionStatus.POLICY_DENIED:
            raise ToolError(result.error or "tool execution denied by policy")
        if not result.success:
            raise ToolError(result.error or "tool execution failed")
        if result.raw_output is None:
            raise ToolError("tool execution returned no output")
        return result.raw_output
