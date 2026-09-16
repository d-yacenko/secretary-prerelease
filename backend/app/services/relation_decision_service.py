"""Confirm/reject proposed correlation edges."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Edge
from app.services.errors import NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.provenance import AGENT_ORIGIN, CONFIRMED_STATE, PROPOSED_STATE, REJECTED_STATE


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
        if edge.state != PROPOSED_STATE:
            raise ValidationError("only proposed edges can be decided")
        if decision == "confirm":
            return self._graph.set_edge_state(edge_id, CONFIRMED_STATE)
        if decision == "reject":
            return self._graph.set_edge_state(edge_id, REJECTED_STATE)
        raise ValidationError("decision must be confirm or reject")
