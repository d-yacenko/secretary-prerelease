"""Explicit user-planned task execution interval.

This is not a deadline (`due_at`) and not calendar busy time.
"""

KIND_TASK = "task"

PLANNED_INTERVAL_BOTH_OR_NEITHER = (
    "planned_start_at and planned_end_at must both be set or both be empty"
)
PLANNED_INTERVAL_END_AFTER_START = "planned_end_at must be after planned_start_at"
PLANNED_INTERVAL_TASKS_ONLY = "planned execution interval is only allowed on tasks"


def validate_planned_execution_interval(
    kind: str | None,
    planned_start_at,
    planned_end_at,
) -> None:
    has_start = planned_start_at is not None
    has_end = planned_end_at is not None
    if not has_start and not has_end:
        return
    if kind != KIND_TASK:
        raise ValueError(PLANNED_INTERVAL_TASKS_ONLY)
    if has_start != has_end:
        raise ValueError(PLANNED_INTERVAL_BOTH_OR_NEITHER)
    if planned_end_at <= planned_start_at:
        raise ValueError(PLANNED_INTERVAL_END_AFTER_START)
