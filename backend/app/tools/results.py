"""Structured tool execution outcomes."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolExecutionStatus(str, Enum):
    SUCCESS = "success"
    TOOL_ERROR = "tool_error"
    EXECUTION_FAILED = "execution_failed"
    LIMIT_REACHED = "limit_reached"
    APPROVAL_REQUIRED = "approval_required"
    POLICY_DENIED = "policy_denied"
    UNKNOWN_TOOL = "unknown_tool"


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool
    tool_name: str
    output: dict[str, Any] | None = None
    error: str | None = None
    limit_reached: bool = False
    approval_required: bool = False
    policy_denied: bool = False
    status: ToolExecutionStatus = ToolExecutionStatus.SUCCESS
    model_output_json: str | None = None
    model_visible_payload: dict[str, Any] | None = None
    staged_action: dict[str, Any] | None = None
    raw_output: Any = Field(default=None, exclude=True)
    validated_arguments: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _status_matches_success(self) -> "ToolExecutionResult":
        if self.success and self.status != ToolExecutionStatus.SUCCESS:
            raise ValueError("success=True requires status=SUCCESS")
        if not self.success and self.status == ToolExecutionStatus.SUCCESS:
            raise ValueError("success=False requires status other than SUCCESS")
        return self
