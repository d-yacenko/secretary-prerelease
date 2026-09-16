from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_user_embedding_service
from app.api.schemas import (
    ContextOut,
    EdgeCreate,
    EdgeOut,
    NeighborOut,
    NeighborsOut,
    ObjectCreate,
    ObjectDeleteResponse,
    ObjectOut,
    ObjectUpdate,
    OpenTargetOut,
    SearchFacetsOut,
    SearchFacetValueOut,
)
from app.core.current_user import CurrentUserContext
from app.llm.embedding_service import EmbeddingService
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.object_deletion_service import ObjectDeletionService
from app.services.open_target_service import OpenTargetService
from app.services.search_facet_service import SearchFacetService
from app.services.search_service import SearchService

router = APIRouter()


def _graph_service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> GraphService:
    return GraphService(session, current_user.user_id)


def _graph_service_with_embedding(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
    embedding_service: EmbeddingService = Depends(get_user_embedding_service),
) -> GraphService:
    return GraphService(session, current_user.user_id, embedding_service)


def _not_found(exc: NotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{exc.resource} not found",
    )


@router.post("/objects", status_code=status.HTTP_201_CREATED, response_model=ObjectOut)
def create_object(
    data: ObjectCreate, service: GraphService = Depends(_graph_service_with_embedding),
) -> ObjectOut:
    try:
        obj = service.create_object(data)
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc
    return ObjectOut.from_model(obj)


@router.get("/objects/{object_id}", response_model=ObjectOut)
def get_object(object_id: UUID, service: GraphService = Depends(_graph_service)) -> ObjectOut:
    try:
        obj = service.get_object(object_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return ObjectOut.from_model(obj)


@router.patch("/objects/{object_id}", response_model=ObjectOut)
def patch_object(
    object_id: UUID,
    data: ObjectUpdate,
    service: GraphService = Depends(_graph_service_with_embedding),
) -> ObjectOut:
    try:
        obj = service.update_object(object_id, data)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc
    return ObjectOut.from_model(obj)


def _object_deletion_service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> ObjectDeletionService:
    return ObjectDeletionService(session, current_user.user_id)


@router.delete("/objects/{object_id}", response_model=ObjectDeleteResponse)
def delete_object(
    object_id: UUID,
    service: ObjectDeletionService = Depends(_object_deletion_service),
) -> ObjectDeleteResponse:
    try:
        result = service.delete_object(object_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return ObjectDeleteResponse(
        object_id=result.object.id,
        deleted_at=result.deleted_at,
        already_deleted=result.already_deleted,
    )


@router.post("/edges", status_code=status.HTTP_201_CREATED, response_model=EdgeOut)
def create_edge(data: EdgeCreate, service: GraphService = Depends(_graph_service)) -> EdgeOut:
    try:
        edge = service.create_edge(data)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc
    return EdgeOut.from_model(edge)


@router.delete("/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_edge(edge_id: UUID, service: GraphService = Depends(_graph_service)) -> Response:
    try:
        service.delete_edge(edge_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/objects/{object_id}/neighbors", response_model=NeighborsOut)
def get_neighbors(object_id: UUID, service: GraphService = Depends(_graph_service)) -> NeighborsOut:
    try:
        neighbor_rows = service.get_neighbors(object_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc

    return NeighborsOut(
        object_id=object_id,
        neighbors=[
            NeighborOut(
                object=ObjectOut.from_model(neighbor),
                edge=EdgeOut.from_model(edge),
                direction=direction,
            )
            for neighbor, edge, direction in neighbor_rows
        ],
    )


@router.get("/objects/{object_id}/context", response_model=ContextOut)
def get_context(object_id: UUID, service: GraphService = Depends(_graph_service)) -> ContextOut:
    try:
        obj, edges, neighbors = service.get_context(object_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc

    return ContextOut(
        object=ObjectOut.from_model(obj),
        edges=[EdgeOut.from_model(edge) for edge in edges],
        neighbors=[ObjectOut.from_model(neighbor) for neighbor in neighbors],
    )


@router.get("/objects/{object_id}/open-target", response_model=OpenTargetOut)
def get_open_target(
    object_id: UUID,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> OpenTargetOut:
    service = OpenTargetService(session, current_user.user_id)
    try:
        target = service.resolve(object_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return OpenTargetOut(
        available=target.available,
        action=target.action,
        label=target.label,
        url=target.url,
        device_key=target.device_key,
        local_path=target.local_path,
        reason=target.reason,
    )


@router.get("/search", response_model=list[ObjectOut])
def search_objects(
    q: str = Query(min_length=1),
    kind: str | None = None,
    provider: str | None = None,
    project_id: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    sort: str = Query(default="relevance"),
    label_id: UUID | None = Query(default=None),
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> list[ObjectOut]:
    service = SearchService(session, current_user.user_id)
    try:
        return service.search(
            query=q,
            kind=kind,
            provider=provider,
            project_id=project_id,
            limit=limit,
            sort=sort,
            label_id=label_id,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
        ) from exc


@router.get("/search/facets", response_model=SearchFacetsOut)
def search_facets(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> SearchFacetsOut:
    data = SearchFacetService(session, current_user.user_id).facets()
    return SearchFacetsOut(
        kinds=[SearchFacetValueOut(**row) for row in data["kinds"]],
        providers=[SearchFacetValueOut(**row) for row in data["providers"]],
    )
