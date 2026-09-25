"""Derived Task actionability. Recomputed from canonical facts; never stored."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.task_lifecycle import is_terminal_for_reads

OPERATIONAL_TERMINAL = "terminal"
OPERATIONAL_BLOCKED = "blocked"
OPERATIONAL_WAITING = "waiting"
OPERATIONAL_DELEGATED = "delegated"
OPERATIONAL_SCHEDULED_LATER = "scheduled_later"
OPERATIONAL_ACTIONABLE = "actionable"

REASON_TERMINAL_LIFECYCLE = "terminal_lifecycle"
REASON_OPEN_DEPENDENCY = "open_dependency"
REASON_WAITING_ON_PERSON = "waiting_on_person"
REASON_DELEGATED_TO_PERSON = "delegated_to_person"
REASON_PLANNED_START_IN_FUTURE = "planned_start_in_future"
REASON_NO_EXTERNAL_BLOCKER = "no_external_blocker"
REASON_OVERDUE = "overdue"

MAX_OPERATIONAL_BATCH = 32
MAX_OPERATIONAL_CHUNKED = 100


class TaskOperationalState(StrEnum):
    TERMINAL = OPERATIONAL_TERMINAL
    BLOCKED = OPERATIONAL_BLOCKED
    WAITING = OPERATIONAL_WAITING
    DELEGATED = OPERATIONAL_DELEGATED
    SCHEDULED_LATER = OPERATIONAL_SCHEDULED_LATER
    ACTIONABLE = OPERATIONAL_ACTIONABLE


@dataclass(frozen=True)
class OperationalDependency:
    task_id: UUID
    title: str
    status: str | None


@dataclass(frozen=True)
class OperationalPerson:
    person_id: UUID
    title: str


@dataclass(frozen=True)
class TaskOperationalProjection:
    operational_state: str
    is_overdue: bool
    is_scheduled_later: bool
    is_planned_now: bool
    due_at: datetime | None
    planned_start_at: datetime | None
    planned_end_at: datetime | None
    blocking_dependencies: tuple[OperationalDependency, ...]
    waiting_on: tuple[OperationalPerson, ...]
    delegated_to: tuple[OperationalPerson, ...]
    reason_codes: tuple[str, ...]


def derive_task_operational_state(
    *,
    status: str | None,
    due_at: datetime | None,
    planned_start_at: datetime | None,
    planned_end_at: datetime | None,
    now: datetime,
    blocking_dependencies: tuple[OperationalDependency, ...] | list[OperationalDependency],
    waiting_on: tuple[OperationalPerson, ...] | list[OperationalPerson],
    delegated_to: tuple[OperationalPerson, ...] | list[OperationalPerson],
) -> TaskOperationalProjection:
    """Precedence: terminal, blocked, waiting, delegated, scheduled_later, actionable."""
    terminal = is_terminal_for_reads(status)
    blockers = tuple(blocking_dependencies)
    waiters = tuple(waiting_on)
    delegates = tuple(delegated_to)
    overdue = (not terminal) and due_at is not None and due_at < now
    scheduled_later = (not terminal) and planned_start_at is not None and planned_start_at > now
    planned_now = (
        planned_start_at is not None
        and planned_end_at is not None
        and planned_start_at <= now <= planned_end_at
    )
    if terminal:
        state = TaskOperationalState.TERMINAL
    elif blockers:
        state = TaskOperationalState.BLOCKED
    elif waiters:
        state = TaskOperationalState.WAITING
    elif delegates:
        state = TaskOperationalState.DELEGATED
    elif scheduled_later:
        state = TaskOperationalState.SCHEDULED_LATER
    else:
        state = TaskOperationalState.ACTIONABLE
    reasons: list[str] = []
    if terminal:
        reasons.append(REASON_TERMINAL_LIFECYCLE)
    if blockers:
        reasons.append(REASON_OPEN_DEPENDENCY)
    if waiters:
        reasons.append(REASON_WAITING_ON_PERSON)
    if delegates:
        reasons.append(REASON_DELEGATED_TO_PERSON)
    if scheduled_later:
        reasons.append(REASON_PLANNED_START_IN_FUTURE)
    if state is TaskOperationalState.ACTIONABLE:
        reasons.append(REASON_NO_EXTERNAL_BLOCKER)
    if overdue:
        reasons.append(REASON_OVERDUE)
    return TaskOperationalProjection(
        operational_state=state.value,
        is_overdue=overdue,
        is_scheduled_later=scheduled_later,
        is_planned_now=planned_now,
        due_at=due_at,
        planned_start_at=planned_start_at,
        planned_end_at=planned_end_at,
        blocking_dependencies=blockers,
        waiting_on=waiters,
        delegated_to=delegates,
        reason_codes=tuple(reasons),
    )
