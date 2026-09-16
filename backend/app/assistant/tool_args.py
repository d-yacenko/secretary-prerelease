from datetime import datetime
from typing import Any

from app.assistant.constants import (
    MAX_ASSISTANT_CONTEXT_CHARS,
    MAX_ASSISTANT_LIST_RESULTS,
    MAX_ASSISTANT_NEIGHBOR_RESULTS,
    MAX_ASSISTANT_RETRIEVE_RESULTS,
    MAX_ASSISTANT_SEARCH_RESULTS,
)
from app.services.retrieval_constants import (
    TIME_SCOPE_ALL,
    TIME_SCOPE_AUTO,
    TIME_SCOPE_RECENT,
)
from app.tools.datetime_utils import normalize_tool_datetime
from app.tools.schemas import ToolError

_RETRIEVE_KIND_WILDCARDS = frozenset({"all", "any", "*"})


def _normalize_retrieve_kind(kind: object) -> str | None:
    if kind is None:
        return None
    if not isinstance(kind, str):
        raise ToolError("retrieve kind must be a string")
    normalized = kind.strip()
    if not normalized or normalized.lower() in _RETRIEVE_KIND_WILDCARDS:
        return None
    return normalized


def _parse_optional_datetime(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return normalize_tool_datetime(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))  # noqa: FURB162
        except ValueError:
            raise ToolError(f"{field_name} must be a valid ISO datetime") from None
        return normalize_tool_datetime(parsed)
    raise ToolError(f"{field_name} must be an ISO datetime string")


def normalize_assistant_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Clamp Assistant tool arguments before domain execution."""
    if tool_name == "search_objects":
        limit = arguments.get("limit", MAX_ASSISTANT_SEARCH_RESULTS)
        if not isinstance(limit, int):
            raise ToolError("search_objects limit must be an integer")
        if limit < 1:
            raise ToolError("search_objects limit must be at least 1")
        return {
            **arguments,
            "limit": min(limit, MAX_ASSISTANT_SEARCH_RESULTS),
        }

    if tool_name == "query_objects":
        from app.assistant.constants import MAX_ASSISTANT_QUERY_OBJECTS_RESULTS

        limit = arguments.get("limit", MAX_ASSISTANT_QUERY_OBJECTS_RESULTS)
        if not isinstance(limit, int):
            raise ToolError("query_objects limit must be an integer")
        if limit < 1:
            raise ToolError("query_objects limit must be at least 1")
        return {
            **arguments,
            "limit": min(limit, MAX_ASSISTANT_QUERY_OBJECTS_RESULTS),
            "due_from": _parse_optional_datetime(arguments.get("due_from"), "due_from"),
            "due_to": _parse_optional_datetime(arguments.get("due_to"), "due_to"),
            "start_from": _parse_optional_datetime(arguments.get("start_from"), "start_from"),
            "start_to": _parse_optional_datetime(arguments.get("start_to"), "start_to"),
            "occurred_from": _parse_optional_datetime(
                arguments.get("occurred_from"), "occurred_from"
            ),
            "occurred_to": _parse_optional_datetime(arguments.get("occurred_to"), "occurred_to"),
        }

    if tool_name == "retrieve":
        limit = arguments.get("limit", MAX_ASSISTANT_RETRIEVE_RESULTS)
        if not isinstance(limit, int):
            raise ToolError("retrieve limit must be an integer")
        if limit < 1:
            raise ToolError("retrieve limit must be at least 1")
        time_scope = arguments.get("time_scope", TIME_SCOPE_AUTO)
        if not isinstance(time_scope, str):
            raise ToolError("retrieve time_scope must be a string")
        if time_scope not in (TIME_SCOPE_AUTO, TIME_SCOPE_RECENT, TIME_SCOPE_ALL):
            raise ToolError("retrieve time_scope must be auto, recent, or all")
        return {
            "query": arguments["query"],
            "kind": _normalize_retrieve_kind(arguments.get("kind")),
            "time_scope": time_scope,
            "date_from": _parse_optional_datetime(arguments.get("date_from"), "date_from"),
            "date_to": _parse_optional_datetime(arguments.get("date_to"), "date_to"),
            "limit": min(limit, MAX_ASSISTANT_RETRIEVE_RESULTS),
        }

    if tool_name == "list_notifications":
        limit = arguments.get("limit", MAX_ASSISTANT_LIST_RESULTS)
        if not isinstance(limit, int):
            raise ToolError("list_notifications limit must be an integer")
        if limit < 1:
            raise ToolError("list_notifications limit must be at least 1")
        return {
            **arguments,
            "limit": min(limit, MAX_ASSISTANT_LIST_RESULTS),
        }

    if tool_name == "list_inbox_since_review_marker":
        limit = arguments.get("limit", MAX_ASSISTANT_LIST_RESULTS)
        if not isinstance(limit, int):
            raise ToolError("list_inbox_since_review_marker limit must be an integer")
        if limit < 1:
            raise ToolError("list_inbox_since_review_marker limit must be at least 1")
        purpose = arguments.get("purpose", "inspect")
        if purpose is None:
            purpose = "inspect"
        if purpose not in ("inspect", "review"):
            raise ToolError("list_inbox_since_review_marker purpose must be inspect or review")
        normalized = {
            **arguments,
            "limit": min(limit, MAX_ASSISTANT_LIST_RESULTS),
            "purpose": purpose,
        }
        cursor = arguments.get("cursor")
        if cursor is not None:
            if not isinstance(cursor, str):
                raise ToolError("list_inbox_since_review_marker cursor must be a string")
            stripped = cursor.strip()
            if stripped:
                normalized["cursor"] = stripped
            else:
                normalized.pop("cursor", None)
        return normalized

    if tool_name == "list_conversation_members":
        object_id = arguments.get("object_id")
        if not object_id:
            raise ToolError("list_conversation_members requires object_id")
        limit = arguments.get("limit", MAX_ASSISTANT_LIST_RESULTS)
        if not isinstance(limit, int):
            raise ToolError("list_conversation_members limit must be an integer")
        if limit < 1:
            raise ToolError("list_conversation_members limit must be at least 1")
        normalized = {
            **arguments,
            "object_id": object_id,
            "limit": min(limit, MAX_ASSISTANT_LIST_RESULTS),
        }
        cursor = arguments.get("cursor")
        if cursor is not None:
            if not isinstance(cursor, str):
                raise ToolError("list_conversation_members cursor must be a string")
            stripped = cursor.strip()
            if stripped:
                normalized["cursor"] = stripped
            else:
                normalized.pop("cursor", None)
        return normalized

    if tool_name == "list_neighbors":
        return {
            **arguments,
            "limit": MAX_ASSISTANT_NEIGHBOR_RESULTS,
        }

    if tool_name == "get_context":
        object_id = arguments.get("object_id")
        if not object_id:
            raise ToolError("get_context requires object_id")
        max_chars = arguments.get("max_chars", MAX_ASSISTANT_CONTEXT_CHARS)
        if not isinstance(max_chars, int):
            raise ToolError("get_context max_chars must be an integer")
        if max_chars < 1:
            raise ToolError("get_context max_chars must be at least 1")
        query = arguments.get("query")
        if query is not None and not isinstance(query, str):
            raise ToolError("get_context query must be a string")
        normalized: dict[str, Any] = {
            "object_id": object_id,
            "max_chars": min(max_chars, MAX_ASSISTANT_CONTEXT_CHARS),
        }
        if query is not None and query.strip():
            normalized["query"] = query.strip()
        return normalized

    return arguments
