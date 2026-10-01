"""AH1 documentation drift checks. No product runtime effect."""

from __future__ import annotations

import re
from pathlib import Path

from app.domain.generic_relations import GENERIC_RELATION_TYPES, GenericRelationType
from app.proactive.constants import PROACTIVE_READ_TOOL_NAMES
from app.tools.registry import TOOL_SPECS
from app.tools.schemas import LinkObjectsInput

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT = REPO_ROOT / "docs" / "ontology_harness_parity_audit.md"
MATRIX = REPO_ROOT / "docs" / "SECRETARY_TOOLSET_MATRIX.md"
AUDITED_SHA = "df72686cc447cbc534739307f645420d867db8de"


def _exposure_rows() -> dict[str, str]:
    text = AUDIT.read_text()
    match = re.search(r"```exposure\n(.*?)```", text, re.DOTALL)
    assert match is not None
    rows: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        name, rest = line.split(" ", 1)
        rows[name] = rest
    return rows


def test_audited_sha_is_recorded() -> None:
    assert AUDITED_SHA in AUDIT.read_text()


def test_generic_relation_literal_matches_domain_and_schema() -> None:
    assert set(GenericRelationType.__args__) == GENERIC_RELATION_TYPES
    assert LinkObjectsInput.model_fields["relation_type"].annotation == GenericRelationType


def test_audit_exposure_matches_registry() -> None:
    proactive = set(PROACTIVE_READ_TOOL_NAMES)
    rows = _exposure_rows()
    assert set(rows) == {spec.name for spec in TOOL_SPECS}
    for spec in TOOL_SPECS:
        expected = (
            f"assistant={int(spec.assistant_exposed)} "
            f"mcp={int(spec.mcp_exposed)} "
            f"proactive={int(spec.name in proactive)} "
            f"permission={spec.permission.value}"
        )
        assert rows[spec.name] == expected


def test_matrix_backticked_tool_names_exist() -> None:
    names = set(re.findall(r"`([a-z][a-z0-9_]*)`", MATRIX.read_text()))
    registry = {spec.name for spec in TOOL_SPECS}
    required = {
        "retrieve",
        "query_objects",
        "get_object",
        "get_context",
        "list_neighbors",
        "get_task_profile",
        "list_notifications",
        "get_today",
        "search_objects",
        "resolve_person",
        "find_person_communications",
        "find_person_identity_candidates",
        "list_person_routes",
        "create_task",
        "update_task",
        "set_task_status",
        "delete_task",
        "link_objects",
        "remove_relation",
        "list_labels",
        "assign_label",
        "remove_label",
        "create_label",
        "rename_label",
        "delete_label",
        "confirm_person_identity",
        "reject_person_identity",
        "retract_person_identity_feedback",
        "record_person_route_choice",
        "create_scheduled_activity",
        "create_recurring_scheduled_activity",
        "cancel_scheduled_activity",
        "send_email",
        "send_message",
        "edit_message",
        "delete_message",
        "mark_message_read",
        "create_calendar_event",
        "list_inbox_since_review_marker",
        "set_inbox_review_marker",
        "clear_inbox_review_marker",
    }
    assert required <= names
    assert required <= registry
