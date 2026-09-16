from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Object, ObjectBookmark
from app.domain.object_bookmarks import BOOKMARK_COLORS, BOOKMARKS_BY_OBJECTS_MAX
from app.domain.object_visibility import object_is_active
from app.services.errors import NotFoundError, ValidationError
from app.services.provenance import REJECTED_STATE


@dataclass(frozen=True)
class BookmarkRecord:
    object_id: UUID
    color: str
    updated_at: datetime


class ObjectBookmarkService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def list_by_objects(self, object_ids: list[UUID]) -> dict[UUID, BookmarkRecord]:
        unique: list[UUID] = []
        seen: set[UUID] = set()
        for object_id in object_ids:
            if object_id in seen:
                continue
            seen.add(object_id)
            unique.append(object_id)
        if len(unique) > BOOKMARKS_BY_OBJECTS_MAX:
            raise ValidationError(
                f"at most {BOOKMARKS_BY_OBJECTS_MAX} object_ids are allowed"
            )
        if not unique:
            return {}
        rows = self._session.execute(
            select(ObjectBookmark)
            .join(Object, Object.id == ObjectBookmark.object_id)
            .where(
                ObjectBookmark.user_id == self._user_id,
                ObjectBookmark.object_id.in_(unique),
                Object.user_id == self._user_id,
                Object.state != REJECTED_STATE,
                object_is_active(Object),
            )
        ).scalars()
        return {
            row.object_id: BookmarkRecord(
                object_id=row.object_id,
                color=row.color,
                updated_at=row.updated_at,
            )
            for row in rows
        }

    def upsert(self, object_id: UUID, color: str) -> BookmarkRecord:
        if color not in BOOKMARK_COLORS:
            raise ValidationError("invalid bookmark color")
        obj = self._require_visible_object(object_id)
        stmt = insert(ObjectBookmark).values(
            user_id=self._user_id,
            object_id=obj.id,
            color=color,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ObjectBookmark.user_id, ObjectBookmark.object_id],
            set_={
                "color": stmt.excluded.color,
                "updated_at": func.now(),
            },
        )
        self._session.execute(stmt)
        self._session.flush()
        row = self._session.get(ObjectBookmark, (self._user_id, obj.id))
        assert row is not None
        self._session.refresh(row)
        return BookmarkRecord(object_id=row.object_id, color=row.color, updated_at=row.updated_at)

    def delete(self, object_id: UUID) -> bool:
        self._require_visible_object(object_id)
        result = self._session.execute(
            delete(ObjectBookmark).where(
                ObjectBookmark.user_id == self._user_id,
                ObjectBookmark.object_id == object_id,
            )
        )
        self._session.flush()
        return (result.rowcount or 0) > 0

    def delete_for_object(self, object_id: UUID) -> None:
        self._session.execute(
            delete(ObjectBookmark).where(ObjectBookmark.object_id == object_id)
        )
        self._session.flush()

    def _require_visible_object(self, object_id: UUID) -> Object:
        obj = self._session.scalar(
            select(Object).where(
                Object.id == object_id,
                Object.user_id == self._user_id,
                Object.state != REJECTED_STATE,
                object_is_active(Object),
            )
        )
        if obj is None:
            raise NotFoundError("object", object_id)
        return obj
