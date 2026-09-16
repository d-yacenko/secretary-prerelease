from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.current_user import CurrentUserContext
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.label_service import LabelRecord, LabelService, label_description
from app.tools.schemas import LabelItemOut

router = APIRouter()


class LabelCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None


class LabelPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None


class LabelWriteOut(BaseModel):
    label: LabelItemOut
    created: bool | None = None
    changed: bool | None = None


class LabelListOut(BaseModel):
    labels: list[LabelItemOut]


class ObjectLabelsOut(BaseModel):
    labels: list[LabelItemOut]


class LabelsByObjectsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_ids: list[UUID]


class ObjectLabelProjectionOut(BaseModel):
    id: UUID
    title: str
    description: str | None = None


class LabelsByObjectsOut(BaseModel):
    objects: dict[str, list[ObjectLabelProjectionOut]]


class AssignLabelOut(BaseModel):
    object_id: UUID
    label_id: UUID
    created: bool


class RemoveLabelOut(BaseModel):
    object_id: UUID
    label_id: UUID
    changed: bool


def _service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> LabelService:
    return LabelService(session, current_user.user_id)


def _not_found(exc: NotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{exc.resource} not found")


def _item(record: LabelRecord) -> LabelItemOut:
    return LabelItemOut(
        id=record.id,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
        description=record.description,
        object_count=record.object_count,
    )


def _item_from_object(label, *, object_count: int = 0) -> LabelItemOut:
    return LabelItemOut(
        id=label.id,
        title=label.title,
        created_at=label.created_at,
        updated_at=label.updated_at,
        description=label_description(label),
        object_count=object_count,
    )


def _raise_domain(exc: Exception) -> NoReturn:
    if isinstance(exc, NotFoundError):
        raise _not_found(exc) from exc
    if isinstance(exc, ConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    if isinstance(exc, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
        ) from exc
    raise exc


@router.get("/labels", response_model=LabelListOut)
def list_labels(
    limit: int = Query(default=100, ge=1, le=200),
    service: LabelService = Depends(_service),
) -> LabelListOut:
    return LabelListOut(labels=[_item(row) for row in service.list_labels(limit=limit)])


@router.post("/labels/by-objects", response_model=LabelsByObjectsOut)
def labels_by_objects(
    payload: LabelsByObjectsRequest,
    service: LabelService = Depends(_service),
) -> LabelsByObjectsOut:
    try:
        grouped = service.list_labels_by_objects(payload.object_ids)
    except (NotFoundError, ConflictError, ValidationError) as exc:
        _raise_domain(exc)
    return LabelsByObjectsOut(
        objects={
            str(object_id): [
                ObjectLabelProjectionOut(
                    id=row.id,
                    title=row.title,
                    description=row.description,
                )
                for row in rows
            ]
            for object_id, rows in grouped.items()
        }
    )


@router.post("/labels", response_model=LabelWriteOut)
def create_label(
    payload: LabelCreateRequest,
    service: LabelService = Depends(_service),
) -> LabelWriteOut:
    try:
        result = service.create_label(payload.name, description=payload.description)
    except (NotFoundError, ConflictError, ValidationError) as exc:
        _raise_domain(exc)
    return LabelWriteOut(label=_item_from_object(result.label), created=result.created)


@router.patch("/labels/{label_id}", response_model=LabelWriteOut)
def update_label(
    label_id: UUID,
    payload: LabelPatchRequest,
    service: LabelService = Depends(_service),
) -> LabelWriteOut:
    if not payload.model_fields_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="no fields to update",
        )
    try:
        result = service.update_label(
            label_id,
            name=payload.name,
            description=payload.description,
            name_set="name" in payload.model_fields_set,
            description_set="description" in payload.model_fields_set,
        )
    except (NotFoundError, ConflictError, ValidationError) as exc:
        _raise_domain(exc)
    return LabelWriteOut(label=_item_from_object(result.label), changed=result.changed)


@router.delete("/labels/{label_id}", response_model=LabelWriteOut)
def delete_label(
    label_id: UUID,
    service: LabelService = Depends(_service),
) -> LabelWriteOut:
    try:
        result = service.delete_label(label_id)
    except (NotFoundError, ConflictError, ValidationError) as exc:
        _raise_domain(exc)
    return LabelWriteOut(label=_item_from_object(result.label), changed=result.changed)


@router.get("/objects/{object_id}/labels", response_model=ObjectLabelsOut)
def get_object_labels(
    object_id: UUID,
    service: LabelService = Depends(_service),
) -> ObjectLabelsOut:
    try:
        rows = service.get_object_labels(object_id)
    except (NotFoundError, ConflictError, ValidationError) as exc:
        _raise_domain(exc)
    return ObjectLabelsOut(labels=[_item(row) for row in rows])


@router.post("/objects/{object_id}/labels/{label_id}", response_model=AssignLabelOut)
def assign_label(
    object_id: UUID,
    label_id: UUID,
    service: LabelService = Depends(_service),
) -> AssignLabelOut:
    try:
        result = service.assign_label(object_id, label_id)
    except (NotFoundError, ConflictError, ValidationError) as exc:
        _raise_domain(exc)
    return AssignLabelOut(object_id=object_id, label_id=label_id, created=result.created)


@router.delete("/objects/{object_id}/labels/{label_id}", response_model=RemoveLabelOut)
def remove_object_label(
    object_id: UUID,
    label_id: UUID,
    service: LabelService = Depends(_service),
) -> RemoveLabelOut:
    try:
        result = service.remove_label(object_id, label_id)
    except (NotFoundError, ConflictError, ValidationError) as exc:
        _raise_domain(exc)
    return RemoveLabelOut(object_id=object_id, label_id=label_id, changed=result.changed)
