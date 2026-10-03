"""MCP create_task and update_task can express Task actor and dependency intent."""

from __future__ import annotations

import uuid

import pytest
from mcp.client import Client
from sqlalchemy import func, select

from app.api.schemas import ObjectCreate
from app.db.models import Edge, Object
from app.domain.task_relations import DELEGATED_TO, INVOLVES, REQUESTED_BY, WAITING_ON
from app.mcp import server as mcp_server
from app.mcp.server import create_mcp_server
from app.services.graph_service import GraphService
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import CONFIRMED_STATE, USER_ORIGIN
from app.services.task_relation_service import TaskRelationService
from app.tools.assistant_contracts import ASSISTANT_FUNCTION_SCHEMAS
from app.tools.execution_context import ExecutionContext
from app.tools.policy import PolicyDecision, ToolPermission, evaluate_policy
from app.tools.registry import TOOL_REGISTRY
from app.users.bootstrap import BOOTSTRAP_USER_ID

RELATION_FIELDS = (
    "requested_by_person_id",
    "delegated_to_person_ids",
    "waiting_on_person_ids",
    "involved_person_ids",
    "depends_on_task_ids",
)
LIST_FIELDS = RELATION_FIELDS[1:]
FORBIDDEN_ALIASES = ("assignee", "owner", "blocker", "participants")
PERSON_MCP_TOOLS = (
    "resolve_person",
    "find_person_communications",
    "find_person_identity_candidates",
    "list_person_routes",
    "get_person_roles",
    "find_people_by_role",
    "assign_person_role",
    "retract_person_role",
    "record_person_route_choice",
    "confirm_person_identity",
    "reject_person_identity",
    "retract_person_identity_feedback",
)


def test_assistant_and_mcp_share_task_relation_parameter_names() -> None:
    for tool_name in ("create_task", "update_task"):
        assistant_names = set(ASSISTANT_FUNCTION_SCHEMAS[tool_name]["parameters"]["properties"])
        for field_name in RELATION_FIELDS:
            assert field_name in assistant_names


def test_mcp_internal_write_still_requires_approval() -> None:
    assert (
        evaluate_policy(ToolPermission.INTERNAL_WRITE, ExecutionContext.MCP)
        == PolicyDecision.REQUIRE_APPROVAL
    )
    for name in PERSON_MCP_TOOLS:
        assert TOOL_REGISTRY[name].mcp_exposed is False


