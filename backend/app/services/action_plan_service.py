"""Persisted frozen action plans for interactive Assistant approval."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.action_plan_constants import (
    MAX_ACTIONS_PER_PLAN,
    PENDING_ACTION_PLAN_STATUS_EXECUTED,
    PENDING_ACTION_PLAN_STATUS_EXPIRED,
    PENDING_ACTION_PLAN_STATUS_FAILED,
    PENDING_ACTION_PLAN_STATUS_PENDING,
    PENDING_ACTION_PLAN_STATUS_REJECTED,
    PENDING_ACTION_PLAN_TTL_SECONDS,
)
from app.assistant.session import execute_approved_actions_with_tools
from app.db.models import PendingActionPlan
from app.services.domain_tool_service import DomainToolService
from app.services.domain_write_mode import DomainWriteMode
from app.services.errors import NotFoundError, ValidationError
from app.tools.policy import ToolPermission
from app.tools.registry import get_tool_spec


@dataclass
class PendingActionPlanView:
    id: UUID
    status: str
    expires_at: datetime
    actions: list[dict[str, Any]]
    result: dict[str, Any] | None = None
    failure: str | None = None


class ActionPlanConflictError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ActionPlanService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def create_plan(self, actions: list[dict[str, Any]]) -> PendingActionPlanView:
        validate_action_plan_actions(actions)

        now = datetime.now(UTC)
        plan = PendingActionPlan(
            user_id=self._user_id,
            status=PENDING_ACTION_PLAN_STATUS_PENDING,
            actions=actions,
            expires_at=now + timedelta(seconds=PENDING_ACTION_PLAN_TTL_SECONDS),
        )
        self._session.add(plan)
        self._session.flush()
        return _to_view(plan)

    def approve(self, plan_id: UUID) -> PendingActionPlanView:
        plan = self._get_owned_plan_for_update(plan_id)
        if plan.status == PENDING_ACTION_PLAN_STATUS_EXECUTED:
            return _to_view(plan)
        if plan.status == PENDING_ACTION_PLAN_STATUS_REJECTED:
            raise ActionPlanConflictError("action plan was rejected")
        if plan.status == PENDING_ACTION_PLAN_STATUS_FAILED:
            return _to_view(plan)
        if plan.status == PENDING_ACTION_PLAN_STATUS_EXPIRED:
            return _to_view(plan)

        now = datetime.now(UTC)
        if plan.expires_at <= now:
            plan.status = PENDING_ACTION_PLAN_STATUS_EXPIRED
            plan.failure = "action plan expired"
            return _to_view(plan)

        if plan.status != PENDING_ACTION_PLAN_STATUS_PENDING:
            raise ActionPlanConflictError("action plan is not pending")

        try:
            validate_action_plan_actions(plan.actions)
        except ValidationError as exc:
            plan.status = PENDING_ACTION_PLAN_STATUS_FAILED
            plan.failure = exc.message
            return _to_view(plan)

        plan.approved_at = now
        tools = DomainToolService(
            self._session,
            self._user_id,
            None,
            defer_write_embeddings=True,
            write_mode=DomainWriteMode.APPROVED_CONFIRMED,
        )
        nested = self._session.begin_nested()
        try:
            execution = execute_approved_actions_with_tools(tools, plan.actions)
            nested.commit()
            plan.status = PENDING_ACTION_PLAN_STATUS_EXECUTED
            plan.executed_at = now
            plan.result = execution
            plan.failure = None
            return _to_view(plan)
        except Exception as exc:  # noqa: BLE001
            nested.rollback()
            plan.status = PENDING_ACTION_PLAN_STATUS_FAILED
            plan.failure = _safe_failure_message(exc)
            return _to_view(plan)

    def get_for_resume(self, plan_id: UUID) -> PendingActionPlanView:
        plan = self._get_owned_plan(plan_id)
        if plan.status != PENDING_ACTION_PLAN_STATUS_EXECUTED:
            raise ActionPlanConflictError("action plan is not executed")
        return _to_view(plan)

    def reject(self, plan_id: UUID) -> PendingActionPlanView:
        plan = self._get_owned_plan_for_update(plan_id)
        if plan.status == PENDING_ACTION_PLAN_STATUS_EXECUTED:
            raise ActionPlanConflictError("action plan already executed")
        if plan.status == PENDING_ACTION_PLAN_STATUS_REJECTED:
            return _to_view(plan)

        now = datetime.now(UTC)
        if plan.expires_at <= now and plan.status == PENDING_ACTION_PLAN_STATUS_PENDING:
            plan.status = PENDING_ACTION_PLAN_STATUS_EXPIRED
            plan.failure = "action plan expired"
            return _to_view(plan)

        if plan.status != PENDING_ACTION_PLAN_STATUS_PENDING:
            raise ActionPlanConflictError("action plan is not pending")

        plan.status = PENDING_ACTION_PLAN_STATUS_REJECTED
        plan.rejected_at = now
        return _to_view(plan)

    def list_recent_terminal_plans(self, limit: int = 8) -> list[PendingActionPlanView]:
        terminal_statuses = (
            PENDING_ACTION_PLAN_STATUS_EXECUTED,
            PENDING_ACTION_PLAN_STATUS_REJECTED,
            PENDING_ACTION_PLAN_STATUS_EXPIRED,
            PENDING_ACTION_PLAN_STATUS_FAILED,
        )
        plans = self._session.scalars(
            select(PendingActionPlan)
            .where(
                PendingActionPlan.user_id == self._user_id,
                PendingActionPlan.status.in_(terminal_statuses),
            )
            .order_by(PendingActionPlan.created_at.desc())
            .limit(limit)
        ).all()
        return [_to_view(plan) for plan in plans]

    def _get_owned_plan(self, plan_id: UUID) -> PendingActionPlan:
        plan = self._session.scalar(
            select(PendingActionPlan).where(
                PendingActionPlan.id == plan_id,
                PendingActionPlan.user_id == self._user_id,
            )
        )
        if plan is None:
            raise NotFoundError("action_plan", plan_id)
        return plan

    def _get_owned_plan_for_update(self, plan_id: UUID) -> PendingActionPlan:
        plan = self._session.execute(
            select(PendingActionPlan)
            .where(
                PendingActionPlan.id == plan_id,
                PendingActionPlan.user_id == self._user_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if plan is None:
            raise NotFoundError("action_plan", plan_id)
        return plan


def _to_view(plan: PendingActionPlan) -> PendingActionPlanView:
    return PendingActionPlanView(
        id=plan.id,
        status=plan.status,
        expires_at=plan.expires_at,
        actions=_public_actions(plan.actions),
        result=plan.result,
        failure=plan.failure,
    )


_PUBLIC_ARGUMENT_HIDDEN_KEYS = frozenset(
    {"operation_id", "rfc822_message_id", "calendar_href"}
)
_IRREVERSIBLE_PERMISSIONS = frozenset(
    {ToolPermission.EXTERNAL_WRITE, ToolPermission.COMMUNICATE}
)


def validate_action_plan_actions(actions: list[dict[str, Any]]) -> None:
    if not actions:
        raise ValidationError("action plan cannot be empty")
    if len(actions) > MAX_ACTIONS_PER_PLAN:
        raise ValidationError("action plan exceeds maximum actions")
    irreversible = any(
        _permission_for_tool(action.get("tool_name")) in _IRREVERSIBLE_PERMISSIONS
        for action in actions
    )
    if irreversible and len(actions) != 1:
        raise ValidationError(
            "external and communicate actions must be the only action in the plan"
        )


def _permission_for_tool(tool_name: object) -> ToolPermission | None:
    if not isinstance(tool_name, str) or not tool_name:
        return None
    spec = get_tool_spec(tool_name)
    if spec is None:
        return None
    return spec.permission


def _public_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in arguments.items()
        if key not in _PUBLIC_ARGUMENT_HIDDEN_KEYS
    }


def _public_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "tool_name": action["tool_name"],
            "arguments": _public_arguments(action["arguments"]),
        }
        for action in actions
    ]


def _safe_failure_message(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return "action plan execution failed"
    return message[:500]
