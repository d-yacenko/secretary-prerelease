"""Central tombstone visibility helpers for Secretary-local object deletion."""

from datetime import UTC, datetime

from sqlalchemy import ColumnElement, and_, or_

from app.db.models import Object
from app.domain.task_lifecycle import TASK_STATUS_DELETED


def is_object_tombstoned(obj: Object) -> bool:
    return obj.deleted_at is not None


def is_legacy_status_deleted(obj: Object) -> bool:
    return obj.status == TASK_STATUS_DELETED


def is_object_hidden_from_active_reads(obj: Object) -> bool:
    return is_object_tombstoned(obj) or is_legacy_status_deleted(obj)


def object_is_active(column: type[Object] = Object) -> ColumnElement[bool]:
    return and_(
        column.deleted_at.is_(None),
        or_(column.status.is_(None), column.status != TASK_STATUS_DELETED),
    )


def object_active_sql_fragment() -> str:
    return "o.deleted_at IS NULL AND (o.status IS NULL OR o.status != 'deleted')"


def restore_object_from_explicit_intake(obj: Object) -> bool:
    changed = False
    if obj.deleted_at is not None:
        obj.deleted_at = None
        changed = True
    if obj.status == TASK_STATUS_DELETED:
        obj.status = None
        changed = True
    return changed


def tombstone_object(obj: Object, *, when: datetime | None = None) -> bool:
    if obj.deleted_at is not None:
        return False
    obj.deleted_at = when or datetime.now(UTC)
    if obj.kind == "task":
        obj.status = TASK_STATUS_DELETED
    return True


def passive_sync_should_skip_existing(existing: Object) -> bool:
    return is_object_hidden_from_active_reads(existing)
