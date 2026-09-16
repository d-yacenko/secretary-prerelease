import json
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.schemas import ObjectOut, ResourceRegisterOut, ResourceRegisterRequest
from app.core.config import settings
from app.core.current_user import CurrentUserContext
from app.resources.constants import (
    MAX_MULTIPART_PAYLOAD_BYTES,
    MAX_REGISTER_PAYLOAD_BYTES,
    MAX_UPLOAD_BYTES,
)
from app.resources.request_bounds import read_bounded_body
from app.resources.upload_staging import stage_upload_file
from app.services.errors import ConflictError, ValidationError
from app.services.job_queue_service import JobQueueService
from app.services.resource_registration_service import ResourceRegistrationService

router = APIRouter()

_PAYLOAD_TOO_LARGE = "register payload exceeds size limit"


def _service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> ResourceRegistrationService:
    return ResourceRegistrationService(
        session=session,
        user_id=current_user.user_id,
        job_queue=JobQueueService(session),
        upload_root=Path(settings.resource_upload_root),
    )


@router.post(
    "/resources/register",
    status_code=status.HTTP_201_CREATED,
    response_model=ResourceRegisterOut,
)
async def register_resource(
    request: Request,
    service: ResourceRegistrationService = Depends(_service),
) -> ResourceRegisterOut:
    content_type = request.headers.get("content-type", "")
    staged_upload = None
    staging_dir = Path(settings.resource_upload_root) / "staging"
    try:
        if "multipart/form-data" in content_type:
            # Starlette applies one max_part_size per part; file ingest also streams
            # with MAX_UPLOAD_BYTES. Payload metadata is bounded post-parse too.
            form = await request.form(
                max_part_size=max(MAX_MULTIPART_PAYLOAD_BYTES, MAX_UPLOAD_BYTES),
            )
            payload_raw = form.get("payload")
            if payload_raw is None:
                raise ValidationError("multipart register requires payload field")
            payload_text = str(payload_raw)
            if len(payload_text.encode("utf-8")) > MAX_MULTIPART_PAYLOAD_BYTES:
                raise ValidationError(_PAYLOAD_TOO_LARGE)
            try:
                payload_data = json.loads(payload_text)
            except json.JSONDecodeError:
                raise ValidationError("multipart payload must be valid JSON")
            try:
                data = ResourceRegisterRequest.model_validate(payload_data)
            except PydanticValidationError as exc:
                raise ValidationError(str(exc)) from exc
            upload = form.get("file")
            if upload is not None and hasattr(upload, "read"):
                staged_upload = await stage_upload_file(upload, staging_dir)
        else:
            body = await read_bounded_body(
                request,
                MAX_REGISTER_PAYLOAD_BYTES,
                _PAYLOAD_TOO_LARGE,
            )
            try:
                data = ResourceRegisterRequest.model_validate_json(body)
            except (json.JSONDecodeError, PydanticValidationError) as exc:
                raise ValidationError("request body must be valid JSON") from exc

        result = service.register(data, staged_upload=staged_upload)
    except ValidationError as exc:
        status_code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if exc.message in {_PAYLOAD_TOO_LARGE, "upload exceeds size limit"}
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=status_code, detail=exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    finally:
        if staged_upload is not None:
            staged_upload.path.unlink(missing_ok=True)

    return ResourceRegisterOut(
        object_id=result.object_id,
        status=result.status,
        kind=result.kind,
        title=result.title,
        canonical_uri=result.canonical_uri,
        provider=result.provider,
        external_id=result.external_id,
        jobs_enqueued=result.jobs_enqueued,
        representations_created=result.representations_created,
    )


@router.get("/resources/{object_id}", response_model=ObjectOut)
def get_registered_resource(
    object_id: UUID,
    service: ResourceRegistrationService = Depends(_service),
) -> ObjectOut:
    from app.services.errors import NotFoundError

    try:
        obj = service.get_object_for_user(object_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc
    return ObjectOut.from_model(obj)
