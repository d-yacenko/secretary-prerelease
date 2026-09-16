from uuid import UUID

from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas import EdgeCreate, ObjectCreate, ObjectUpdate
from app.db.models import Edge, Object
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.planned_execution import validate_planned_execution_interval
from app.llm.embedding_service import EmbeddingService
from app.services.db_errors import is_external_object_unique_violation
from app.services.embedding_index import refresh_object_embedding
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.label_service import (
    reserved_label_create_reason,
    reserved_label_update_reason,
    reserved_labeled_with_reason,
)
from app.services.provenance import (
    default_object_state,
    validate_agent_proposal,
    validate_edge_state_transition,
    validate_origin,
    validate_state,
)

_SEARCHABLE_FIELDS = frozenset({"kind", "title", "body", "metadata"})


class GraphService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._embedding_service = embedding_service

    def _flush_object(self) -> None:
        try:
            self._session.flush()
        except IntegrityError as exc:
            if is_external_object_unique_violation(exc):
                raise ConflictError("external object already exists") from exc
            raise

    def _get_object_row(self, object_id: UUID) -> Object | None:
        return self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )

    def create_object(self, data: ObjectCreate) -> Object:
        reserved = reserved_label_create_reason(data.kind)
        if reserved is not None:
            raise ValidationError(reserved)
        state = default_object_state(data.origin, data.state)
        try:
            validate_origin(data.origin, "object")
            state = default_object_state(data.origin, data.state)
            validate_state(state, "object")
            validate_agent_proposal(data.origin, state, data.confidence, "object")
            validate_planned_execution_interval(
                data.kind, data.planned_start_at, data.planned_end_at
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        obj = Object(
            user_id=self._user_id,
            kind=data.kind,
            title=data.title,
            origin=data.origin,
            state=state,
            body=data.body,
            provider=data.provider,
            external_id=data.external_id,
            canonical_uri=data.canonical_uri,
            status=data.status,
            start_at=data.start_at,
            due_at=data.due_at,
            planned_start_at=data.planned_start_at,
            planned_end_at=data.planned_end_at,
            metadata_=data.metadata,
            confidence=data.confidence,
        )
        self._session.add(obj)
        self._flush_object()
        self._maybe_refresh_embedding(obj, set(_SEARCHABLE_FIELDS))
        return obj

    def get_object(self, object_id: UUID) -> Object:
        obj = self._get_object_row(object_id)
        if obj is None or is_object_hidden_from_active_reads(obj):
            raise NotFoundError("object", object_id)
        return obj

    def update_object(self, object_id: UUID, data: ObjectUpdate) -> Object:
        obj = self.get_object(object_id)
        updates = data.model_dump(exclude_unset=True)
        reserved = reserved_label_update_reason(obj.kind)
        if reserved is not None:
            raise ValidationError(reserved)
        requested_kind = updates.get("kind")
        if requested_kind is not None:
            create_reserved = reserved_label_create_reason(requested_kind)
            if create_reserved is not None:
                raise ValidationError(create_reserved)
        metadata_updated = "metadata" in data.model_fields_set
        if "metadata" in updates:
            obj.metadata_ = updates.pop("metadata")
        for field, value in updates.items():
            setattr(obj, field, value)
        changed_fields = set(updates.keys())
        if metadata_updated:
            changed_fields.add("metadata")
        if "state" in updates:
            validate_state(updates["state"], "object")
        self._validate_object_provenance(obj)
        try:
            validate_planned_execution_interval(
                obj.kind, obj.planned_start_at, obj.planned_end_at
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        self._maybe_refresh_embedding(obj, changed_fields)
        self._flush_object()
        return obj

    def _maybe_refresh_embedding(self, obj: Object, changed_fields: set[str]) -> None:
        if self._embedding_service is None:
            return
        if not changed_fields.intersection(_SEARCHABLE_FIELDS):
            return
        refresh_object_embedding(obj, self._embedding_service)
        self._flush_object()

    def delete_object(self, object_id: UUID) -> None:
        obj = self.get_object(object_id)
        edge_count = self._session.scalar(
            select(func.count())
            .select_from(Edge)
            .where(
                Edge.user_id == self._user_id,
                or_(Edge.source_id == object_id, Edge.target_id == object_id),
            )
        )
        if edge_count and edge_count > 0:
            raise ConflictError("object has incident edges")
        self._session.delete(obj)
        self._session.flush()
        self._session.expire_all()

    def create_edge(self, data: EdgeCreate) -> Edge:
        reserved = reserved_labeled_with_reason(data.type)
        if reserved is not None:
            raise ValidationError(reserved)
        try:
            validate_origin(data.origin, "edge")
            validate_state(data.state, "edge")
            validate_agent_proposal(data.origin, data.state, data.confidence, "edge")
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        source = self._get_object_row(data.source_id)
        if source is None:
            raise NotFoundError("object", data.source_id)
        target = self._get_object_row(data.target_id)
        if target is None:
            raise NotFoundError("object", data.target_id)

        edge = Edge(
            user_id=self._user_id,
            source_id=data.source_id,
            target_id=data.target_id,
            type=data.type,
            origin=data.origin,
            state=data.state,
            confidence=data.confidence,
            metadata_=data.metadata,
        )
        self._session.add(edge)
        self._session.flush()
        return edge

    def delete_edge(self, edge_id: UUID) -> None:
        edge = self._session.scalar(
            select(Edge).where(Edge.id == edge_id, Edge.user_id == self._user_id)
        )
        if edge is None:
            raise NotFoundError("edge", edge_id)
        reserved = reserved_labeled_with_reason(edge.type)
        if reserved is not None:
            raise ValidationError(reserved)
        self._session.delete(edge)
        self._session.flush()

    def set_edge_state(self, edge_id: UUID, state: str) -> Edge:
        edge = self._session.scalar(
            select(Edge).where(Edge.id == edge_id, Edge.user_id == self._user_id)
        )
        if edge is None:
            raise NotFoundError("edge", edge_id)
        reserved = reserved_labeled_with_reason(edge.type)
        if reserved is not None:
            raise ValidationError(reserved)
        try:
            validate_edge_state_transition(edge.state, state)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        edge.state = state
        self._session.flush()
        return edge

    def get_neighbors(
        self,
        object_id: UUID,
        include_rejected: bool = False,
        limit: int | None = None,
    ) -> list[tuple[Object, Edge, str]]:
        self.get_object(object_id)
        if limit is not None:
            return self._get_neighbors_limited(object_id, include_rejected, limit)

        edges = self._session.scalars(
            select(Edge).where(
                Edge.user_id == self._user_id,
                or_(Edge.source_id == object_id, Edge.target_id == object_id),
            ).order_by(Edge.id)
        ).all()

        results: list[tuple[Object, Edge, str]] = []
        for edge in edges:
            if not include_rejected and edge.state == "rejected":
                continue
            if edge.source_id == object_id:
                neighbor = self._get_object_row(edge.target_id)
                direction = "outgoing"
            else:
                neighbor = self._get_object_row(edge.source_id)
                direction = "incoming"
            if neighbor is None:
                continue
            if is_object_hidden_from_active_reads(neighbor):
                continue
            if not include_rejected and neighbor.state == "rejected":
                continue
            results.append((neighbor, edge, direction))
        return results

    def _get_neighbors_limited(
        self,
        object_id: UUID,
        include_rejected: bool,
        limit: int,
    ) -> list[tuple[Object, Edge, str]]:
        outgoing_filters = [
            Edge.user_id == self._user_id,
            Edge.source_id == object_id,
            Object.user_id == self._user_id,
        ]
        incoming_filters = [
            Edge.user_id == self._user_id,
            Edge.target_id == object_id,
            Object.user_id == self._user_id,
        ]
        if not include_rejected:
            outgoing_filters.extend([Edge.state != "rejected", Object.state != "rejected"])
            incoming_filters.extend([Edge.state != "rejected", Object.state != "rejected"])
        outgoing_filters.append(object_is_active(Object))
        incoming_filters.append(object_is_active(Object))

        outgoing = (
            select(Edge.id, literal("outgoing").label("direction"))
            .select_from(Edge)
            .join(Object, Edge.target_id == Object.id)
            .where(*outgoing_filters)
        )
        incoming = (
            select(Edge.id, literal("incoming").label("direction"))
            .select_from(Edge)
            .join(Object, Edge.source_id == Object.id)
            .where(*incoming_filters)
        )

        neighbor_edges = union_all(outgoing, incoming).subquery("neighbor_edges")
        edge_rows = self._session.execute(
            select(neighbor_edges.c.id, neighbor_edges.c.direction)
            .order_by(neighbor_edges.c.id)
            .limit(limit)
        ).all()

        results: list[tuple[Object, Edge, str]] = []
        for edge_id, direction in edge_rows:
            edge = self._session.get(Edge, edge_id)
            if edge is None:
                continue
            if edge.source_id == object_id:
                neighbor = self._get_object_row(edge.target_id)
            else:
                neighbor = self._get_object_row(edge.source_id)
            if neighbor is None:
                continue
            results.append((neighbor, edge, direction))
        return results

    def _validate_object_provenance(self, obj: Object) -> None:
        try:
            validate_origin(obj.origin, "object")
            validate_state(obj.state, "object")
            validate_agent_proposal(obj.origin, obj.state, obj.confidence, "object")
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    def get_context(
        self,
        object_id: UUID,
        include_rejected: bool = False,
    ) -> tuple[Object, list[Edge], list[Object]]:
        obj = self.get_object(object_id)
        edges = self._session.scalars(
            select(Edge).where(
                Edge.user_id == self._user_id,
                or_(Edge.source_id == object_id, Edge.target_id == object_id),
            )
        ).all()

        visible_edges: list[Edge] = []
        neighbor_ids: set[UUID] = set()
        for edge in edges:
            if not include_rejected and edge.state == "rejected":
                continue
            neighbor_id = (
                edge.target_id if edge.source_id == object_id else edge.source_id
            )
            neighbor = self._get_object_row(neighbor_id)
            if neighbor is None:
                continue
            if is_object_hidden_from_active_reads(neighbor):
                continue
            if not include_rejected and neighbor.state == "rejected":
                continue
            visible_edges.append(edge)
            neighbor_ids.add(neighbor_id)

        neighbors: list[Object] = []
        if neighbor_ids:
            neighbors = list(
                self._session.scalars(
                    select(Object).where(
                        Object.user_id == self._user_id,
                        Object.id.in_(neighbor_ids),
                    )
                ).all()
            )
        return obj, visible_edges, neighbors
