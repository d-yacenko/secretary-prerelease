from typing import Any
from uuid import UUID


def collect_object_ids_from_bounded_tool(
    tool_name: str,
    bounded: dict[str, Any],
    candidate_ids: list[UUID],
    affected_ids: list[UUID],
) -> None:
    if tool_name == "search_objects":
        for obj in bounded.get("objects", []):
            _append_uuid(candidate_ids, obj.get("id"))
    elif tool_name == "query_objects":
        for row in bounded.get("objects", []):
            _append_uuid(candidate_ids, row.get("object_id"))
    elif tool_name == "retrieve":
        for hit in bounded.get("hits", []):
            _append_uuid(candidate_ids, hit.get("object_id"))
    elif tool_name == "get_object":
        obj = bounded.get("object")
        if obj:
            _append_uuid(candidate_ids, obj.get("id"))
    elif tool_name == "get_context":
        for item in bounded.get("items", []):
            _append_uuid(candidate_ids, item.get("object_id"))
    elif tool_name == "list_neighbors":
        for neighbor in bounded.get("neighbors", []):
            obj = neighbor.get("object")
            if obj:
                _append_uuid(candidate_ids, obj.get("id"))
    elif tool_name == "list_inbox_since_review_marker":
        for item in bounded.get("items", []):
            _append_uuid(candidate_ids, item.get("object_id"))
        for item in bounded.get("compact_items", []):
            stack = item.get("stack") if isinstance(item, dict) else None
            if stack:
                for object_id in stack.get("object_ids") or []:
                    _append_uuid(candidate_ids, object_id)
            else:
                _append_uuid(candidate_ids, item.get("object_id"))
    elif tool_name == "list_conversation_members":
        for item in bounded.get("members", []):
            _append_uuid(candidate_ids, item.get("object_id"))
    elif tool_name == "remove_relation":
        edge = bounded.get("edge")
        if edge and bounded.get("changed"):
            _append_uuid(affected_ids, edge.get("source_id"))
            _append_uuid(affected_ids, edge.get("target_id"))
    elif tool_name == "link_objects":
        edge = bounded.get("edge")
        if edge and bounded.get("created"):
            _append_uuid(affected_ids, edge.get("source_id"))
            _append_uuid(affected_ids, edge.get("target_id"))
    elif tool_name == "assign_label":
        if bounded.get("created"):
            _append_uuid(affected_ids, bounded.get("object_id"))
    elif tool_name == "remove_label":
        if bounded.get("changed"):
            _append_uuid(affected_ids, bounded.get("object_id"))
    elif tool_name in (
        "create_task",
        "update_task",
        "set_task_status",
        "delete_task",
        "create_scheduled_activity",
        "create_recurring_scheduled_activity",
        "cancel_scheduled_activity",
    ):
        obj = bounded.get("object")
        if obj:
            _append_uuid(candidate_ids, obj.get("id"))
            if tool_name == "create_task" or tool_name in (
                "create_scheduled_activity",
                "create_recurring_scheduled_activity",
            ) or tool_name == "update_task" and bounded.get("changed") or tool_name in ("set_task_status", "delete_task", "cancel_scheduled_activity") and bounded.get("changed"):
                _append_uuid(affected_ids, obj.get("id"))


