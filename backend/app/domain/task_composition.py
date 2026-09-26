"""Canonical part_of forest rules.

Orientation is child/source -> parent/target. A non-rejected part_of edge
occupies the child's single parent slot, including a proposed edge. Legacy
contains is not an inverse and is not consulted here.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Edge, Object
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.domain.task_completion import (
    TASK_COMPLETION_ONGOING,
    effective_task_completion_mode,
)
from app.domain.task_relations import PART_OF
from app.services.errors import ValidationError
from app.services.provenance import REJECTED_STATE


def composition_modes_compatible(child_mode: str, parent_mode: str) -> bool:
    """finite->finite, finite->ongoing, and ongoing->ongoing are allowed."""
    return not (
        child_mode == TASK_COMPLETION_ONGOING and parent_mode != TASK_COMPLETION_ONGOING
    )


def validate_part_of_edge(
    session: Session,
    user_id: UUID,
    child: Object,
    parent: Object,
    *,
    ignore_edge_id: UUID | None = None,
) -> None:
    """Validate a non-rejected child -> parent part_of edge before it is stored or confirmed."""
    if child.id == parent.id:
        raise ValidationError("a task cannot be part of itself")
    child_mode = _active_task_mode(child, user_id)
    parent_mode = _active_task_mode(parent, user_id)
    if not composition_modes_compatible(child_mode, parent_mode):
        raise ValidationError("an ongoing task cannot be part of a finite task")
    if _other_parent_edge(session, user_id, child.id, ignore_edge_id) is not None:
        raise ValidationError(
            "task already has a composition parent; remove that relation before assigning another"
        )
    if _creates_cycle(session, user_id, child.id, parent.id, ignore_edge_id):
        raise ValidationError("part_of would create a cycle")


def validate_completion_mode_change(
    session: Session,
    user_id: UUID,
    task: Object,
    next_mode: str,
) -> None:
    """Reject a mode change that would leave an active part_of edge incompatible."""
    for edge in _part_of_edges(session, user_id, source_id=task.id):
        parent = session.get(Object, edge.target_id)
        if parent is None:
            continue
        parent_mode = _mode_if_active_task(parent, user_id)
        if parent_mode is None:
            continue
        if not composition_modes_compatible(next_mode, parent_mode):
            raise ValidationError(
                "cannot change this task to ongoing while it is part of a finite task"
            )
    for edge in _part_of_edges(session, user_id, target_id=task.id):
        child = session.get(Object, edge.source_id)
        if child is None:
            continue
        child_mode = _mode_if_active_task(child, user_id)
        if child_mode is None:
            continue
        if not composition_modes_compatible(child_mode, next_mode):
            raise ValidationError(
                "cannot change this task to finite while an ongoing task is part of it"
            )


def _active_task_mode(obj: Object, user_id: UUID) -> str:
    mode = _mode_if_active_task(obj, user_id)
    if mode is None:
        if obj.user_id != user_id:
            raise ValidationError("part_of endpoints must belong to the same user")
        if obj.kind != "task":
            raise ValidationError("part_of endpoints must both be tasks")
        raise ValidationError("part_of endpoints must be active tasks")
    return mode


def _mode_if_active_task(obj: Object, user_id: UUID) -> str | None:
    if obj.user_id != user_id or obj.kind != "task":
        return None
    if obj.state == REJECTED_STATE or is_object_hidden_from_active_reads(obj):
        return None
    return effective_task_completion_mode(obj.kind, obj.completion_mode)


def _other_parent_edge(
    session: Session,
    user_id: UUID,
    child_id: UUID,
    ignore_edge_id: UUID | None,
) -> Edge | None:
    return session.scalar(
        _part_of_filter(
            select(Edge).where(Edge.source_id == child_id),
            user_id,
            ignore_edge_id,
        ).limit(1)
    )


def _creates_cycle(
    session: Session,
    user_id: UUID,
    child_id: UUID,
    parent_id: UUID,
    ignore_edge_id: UUID | None,
) -> bool:
    seen: set[UUID] = set()
    frontier = [parent_id]
    while frontier:
        current = frontier.pop()
        if current == child_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        frontier.extend(
            session.scalars(
                _part_of_filter(
                    select(Edge.target_id).where(Edge.source_id == current),
                    user_id,
                    ignore_edge_id,
                )
            )
        )
    return False


def _part_of_edges(
    session: Session,
    user_id: UUID,
    *,
    source_id: UUID | None = None,
    target_id: UUID | None = None,
) -> list[Edge]:
    statement = select(Edge)
    if source_id is not None:
        statement = statement.where(Edge.source_id == source_id)
    if target_id is not None:
        statement = statement.where(Edge.target_id == target_id)
    return list(session.scalars(_part_of_filter(statement, user_id, None)))


def _part_of_filter(statement, user_id: UUID, ignore_edge_id: UUID | None):
    statement = statement.where(
        Edge.user_id == user_id,
        Edge.type == PART_OF,
        Edge.state != REJECTED_STATE,
    )
    if ignore_edge_id is not None:
        statement = statement.where(Edge.id != ignore_edge_id)
    return statement