@pytest.mark.asyncio
async def test_mcp_task_relation_schema_and_forwarding(
    db_session, patched_mcp_tool_session, monkeypatch
) -> None:
    forwarded: list[tuple[str, dict]] = []
    real_execute = mcp_server.execute_mcp_tool

    def spy(tool_name: str, arguments: dict):
        forwarded.append((tool_name, dict(arguments)))
        return real_execute(tool_name, arguments)

    monkeypatch.setattr(mcp_server, "execute_mcp_tool", spy)
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = graph.create_object(
        ObjectCreate(kind="task", title="Existing", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    before_objects = db_session.scalar(select(func.count()).select_from(Object))
    before_edges = db_session.scalar(select(func.count()).select_from(Edge))
    relation_arguments = {
        "requested_by_person_id": str(uuid.uuid4()),
        "delegated_to_person_ids": [str(uuid.uuid4())],
        "waiting_on_person_ids": [str(uuid.uuid4())],
        "involved_person_ids": [str(uuid.uuid4())],
        "depends_on_task_ids": [str(uuid.uuid4())],
    }

    async with Client(create_mcp_server()) as client:
        listed = await client.list_tools()
        by_name = {tool.name: tool for tool in listed.tools}
        for tool_name in ("create_task", "update_task"):
            schema = by_name[tool_name].input_schema
            _assert_relation_schema(schema)
            assistant_names = ASSISTANT_FUNCTION_SCHEMAS[tool_name]["parameters"]["properties"]
            assert set(RELATION_FIELDS) <= set(assistant_names)
            assert set(RELATION_FIELDS) <= set(schema["properties"])
        for name in PERSON_MCP_TOOLS:
            assert name not in by_name

        created = await client.call_tool(
            "create_task",
            {"title": "MCP relations", "confidence": 0.4, **relation_arguments},
        )
        omitted = await client.call_tool(
            "create_task",
            {"title": "MCP omitted relations", "confidence": 0.4},
        )
        empty_list = await client.call_tool(
            "create_task",
            {
                "title": "MCP empty relations",
                "confidence": 0.4,
                "delegated_to_person_ids": [],
            },
        )
        updated = await client.call_tool(
            "update_task",
            {"object_id": str(task.id), **relation_arguments},
        )
        omitted_update = await client.call_tool("update_task", {"object_id": str(task.id)})
        readable = await client.call_tool("get_today", {})

    assert created.is_error
    assert "approval" in _tool_text(created)
    assert omitted.is_error
    assert "approval" in _tool_text(omitted)
    assert empty_list.is_error
    assert "approval" in _tool_text(empty_list)
    assert updated.is_error
    assert "approval" in _tool_text(updated)
    assert omitted_update.is_error
    assert "approval" in _tool_text(omitted_update)
    assert not readable.is_error
    assert db_session.scalar(select(func.count()).select_from(Object)) == before_objects
    assert db_session.scalar(select(func.count()).select_from(Edge)) == before_edges
    db_session.refresh(task)
    assert task.title == "Existing"

    by_tool: dict[str, list[dict]] = {}
    for tool_name, arguments in forwarded:
        by_tool.setdefault(tool_name, []).append(arguments)
    full_create = next(item for item in by_tool["create_task"] if item["title"] == "MCP relations")
    for field_name, value in relation_arguments.items():
        assert full_create[field_name] == value
    omitted_create = next(
        item for item in by_tool["create_task"] if item["title"] == "MCP omitted relations"
    )
    assert all(field_name not in omitted_create for field_name in RELATION_FIELDS)
    empty = next(item for item in by_tool["create_task"] if item["title"] == "MCP empty relations")
    assert empty["delegated_to_person_ids"] == []
    assert "requested_by_person_id" not in empty
    full_update = next(item for item in by_tool["update_task"] if "requested_by_person_id" in item)
    for field_name, value in relation_arguments.items():
        assert full_update[field_name] == value
    assert full_update["object_id"] == str(task.id)
    bare_update = next(item for item in by_tool["update_task"] if set(item) == {"object_id"})
    assert bare_update["object_id"] == str(task.id)


@pytest.mark.asyncio
async def test_mcp_task_relation_input_is_rejected_before_mutation(
    db_session, patched_mcp_tool_session, monkeypatch
) -> None:
    forwarded: list[tuple[str, dict]] = []
    real_execute = mcp_server.execute_mcp_tool

    def spy(tool_name: str, arguments: dict):
        forwarded.append((tool_name, dict(arguments)))
        return real_execute(tool_name, arguments)

    monkeypatch.setattr(mcp_server, "execute_mcp_tool", spy)
    before_objects = db_session.scalar(select(func.count()).select_from(Object))
    before_edges = db_session.scalar(select(func.count()).select_from(Edge))
    nine = [str(uuid.uuid4()) for _ in range(9)]

    async with Client(create_mcp_server()) as client:
        null_requester = await client.call_tool(
            "create_task",
            {"title": "Null requester", "confidence": 0.4, "requested_by_person_id": None},
        )
        null_list = await client.call_tool(
            "create_task",
            {"title": "Null list", "confidence": 0.4, "delegated_to_person_ids": None},
        )
        scalar_list = await client.call_tool(
            "create_task",
            {"title": "Scalar list", "confidence": 0.4, "waiting_on_person_ids": str(uuid.uuid4())},
        )
        too_many = await client.call_tool(
            "update_task",
            {"object_id": str(uuid.uuid4()), "involved_person_ids": nine},
        )
        malformed = await client.call_tool(
            "create_task",
            {"title": "Bad uuid", "confidence": 0.4, "requested_by_person_id": "not-a-uuid"},
        )

    for result in (null_requester, null_list, scalar_list, too_many, malformed):
        assert result.is_error
        text = _tool_text(result)
        assert "Traceback" not in text
        assert "ValidationError" not in text
    assert "approval" not in _tool_text(malformed).lower()
    assert db_session.scalar(select(func.count()).select_from(Object)) == before_objects
    assert db_session.scalar(select(func.count()).select_from(Edge)) == before_edges
    assert [item["title"] for _name, item in forwarded if "title" in item] == ["Bad uuid"]
    assert forwarded[0][1]["requested_by_person_id"] == "not-a-uuid"


@pytest.mark.asyncio
async def test_mcp_profile_reads_the_same_relation_categories(
    db_session, patched_mcp_tool_session
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = graph.create_object(
        ObjectCreate(kind="task", title="Profile task", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    dependency = graph.create_object(
        ObjectCreate(kind="task", title="Prerequisite", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    people = PersonIdentityService(db_session, BOOTSTRAP_USER_ID)
    requester = people.create_person("Requester")
    delegate = people.create_person("Delegate")
    waiter = people.create_person("Waiter")
    participant = people.create_person("Participant")
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    relations.add_actor(task.id, requester.id, REQUESTED_BY)
    relations.add_actor(task.id, delegate.id, DELEGATED_TO)
    relations.add_actor(task.id, waiter.id, WAITING_ON)
    relations.add_actor(task.id, participant.id, INVOLVES)
    relations.add_dependency(task.id, dependency.id)

    async with Client(create_mcp_server()) as client:
        result = await client.call_tool("get_task_profile", {"task_id": str(task.id)})

    assert not result.is_error
    payload = result.structured_content
    assert [item["person_id"] for item in payload["requested_by"]] == [str(requester.id)]
    assert [item["person_id"] for item in payload["delegated_to"]] == [str(delegate.id)]
    assert [item["person_id"] for item in payload["waiting_on"]] == [str(waiter.id)]
    assert [item["person_id"] for item in payload["involves"]] == [str(participant.id)]
    assert [item["object_id"] for item in payload["depends_on"]] == [str(dependency.id)]


def _assert_relation_schema(schema: dict) -> None:
    properties = schema["properties"]
    required = set(schema.get("required") or [])
    for field_name in RELATION_FIELDS:
        assert field_name not in required
        assert not _advertises_null(properties[field_name])
    requester = properties["requested_by_person_id"]
    assert _schema_type(requester) == "string"
    for field_name in LIST_FIELDS:
        prop = properties[field_name]
        assert _schema_type(prop) == "array"
        assert _schema_type(prop["items"]) == "string"
        assert prop["maxItems"] == 8
    for alias in FORBIDDEN_ALIASES:
        assert alias not in properties
    completion = properties["completion_mode"]
    assert "completion_mode" not in required
    assert _schema_type(completion) == "string"
    assert set(completion.get("enum") or []) == {"finite", "ongoing"}
    assert not _advertises_null(completion)


def _schema_type(node: dict) -> str | None:
    type_value = node.get("type")
    if isinstance(type_value, str):
        return type_value
    for key in ("anyOf", "oneOf", "allOf"):
        options = node.get(key)
        if isinstance(options, list):
            for option in options:
                if isinstance(option, dict):
                    found = _schema_type(option)
                    if found is not None and found != "null":
                        return found
    return None


def _advertises_null(node) -> bool:
    if isinstance(node, dict):
        type_value = node.get("type")
        if type_value == "null" or (isinstance(type_value, list) and "null" in type_value):
            return True
        if "const" in node and node["const"] is None:
            return True
        enum = node.get("enum")
        if isinstance(enum, list) and any(item is None for item in enum):
            return True
        return any(_advertises_null(value) for value in node.values())
    if isinstance(node, list):
        return any(_advertises_null(item) for item in node)
    return False


def _tool_text(result) -> str:
    return result.content[0].text
