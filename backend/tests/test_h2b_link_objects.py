"""link_objects accepts only the canonical generic relation types."""

from __future__ import annotations

import uuid

import pytest
from mcp.client import Client
from pydantic import ValidationError
from sqlalchemy import func, select

import app.mcp.server as mcp_server
from app.api.schemas import ObjectCreate
from app.db.models import Edge, Object
from app.domain.generic_relations import GENERIC_RELATION_TYPE_VALUES
from app.domain.labels import EDGE_TYPE_LABELED_WITH
from app.domain.task_completion import TASK_COMPLETION_ONGOING
from app.domain.task_relations import (
    DELEGATED_TO,
    DEPENDS_ON,
    INVOLVES,
    PART_OF,
    REFERENCES,
    REQUESTED_BY,
    WAITING_ON,
)
from app.mcp.server import create_mcp_server
from app.services.domain_tool_service import DomainToolService
from app.services.domain_write_mode import DomainWriteMode
from app.services.graph_service import GraphService
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import AGENT_ORIGIN, CONFIRMED_STATE, PROPOSED_STATE, USER_ORIGIN
from app.tools.assistant_contracts import ASSISTANT_FUNCTION_SCHEMAS
from app.tools.schemas import (
    CreateTaskInput,
    GetTaskProfileInput,
    LinkObjectsInput,
    ToolError,
    UpdateTaskInput,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID

CANONICAL = ("related_to", "references", "depends_on", "part_of")


def test_link_objects_input_accepts_only_the_canonical_types() -> None:
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()
    for relation_type in CANONICAL:
        parsed = LinkObjectsInput(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            confidence=0.5,
        )
        assert parsed.relation_type == relation_type
    for rejected in ("invented_link", "requested_by", EDGE_TYPE_LABELED_WITH, "contains", None):
        with pytest.raises(ValidationError):
            LinkObjectsInput(
                source_id=source_id,
                target_id=target_id,
                relation_type=rejected,
                confidence=0.5,
            )


def test_assistant_and_registry_schemas_share_the_allowlist() -> None:
    definition = ASSISTANT_FUNCTION_SCHEMAS["link_objects"]
    prop = definition["parameters"]["properties"]["relation_type"]
    assert prop["enum"] == list(CANONICAL)
    assert prop["enum"] == list(GENERIC_RELATION_TYPE_VALUES)
    assert "relation_type" in definition["parameters"]["required"]
    text = definition["description"]
    assert "symmetric general relation" in text
    assert "cites or refers" in text
    assert "source/dependent" in text
    assert "child Task" in text
    assert "assign_label" in text
    assert "typed Task fields" in text
    for name, schema in ASSISTANT_FUNCTION_SCHEMAS.items():
        if name == "link_objects":
            continue
        assert "relation_type" not in schema["parameters"].get("properties", {})


@pytest.mark.asyncio
async def test_mcp_link_objects_schema_and_calls(
    db_session, patched_mcp_tool_session, monkeypatch
) -> None:
    forwarded: list[tuple[str, dict]] = []
    real_execute = mcp_server.execute_mcp_tool

    def spy(tool_name: str, arguments: dict):
        forwarded.append((tool_name, dict(arguments)))
        return real_execute(tool_name, arguments)

    monkeypatch.setattr(mcp_server, "execute_mcp_tool", spy)
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _task(graph, "MCP source")
    target = _task(graph, "MCP target")
    before = _edge_count(db_session)

    async with Client(create_mcp_server()) as client:
        listed = await client.list_tools()
        by_name = {tool.name: tool for tool in listed.tools}
        schema = by_name["link_objects"].input_schema
        prop = schema["properties"]["relation_type"]
        assert "relation_type" in schema["required"]
        assert prop.get("type") == "string"
        assert prop.get("enum") == list(CANONICAL)
        assert not _advertises_null(prop)
        for tool in listed.tools:
            if tool.name == "link_objects":
                continue
            assert "relation_type" not in tool.input_schema.get("properties", {})

        accepted = []
        for relation_type in CANONICAL:
            accepted.append(
                await client.call_tool(
                    "link_objects",
                    {
                        "source_id": str(source.id),
                        "target_id": str(target.id),
                        "relation_type": relation_type,
                        "confidence": 0.4,
                    },
                )
            )
        rejected_values = ("invented_link", "requested_by", "labeled_with", "contains", None)
        rejected = [
            await client.call_tool(
                "link_objects",
                {
                    "source_id": str(source.id),
                    "target_id": str(target.id),
                    "relation_type": relation_type,
                    "confidence": 0.4,
                },
            )
            for relation_type in rejected_values
        ]

    for result in accepted:
        assert result.is_error
        assert "approval" in _tool_text(result).lower()
    for result in rejected:
        assert result.is_error
        assert "approval" not in _tool_text(result).lower()
    assert _edge_count(db_session) == before
    forwarded_types = [item["relation_type"] for _name, item in forwarded]
    assert forwarded_types == list(CANONICAL)


def test_domain_link_objects_keeps_direction_and_guards(db_session, fake_embedding_service) -> None:
    tools = _tools(db_session, fake_embedding_service)
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _task(graph, "Source")
    target = _task(graph, "Target")

    related = tools.link_objects(
        LinkObjectsInput(
            source_id=source.id,
            target_id=target.id,
            relation_type="related_to",
            confidence=0.66,
        )
    )
    assert related.created is True
    assert related.edge.type == "related_to"
    assert related.edge.origin == AGENT_ORIGIN
    assert related.edge.state == PROPOSED_STATE
    assert related.edge.source_id == source.id
    assert related.edge.target_id == target.id

    cited = _task(graph, "Cited")
    references = tools.link_objects(
        LinkObjectsInput(
            source_id=source.id,
            target_id=cited.id,
            relation_type="references",
            confidence=0.5,
        )
    )
    assert references.edge.source_id == source.id
    assert references.edge.target_id == cited.id
    assert references.edge.type == REFERENCES

    prerequisite = _task(graph, "Prerequisite")
    depends = tools.link_objects(
        LinkObjectsInput(
            source_id=source.id,
            target_id=prerequisite.id,
            relation_type="depends_on",
            confidence=0.5,
        )
    )
    assert depends.edge.source_id == source.id
    assert depends.edge.target_id == prerequisite.id
    assert depends.edge.type == DEPENDS_ON

    parent = _task(graph, "Parent")
    part = tools.link_objects(
        LinkObjectsInput(
            source_id=source.id,
            target_id=parent.id,
            relation_type="part_of",
            confidence=0.5,
        )
    )
    assert part.edge.source_id == source.id
    assert part.edge.target_id == parent.id
    assert part.edge.type == PART_OF

    again = tools.link_objects(
        LinkObjectsInput(
            source_id=source.id,
            target_id=target.id,
            relation_type="related_to",
            confidence=0.2,
        )
    )
    assert again.created is False
    assert again.edge.id == related.edge.id

    with pytest.raises(ToolError, match="must differ"):
        tools.link_objects(
            LinkObjectsInput(
                source_id=source.id,
                target_id=source.id,
                relation_type="related_to",
                confidence=0.5,
            )
        )

    child = _task(graph, "Ongoing child", completion_mode=TASK_COMPLETION_ONGOING)
    finite_parent = _task(graph, "Finite parent")
    before = _edge_count(db_session)
    with pytest.raises(ToolError):
        tools.link_objects(
            LinkObjectsInput(
                source_id=child.id,
                target_id=finite_parent.id,
                relation_type="part_of",
                confidence=0.5,
            )
        )
    assert _edge_count(db_session) == before

    approved = DomainToolService(
        db_session,
        BOOTSTRAP_USER_ID,
        fake_embedding_service,
        write_mode=DomainWriteMode.APPROVED_CONFIRMED,
    )
    confirmed = approved.link_objects(
        LinkObjectsInput(
            source_id=cited.id,
            target_id=prerequisite.id,
            relation_type="related_to",
            confidence=0.8,
        )
    )
    assert confirmed.edge.origin == AGENT_ORIGIN
    assert confirmed.edge.state == CONFIRMED_STATE
    assert confirmed.edge.source_id == cited.id
    assert confirmed.edge.target_id == prerequisite.id


def test_unsupported_relation_fails_before_insert(db_session, fake_embedding_service) -> None:
    tools = _tools(db_session, fake_embedding_service)
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _task(graph, "Guard source")
    target = _task(graph, "Guard target")
    before = _edge_count(db_session)
    for relation_type in ("invented_link", "requested_by", "contains"):
        with pytest.raises(ToolError, match="unsupported relation type"):
            tools.link_objects(
                LinkObjectsInput.model_construct(
                    source_id=source.id,
                    target_id=target.id,
                    relation_type=relation_type,
                    confidence=0.5,
                )
            )
    with pytest.raises(ToolError, match="assign_label"):
        tools.link_objects(
            LinkObjectsInput.model_construct(
                source_id=source.id,
                target_id=target.id,
                relation_type=EDGE_TYPE_LABELED_WITH,
                confidence=0.5,
            )
        )
    assert _edge_count(db_session) == before


def test_typed_task_relations_stay_available(db_session, fake_embedding_service) -> None:
    tools = _tools(db_session, fake_embedding_service)
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    requester = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Olga")
    other = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Ivan")
    dependency = _task(graph, "Dependency")
    later_dependency = _task(graph, "Later dependency")
    evidence = graph.create_object(
        ObjectCreate(kind="email", title="Mail", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    later_evidence = graph.create_object(
        ObjectCreate(kind="email", title="Later mail", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    created = tools.create_task(
        CreateTaskInput(
            title="Ask Olga",
            confidence=0.8,
            requested_by_person_id=requester.id,
            delegated_to_person_ids=[requester.id],
            waiting_on_person_ids=[requester.id],
            involved_person_ids=[requester.id],
            depends_on_task_ids=[dependency.id],
            evidence_object_ids=[evidence.id],
        )
    )
    updated = tools.update_task(
        UpdateTaskInput(
            object_id=created.object.id,
            delegated_to_person_ids=[other.id],
            waiting_on_person_ids=[other.id],
            involved_person_ids=[other.id],
            depends_on_task_ids=[later_dependency.id],
            evidence_object_ids=[later_evidence.id],
        )
    )
    assert updated.changed is True
    profile = tools.get_task_profile(GetTaskProfileInput(task_id=created.object.id))
    assert [item.person_id for item in profile.requested_by] == [requester.id]
    assert {item.person_id for item in profile.delegated_to} == {requester.id, other.id}
    assert {item.person_id for item in profile.waiting_on} == {requester.id, other.id}
    assert {item.person_id for item in profile.involves} == {requester.id, other.id}
    assert {item.object_id for item in profile.depends_on} == {dependency.id, later_dependency.id}
    assert {item.object_id for item in profile.evidence} == {evidence.id, later_evidence.id}
    stored = {
        (edge.type, edge.source_id, edge.target_id)
        for edge in db_session.scalars(select(Edge).where(Edge.source_id == created.object.id))
    }
    assert (REQUESTED_BY, created.object.id, requester.id) in stored
    assert (DELEGATED_TO, created.object.id, other.id) in stored
    assert (WAITING_ON, created.object.id, other.id) in stored
    assert (INVOLVES, created.object.id, other.id) in stored
    assert (DEPENDS_ON, created.object.id, later_dependency.id) in stored
    assert (REFERENCES, created.object.id, later_evidence.id) in stored


def _tools(db_session, fake_embedding_service) -> DomainToolService:
    return DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)


def _task(graph: GraphService, title: str, completion_mode: str | None = None) -> Object:
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
            completion_mode=completion_mode,
        )
    )


def _edge_count(db_session) -> int:
    return db_session.scalar(select(func.count()).select_from(Edge))


def _tool_text(result) -> str:
    return result.content[0].text


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
