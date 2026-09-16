"""PHASE 28D-B-R1-R1 corrective regression tests."""

import uuid

from app.assistant.execution_effects import (
    classify_tool_execution_effect,
    describe_execution_effect,
)
from app.llm.openai_assistant_provider import FINALIZATION_INSTRUCTIONS
from app.services.assistant_service import _affected_object_ids_from_execution_result


def test_finalization_instructions_no_unconditional_success_claim() -> None:
    lowered = FINALIZATION_INSTRUCTIONS.lower()
    assert "already been executed successfully" not in lowered
    assert "action plan has already been executed" not in lowered
    assert "authoritative record of what happened" in lowered
    assert "success=true does not mean changed=true" in lowered
    assert "changed=false" in lowered


def test_affected_object_ids_link_objects_noop_when_not_created() -> None:
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()
    result = {
        "actions": [
            {
                "tool_name": "link_objects",
                "success": True,
                "output": {
                    "created": False,
                    "edge": {
                        "id": str(uuid.uuid4()),
                        "source_id": str(source_id),
                        "target_id": str(target_id),
                        "type": "related_to",
                    },
                },
            }
        ]
    }
    affected = _affected_object_ids_from_execution_result(result)
    assert affected == []


def test_affected_object_ids_link_objects_when_created() -> None:
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()
    result = {
        "actions": [
            {
                "tool_name": "link_objects",
                "success": True,
                "output": {
                    "created": True,
                    "edge": {
                        "id": str(uuid.uuid4()),
                        "source_id": str(source_id),
                        "target_id": str(target_id),
                        "type": "related_to",
                    },
                },
            }
        ]
    }
    affected = _affected_object_ids_from_execution_result(result)
    assert source_id in affected
    assert target_id in affected


def test_affected_object_ids_remove_relation_noop_when_not_changed() -> None:
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()
    result = {
        "actions": [
            {
                "tool_name": "remove_relation",
                "success": True,
                "output": {
                    "changed": False,
                    "edge": {
                        "id": str(uuid.uuid4()),
                        "source_id": str(source_id),
                        "target_id": str(target_id),
                        "type": "references",
                    },
                },
            }
        ]
    }
    affected = _affected_object_ids_from_execution_result(result)
    assert affected == []


def test_affected_object_ids_remove_relation_when_changed() -> None:
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()
    result = {
        "actions": [
            {
                "tool_name": "remove_relation",
                "success": True,
                "output": {
                    "changed": True,
                    "edge": {
                        "id": str(uuid.uuid4()),
                        "source_id": str(source_id),
                        "target_id": str(target_id),
                        "type": "references",
                    },
                },
            }
        ]
    }
    affected = _affected_object_ids_from_execution_result(result)
    assert source_id in affected
    assert target_id in affected


def test_execution_effects_update_task_noop() -> None:
    assert classify_tool_execution_effect("update_task", {"changed": False}) == "no_op"
    desc = describe_execution_effect(
        "update_task",
        {"changed": False, "evidence_already_linked_object_ids": ["a"]},
    )
    assert "changed=false" in desc


def test_execution_effects_remove_relation_removed_vs_noop() -> None:
    assert classify_tool_execution_effect("remove_relation", {"changed": True}) == "removed"
    assert classify_tool_execution_effect("remove_relation", {"changed": False}) == "no_op"
