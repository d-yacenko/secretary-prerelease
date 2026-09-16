"""Semantics for Assistant/user removable graph relations (PHASE 28D-B-R1)."""

from app.services.provenance import (
    AGENT_ORIGIN,
    SOURCE_ORIGIN,
    SYSTEM_ORIGIN,
    USER_ORIGIN,
)

REMOVABLE_EDGE_TYPES = frozenset({"references", "related_to", "depends_on"})
PROTECTED_EDGE_TYPES = frozenset({"contains", "labeled_with"})
REMOVABLE_EDGE_ORIGINS = frozenset({AGENT_ORIGIN, USER_ORIGIN})


def is_edge_removable(origin: str, edge_type: str) -> bool:
    if origin in {SOURCE_ORIGIN, SYSTEM_ORIGIN}:
        return False
    if edge_type in PROTECTED_EDGE_TYPES:
        return False
    if origin not in REMOVABLE_EDGE_ORIGINS:
        return False
    return edge_type in REMOVABLE_EDGE_TYPES


def removable_edge_rejection_reason(origin: str, edge_type: str) -> str | None:
    if origin in {SOURCE_ORIGIN, SYSTEM_ORIGIN}:
        return "source structural relations cannot be removed through Assistant tools"
    if edge_type == "labeled_with":
        return "labeled_with assignments must be removed with remove_label"
    if edge_type in PROTECTED_EDGE_TYPES:
        return f"protected relation type '{edge_type}' cannot be removed"
    if origin not in REMOVABLE_EDGE_ORIGINS:
        return "only user-created or agent-created semantic relations can be removed"
    if edge_type not in REMOVABLE_EDGE_TYPES:
        return f"relation type '{edge_type}' is not removable through remove_relation"
    return None
