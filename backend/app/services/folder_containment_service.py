"""Deterministic folder containment edges."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.schemas import EdgeCreate
from app.db.models import Edge, Object
from app.services.correlation_constants import EDGE_TYPE_CONTAINS
from app.services.edge_dedup import has_equivalent_relation
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE, SYSTEM_ORIGIN


class FolderContainmentService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._graph = GraphService(session, user_id)

    def link_files_to_folder(
        self,
        folder_id: UUID,
        file_object_ids: list[UUID],
    ) -> int:
        created = 0
        for file_id in file_object_ids:
            if file_id == folder_id:
                continue
            file_obj = self._session.scalar(
                select(Object).where(Object.id == file_id, Object.user_id == self._user_id)
            )
            if file_obj is None:
                continue
            if has_equivalent_relation(
                self._session, self._user_id, folder_id, file_id, EDGE_TYPE_CONTAINS
            ):
                continue
            self._graph.create_edge(
                EdgeCreate(
                    source_id=folder_id,
                    target_id=file_id,
                    type=EDGE_TYPE_CONTAINS,
                    origin=SYSTEM_ORIGIN,
                    state=CONFIRMED_STATE,
                    metadata={"containment": "local_root"},
                )
            )
            created += 1
        return created

    def prune_stale_containment(
        self,
        folder_id: UUID,
        present_file_ids: set[UUID],
    ) -> int:
        edges = self._session.scalars(
            select(Edge).where(
                Edge.user_id == self._user_id,
                Edge.source_id == folder_id,
                Edge.type == EDGE_TYPE_CONTAINS,
                Edge.origin == SYSTEM_ORIGIN,
            )
        ).all()
        removed = 0
        for edge in edges:
            if edge.target_id in present_file_ids:
                continue
            self._session.delete(edge)
            removed += 1
        if removed:
            self._session.flush()
        return removed
