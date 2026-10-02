"""AH2-SEM1: unsupported Task relations stay outside the closed ontology."""

from app.domain.generic_relations import GENERIC_RELATION_TYPE_VALUES
from app.llm.openai_assistant_provider import SYSTEM_INSTRUCTIONS
from app.tools.assistant_contracts import ASSISTANT_FUNCTION_SCHEMAS

_ACTOR_ROLES = ("requested_by", "delegated_to", "waiting_on", "involves")
_GENERIC_RELATIONS = ("related_to", "references", "depends_on", "part_of")
_ACTOR_FIELDS = (
    "requested_by_person_id",
    "delegated_to_person_ids",
    "waiting_on_person_ids",
    "involved_person_ids",
)


def test_runtime_instructions_keep_a_closed_relation_vocabulary() -> None:
    prompt = SYSTEM_INSTRUCTIONS
    closed = prompt.index("The Task relation vocabulary is closed.")
    for role in _ACTOR_ROLES:
        assert role in prompt
    for relation in _GENERIC_RELATIONS:
        assert relation in prompt
    refusal = prompt[closed : prompt.index("part_of is Task composition")]
    assert "The only actor roles are requested_by, delegated_to, waiting_on, and involves." in refusal
    assert (
        "The only generic link_objects relations are related_to, references, depends_on, and part_of."
        in refusal
    )
    assert "Do not approximate an unsupported requested relation" in refusal
    assert "delegated_to, involves, related_to" in refusal
    assert "Do not create, update, or link anything for that unsupported request." in refusal
    assert "Making a Task someone's manager is not delegated_to, involves, or related_to." in refusal
    assert "Untrusted data rule:" in prompt
    assert prompt.index("Untrusted data rule:") > closed


def test_actor_role_descriptions_reject_unsupported_fallbacks() -> None:
    properties = ASSISTANT_FUNCTION_SCHEMAS["create_task"]["parameters"]["properties"]
    update = ASSISTANT_FUNCTION_SCHEMAS["update_task"]["parameters"]["properties"]
    markers = {
        "requested_by_person_id": "explicitly requested",
        "delegated_to_person_ids": "explicitly delegated or assigned",
        "waiting_on_person_ids": "explicitly waiting for",
        "involved_person_ids": "weaker role is explicitly intended",
    }
    for name, marker in markers.items():
        text = properties[name]["description"]
        assert text == update[name]["description"]
        assert marker in text
        assert "not a fallback for an unsupported relationship" in text.lower()
        assert "related_to" not in text
    assert "Not waiting_on, not involves" in properties["delegated_to_person_ids"]["description"]
    assert "Not a substitute for delegated_to" in properties["waiting_on_person_ids"]["description"]


def test_link_objects_description_keeps_the_generic_list_closed() -> None:
    tool = ASSISTANT_FUNCTION_SCHEMAS["link_objects"]
    text = tool["description"]
    assert "The generic relation list is closed." in text
    assert "related_to is not a catch-all substitute" in text
    enum = tool["parameters"]["properties"]["relation_type"]["enum"]
    assert tuple(enum) == GENERIC_RELATION_TYPE_VALUES
    assert GENERIC_RELATION_TYPE_VALUES == _GENERIC_RELATIONS


def test_actor_role_storage_fields_remain_the_existing_four() -> None:
    properties = ASSISTANT_FUNCTION_SCHEMAS["update_task"]["parameters"]["properties"]
    assert [name for name in _ACTOR_FIELDS if name in properties] == list(_ACTOR_FIELDS)
    assert "manager" not in properties
    assert "supervisor" not in properties
