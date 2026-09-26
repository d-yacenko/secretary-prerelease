"""Task completion/closure mode. Not a separate object kind."""

from typing import Final

TASK_COMPLETION_FINITE: Final[str] = "finite"
TASK_COMPLETION_ONGOING: Final[str] = "ongoing"
TASK_COMPLETION_MODES: Final[frozenset[str]] = frozenset(
    {TASK_COMPLETION_FINITE, TASK_COMPLETION_ONGOING}
)
_DONE_STATUSES: Final[frozenset[str]] = frozenset({"done", "completed"})


def effective_task_completion_mode(kind: str, completion_mode: str | None) -> str | None:
    """Read path. A missing Task mode is finite. Non-tasks have no mode."""
    if kind != "task":
        return None
    if completion_mode == TASK_COMPLETION_ONGOING:
        return TASK_COMPLETION_ONGOING
    return TASK_COMPLETION_FINITE


def completion_mode_for_storage(
    *,
    kind: str,
    completion_mode: str | None,
    status: str | None,
    mode_was_set: bool,
) -> str | None:
    """Value to persist. ``None`` means leave a Task mode unchanged by the caller."""
    if kind != "task":
        if completion_mode is not None:
            raise ValueError("completion_mode is only valid for task objects")
        return None
    if not mode_was_set and completion_mode is None:
        return None
    mode = TASK_COMPLETION_FINITE if completion_mode is None else completion_mode
    if mode not in TASK_COMPLETION_MODES:
        raise ValueError("completion_mode must be finite or ongoing")
    if mode == TASK_COMPLETION_ONGOING and status in _DONE_STATUSES:
        raise ValueError("ongoing task cannot be done")
    return mode


def reject_done_status_for_ongoing(
    *,
    kind: str,
    completion_mode: str | None,
    status: str | None,
) -> None:
    if (
        effective_task_completion_mode(kind, completion_mode) == TASK_COMPLETION_ONGOING
        and status in _DONE_STATUSES
    ):
        raise ValueError("ongoing task cannot be done")
