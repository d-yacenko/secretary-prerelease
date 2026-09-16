"""Canonical task lifecycle statuses for Secretary tasks."""

from typing import Final

# Active / lifecycle statuses for new Agent writes
TASK_STATUS_OPEN: Final[str] = "open"
TASK_STATUS_IN_PROGRESS: Final[str] = "in_progress"
TASK_STATUS_DONE: Final[str] = "done"
TASK_STATUS_CANCELLED: Final[str] = "cancelled"
TASK_STATUS_ARCHIVED: Final[str] = "archived"
TASK_STATUS_DELETED: Final[str] = "deleted"

# Legacy terminal status recognized for reads/filtering
LEGACY_TASK_STATUS_COMPLETED: Final[str] = "completed"

CANONICAL_TASK_STATUSES: frozenset[str] = frozenset(
    {
        TASK_STATUS_OPEN,
        TASK_STATUS_IN_PROGRESS,
        TASK_STATUS_DONE,
        TASK_STATUS_CANCELLED,
        TASK_STATUS_ARCHIVED,
        TASK_STATUS_DELETED,
    }
)

SET_TASK_STATUS_VALUES: frozenset[str] = frozenset(
    {
        TASK_STATUS_OPEN,
        TASK_STATUS_IN_PROGRESS,
        TASK_STATUS_DONE,
        TASK_STATUS_CANCELLED,
        TASK_STATUS_ARCHIVED,
    }
)

TERMINAL_TASK_STATUSES_FOR_READS: frozenset[str] = frozenset(
    {
        TASK_STATUS_DONE,
        LEGACY_TASK_STATUS_COMPLETED,
        TASK_STATUS_CANCELLED,
        TASK_STATUS_ARCHIVED,
        TASK_STATUS_DELETED,
    }
)

TERMINAL_TASK_STATUSES_FOR_TODAY: frozenset[str] = frozenset(
    {
        TASK_STATUS_DONE,
        LEGACY_TASK_STATUS_COMPLETED,
        TASK_STATUS_CANCELLED,
        TASK_STATUS_ARCHIVED,
        TASK_STATUS_DELETED,
    }
)

HIDDEN_FROM_RETRIEVAL_STATUSES: frozenset[str] = frozenset({TASK_STATUS_DELETED})


def is_terminal_for_reads(status: str | None) -> bool:
    if status is None:
        return False
    return status in TERMINAL_TASK_STATUSES_FOR_READS


def is_hidden_from_retrieval(status: str | None) -> bool:
    if status is None:
        return False
    return status in HIDDEN_FROM_RETRIEVAL_STATUSES


def canonical_task_status_for_model(status: str | None) -> str | None:
    """Normalize legacy task statuses for model-visible structured reads."""
    if status is None:
        return TASK_STATUS_OPEN
    if status == LEGACY_TASK_STATUS_COMPLETED:
        return TASK_STATUS_DONE
    return status
