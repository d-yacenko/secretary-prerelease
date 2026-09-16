from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.schemas import EdgeOut, GraphWorkspaceOut, ObjectOut
from app.core.current_user import CurrentUserContext
from app.services.errors import NotFoundError
from app.services.graph_workspace_service import (
    DEFAULT_NEIGHBOR_LIMIT,
    DEFAULT_NODE_LIMIT,
    DEFAULT_SEED_LIMIT,
    GraphWorkspaceService,
    MAX_NEIGHBOR_LIMIT,
    MAX_NODE_LIMIT,
    MAX_SEED_LIMIT,
)

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
