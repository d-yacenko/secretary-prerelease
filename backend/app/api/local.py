import json
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.current_user import CurrentUserContext
from app.local.constants import MAX_REPORT_BATCH
from app.local.errors import LocalAccessError, LocalFileError, LocalPathError
from app.local.paths import LocalPathResolver
from app.resources.request_bounds import read_bounded_body
from app.services.client_file_intake_service import ClientFileIntakeService
from app.services.client_intake_constants import MAX_CLIENT_INTAKE_REQUEST_BYTES
from app.services.dataset_tool_service import DatasetToolService
from app.services.errors import NotFoundError, ValidationError
from app.services.job_queue_service import JobQueueService
from app.services.local_device_service import LocalDeviceService
from app.services.local_file_sync_service import LocalFileReport, LocalFileSyncService
from app.services.local_folder_intake_service import LocalFolderIntakeService

router = APIRouter(tags=["local"])

_CLIENT_INTAKE_PAYLOAD_TOO_LARGE = "client intake payload exceeds size limit"


def _path_resolver() -> LocalPathResolver:
    return LocalPathResolver(Path(settings.local_files_root))


def _device_service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> LocalDeviceService:
    return LocalDeviceService(session, current_user.user_id, _path_resolver())


def _sync_service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> LocalFileSyncService:
    return LocalFileSyncService(
        session=session,
        user_id=current_user.user_id,
        path_resolver=_path_resolver(),
        job_queue=JobQueueService(session),
        upload_root=Path(settings.resource_upload_root),
    )


def _dataset_service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> DatasetToolService:
    return DatasetToolService(
        session=session,
        user_id=current_user.user_id,
        path_resolver=_path_resolver(),
        upload_root=Path(settings.resource_upload_root),
    )


class LocalDeviceRegisterRequest(BaseModel):
    device_key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)


class LocalDeviceRegisterOut(BaseModel):
    device_id: UUID
    device_key: str
    display_name: str
    created: bool


class LocalRootRegisterRequest(BaseModel):
    device_key: str = Field(min_length=1, max_length=128)
    root_path: str = Field(min_length=1, max_length=512)
    default_policy: str = "metadata_only"
    client_source_path: str | None = Field(default=None, max_length=1024)


class LocalRootRegisterOut(BaseModel):
    root_id: UUID
    device_key: str
    root_path: str
    default_policy: str
    created: bool


class LocalFileReportItem(BaseModel):
    relative_path: str = Field(min_length=1, max_length=512)
    size: int = Field(ge=0)
    modified_at: str = Field(min_length=1)
    content_hash: str | None = None
    policy: str | None = None
    client_source_path: str | None = Field(default=None, max_length=1024)


class LocalFilesReportRequest(BaseModel):
    device_key: str = Field(min_length=1, max_length=128)
    root_path: str = Field(min_length=1, max_length=512)
    files: list[LocalFileReportItem] = Field(min_length=1, max_length=MAX_REPORT_BATCH)


class LocalSyncOut(BaseModel):
    objects_created: int
    objects_updated: int
    objects_unchanged: int
    ingest_jobs_enqueued: int
    items_seen: int
    items_truncated: bool


class DatasetQueryRequest(BaseModel):
    columns: list[str] = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=50)


class ClientRepresentationItem(BaseModel):
    model_config = {"extra": "forbid"}

    kind: str = Field(min_length=1, max_length=32)
    text: str = ""
    part_index: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClientFileIntakeRequest(BaseModel):
    model_config = {"extra": "forbid"}

    device_key: str = Field(min_length=1, max_length=128)
    source_path: str = Field(min_length=1, max_length=1024)
    filename: str = Field(min_length=1, max_length=512)
    size: int = Field(ge=0)
    modified_at: str = Field(min_length=1, max_length=128)
    content_revision: str = Field(min_length=1, max_length=128)
    representations: list[ClientRepresentationItem] = Field(default_factory=list)
    content_hash: str | None = Field(default=None, max_length=128)
    metadata_only: bool = False
    root_path: str | None = Field(default=None, max_length=512)
    client_absolute_path: str | None = Field(default=None, max_length=1024)
    intake_mode: str | None = Field(default=None, max_length=32)


