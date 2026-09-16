"""Shared edge deduplication helpers for correlation."""

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import Edge
from app.services.correlation_constants import CORRELATION_VERSION, EDGE_TYPE_RELATED_TO

_NON_REJECTED_STATES = ("observed", "proposed", "confirmed")


def correlation_signature(trigger_id: UUID, target_id: UUID, relation_type: str) -> str:
    if relation_type == EDGE_TYPE_RELATED_TO:
        left_id, right_id = sorted((trigger_id, target_id), key=str)
        return f"{CORRELATION_VERSION}:{left_id}:{right_id}:{relation_type}"
    return f"{CORRELATION_VERSION}:{trigger_id}:{target_id}:{relation_type}"


def has_equivalent_relation(
    session: Session,
    user_id: UUID,
    source_id: UUID,
    target_id: UUID,
    relation_type: str,
) -> bool:
    if relation_type == EDGE_TYPE_RELATED_TO:
        return _has_symmetric_related(session, user_id, source_id, target_id)
    return _has_directional_edge(session, user_id, source_id, target_id, relation_type)


def _has_symmetric_related(
    session: Session,
    user_id: UUID,
    left_id: UUID,
    right_id: UUID,
) -> bool:
    existing = session.scalar(
        select(Edge.id).where(
            Edge.user_id == user_id,
            Edge.type == EDGE_TYPE_RELATED_TO,
            Edge.state.in_(_NON_REJECTED_STATES),
            or_(
                and_(Edge.source_id == left_id, Edge.target_id == right_id),
                and_(Edge.source_id == right_id, Edge.target_id == left_id),
            ),
        ).limit(1)
    )
    return existing is not None


def _has_directional_edge(
    session: Session,
    user_id: UUID,
    source_id: UUID,
    target_id: UUID,
    relation_type: str,
) -> bool:
    existing = session.scalar(
        select(Edge.id).where(
            Edge.user_id == user_id,
            Edge.source_id == source_id,
            Edge.target_id == target_id,
            Edge.type == relation_type,
            Edge.state.in_(_NON_REJECTED_STATES),
        ).limit(1)
    )
    return existing is not None


def has_rejected_proposal_signature(
    session: Session,
    user_id: UUID,
    trigger_object_id: UUID,
    target_id: UUID,
    relation_type: str,
    signature: str,
) -> bool:
    if relation_type == EDGE_TYPE_RELATED_TO:
        edges = session.scalars(
            select(Edge).where(
                Edge.user_id == user_id,
                Edge.type == EDGE_TYPE_RELATED_TO,
                Edge.origin == "agent",
                Edge.state == "rejected",
                or_(
                    and_(Edge.source_id == trigger_object_id, Edge.target_id == target_id),
                    and_(Edge.source_id == target_id, Edge.target_id == trigger_object_id),
                ),
            )
        ).all()
    else:
        edges = session.scalars(
            select(Edge).where(
                Edge.user_id == user_id,
                Edge.source_id == trigger_object_id,
                Edge.target_id == target_id,
                Edge.type == relation_type,
                Edge.origin == "agent",
                Edge.state == "rejected",
            )
        ).all()
    for edge in edges:
        meta = edge.metadata_ or {}
        if meta.get("correlation_signature") == signature:
            return True
    return False
