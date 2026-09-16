"""Secretary-local tombstone deletion for any object kind."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Object
from app.domain.object_visibility import is_object_tombstoned, tombstone_object
from app.services.errors import NotFoundError
from app.services.object_bookmark_service import ObjectBookmarkService


@dataclass(frozen=True)
class ObjectDeleteResult:
    object: Object
    deleted_at: datetime
    already_deleted: bool


class ObjectDeletionService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def _get_owned_object(self, object_id: UUID) -> Object:
        obj = self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if obj is None:
            raise NotFoundError("object", object_id)
        return obj

    def delete_object(self, object_id: UUID) -> ObjectDeleteResult:
        obj = self._get_owned_object(object_id)
        if is_object_tombstoned(obj):
            return ObjectDeleteResult(
                object=obj,
                deleted_at=obj.deleted_at,
                already_deleted=True,
            )
        deleted_at = datetime.now(UTC)
        tombstone_object(obj, when=deleted_at)
        ObjectBookmarkService(self._session, self._user_id).delete_for_object(object_id)
        self._session.flush()
        return ObjectDeleteResult(
            object=obj,
            deleted_at=deleted_at,
            already_deleted=False,
        )
