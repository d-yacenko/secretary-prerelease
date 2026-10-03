"""Frozen semantic snapshots for internal approval cards.

Built once at plan creation from user-owned state. Execution never reads it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Edge, Object

TITLE_MAX_CHARS = 120
MAX_LINKED_ENTITIES = 8

_INTERNAL_TOOLS = frozenset(
    {
        "create_task",
        "update_task",
        "set_task_status",
        "delete_task",
        "link_objects",
        "remove_relation",
        "create_scheduled_activity",
        "assign_person_role",
        "retract_person_role",
    }
)
_UPDATE_FIELDS = (
    "title",
    "due_at",
    "planned_start_at",
    "planned_end_at",
    "completion_mode",
)
_SCHEDULE_FIELDS = ("title", "run_at", "priority")


def attach_approval_presentations(
    session: Session,
    user_id: UUID,
    actions: list[dict[str, Any]],
) -> None:
    for action in actions:
        if not isinstance(action, dict):
            continue
        action.pop("presentation", None)
        snapshot = build_approval_presentation(session, user_id, action)
        if snapshot is not None:
            action["presentation"] = snapshot


def build_approval_presentation(
    session: Session,
    user_id: UUID,
    action: dict[str, Any],
) -> dict[str, Any] | None:
    tool_name = action.get("tool_name")
    if tool_name not in _INTERNAL_TOOLS:
        return None
    arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
    if tool_name == "create_task":
        return _create_task(arguments)
    if tool_name == "update_task":
        return _update_task(session, user_id, arguments)
    if tool_name == "set_task_status":
        return _set_status(session, user_id, arguments)
    if tool_name == "delete_task":
        return _delete_task(session, user_id, arguments)
    if tool_name == "link_objects":
        return _link(session, user_id, arguments)
    if tool_name == "remove_relation":
        return _remove(session, user_id, arguments)
    if tool_name == "create_scheduled_activity":
        return _scheduled(arguments)
    if tool_name == "assign_person_role":
        return _assign_person_role(session, user_id, arguments)
    if tool_name == "retract_person_role":
        return _retract_person_role(session, user_id, arguments)
    return None


def _create_task(arguments: dict[str, Any]) -> dict[str, Any]:
    mode = arguments.get("completion_mode")
    operation = "create_direction" if mode == "ongoing" else "create_task"
    return {"operation": operation, "entities": [], "fields": _fields(arguments, ("title", *_UPDATE_FIELDS[1:]))}


def _update_task(session: Session, user_id: UUID, arguments: dict[str, Any]) -> dict[str, Any]:
    entities = []
    target = _entity(session, user_id, arguments.get("object_id"), "target")
    if target is not None:
        entities.append(target)
    entities.extend(_linked(session, user_id, arguments.get("waiting_on_person_ids"), "waiting_on"))
    entities.extend(_linked(session, user_id, arguments.get("evidence_object_ids"), "evidence"))
    return {
        "operation": "update_task",
        "entities": entities,
        "fields": _fields(arguments, _UPDATE_FIELDS),
    }


def _set_status(session: Session, user_id: UUID, arguments: dict[str, Any]) -> dict[str, Any]:
    target = _entity(session, user_id, arguments.get("object_id"), "target")
    fields = []
    if target is not None and target.get("status") is not None:
        fields.append({"name": "current_status", "value": target["status"]})
    if "status" in arguments:
        fields.append({"name": "status", "value": _scalar(arguments.get("status"))})
    return {
        "operation": "set_task_status",
        "entities": [target] if target is not None else [],
        "fields": fields,
    }


def _delete_task(session: Session, user_id: UUID, arguments: dict[str, Any]) -> dict[str, Any]:
    target = _entity(session, user_id, arguments.get("object_id"), "target")
    return {
        "operation": "delete_task",
        "entities": [target] if target is not None else [],
        "fields": [],
    }


def _link(session: Session, user_id: UUID, arguments: dict[str, Any]) -> dict[str, Any]:
    source = _entity(session, user_id, arguments.get("source_id"), "source")
    target = _entity(session, user_id, arguments.get("target_id"), "target")
    entities = [item for item in (source, target) if item is not None]
    relation = arguments.get("type") if isinstance(arguments.get("type"), str) else None
    snapshot: dict[str, Any] = {"operation": "link_objects", "entities": entities, "fields": []}
    if relation:
        snapshot["relation_type"] = relation.strip()[:64]
    return snapshot


def _remove(session: Session, user_id: UUID, arguments: dict[str, Any]) -> dict[str, Any]:
    edge = _owned_edge(session, user_id, arguments.get("edge_id"))
    entities: list[dict[str, Any]] = []
    relation = None
    if edge is not None:
        source = _entity(session, user_id, edge.source_id, "source")
        target = _entity(session, user_id, edge.target_id, "target")
        entities = [item for item in (source, target) if item is not None]
        relation = edge.type
    snapshot: dict[str, Any] = {
        "operation": "remove_relation",
        "entities": entities,
        "fields": [],
    }
    if relation:
        snapshot["relation_type"] = relation
    return snapshot


def _assign_person_role(
    session: Session, user_id: UUID, arguments: dict[str, Any]
) -> dict[str, Any]:
    target = _entity(session, user_id, arguments.get("person_id"), "target")
    mode = "create_if_missing" if arguments.get("create_if_missing") else "reuse_existing"
    fields = [{"name": "role", "value": _scalar(arguments.get("role"))}]
    if arguments.get("context"):
        fields.append({"name": "context", "value": _scalar(arguments.get("context"))})
    fields.append({"name": "vocabulary_mode", "value": mode})
    return {
        "operation": "assign_person_role",
        "entities": [target] if target is not None else [],
        "fields": fields,
    }


def _retract_person_role(
    session: Session, user_id: UUID, arguments: dict[str, Any]
) -> dict[str, Any]:
    target = _entity(session, user_id, arguments.get("person_id"), "target")
    fields = [{"name": "role", "value": _scalar(arguments.get("role"))}]
    if arguments.get("context"):
        fields.append({"name": "context", "value": _scalar(arguments.get("context"))})
    return {
        "operation": "retract_person_role",
        "entities": [target] if target is not None else [],
        "fields": fields,
    }


def _scheduled(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation": "create_scheduled_activity",
        "entities": [],
        "fields": _fields(arguments, _SCHEDULE_FIELDS),
    }


def _fields(arguments: dict[str, Any], names: tuple[str, ...]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for name in names:
        if name not in arguments:
            continue
        fields.append({"name": name, "value": _scalar(arguments.get(name))})
    return fields


def _scalar(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _bound_title(value) if value.strip() else value
    return str(value)[:TITLE_MAX_CHARS]


def _linked(
    session: Session,
    user_id: UUID,
    raw_ids: object,
    role: str,
) -> list[dict[str, Any]]:
    if not isinstance(raw_ids, list):
        return []
    entities: list[dict[str, Any]] = []
    for raw in raw_ids[:MAX_LINKED_ENTITIES]:
        entity = _entity(session, user_id, raw, role)
        if entity is not None:
            entities.append(entity)
    return entities


def _entity(session: Session, user_id: UUID, raw_id: object, role: str) -> dict[str, Any] | None:
    object_id = _uuid(raw_id)
    if object_id is None:
        return None
    row = session.get(Object, object_id)
    if row is None or row.user_id != user_id:
        return None
    entity: dict[str, Any] = {
        "role": role,
        "id": str(row.id),
        "title": _bound_title(row.title),
        "kind": row.kind,
    }
    if row.status:
        entity["status"] = row.status
    return entity


def _owned_edge(session: Session, user_id: UUID, raw_id: object) -> Edge | None:
    edge_id = _uuid(raw_id)
    if edge_id is None:
        return None
    edge = session.scalar(select(Edge).where(Edge.id == edge_id, Edge.user_id == user_id))
    return edge


def _uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return UUID(value.strip())
    except ValueError:
        return None


def _bound_title(title: str) -> str:
    compact = " ".join(title.split())
    if len(compact) <= TITLE_MAX_CHARS:
        return compact
    return compact[: TITLE_MAX_CHARS - 1].rstrip() + "…"
