from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    EMBEDDING_PROVIDER_UNAVAILABLE,
    get_current_user,
    get_db,
)
from app.api.schemas import (
    EdgeOut,
    ObjectOut,
    TaskActorAttachRequest,
    TaskDependencyAttachRequest,
    TaskEvidenceAttachRequest,
    TaskMutationResponse,
    TaskPatchRequest,
    TaskProfileOut,
    TaskRelationMutationResponse,
    TaskStatusRequest,
    TaskStatusResponse,
)
from app.core.current_user import CurrentUserContext
from app.llm.embedding_service import EmbeddingService
from app.services.errors import NotFoundError, ValidationError
from app.services.task_mutation_service import TaskMutationService
from app.services.task_profile_service import TaskProfileService
from app.services.task_relation_service import TaskRelationService
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


def _relations(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TaskRelationService:
    return TaskRelationService(session, current_user.user_id)


def _profile(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TaskProfileService:
    return TaskProfileService(session, current_user.user_id)


def _relation_response(edge, *, created: bool = False, changed: bool = False) -> TaskRelationMutationResponse:
    return TaskRelationMutationResponse(
        edge=EdgeOut.from_model(edge),
        created=created,
        changed=changed,
    )


@router.get("/tasks/{task_id}/profile", response_model=TaskProfileOut)
def get_task_profile(
    task_id: UUID,
    service: TaskProfileService = Depends(_profile),
) -> TaskProfileOut:
    try:
        return service.get_profile(task_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/tasks/{task_id}/actors", response_model=TaskRelationMutationResponse)
def add_task_actor(
    task_id: UUID,
    data: TaskActorAttachRequest,
    service: TaskRelationService = Depends(_relations),
) -> TaskRelationMutationResponse:
    try:
        edge, created = service.add_actor(task_id, data.person_id, data.role)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    return _relation_response(edge, created=created, changed=created)


@router.delete("/tasks/{task_id}/actors/{edge_id}", response_model=TaskRelationMutationResponse)
def remove_task_actor(
    task_id: UUID,
    edge_id: UUID,
    service: TaskRelationService = Depends(_relations),
) -> TaskRelationMutationResponse:
    try:
        edge, changed = service.remove_actor(task_id, edge_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    return _relation_response(edge, changed=changed)


@router.post("/tasks/{task_id}/dependencies", response_model=TaskRelationMutationResponse)
def add_task_dependency(
    task_id: UUID,
    data: TaskDependencyAttachRequest,
    service: TaskRelationService = Depends(_relations),
) -> TaskRelationMutationResponse:
    try:
        edge, created = service.add_dependency(task_id, data.depends_on_task_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    return _relation_response(edge, created=created, changed=created)


@router.delete("/tasks/{task_id}/dependencies/{edge_id}", response_model=TaskRelationMutationResponse)
def remove_task_dependency(
    task_id: UUID,
    edge_id: UUID,
    service: TaskRelationService = Depends(_relations),
) -> TaskRelationMutationResponse:
    try:
        edge, changed = service.remove_dependency(task_id, edge_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    return _relation_response(edge, changed=changed)


@router.post("/tasks/{task_id}/evidence", response_model=TaskRelationMutationResponse)
def attach_task_evidence(
    task_id: UUID,
    data: TaskEvidenceAttachRequest,
    service: TaskRelationService = Depends(_relations),
) -> TaskRelationMutationResponse:
    try:
        edge, created = service.attach_evidence(task_id, data.object_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    return _relation_response(edge, created=created, changed=created)
