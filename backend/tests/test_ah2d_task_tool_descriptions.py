"""AH2-D: Task tool descriptions match the canonical profile and field meanings."""

from app.tools.assistant_contracts import ASSISTANT_FUNCTION_SCHEMAS

_CREATE_PROPERTIES = {
    "title",
    "confidence",
    "body",
    "due_at",
    "evidence_object_ids",
    "requested_by_person_id",
    "delegated_to_person_ids",
    "waiting_on_person_ids",
    "involved_person_ids",
    "depends_on_task_ids",
    "completion_mode",
}
_UPDATE_PROPERTIES = {
    "object_id",
    "title",
    "body",
    "due_at",
    "evidence_object_ids",
    "requested_by_person_id",
    "delegated_to_person_ids",
    "waiting_on_person_ids",
    "involved_person_ids",
    "depends_on_task_ids",
    "completion_mode",
}
_DESCRIBED_FIELDS = (
    "requested_by_person_id",
    "delegated_to_person_ids",
    "waiting_on_person_ids",
    "involved_person_ids",
    "depends_on_task_ids",
    "evidence_object_ids",
)


def test_get_task_profile_description_names_returned_semantics() -> None:
    text = ASSISTANT_FUNCTION_SCHEMAS["get_task_profile"]["description"]
    for marker in (
        "status",
        "lifecycle",
        "completion_mode",
        "finite",
        "ongoing",
        "parent_task",
        "part_of",
        "composition",
        "requested_by",
        "delegated_to",
        "waiting_on",
        "involves",
        "depends_on",
        "dependent",
        "planned_start_at",
        "planned_end_at",
        "evidence",
        "operational_state",
        "read-only",
        "Does not mutate.",
        "ignores proposed relations",
    ):
        assert marker in text
    assert "does not write the planned interval" in text


def test_create_and_update_field_descriptions_share_canonical_meanings() -> None:
    create = ASSISTANT_FUNCTION_SCHEMAS["create_task"]["parameters"]
    update = ASSISTANT_FUNCTION_SCHEMAS["update_task"]["parameters"]
    assert set(create["properties"]) == _CREATE_PROPERTIES
    assert set(update["properties"]) == _UPDATE_PROPERTIES
    assert create["required"] == ["title", "confidence"]
    assert update["required"] == ["object_id"]
    for name in _DESCRIBED_FIELDS:
        create_text = create["properties"][name]["description"]
        update_text = update["properties"][name]["description"]
        assert create_text == update_text
        assert "related_to" not in create_text
    for role, marker in (
        ("requested_by_person_id", "explicitly requested"),
        ("delegated_to_person_ids", "delegated or assigned"),
        ("waiting_on_person_ids", "waiting for"),
        ("involved_person_ids", "no stronger requested, delegated, or waiting role"),
    ):
        text = create["properties"][role]["description"]
        assert "typed Task-to-Person actor role" in text
        assert marker in text
    dependency = create["properties"]["depends_on_task_ids"]["description"]
    assert "prerequisite" in dependency
    assert "not part_of composition" in dependency
    evidence = create["properties"]["evidence_object_ids"]["description"]
    assert "Additive" in evidence
    assert "never removes" in evidence
    assert "does not create a Task" in evidence


def test_link_objects_description_keeps_canonical_relation_split() -> None:
    text = ASSISTANT_FUNCTION_SCHEMAS["link_objects"]["description"]
    for marker in (
        "related_to",
        "references",
        "depends_on",
        "part_of",
        "typed Task fields",
    ):
        assert marker in text
