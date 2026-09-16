"""Deterministic tool permission policy for Secretary domain tools."""

from enum import Enum

from app.tools.execution_context import ExecutionContext


class ToolPermission(str, Enum):
    READ = "READ"
    # Low-risk, local, reversible semantic annotation of existing Secretary data
    # (e.g. assigning/removing an existing label). Still a mutation: audited,
    # counted, ownership-validated; never a provider write, never READ.
    ANNOTATE = "ANNOTATE"
    INTERNAL_WRITE = "INTERNAL_WRITE"
    DESTRUCTIVE_INTERNAL_WRITE = "DESTRUCTIVE_INTERNAL_WRITE"
    EXTERNAL_PROPOSE = "EXTERNAL_PROPOSE"
    EXTERNAL_WRITE = "EXTERNAL_WRITE"
    COMMUNICATE = "COMMUNICATE"


class PolicyDecision(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


def evaluate_policy(
    permission: ToolPermission,
    context: ExecutionContext = ExecutionContext.BASELINE,
) -> PolicyDecision:
    if context == ExecutionContext.APPROVED_ACTION_PLAN:
        if permission in (
            ToolPermission.READ,
            ToolPermission.ANNOTATE,
            ToolPermission.INTERNAL_WRITE,
            ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
            ToolPermission.EXTERNAL_PROPOSE,
            ToolPermission.EXTERNAL_WRITE,
            ToolPermission.COMMUNICATE,
        ):
            return PolicyDecision.ALLOW
        return PolicyDecision.DENY

    if context == ExecutionContext.INTERACTIVE_ASSISTANT:
        if permission in (ToolPermission.READ, ToolPermission.ANNOTATE):
            return PolicyDecision.ALLOW
        if permission in (
            ToolPermission.INTERNAL_WRITE,
            ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
        ):
            return PolicyDecision.REQUIRE_APPROVAL
        if permission == ToolPermission.EXTERNAL_PROPOSE:
            return PolicyDecision.ALLOW
        if permission in (
            ToolPermission.EXTERNAL_WRITE,
            ToolPermission.COMMUNICATE,
        ):
            return PolicyDecision.REQUIRE_APPROVAL
        return PolicyDecision.DENY

    if context == ExecutionContext.MCP:
        if permission == ToolPermission.READ:
            return PolicyDecision.ALLOW
        if permission == ToolPermission.EXTERNAL_PROPOSE:
            return PolicyDecision.ALLOW
        # MCP has no trusted approval transport: ANNOTATE fails closed here.
        if permission in (
            ToolPermission.ANNOTATE,
            ToolPermission.INTERNAL_WRITE,
            ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
            ToolPermission.EXTERNAL_WRITE,
            ToolPermission.COMMUNICATE,
        ):
            return PolicyDecision.REQUIRE_APPROVAL
        return PolicyDecision.DENY

    # BASELINE / SYSTEM
    if permission in (
        ToolPermission.READ,
        ToolPermission.ANNOTATE,
        ToolPermission.INTERNAL_WRITE,
        ToolPermission.EXTERNAL_PROPOSE,
    ):
        return PolicyDecision.ALLOW
    if permission in (
        ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
        ToolPermission.EXTERNAL_WRITE,
        ToolPermission.COMMUNICATE,
    ):
        return PolicyDecision.REQUIRE_APPROVAL
    return PolicyDecision.DENY


def policy_block_message(decision: PolicyDecision) -> str:
    if decision == PolicyDecision.REQUIRE_APPROVAL:
        return "tool execution requires approval"
    return "tool execution denied by policy"
