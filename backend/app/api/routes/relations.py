from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.schemas import EdgeOut, RelationCreateRequest, RelationCreateResponse, RelationDecisionRequest, RelationDecisionResponse
from app.core.current_user import CurrentUserContext
from app.services.errors import NotFoundError, ValidationError
from app.services.relation_decision_service import RelationDecisionService
from app.services.relation_service import RelationService

router = APIRouter()


def _service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> RelationService:
    return RelationService(session, current_user.user_id)


@router.post("/relations", response_model=RelationCreateResponse)
def create_relation(
    data: RelationCreateRequest,
    service: RelationService = Depends(_service),
) -> RelationCreateResponse:
    try:
        result = service.create_relation(data.source_id, data.target_id, data.type)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc
    return RelationCreateResponse(
        edge=EdgeOut.from_model(result.edge),
        created=result.created,
    )


def _decision_service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> RelationDecisionService:
    return RelationDecisionService(session, current_user.user_id)


@router.post("/relations/{edge_id}/decision", response_model=RelationDecisionResponse)
def decide_relation(
    edge_id: UUID,
    data: RelationDecisionRequest,
    service: RelationDecisionService = Depends(_decision_service),
) -> RelationDecisionResponse:
    try:
        edge = service.apply_decision(edge_id, data.decision)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc
    return RelationDecisionResponse(edge=EdgeOut.from_model(edge))


@router.delete("/relations/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_relation(
    edge_id: UUID,
    service: RelationService = Depends(_service),
) -> Response:
    try:
        service.delete_relation(edge_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
