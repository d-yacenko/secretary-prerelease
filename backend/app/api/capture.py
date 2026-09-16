from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth_schemas import (
    CaptureNoteOut,
    CaptureNoteRequest,
    CaptureTaskOut,
    CaptureTaskRequest,
)
from app.api.deps import get_current_user, get_db
from app.core.current_user import CurrentUserContext
from app.services.capture_service import CaptureService
from app.services.errors import NotFoundError, ValidationError

router = APIRouter(tags=["capture"])


@router.post("/capture/task", status_code=status.HTTP_201_CREATED, response_model=CaptureTaskOut)
def capture_task(
    data: CaptureTaskRequest,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> CaptureTaskOut:
    service = CaptureService(session, current_user.user_id)
    try:
        result = service.capture_task(
            text=data.text,
            title=data.title,
            context_object_ids=data.context_object_ids,
            depends_on_ids=data.depends_on_ids,
        )
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

    return CaptureTaskOut(
        task_id=result.task_id,
        context_edge_ids=result.context_edge_ids,
        dependency_edge_ids=result.dependency_edge_ids,
    )


@router.post("/capture/note", status_code=status.HTTP_201_CREATED, response_model=CaptureNoteOut)
def capture_note(
    data: CaptureNoteRequest,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> CaptureNoteOut:
    service = CaptureService(session, current_user.user_id)
    try:
        result = service.capture_note(text=data.text, title=data.title)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc

    return CaptureNoteOut(note_id=result.note_id)
