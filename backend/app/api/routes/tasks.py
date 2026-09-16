from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    EMBEDDING_PROVIDER_UNAVAILABLE,
    get_current_user,
    get_db,
)
from app.api.schemas import (
    ObjectOut,
    TaskMutationResponse,
    TaskPatchRequest,
    TaskStatusRequest,
    TaskStatusResponse,
)
from app.core.current_user import CurrentUserContext
from app.llm.embedding_service import EmbeddingService
from app.services.errors import NotFoundError, ValidationError
from app.services.task_mutation_service import TaskMutationService
from app.services.user_embedding_resolver import resolve_embedding_service_for_user
from app.services.user_openai_credential_errors import UserOpenAICredentialConfigurationError

router = APIRouter()


def _task_service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TaskMutationService:
    return TaskMutationService(session, current_user.user_id)


def _not_found(exc: NotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{exc.resource} not found",
    )


def _validation_error(exc: ValidationError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=exc.message,
    )


def _embedding_configuration_error(exc: UserOpenAICredentialConfigurationError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=EMBEDDING_PROVIDER_UNAVAILABLE,
    )


def _embedding_service_for_task_patch(
    data: TaskPatchRequest,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> EmbeddingService | None:
    if "title" not in data.model_fields_set and "body" not in data.model_fields_set:
        return None
    try:
        return resolve_embedding_service_for_user(session, current_user.user_id)
    except UserOpenAICredentialConfigurationError as exc:
        raise _embedding_configuration_error(exc) from exc


@router.patch("/tasks/{task_id}", response_model=TaskMutationResponse)
def patch_task(
    task_id: UUID,
    data: TaskPatchRequest,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
    embedding_service: EmbeddingService | None = Depends(_embedding_service_for_task_patch),
) -> TaskMutationResponse:
    service = TaskMutationService(session, current_user.user_id, embedding_service)
    try:
        result = service.patch_task_fields(
            task_id,
            title=data.title if "title" in data.model_fields_set else None,
            body=data.body if "body" in data.model_fields_set else None,
            due_at=data.due_at if "due_at" in data.model_fields_set else None,
            fields_set=set(data.model_fields_set),
        )
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    return TaskMutationResponse(
        object=ObjectOut.from_model(result.object),
        changed=result.changed,
    )


@router.post("/tasks/{task_id}/status", response_model=TaskStatusResponse)
def set_task_status(
    task_id: UUID,
    data: TaskStatusRequest,
    service: TaskMutationService = Depends(_task_service),
) -> TaskStatusResponse:
    try:
        result = service.set_task_status(task_id, data.status)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    return TaskStatusResponse(
        object=ObjectOut.from_model(result.object),
        changed=result.changed,
        previous_status=result.previous_status,
        new_status=result.new_status,
    )


@router.delete("/tasks/{task_id}", response_model=TaskStatusResponse)
def delete_task(
    task_id: UUID,
    service: TaskMutationService = Depends(_task_service),
) -> TaskStatusResponse:
    try:
        result = service.soft_delete_task(task_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    return TaskStatusResponse(
        object=ObjectOut.from_model(result.object),
        changed=result.changed,
        previous_status=result.previous_status,
        new_status=result.new_status,
    )
