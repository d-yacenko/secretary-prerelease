"""Canonical task field/status/delete mutations for tools and direct REST."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.schemas import ObjectUpdate
from app.db.models import Object
from app.domain.object_visibility import is_object_tombstoned
from app.domain.task_lifecycle import (
    SET_TASK_STATUS_VALUES,
    TASK_STATUS_DELETED,
)
from app.llm.embedding_service import EmbeddingService
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.object_deletion_service import ObjectDeletionService
from app.tools.datetime_utils import normalize_tool_datetime


@dataclass(frozen=True)
class TaskPatchResult:
    object: Object
    changed: bool


@dataclass(frozen=True)
class TaskStatusResult:
    object: Object
    changed: bool
    previous_status: str | None
    new_status: str


@dataclass(frozen=True)
class TaskDeleteResult:
    object: Object
    changed: bool
    previous_status: str | None
    new_status: str


class TaskMutationService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self._graph = GraphService(session, user_id, embedding_service)

    def _get_task(self, task_id: UUID, *, allow_deleted: bool = False) -> Object:
        try:
            obj = self._graph.get_object(task_id)
        except NotFoundError:
            raise
        if obj.kind != "task":
            raise ValidationError("operation only supports task objects")
        if not allow_deleted and (
            is_object_tombstoned(obj) or obj.status == TASK_STATUS_DELETED
        ):
            raise ValidationError("deleted task cannot be modified")
        return obj

    def _effective_field_updates(self, obj: Object, update_data: dict) -> dict:
        effective: dict = {}
        if "title" in update_data and update_data["title"] != obj.title:
            effective["title"] = update_data["title"]
        if "body" in update_data and update_data["body"] != obj.body:
            effective["body"] = update_data["body"]
        if "due_at" in update_data and update_data["due_at"] != obj.due_at:
            effective["due_at"] = update_data["due_at"]
        return effective

    def patch_task_fields(
        self,
        task_id: UUID,
        *,
        title: str | None = None,
        body: str | None = None,
        due_at: datetime | None = None,
        fields_set: set[str],
    ) -> TaskPatchResult:
        obj = self._get_task(task_id)
        update_data: dict = {}
        if "title" in fields_set:
            if title is None:
                raise ValidationError("title cannot be null or empty")
            if not title.strip():
                raise ValidationError("title cannot be null or empty")
            update_data["title"] = title
        if "body" in fields_set:
            update_data["body"] = body
        if "due_at" in fields_set:
            update_data["due_at"] = normalize_tool_datetime(due_at)

        if not update_data:
            raise ValidationError("at least one editable field must be supplied")

        effective = self._effective_field_updates(obj, update_data)
        if not effective:
            return TaskPatchResult(object=obj, changed=False)

        try:
            updated = self._graph.update_object(task_id, ObjectUpdate(**effective))
        except ValidationError as exc:
            raise ValidationError(exc.message) from exc
        except ConflictError as exc:
            raise ValidationError(exc.message) from exc
        return TaskPatchResult(object=updated, changed=True)

    def set_task_status(self, task_id: UUID, status: str) -> TaskStatusResult:
        if status not in SET_TASK_STATUS_VALUES:
            raise ValidationError(f"invalid task status: {status}")
        obj = self._get_task(task_id)
        previous_status = obj.status
        if obj.status == status:
            return TaskStatusResult(
                object=obj,
                changed=False,
                previous_status=previous_status,
                new_status=status,
            )
        try:
            updated = self._graph.update_object(task_id, ObjectUpdate(status=status))
        except ValidationError as exc:
            raise ValidationError(exc.message) from exc
        except ConflictError as exc:
            raise ValidationError(exc.message) from exc
        return TaskStatusResult(
            object=updated,
            changed=True,
            previous_status=previous_status,
            new_status=status,
        )

    def soft_delete_task(self, task_id: UUID) -> TaskDeleteResult:
        service = ObjectDeletionService(self._graph._session, self._graph._user_id)
        obj = service._get_owned_object(task_id)
        if obj.kind != "task":
            raise ValidationError("operation only supports task objects")
        previous_status = obj.status
        result = service.delete_object(task_id)
        return TaskDeleteResult(
            object=result.object,
            changed=not result.already_deleted,
            previous_status=previous_status,
            new_status=TASK_STATUS_DELETED,
        )
