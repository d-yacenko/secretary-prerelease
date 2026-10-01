"""Confirm/reject proposed correlation edges."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Edge
from app.services.errors import NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.provenance import AGENT_ORIGIN, CONFIRMED_STATE, PROPOSED_STATE, REJECTED_STATE
from app.services.relation_removal import is_edge_removable, removable_edge_rejection_reason


class RelationDecisionService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._graph = GraphService(session, user_id)

    def apply_decision(self, edge_id: UUID, decision: str) -> Edge:
        edge = self._session.scalar(
            select(Edge).where(Edge.id == edge_id, Edge.user_id == self._user_id)
        )
        if edge is None:
            raise NotFoundError("edge", edge_id)
        if edge.origin != AGENT_ORIGIN:
            raise ValidationError("only agent-proposed edges can be decided through this endpoint")
        if decision not in {"confirm", "reject"}:
            raise ValidationError("decision must be confirm or reject")
        if edge.state == PROPOSED_STATE:
            if decision == "confirm":
                return self._graph.set_edge_state(edge_id, CONFIRMED_STATE)
            return self._graph.set_edge_state(edge_id, REJECTED_STATE)
        if decision == "confirm" or edge.state != CONFIRMED_STATE:
            raise ValidationError("only proposed edges can be decided")
        reason = removable_edge_rejection_reason(edge.origin, edge.type)
        if reason is not None or not is_edge_removable(edge.origin, edge.type):
            raise ValidationError(reason or "relation cannot be removed")
        return self._graph.reject_confirmed_agent_relation(edge)