def collect_seen_object_ids_from_bounded_tool(
    tool_name: str,
    bounded: dict[str, Any],
) -> list[UUID]:
    seen_ids: list[UUID] = []
    if tool_name == "search_objects":
        for obj in bounded.get("objects", []):
            _append_uuid(seen_ids, obj.get("id"))
    elif tool_name == "query_objects":
        for row in bounded.get("objects", []):
            _append_uuid(seen_ids, row.get("object_id"))
    elif tool_name == "retrieve":
        for hit in bounded.get("hits", []):
            _append_uuid(seen_ids, hit.get("object_id"))
    elif tool_name == "get_object":
        obj = bounded.get("object")
        if obj:
            _append_uuid(seen_ids, obj.get("id"))
    elif tool_name == "get_context":
        for item in bounded.get("items", []):
            _append_uuid(seen_ids, item.get("object_id"))
    elif tool_name == "list_neighbors":
        for neighbor in bounded.get("neighbors", []):
            obj = neighbor.get("object")
            if obj:
                _append_uuid(seen_ids, obj.get("id"))
    elif tool_name == "list_notifications":
        for row in bounded.get("notifications", []):
            _append_uuid(seen_ids, row.get("source_object_id"))
            _append_uuid(seen_ids, row.get("related_object_id"))
    elif tool_name == "list_labels":
        for row in bounded.get("labels", []):
            _append_uuid(seen_ids, row.get("id"))
    elif tool_name == "list_inbox_since_review_marker":
        _append_uuid(seen_ids, bounded.get("anchor_object_id"))
        for item in bounded.get("items", []):
            _append_uuid(seen_ids, item.get("object_id"))
        for item in bounded.get("compact_items", []):
            stack = item.get("stack") if isinstance(item, dict) else None
            if stack:
                for object_id in stack.get("object_ids") or []:
                    _append_uuid(seen_ids, object_id)
            else:
                _append_uuid(seen_ids, item.get("object_id"))
    elif tool_name == "list_conversation_members":
        for item in bounded.get("members", []):
            _append_uuid(seen_ids, item.get("object_id"))
    elif tool_name == "resolve_person":
        _append_uuid(seen_ids, bounded.get("person_id"))
        for candidate in bounded.get("candidates") or []:
            if isinstance(candidate, dict):
                _append_uuid(seen_ids, candidate.get("person_id"))
    elif tool_name == "find_person_communications":
        for obj in bounded.get("objects") or []:
            if isinstance(obj, dict):
                _append_uuid(seen_ids, obj.get("id"))
    elif tool_name in (
        "create_task",
        "update_task",
        "set_task_status",
        "delete_task",
        "create_scheduled_activity",
        "create_recurring_scheduled_activity",
        "cancel_scheduled_activity",
    ):
        obj = bounded.get("object")
        if obj:
            _append_uuid(seen_ids, obj.get("id"))
    return seen_ids


def collect_seen_person_candidates(
    tool_name: str,
    bounded: dict[str, Any],
) -> list[tuple[UUID, str, str, str, str]]:
    if tool_name != "resolve_person":
        return []
    found: list[tuple[UUID, str, str, str, str]] = []
    for candidate in bounded.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        try:
            person_id = UUID(str(candidate.get("person_id")))
        except (ValueError, TypeError):
            continue
        for identity in candidate.get("identities") or []:
            if not isinstance(identity, dict):
                continue
            found.append(
                (
                    person_id,
                    str(identity.get("identity_type") or ""),
                    str(identity.get("provider") or ""),
                    str(identity.get("realm") or ""),
                    str(identity.get("canonical_value") or ""),
                )
            )
    return found


def collect_seen_edge_ids_from_bounded_tool(
    tool_name: str,
    bounded: dict[str, Any],
) -> list[UUID]:
    seen_ids: list[UUID] = []
    if tool_name == "list_neighbors":
        for neighbor in bounded.get("neighbors", []):
            edge = neighbor.get("edge")
            if edge:
                _append_uuid(seen_ids, edge.get("id"))
    elif tool_name == "remove_relation":
        edge = bounded.get("edge")
        if edge:
            _append_uuid(seen_ids, edge.get("id"))
    return seen_ids


def dedupe_preserve_order(ids: list[UUID]) -> list[UUID]:
    seen: set[UUID] = set()
    ordered: list[UUID] = []
    for object_id in ids:
        if object_id in seen:
            continue
        seen.add(object_id)
        ordered.append(object_id)
    return ordered


def cap_reference_candidate_ids(
    candidate_ids: list[UUID],
    mandatory_ids: list[UUID],
    max_refs: int,
) -> list[UUID]:
    mandatory_unique = dedupe_preserve_order(mandatory_ids)
    rest = [
        object_id
        for object_id in dedupe_preserve_order(candidate_ids)
        if object_id not in mandatory_unique
    ]
    return (mandatory_unique + rest)[:max_refs]


def _append_uuid(target: list[UUID], value: object) -> None:
    if not value:
        return
    try:
        parsed = UUID(str(value))
    except ValueError:
        return
    if parsed not in target:
        target.append(parsed)
