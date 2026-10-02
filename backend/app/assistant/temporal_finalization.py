"""User-facing date/time facts for post-approval finalization.

Execution output stays authoritative for the instant. A frozen argument is a
display fact only when it is the same instant.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

TEMPORAL_DISPLAY_FACTS_HEADER = (
    "Temporal display facts (authoritative for user-facing date/time wording; "
    "execution results remain authoritative for state/instant):"
)
APPROVED_TEMPORAL_REPRESENTATION_APPLIED = "approved temporal representation applied"
INSTANT_MISMATCH_FACT = (
    "instant mismatch; do not narrate a frozen representation as execution truth"
)
_MAX_ISO_CHARS = 40

_UPDATE_FIELDS = (
    ("due_at", "due_at"),
    ("planned_start_at", "planned_start_at"),
    ("planned_end_at", "planned_end_at"),
)


def build_temporal_display_facts(
    actions: list[dict[str, Any]] | None,
    result: dict[str, Any] | None,
) -> list[str]:
    if not actions or not result:
        return []
    executed = result.get("actions")
    if not isinstance(executed, list):
        return []
    facts: list[str] = []
    for index, frozen in enumerate(actions):
        if index >= len(executed):
            break
        outcome = executed[index]
        if not isinstance(frozen, dict) or not isinstance(outcome, dict):
            continue
        tool_name = frozen.get("tool_name")
        if outcome.get("tool_name") != tool_name:
            continue
        if tool_name == "update_task":
            facts.extend(_update_task_facts(frozen, outcome))
        elif tool_name == "create_scheduled_activity":
            facts.extend(_one_shot_facts(frozen, outcome))
        elif tool_name == "create_recurring_scheduled_activity":
            facts.extend(_recurring_facts(frozen, outcome))
    return facts


def temporal_display_section(
    actions: list[dict[str, Any]] | None,
    result: dict[str, Any] | None,
) -> str:
    facts = build_temporal_display_facts(actions, result)
    if not facts:
        return ""
    return TEMPORAL_DISPLAY_FACTS_HEADER + "\n" + "\n".join(facts)


def _update_task_facts(frozen: dict[str, Any], outcome: dict[str, Any]) -> list[str]:
    output = outcome.get("output") if isinstance(outcome.get("output"), dict) else {}
    if output.get("changed") is not True:
        return []
    arguments = frozen.get("arguments") if isinstance(frozen.get("arguments"), dict) else {}
    obj = output.get("object") if isinstance(output.get("object"), dict) else {}
    lines: list[str] = []
    for argument_name, output_name in _UPDATE_FIELDS:
        if argument_name not in arguments:
            continue
        lines.append(
            _pair_fact(
                "update_task",
                argument_name,
                arguments.get(argument_name),
                obj.get(output_name),
                include_calendar_date=argument_name == "due_at",
            )
        )
    return lines


def _one_shot_facts(frozen: dict[str, Any], outcome: dict[str, Any]) -> list[str]:
    if outcome.get("success") is False:
        return []
    output = outcome.get("output") if isinstance(outcome.get("output"), dict) else {}
    arguments = frozen.get("arguments") if isinstance(frozen.get("arguments"), dict) else {}
    if "run_at" not in arguments:
        return []
    obj = output.get("object") if isinstance(output.get("object"), dict) else {}
    return [
        _pair_fact(
            "create_scheduled_activity",
            "run_at",
            arguments.get("run_at"),
            obj.get("due_at"),
            include_calendar_date=False,
        )
    ]


def _recurring_facts(frozen: dict[str, Any], outcome: dict[str, Any]) -> list[str]:
    if outcome.get("success") is False:
        return []
    arguments = frozen.get("arguments") if isinstance(frozen.get("arguments"), dict) else {}
    local_time = arguments.get("local_time")
    timezone = arguments.get("timezone")
    if not isinstance(local_time, str) or not isinstance(timezone, str):
        return []
    local_time = local_time.strip()
    timezone = timezone.strip()
    if not local_time or not timezone or len(local_time) > 16 or len(timezone) > 64:
        return []
    return [
        (
            "create_recurring_scheduled_activity: user-facing schedule "
            f"local_time={local_time} timezone={timezone}; "
            "do not replace this schedule with the occurrence instant"
        )
    ]


def _pair_fact(
    tool_name: str,
    field_name: str,
    frozen_value: object,
    executed_value: object,
    *,
    include_calendar_date: bool,
) -> str:
    prefix = f"{tool_name} {field_name}:"
    frozen_text, frozen_at, frozen_date = _aware_instant(frozen_value)
    _executed_text, executed_at, _executed_date = _aware_instant(executed_value)
    if frozen_at is None or executed_at is None or frozen_at != executed_at:
        return f"{prefix} {INSTANT_MISMATCH_FACT}"
    applied = f"{prefix} {APPROVED_TEMPORAL_REPRESENTATION_APPLIED}: {frozen_text}"
    if include_calendar_date and frozen_date is not None:
        applied += f"; calendar date {frozen_date.isoformat()}"
    return applied


def _aware_instant(value: object) -> tuple[str | None, datetime | None, date | None]:
    if not isinstance(value, str):
        return None, None, None
    text = value.strip()
    if not text or len(text) > _MAX_ISO_CHARS or "T" not in text:
        return None, None, None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, None, None
    if parsed.tzinfo is None:
        return None, None, None
    return text, parsed.astimezone(UTC), parsed.date()
