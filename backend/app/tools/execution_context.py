"""Deterministic tool execution contexts for policy evaluation."""

from enum import Enum


class ExecutionContext(str, Enum):
    BASELINE = "BASELINE"
    INTERACTIVE_ASSISTANT = "INTERACTIVE_ASSISTANT"
    APPROVED_ACTION_PLAN = "APPROVED_ACTION_PLAN"
    MCP = "MCP"
