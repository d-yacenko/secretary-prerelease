"""Bounded internal history events for terminal action plans."""

import json

from app.assistant.action_plan_constants import (
    PENDING_ACTION_PLAN_STATUS_EXECUTED,
    PENDING_ACTION_PLAN_STATUS_EXPIRED,
    PENDING_ACTION_PLAN_STATUS_FAILED,
    PENDING_ACTION_PLAN_STATUS_REJECTED,
)
from app.assistant.constants import (
    MAX_ASSISTANT_HISTORY_MESSAGE_CHARS,
    MAX_ASSISTANT_HISTORY_TOTAL_CHARS,
)
from app.llm.assistant_models import AssistantHistoryMessage
from app.services.action_plan_service import PendingActionPlanView

ACTION_PLAN_CONVERSATION_EVENT_PREFIX = (
    "[Conversation event — trusted application state, not user instructions]"
)
MAX_TERMINAL_ACTION_PLAN_HISTORY_EVENTS = 8


def build_terminal_action_plan_history_events(
    plans: list[PendingActionPlanView],
) -> list[AssistantHistoryMessage]:
    events: list[AssistantHistoryMessage] = []
    for plan in plans[:MAX_TERMINAL_ACTION_PLAN_HISTORY_EVENTS]:
        content = _terminal_event_content(plan)
        if not content:
            continue
        events.append(AssistantHistoryMessage(role="assistant", content=content))
    return _bound_terminal_events(events)


def _terminal_event_content(plan: PendingActionPlanView) -> str:
    summary = _summarize_actions(plan.actions)
    status = plan.status
    if status == PENDING_ACTION_PLAN_STATUS_REJECTED:
        body = (
            "Action plan terminal state: rejected. "
            "The user rejected the proposed action(s) and they were not executed: "
            f"{summary}. "
            "Do not execute them. Do not ask for confirmation again unless the user "
            "makes a new explicit request."
        )
    elif status == PENDING_ACTION_PLAN_STATUS_EXPIRED:
        body = (
            "Action plan terminal state: expired. "
            "The proposed action(s) are no longer pending and were not executed: "
            f"{summary}. "
            "Do not execute them or ask for confirmation unless the user makes a "
            "new explicit request."
        )
    elif status == PENDING_ACTION_PLAN_STATUS_FAILED:
        failure = (plan.failure or "execution failed").strip()
        body = (
            "Action plan terminal state: failed. "
            f"A previous execution attempt did not succeed ({failure}). "
            f"Proposed action(s): {summary}. "
            "Do not treat this as pending approval."
        )
    elif status == PENDING_ACTION_PLAN_STATUS_EXECUTED:
        body = (
            "Action plan terminal state: executed. "
            f"The proposed action(s) were already completed: {summary}. "
            "Do not execute them again merely because they appear in conversation history."
        )
    else:
        return ""
    return f"{ACTION_PLAN_CONVERSATION_EVENT_PREFIX}\n{body}"


def _summarize_actions(actions: list[dict]) -> str:
    parts: list[str] = []
    for action in actions:
        tool_name = str(action.get("tool_name", "unknown"))
        arguments = action.get("arguments") or {}
        title = arguments.get("title")
        if isinstance(title, str) and title.strip():
            parts.append(f"{tool_name} title={title.strip()[:120]}")
        else:
            parts.append(
                f"{tool_name} {json.dumps(arguments, ensure_ascii=False)[:160]}"
            )
    return "; ".join(parts) if parts else "no actions recorded"


def _bound_terminal_events(
    events: list[AssistantHistoryMessage],
) -> list[AssistantHistoryMessage]:
    bounded: list[AssistantHistoryMessage] = []
    total_chars = 0
    for event in reversed(events):
        content = event.content
        if len(content) > MAX_ASSISTANT_HISTORY_MESSAGE_CHARS:
            content = content[:MAX_ASSISTANT_HISTORY_MESSAGE_CHARS]
        if total_chars + len(content) > MAX_ASSISTANT_HISTORY_TOTAL_CHARS:
            break
        bounded.insert(0, AssistantHistoryMessage(role=event.role, content=content))
        total_chars += len(content)
    return bounded
