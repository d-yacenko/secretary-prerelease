"""Model-facing create_task and update_task can set completion_mode."""

from __future__ import annotations

import uuid

import pytest
from mcp.client import Client
from pydantic import ValidationError

from app.api.schemas import ObjectCreate
from app.db.models import Edge, Object
from app.domain.task_relations import PART_OF
from app.mcp.server import create_mcp_server
from app.services.domain_tool_service import DomainToolService
from app.services.domain_write_mode import DomainWriteMode
from app.services.graph_service import GraphService
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import AGENT_ORIGIN, CONFIRMED_STATE, PROPOSED_STATE, USER_ORIGIN
from app.tools.registry import TOOL_REGISTRY, get_tool_spec, validate_tool_arguments
from app.tools.schemas import (
    CreateTaskInput,
    GetTaskProfileInput,
    LinkObjectsInput,
    SetTaskStatusInput,
    ToolError,
    UpdateTaskInput,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID


def test_task_inputs_accept_only_finite_or_ongoing() -> None:
    omitted = CreateTaskInput(title="Task", confidence=0.5)
    assert "completion_mode" not in omitted.model_fields_set
    assert (
        CreateTaskInput(title="Task", confidence=0.5, completion_mode="finite").completion_mode
        == "finite"
    )
    assert (
        CreateTaskInput(title="Task", confidence=0.5, completion_mode="ongoing").completion_mode
        == "ongoing"
    )
    with pytest.raises(ValidationError):
        CreateTaskInput(title="Task", confidence=0.5, completion_mode="weekly")
    with pytest.raises(ValidationError):
        CreateTaskInput(title="Task", confidence=0.5, completion_mode=None)

    task_id = uuid.uuid4()
    title_only = UpdateTaskInput(object_id=task_id, title="Renamed")
    assert "completion_mode" not in title_only.model_fields_set
    assert UpdateTaskInput(object_id=task_id, completion_mode="finite").completion_mode == "finite"
    assert (
        UpdateTaskInput(object_id=task_id, completion_mode="ongoing").completion_mode == "ongoing"
    )
    with pytest.raises(ValidationError):
        UpdateTaskInput(object_id=task_id, completion_mode="weekly")
    with pytest.raises(ValidationError):
        UpdateTaskInput(object_id=task_id, completion_mode=None)


def test_gateway_preserves_completion_mode_presence_and_schemas() -> None:
    task_id = str(uuid.uuid4())
    update_spec = get_tool_spec("update_task")
    assert update_spec is not None
    staged = validate_tool_arguments(
        update_spec,
        {"object_id": task_id, "completion_mode": "ongoing"},
    )
    assert staged["completion_mode"] == "ongoing"
    title_only = validate_tool_arguments(update_spec, {"object_id": task_id, "title": "Renamed"})
    assert "completion_mode" not in title_only

    for model in (CreateTaskInput, UpdateTaskInput):
        assert _enum_values(model.model_json_schema()["properties"]["completion_mode"]) == {
            "finite",
            "ongoing",
        }
    for name in ("create_task", "update_task"):
        definition = get_tool_spec(name).assistant_definition
        assert definition["parameters"]["properties"]["completion_mode"]["enum"] == [
            "finite",
            "ongoing",
        ]
    for name, spec in TOOL_REGISTRY.items():
        if name in {"create_task", "update_task"}:
            continue
        properties = (spec.assistant_definition or {}).get("parameters", {}).get("properties", {})
        assert "completion_mode" not in properties
        if spec.input_model is not None:
            assert "completion_mode" not in spec.input_model.model_fields


@pytest.mark.asyncio
async def test_mcp_schema_matches_the_completion_mode_enum(patched_mcp_tool_session) -> None:
    async with Client(create_mcp_server()) as client:
        listed = await client.list_tools()
    by_name = {tool.name: tool for tool in listed.tools}
    for name in ("create_task", "update_task"):
        assert _enum_values(by_name[name].input_schema["properties"]["completion_mode"]) == {
            "finite",
            "ongoing",
        }
    for tool in listed.tools:
        if tool.name in {"create_task", "update_task"}:
            continue
        assert "completion_mode" not in tool.input_schema.get("properties", {})


def test_create_and_update_completion_mode(db_session, fake_embedding_service) -> None:
    tools = _tools(db_session, fake_embedding_service)
    omitted = tools.create_task(CreateTaskInput(title="Plain", confidence=0.4))
    explicit = tools.create_task(
        CreateTaskInput(title="Finite", confidence=0.4, completion_mode="finite")
    )
    ongoing = tools.create_task(
        CreateTaskInput(title="Direction", confidence=0.4, completion_mode="ongoing")
    )
    assert omitted.object.completion_mode == "finite"
    assert omitted.object.status == "open"
    assert omitted.object.origin == AGENT_ORIGIN
    assert omitted.object.state == PROPOSED_STATE
    assert explicit.object.completion_mode == "finite"
    assert ongoing.object.completion_mode == "ongoing"
    assert ongoing.object.status == "open"

    changed = tools.update_task(
        UpdateTaskInput(object_id=explicit.object.id, completion_mode="ongoing")
    )
    assert changed.changed is True
    assert changed.object.completion_mode == "ongoing"
    restored = tools.update_task(
        UpdateTaskInput(object_id=explicit.object.id, completion_mode="finite")
    )
    assert restored.changed is True
    assert restored.object.completion_mode == "finite"
    same = tools.update_task(
        UpdateTaskInput(object_id=explicit.object.id, completion_mode="finite")
    )
    assert same.changed is False
    assert same.object.completion_mode == "finite"

    approved = _tools(
        db_session,
        fake_embedding_service,
        write_mode=DomainWriteMode.APPROVED_CONFIRMED,
    )
    confirmed = approved.create_task(
        CreateTaskInput(title="Confirmed direction", confidence=0.9, completion_mode="ongoing")
    )
    assert confirmed.object.state == CONFIRMED_STATE
    assert confirmed.object.completion_mode == "ongoing"
    profile = tools.get_task_profile(GetTaskProfileInput(task_id=confirmed.object.id))
    assert profile.task.completion_mode == "ongoing"


def test_completion_mode_keeps_relations_and_lifecycle_guards(
    db_session, fake_embedding_service
) -> None:
    tools = _tools(db_session, fake_embedding_service)
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Olga")
    dependency = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(kind="task", title="Dependency", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    evidence = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(kind="email", title="Mail", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    created = tools.create_task(
        CreateTaskInput(
            title="Ask Olga",
            confidence=0.8,
            completion_mode="ongoing",
            requested_by_person_id=person.id,
            depends_on_task_ids=[dependency.id],
            evidence_object_ids=[evidence.id],
        )
    )
    profile = tools.get_task_profile(GetTaskProfileInput(task_id=created.object.id))
    assert profile.task.completion_mode == "ongoing"
    assert [item.person_id for item in profile.requested_by] == [person.id]
    assert [item.object_id for item in profile.depends_on] == [dependency.id]
    assert [item.object_id for item in profile.evidence] == [evidence.id]

    with pytest.raises(ToolError):
        tools.set_task_status(SetTaskStatusInput(object_id=created.object.id, status="done"))
    assert db_session.get(Object, created.object.id).status == "open"
    assert db_session.get(Object, created.object.id).completion_mode == "ongoing"

    finite = tools.create_task(CreateTaskInput(title="Closeable", confidence=0.5))
    done = tools.set_task_status(SetTaskStatusInput(object_id=finite.object.id, status="done"))
    assert done.object.status == "done"
    with pytest.raises(ToolError):
        tools.update_task(UpdateTaskInput(object_id=finite.object.id, completion_mode="ongoing"))
    stored = db_session.get(Object, finite.object.id)
    assert stored.status == "done"
    assert stored.completion_mode == "finite"

    direction = tools.create_task(
        CreateTaskInput(title="Later finite", confidence=0.5, completion_mode="ongoing")
    )
    made_finite = tools.update_task(
        UpdateTaskInput(object_id=direction.object.id, completion_mode="finite")
    )
    assert made_finite.changed is True
    closed = tools.set_task_status(SetTaskStatusInput(object_id=direction.object.id, status="done"))
    assert closed.object.status == "done"
    assert closed.object.completion_mode == "finite"


def test_update_rejects_forbidden_part_of_and_allows_a_valid_parent(
    db_session, fake_embedding_service
) -> None:
    tools = _tools(db_session, fake_embedding_service)
    child = tools.create_task(CreateTaskInput(title="Child", confidence=0.5))
    parent = tools.create_task(CreateTaskInput(title="Parent", confidence=0.5))
    linked = tools.link_objects(
        LinkObjectsInput(
            source_id=child.object.id,
            target_id=parent.object.id,
            relation_type=PART_OF,
            confidence=0.7,
        )
    )
    edge_id = linked.edge.id
    with pytest.raises(ToolError, match="part of a finite"):
        tools.update_task(UpdateTaskInput(object_id=child.object.id, completion_mode="ongoing"))
    assert db_session.get(Object, child.object.id).completion_mode == "finite"
    edge = db_session.get(Edge, edge_id)
    assert edge is not None
    assert edge.type == PART_OF
    assert edge.state == PROPOSED_STATE

    allowed = tools.update_task(
        UpdateTaskInput(object_id=parent.object.id, completion_mode="ongoing")
    )
    assert allowed.changed is True
    assert allowed.object.completion_mode == "ongoing"
    assert db_session.get(Object, child.object.id).completion_mode == "finite"
    assert db_session.get(Edge, edge_id).state == PROPOSED_STATE


def test_invalid_mode_does_not_mutate(db_session, fake_embedding_service) -> None:
    tools = _tools(db_session, fake_embedding_service)
    created = tools.create_task(CreateTaskInput(title="Stable", confidence=0.5))
    spec = get_tool_spec("update_task")
    with pytest.raises(ValidationError):
        validate_tool_arguments(
            spec,
            {"object_id": str(created.object.id), "completion_mode": "weekly"},
        )
    assert db_session.get(Object, created.object.id).completion_mode == "finite"


def _tools(db_session, fake_embedding_service, **kwargs) -> DomainToolService:
    return DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service, **kwargs)


def _enum_values(schema: dict) -> set[str]:
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("enum"), list):
                found.update(str(item) for item in node["enum"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return found
