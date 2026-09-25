from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.schemas import (
    EdgeOut,
    GraphWorkspaceOut,
    ObjectOut,
    PeopleWorkspaceOut,
    PersonIdentityCorrectionRequest,
    PersonPresentation,
)
from app.core.current_user import CurrentUserContext
from app.services.errors import NotFoundError, ValidationError
from app.services.graph_workspace_service import (
    DEFAULT_NEIGHBOR_LIMIT,
    DEFAULT_NODE_LIMIT,
    DEFAULT_SEED_LIMIT,
    MAX_NEIGHBOR_LIMIT,
    MAX_NODE_LIMIT,
    MAX_SEED_LIMIT,
    GraphWorkspaceService,
)
from app.services.person_graph_workspace_service import PersonGraphWorkspaceService

router = APIRouter()


def _service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> GraphWorkspaceService:
    return GraphWorkspaceService(session, current_user.user_id)


@router.get("/graph/workspace", response_model=GraphWorkspaceOut)
def get_graph_workspace(
    root_id: UUID | None = Query(default=None),
    seed_limit: int = Query(default=DEFAULT_SEED_LIMIT, ge=1, le=MAX_SEED_LIMIT),
    neighbor_limit: int = Query(default=DEFAULT_NEIGHBOR_LIMIT, ge=1, le=MAX_NEIGHBOR_LIMIT),
    node_limit: int = Query(default=DEFAULT_NODE_LIMIT, ge=1, le=MAX_NODE_LIMIT),
    service: GraphWorkspaceService = Depends(_service),
) -> GraphWorkspaceOut:
    try:
        result = service.get_workspace(
            root_id=root_id,
            seed_limit=seed_limit,
            neighbor_limit=neighbor_limit,
            node_limit=node_limit,
        )
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc
    return GraphWorkspaceOut(
        root_id=result.root_id,
        seed_ids=result.seed_ids,
        nodes=[ObjectOut.from_model(node) for node in result.nodes],
        edges=[EdgeOut.from_model(edge) for edge in result.edges],
        truncated=result.truncated,
    )


def _people_service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> PersonGraphWorkspaceService:
    return PersonGraphWorkspaceService(session, current_user.user_id)


@router.get("/graph/people-workspace", response_model=PeopleWorkspaceOut)
def get_people_workspace(
    root_id: UUID | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    seed_limit: int = Query(default=DEFAULT_SEED_LIMIT, ge=1, le=MAX_SEED_LIMIT),
    neighbor_limit: int = Query(default=DEFAULT_NEIGHBOR_LIMIT, ge=1, le=MAX_NEIGHBOR_LIMIT),
    service: PersonGraphWorkspaceService = Depends(_people_service),
) -> PeopleWorkspaceOut:
    try:
        result = service.get_workspace(
            root_id=root_id,
            query=q,
            seed_limit=seed_limit,
            neighbor_limit=neighbor_limit,
        )
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc
    return PeopleWorkspaceOut(
        root_id=result.root_id,
        seed_ids=result.seed_ids,
        nodes=[ObjectOut.from_model(node) for node in result.nodes],
        edges=[EdgeOut.from_model(edge) for edge in result.edges],
        truncated=result.truncated,
        people=[PersonPresentation.model_validate(person) for person in result.people],
    )


@router.post("/graph/people/{person_id}/identity-correction")
def correct_person_identity(
    person_id: UUID,
    body: PersonIdentityCorrectionRequest,
    service: PersonGraphWorkspaceService = Depends(_people_service),
):
    try:
        row = service.correct_identity(
            person_id,
            action=body.action,
            identity_type=body.identity_type,
            provider=body.provider,
            realm=body.realm,
            canonical_value=body.canonical_value,
        )
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc
    return {
        "person_id": str(row.person_id),
        "evidence_id": str(row.evidence_id),
        "evidence_type": row.evidence_type,
        "state": row.state,
    }
