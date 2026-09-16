"""Capture-OFF structural tool-argument metadata without wholesale free-text retention."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

_FREE_TEXT_KEYS = frozenset(
    {
        "query",
        "title",
        "body",
        "content",
        "message",
        "text",
        "summary",
        "description",
        "notes",
        "rationale",
        "subject",
        "snippet",
        "transcript",
    }
)


def _type_label(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _summarize_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, (UUID, date, datetime)):
        return str(value)
    if isinstance(value, str):
        if key in _FREE_TEXT_KEYS or len(value) > 64:
            return {"type": "string", "chars": len(value)}
        return value
    if isinstance(value, list):
        item_types = sorted({_type_label(item) for item in value})
        return {"array_count": len(value), "item_types": item_types}
    if isinstance(value, dict):
        return {child_key: _summarize_value(child_key, child_value) for child_key, child_value in value.items()}
    return {"type": _type_label(value)}


def summarize_tool_arguments_for_metadata(arguments: dict[str, Any] | None) -> dict[str, Any]:
    if not arguments:
        return {"argument_keys": [], "argument_structure": {}}
    return {
        "argument_keys": sorted(arguments.keys()),
        "argument_structure": {
            key: _summarize_value(key, value) for key, value in arguments.items()
        },
    }
