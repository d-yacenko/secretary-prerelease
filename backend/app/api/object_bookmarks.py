from datetime import datetime
from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.current_user import CurrentUserContext
from app.services.errors import NotFoundError, ValidationError
from app.services.object_bookmark_service import BookmarkRecord, ObjectBookmarkService

router = APIRouter()


class BookmarksByObjectsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_ids: list[UUID]


class BookmarkColorOut(BaseModel):
    color: str


class BookmarksByObjectsOut(BaseModel):
    objects: dict[str, BookmarkColorOut]


class BookmarkPutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    color: str


class BookmarkWriteOut(BaseModel):
    object_id: UUID
    color: str
    updated_at: datetime


class BookmarkDeleteOut(BaseModel):
    object_id: UUID
    changed: bool


def _service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> ObjectBookmarkService:
    return ObjectBookmarkService(session, current_user.user_id)


def _raise_domain(exc: Exception) -> NoReturn:
    if isinstance(exc, NotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{exc.resource} not found"
        ) from exc
    if isinstance(exc, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
        ) from exc
    raise exc


def _write_out(record: BookmarkRecord) -> BookmarkWriteOut:
    return BookmarkWriteOut(
        object_id=record.object_id,
        color=record.color,
        updated_at=record.updated_at,
    )


@router.post("/object-bookmarks/by-objects", response_model=BookmarksByObjectsOut)
def bookmarks_by_objects(
    payload: BookmarksByObjectsRequest,
    service: ObjectBookmarkService = Depends(_service),
) -> BookmarksByObjectsOut:
    try:
        grouped = service.list_by_objects(payload.object_ids)
    except (NotFoundError, ValidationError) as exc:
        _raise_domain(exc)
    return BookmarksByObjectsOut(
        objects={
            str(object_id): BookmarkColorOut(color=record.color)
            for object_id, record in grouped.items()
        }
    )


@router.put("/object-bookmarks/{object_id}", response_model=BookmarkWriteOut)
def put_object_bookmark(
    object_id: UUID,
    payload: BookmarkPutRequest,
    service: ObjectBookmarkService = Depends(_service),
) -> BookmarkWriteOut:
    try:
        record = service.upsert(object_id, payload.color)
    except (NotFoundError, ValidationError) as exc:
        _raise_domain(exc)
    return _write_out(record)


@router.delete("/object-bookmarks/{object_id}", response_model=BookmarkDeleteOut)
def delete_object_bookmark(
    object_id: UUID,
    service: ObjectBookmarkService = Depends(_service),
) -> BookmarkDeleteOut:
    try:
        changed = service.delete(object_id)
    except (NotFoundError, ValidationError) as exc:
        _raise_domain(exc)
    return BookmarkDeleteOut(object_id=object_id, changed=changed)