class ClientFileIntakeOut(BaseModel):
    object_id: UUID
    status: str
    jobs_enqueued: int
    representations_created: int
    metadata_only: bool


class ClientFolderIntakeRequest(BaseModel):
    model_config = {"extra": "forbid"}

    device_key: str = Field(min_length=1, max_length=128)
    root_path: str = Field(min_length=1, max_length=512)
    client_source_path: str = Field(min_length=1, max_length=1024)
    display_name: str | None = Field(default=None, max_length=128)


class ClientFolderIntakeOut(BaseModel):
    object_id: UUID
    status: str


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    if isinstance(exc, NotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        )
    if isinstance(exc, LocalPathError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    if isinstance(exc, LocalAccessError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    if isinstance(exc, LocalFileError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    raise exc


@router.post("/local/devices/register", status_code=status.HTTP_201_CREATED)
def register_local_device(
    data: LocalDeviceRegisterRequest,
    service: LocalDeviceService = Depends(_device_service),
) -> LocalDeviceRegisterOut:
    try:
        result = service.register_device(data.device_key, data.display_name)
    except (ValidationError, LocalPathError) as exc:
        raise _http_error(exc) from exc
    return LocalDeviceRegisterOut(
        device_id=result.device_id,
        device_key=result.device_key,
        display_name=result.display_name,
        created=result.created,
    )


@router.post("/local/roots/register", status_code=status.HTTP_201_CREATED)
def register_local_root(
    data: LocalRootRegisterRequest,
    service: LocalDeviceService = Depends(_device_service),
) -> LocalRootRegisterOut:
    try:
        result = service.register_root(
            data.device_key,
            data.root_path,
            default_policy=data.default_policy,
            client_source_path=data.client_source_path,
        )
    except (ValidationError, NotFoundError, LocalPathError) as exc:
        raise _http_error(exc) from exc
    return LocalRootRegisterOut(
        root_id=result.root_id,
        device_key=result.device_key,
        root_path=result.root_path,
        default_policy=result.default_policy,
        created=result.created,
    )


@router.post("/local/roots/{root_id}/scan")
def scan_local_root(
    root_id: UUID,
    service: LocalFileSyncService = Depends(_sync_service),
) -> LocalSyncOut:
    try:
        result = service.scan_root(root_id)
    except (ValidationError, NotFoundError, LocalPathError, LocalAccessError) as exc:
        raise _http_error(exc) from exc
    return LocalSyncOut(
        objects_created=result.objects_created,
        objects_updated=result.objects_updated,
        objects_unchanged=result.objects_unchanged,
        ingest_jobs_enqueued=result.ingest_jobs_enqueued,
        items_seen=result.items_seen,
        items_truncated=result.items_truncated,
    )


@router.post("/local/files/report")
def report_local_files(
    data: LocalFilesReportRequest,
    service: LocalFileSyncService = Depends(_sync_service),
) -> LocalSyncOut:
    reports = [
        LocalFileReport(
            relative_path=item.relative_path,
            size=item.size,
            modified_at=item.modified_at,
            content_hash=item.content_hash,
            policy=item.policy,
            client_source_path=item.client_source_path,
        )
        for item in data.files
    ]
    try:
        result = service.report_files(data.device_key, data.root_path, reports)
    except (ValidationError, NotFoundError, LocalPathError, LocalAccessError, LocalFileError) as exc:
        raise _http_error(exc) from exc
    return LocalSyncOut(
        objects_created=result.objects_created,
        objects_updated=result.objects_updated,
        objects_unchanged=result.objects_unchanged,
        ingest_jobs_enqueued=result.ingest_jobs_enqueued,
        items_seen=result.items_seen,
        items_truncated=result.items_truncated,
    )


@router.post("/local/files/client-intake", status_code=status.HTTP_201_CREATED)
async def client_file_intake(
    request: Request,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> ClientFileIntakeOut:
    device_service = LocalDeviceService(
        session, current_user.user_id, _path_resolver()
    )
    intake_service = ClientFileIntakeService(
        session, current_user.user_id, device_service
    )
    try:
        body = await read_bounded_body(
            request,
            MAX_CLIENT_INTAKE_REQUEST_BYTES,
            _CLIENT_INTAKE_PAYLOAD_TOO_LARGE,
        )
        try:
            data = ClientFileIntakeRequest.model_validate_json(body)
        except (json.JSONDecodeError, PydanticValidationError) as exc:
            raise ValidationError("request body must be valid JSON") from exc
        reps = [
            {
                "kind": item.kind,
                "text": item.text,
                "part_index": item.part_index,
                "metadata": item.metadata,
            }
            for item in data.representations
        ]
        result = intake_service.intake(
            device_key=data.device_key,
            source_path=data.source_path,
            filename=data.filename,
            size=data.size,
            modified_at=data.modified_at,
            content_revision=data.content_revision,
            representations=reps,
            content_hash=data.content_hash,
            metadata_only=data.metadata_only,
            root_path=data.root_path,
            client_absolute_path=data.client_absolute_path,
            intake_mode=data.intake_mode,
        )
    except ValidationError as exc:
        status_code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if exc.message == _CLIENT_INTAKE_PAYLOAD_TOO_LARGE
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=status_code, detail=exc.message) from exc
    except (NotFoundError, LocalPathError) as exc:
        raise _http_error(exc) from exc
    session.commit()
    return ClientFileIntakeOut(
        object_id=result.object_id,
        status=result.status,
        jobs_enqueued=result.jobs_enqueued,
        representations_created=result.representations_created,
        metadata_only=result.metadata_only,
    )


@router.post("/local/folders/client-intake", status_code=status.HTTP_201_CREATED, response_model=ClientFolderIntakeOut)
def client_folder_intake(
    body: ClientFolderIntakeRequest,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> ClientFolderIntakeOut:
    device_service = LocalDeviceService(
        session, current_user.user_id, _path_resolver()
    )
    folder_service = LocalFolderIntakeService(
        session, current_user.user_id, device_service
    )
    try:
        result = folder_service.intake_folder(
            device_key=body.device_key,
            root_path=body.root_path,
            client_source_path=body.client_source_path,
            display_name=body.display_name,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    session.commit()
    return ClientFolderIntakeOut(object_id=result.object_id, status=result.status)


@router.get("/datasets/{object_id}/schema")
def get_dataset_schema(
    object_id: UUID,
    service: DatasetToolService = Depends(_dataset_service),
) -> dict:
    try:
        return service.get_schema(object_id)
    except (ValidationError, NotFoundError, LocalAccessError, LocalFileError) as exc:
        raise _http_error(exc) from exc


@router.get("/datasets/{object_id}/sample")
def get_dataset_sample(
    object_id: UUID,
    limit: int = 5,
    service: DatasetToolService = Depends(_dataset_service),
) -> dict:
    try:
        return service.get_sample(object_id, limit=limit)
    except (ValidationError, NotFoundError, LocalAccessError, LocalFileError) as exc:
        raise _http_error(exc) from exc


@router.get("/datasets/{object_id}/stats")
def get_dataset_stats(
    object_id: UUID,
    service: DatasetToolService = Depends(_dataset_service),
) -> dict:
    try:
        return service.get_basic_stats(object_id)
    except (ValidationError, NotFoundError, LocalAccessError, LocalFileError) as exc:
        raise _http_error(exc) from exc


@router.post("/datasets/{object_id}/query")
def query_dataset_columns(
    object_id: UUID,
    data: DatasetQueryRequest,
    service: DatasetToolService = Depends(_dataset_service),
) -> dict:
    try:
        return service.query_columns(object_id, data.columns, limit=data.limit)
    except (ValidationError, NotFoundError, LocalAccessError, LocalFileError) as exc:
        raise _http_error(exc) from exc
