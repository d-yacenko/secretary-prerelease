"""Direct user relation create/remove for first-party UI."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import EdgeCreate, EdgeOut
from app.db.models import Edge, Object
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE

USER_RELATION_TYPES = frozenset({"related_to", "references", "depends_on"})
USER_ORIGIN = "user"


@dataclass(frozen=True)
class RelationCreateResult:
    edge: Edge
    created: bool


class RelationService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._graph = GraphService(session, user_id)

    def create_relation(
        self,
        source_id: UUID,
        target_id: UUID,
        relation_type: str,
    ) -> RelationCreateResult:
        if source_id == target_id:
            raise ValidationError("source and target must differ")
        if relation_type not in USER_RELATION_TYPES:
            raise ValidationError(f"unsupported relation type: {relation_type}")

        source = self._get_endpoint(source_id)
        target = self._get_endpoint(target_id)
        self._validate_endpoint_for_relation(source)
        self._validate_endpoint_for_relation(target)

        existing = self._session.scalar(
            select(Edge).where(
                Edge.user_id == self._user_id,
                Edge.source_id == source_id,
                Edge.target_id == target_id,
                Edge.type == relation_type,
            )
        )
        if existing is not None:
            return RelationCreateResult(edge=existing, created=False)

        try:
            edge = self._graph.create_edge(
                EdgeCreate(
                    source_id=source_id,
                    target_id=target_id,
                    type=relation_type,
                    origin=USER_ORIGIN,
                    state=CONFIRMED_STATE,
                )
            )
        except NotFoundError:
            raise
        except ValidationError as exc:
            raise ValidationError(exc.message) from exc
        except ConflictError as exc:
            raise ValidationError(exc.message) from exc
        return RelationCreateResult(edge=edge, created=True)

    def delete_relation(self, edge_id: UUID) -> None:
        edge = self._session.scalar(
            select(Edge).where(Edge.id == edge_id, Edge.user_id == self._user_id)
        )
        if edge is None:
            raise NotFoundError("edge", edge_id)
        if edge.origin != USER_ORIGIN:
            raise ValidationError(
                "only user-created relations can be deleted through this endpoint"
            )
        self._graph.delete_edge(edge_id)

    def _get_endpoint(self, object_id: UUID) -> Object:
        try:
            return self._graph.get_object(object_id)
        except NotFoundError:
            raise

    def _validate_endpoint_for_relation(self, obj: Object) -> None:
        if obj.state == REJECTED_STATE:
            raise ValidationError("rejected objects cannot receive new relations")
        if is_object_hidden_from_active_reads(obj):
            raise ValidationError("deleted objects cannot receive new relations")
