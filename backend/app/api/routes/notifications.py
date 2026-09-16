from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.schemas import NotificationListOut, NotificationOut
from app.core.current_user import CurrentUserContext
from app.notifications.constants import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT
from app.services.errors import NotFoundError, ValidationError
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> NotificationService:
    return NotificationService(session, current_user.user_id)


def _not_found(exc: NotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{exc.resource} not found",
    )


@router.get("", response_model=NotificationListOut)
def list_notifications(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    service: NotificationService = Depends(_service),
) -> NotificationListOut:
    try:
        rows = service.list_notifications(status=status_filter, limit=limit)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        )
    return NotificationListOut(
        notifications=[NotificationOut.from_model(row) for row in rows]
    )


@router.get("/{notification_id}", response_model=NotificationOut)
def get_notification(
    notification_id: UUID,
    service: NotificationService = Depends(_service),
) -> NotificationOut:
    try:
        notification = service.get(notification_id)
    except NotFoundError as exc:
        raise _not_found(exc)
    return NotificationOut.from_model(notification)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def read_notification(
    notification_id: UUID,
    service: NotificationService = Depends(_service),
) -> NotificationOut:
    try:
        notification = service.mark_read(notification_id)
    except NotFoundError as exc:
        raise _not_found(exc)
    return NotificationOut.from_model(notification)


@router.post("/{notification_id}/accept", response_model=NotificationOut)
def accept_notification(
    notification_id: UUID,
    service: NotificationService = Depends(_service),
) -> NotificationOut:
    try:
        notification = service.accept(notification_id)
    except NotFoundError as exc:
        raise _not_found(exc)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        )
    return NotificationOut.from_model(notification)


@router.post("/{notification_id}/ignore", response_model=NotificationOut)
def ignore_notification(
    notification_id: UUID,
    service: NotificationService = Depends(_service),
) -> NotificationOut:
    try:
        notification = service.ignore(notification_id)
    except NotFoundError as exc:
        raise _not_found(exc)
    return NotificationOut.from_model(notification)


@router.post("/{notification_id}/resolve", response_model=NotificationOut)
def resolve_notification(
    notification_id: UUID,
    service: NotificationService = Depends(_service),
) -> NotificationOut:
    try:
        notification = service.resolve(notification_id)
    except NotFoundError as exc:
        raise _not_found(exc)
    return NotificationOut.from_model(notification)
