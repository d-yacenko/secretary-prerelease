"""Task-map topology participation and layout-revision invalidation.

Matches the client Tasks map: both endpoints are Tasks, rejected edges are
absent, `part_of` counts only when confirmed, and actor/label/temporal edges
stay off the map. This module never creates layout state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import TaskLayoutState
from app.domain.task_relations import PART_OF
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE

# Same membership as client `kGraphMapHiddenRelationTypes`.
TASK_MAP_HIDDEN_RELATION_TYPES = frozenset(
    {
        "requested_by",
        "delegated_to",
        "waiting_on",
        "involves",
        "labeled_with",
        "temporal_evidence",
        "temporal_confirmation",
    }
)


def relation_affects_task_map(
    *,
    edge_type: str,
    state: str | None,
    source_kind: str | None,
    target_kind: str | None,
) -> bool:
    if source_kind != "task" or target_kind != "task":
        return False
    if state is None or state == REJECTED_STATE:
        return False
    if edge_type in TASK_MAP_HIDDEN_RELATION_TYPES:
        return False
    if edge_type == PART_OF:
        return state == CONFIRMED_STATE
    return True


def invalidate_existing_task_layout(session: Session, user_id: UUID) -> None:
    state = session.scalar(
        select(TaskLayoutState)
        .where(TaskLayoutState.user_id == user_id)
        .with_for_update()
    )
    if state is None:
        return
    state.topology_revision += 1
    state.updated_at = datetime.now(UTC)
    session.flush()


def note_task_map_participation_change(
    session: Session,
    user_id: UUID,
    *,
    edge_type: str,
    previous_state: str | None,
    new_state: str | None,
    source_kind: str | None,
    target_kind: str | None,
) -> None:
    before = relation_affects_task_map(
        edge_type=edge_type,
        state=previous_state,
        source_kind=source_kind,
        target_kind=target_kind,
    )
    after = relation_affects_task_map(
        edge_type=edge_type,
        state=new_state,
        source_kind=source_kind,
        target_kind=target_kind,
    )
    if before != after:
        invalidate_existing_task_layout(session, user_id)
