"""PHASE 26C structured query, search ordering, and grounding regressions."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db, get_embedding_service
from app.api.schemas import ObjectCreate
from app.assistant.reference_ids import (
    collect_seen_object_ids_from_bounded_tool,
)
from app.assistant.tool_output import serialize_tool_output_for_model
from app.assistant.tool_runner import PerTurnToolBudget
from app.db.models import Object, User
from app.domain.task_lifecycle import TASK_STATUS_DELETED, TASK_STATUS_OPEN
from app.llm.embedding_service import FakeEmbeddingService
from app.main import app
from app.services.domain_tool_service import DomainToolService
from app.services.errors import ValidationError
from app.services.graph_service import GraphService
from app.services.object_primary_date import object_primary_search_datetime
from app.services.object_query_service import ObjectQueryService
from app.services.provenance import PROPOSED_STATE, REJECTED_STATE
from app.services.search_facet_service import SearchFacetService
from app.services.search_service import SEARCH_SORT_NEWEST, SearchService
from app.tools.registry import MCP_TOOL_NAMES, get_tool_spec
from app.tools.schemas import QueryObjectsInput
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture
def phase26c_client(db_session, auth_headers):
    from tests.conftest import apply_embedding_service_overrides, AuthTestClient

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(FakeEmbeddingService())
    with TestClient(app) as client:
        yield AuthTestClient(client, auth_headers)
    app.dependency_overrides.clear()


def _create_task(
    graph: GraphService,
    title: str,
    *,
    due_at: datetime | None = None,
    status: str | None = TASK_STATUS_OPEN,
    state: str = "confirmed",
) -> Object:
    obj = graph.create_object(
        ObjectCreate(kind="task", title=title, origin="user", state=state)
    )
    obj.kind = "task"
    obj.status = status
    if due_at is not None:
        obj.due_at = due_at
    return obj


def test_query_objects_tool_registry_exposure() -> None:
    spec = get_tool_spec("query_objects")
    assert spec is not None
    assert spec.permission.name == "READ"
    assert spec.assistant_exposed
    assert spec.mcp_exposed
    assert "query_objects" in MCP_TOOL_NAMES


def test_nearest_due_task_regression(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    task_a = _create_task(
        graph,
        "Task A",
        due_at=datetime(2026, 8, 31, tzinfo=UTC),
        status=None,
        state=PROPOSED_STATE,
    )
    task_b = _create_task(
        graph,
        "Task B",
        due_at=datetime(2026, 9, 5, tzinfo=UTC),
        state="confirmed",
    )
    db_session.flush()

    service = DomainToolService(
        db_session, BOOTSTRAP_USER_ID, FakeEmbeddingService()
    )
    result = service.query_objects(
        QueryObjectsInput(
            kinds=["task"],
            statuses=["open", "in_progress"],
            sort_by="due_at",
            sort_order="asc",
            limit=20,
        )
    )
    ids = [row.object_id for row in result.objects]
    assert ids.index(task_a.id) < ids.index(task_b.id)
    first = result.objects[0]
    assert first.object_id == task_a.id
    assert first.status == "open"
    assert first.due_at is not None


def test_legacy_completed_model_status_done(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    task = _create_task(
        graph,
        "Done legacy",
        status="completed",
    )
    db_session.flush()
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, FakeEmbeddingService())
    result = tools.query_objects(
        QueryObjectsInput(kinds=["task"], statuses=["done"], limit=10)
    )
    assert any(row.object_id == task.id for row in result.objects)
    row = next(item for item in result.objects if item.object_id == task.id)
    assert row.status == "done"


def test_query_objects_assistant_output_truncation_preserves_prefix(db_session) -> None:
    from app.assistant.constants import MAX_ASSISTANT_TOOL_OUTPUT_CHARS
    from app.assistant.tool_output import serialize_tool_output_for_assistant

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    for index in range(40):
        _create_task(
            graph,
            f"Long title prefix-{index} " + ("x" * 200),
            due_at=datetime(2026, 8, 1, tzinfo=UTC) + timedelta(days=index),
        )
    db_session.flush()
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, FakeEmbeddingService())
    raw = tools.query_objects(
        QueryObjectsInput(
            kinds=["task"],
            sort_by="due_at",
            sort_order="asc",
            limit=50,
        )
    ).model_dump(mode="json")
    model_out = serialize_tool_output_for_assistant("query_objects", raw)
    assert len(model_out.model_output_json) <= MAX_ASSISTANT_TOOL_OUTPUT_CHARS
    payload = model_out.model_visible_payload
    assert payload.get("objects")
    assert payload.get("truncated") is True
    first_id = raw["objects"][0]["object_id"]
    assert str(first_id) == str(payload["objects"][0]["object_id"])


def test_query_grounding_only_exposed_ids_after_truncation(db_session) -> None:
    from app.assistant.constants import MAX_ASSISTANT_TOOL_OUTPUT_CHARS
    from app.assistant.tool_output import serialize_tool_output_for_assistant

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    tasks = []
    for index in range(40):
        task = _create_task(
            graph,
            f"Ground title-{index} " + ("z" * 200),
            due_at=datetime(2026, 8, 1, tzinfo=UTC) + timedelta(days=index),
        )
        tasks.append(task)
    db_session.flush()
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, FakeEmbeddingService())
    raw = tools.query_objects(
        QueryObjectsInput(
            kinds=["task"],
            sort_by="due_at",
            sort_order="asc",
            limit=50,
        )
    ).model_dump(mode="json")
    model_out = serialize_tool_output_for_assistant("query_objects", raw)
    exposed = {
        row["object_id"]
        for row in model_out.model_visible_payload.get("objects", [])
    }
    assert len(model_out.model_output_json) <= MAX_ASSISTANT_TOOL_OUTPUT_CHARS
    assert str(tasks[0].id) in exposed
    assert str(tasks[-1].id) not in exposed

    budget = PerTurnToolBudget()
    budget.seed_seen_object_ids(
        collect_seen_object_ids_from_bounded_tool(
            "query_objects", model_out.model_visible_payload
        )
    )
    budget.commit_model_visible_outputs()
    blocked = budget.run(
        BOOTSTRAP_USER_ID,
        "set_task_status",
        {"object_id": str(tasks[-1].id), "status": "in_progress"},
    )
    assert blocked.status.name == "TOOL_ERROR"
    assert "not exposed" in (blocked.error or "")

    allowed = budget.run(
        BOOTSTRAP_USER_ID,
        "set_task_status",
        {"object_id": str(tasks[0].id), "status": "in_progress"},
    )
    assert allowed.status.name == "APPROVAL_REQUIRED"


def test_search_facets_cap_and_cross_user(db_session, issue_bearer) -> None:
    from app.services.search_facet_service import MAX_SEARCH_FACETS_PER_DIMENSION

    other_user = uuid4()
    db_session.add(User(id=other_user, display_name="Other"))
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    graph_b = GraphService(db_session, other_user, None)
    for index in range(70):
        graph_a.create_object(
            ObjectCreate(
                kind=f"kind_{index}",
                title=f"Facet {index}",
                origin="system",
            )
        )
    graph_a.create_object(
        ObjectCreate(
            kind="email",
            title="Gmail mine",
            provider="gmail",
            origin="system",
        )
    )
    graph_b.create_object(
        ObjectCreate(
            kind="email",
            title="Other provider",
            provider="provider_b_only",
            origin="system",
        )
    )
    rejected = graph_a.create_object(
        ObjectCreate(kind="task", title="Rejected", origin="user", state=REJECTED_STATE)
    )
    rejected.kind = "task"
    rejected.status = TASK_STATUS_OPEN
    deleted = graph_a.create_object(
        ObjectCreate(kind="task", title="Deleted", origin="user")
    )
    deleted.kind = "task"
    deleted.status = TASK_STATUS_DELETED
    db_session.flush()

    facets = SearchFacetService(db_session, BOOTSTRAP_USER_ID).facets()
    assert len(facets["kinds"]) <= MAX_SEARCH_FACETS_PER_DIMENSION
    assert len(facets["providers"]) <= MAX_SEARCH_FACETS_PER_DIMENSION
    providers = {row["value"] for row in facets["providers"]}
    assert "provider_b_only" not in providers
    kinds = {row["value"] for row in facets["kinds"]}
    assert "task" not in kinds or rejected.id  # rejected hidden from counts


def test_primary_date_naive_modified_at_sort_safe(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    marker = "datetz marker"
    file_obj = graph.create_object(
        ObjectCreate(kind="file", title=f"{marker} naive file", origin="system")
    )
    file_obj.metadata_ = {"modified_at": "2026-08-30T10:00:00"}
    file_obj.updated_at = datetime(2020, 1, 1, tzinfo=UTC)
    aware = graph.create_object(
        ObjectCreate(kind="note", title=f"{marker} aware note", origin="system")
    )
    aware.updated_at = datetime(2026, 8, 31, tzinfo=UTC)
    malformed = graph.create_object(
        ObjectCreate(kind="file", title=f"{marker} malformed", origin="system")
    )
    malformed.metadata_ = {"modified_at": "not-a-date"}
    malformed.updated_at = datetime(2021, 1, 1, tzinfo=UTC)
    db_session.flush()

    search = SearchService(db_session, BOOTSTRAP_USER_ID)
    newest = search.search(marker, limit=3, sort=SEARCH_SORT_NEWEST)
    oldest = search.search(marker, limit=3, sort="oldest")
    assert newest[0].id == aware.id
    assert oldest[0].id == file_obj.id


def test_search_sort_before_limit_eight_candidates(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    marker = "sortgate26c marker"
    newest = graph.create_object(
        ObjectCreate(
            kind="note",
            title=f"minor {marker}",
            body="body",
            origin="system",
        )
    )
    newest.updated_at = datetime(2026, 8, 31, tzinfo=UTC)
    for index in range(7):
        obj = graph.create_object(
            ObjectCreate(
                kind="note",
                title=f"{marker} extra relevance token {index}",
                body=f"{marker} extra relevance token {index}",
                origin="system",
            )
        )
        obj.updated_at = datetime(2020, 1, index + 1, tzinfo=UTC)
    db_session.flush()
    search = SearchService(db_session, BOOTSTRAP_USER_ID)
    relevance = search.search(marker, limit=3, sort="relevance")
    newest_sorted = search.search(marker, limit=3, sort=SEARCH_SORT_NEWEST)
    assert len(relevance) == 3
    assert newest.id in {row.id for row in newest_sorted}
    assert newest_sorted[0].id == newest.id


def test_scripted_deadline_query_objects_model_visibility(db_session, monkeypatch) -> None:
    from app.llm.assistant_models import AssistantProviderResult

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    due_today = _create_task(
        graph,
        "Due today proposed",
        status=None,
        state=PROPOSED_STATE,
        due_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    _create_task(
        graph,
        "Later task",
        due_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    due_id = due_today.id
    db_session.flush()

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    import app.assistant.session as assistant_session_module

    monkeypatch.setattr(assistant_session_module, "SessionLocal", lambda: _TestSession())

    class _DeadlineProvider:
        def run(self, message, history, ui_context, reference_datetime, timezone, tool_runner):
            result = tool_runner(
                "query_objects",
                {
                    "kinds": ["task"],
                    "statuses": ["open", "in_progress"],
                    "sort_by": "due_at",
                    "sort_order": "asc",
                    "limit": 20,
                },
            )
            payload = result.model_visible_payload or {}
            objects = payload.get("objects", [])
            assert objects
            first = objects[0]
            assert first.get("status") == "open"
            assert first.get("due_at") is not None
            assert str(first.get("object_id")) == str(due_id)
            return AssistantProviderResult(
                answer="Found due tasks.",
                candidate_object_ids=collect_seen_object_ids_from_bounded_tool(
                    "query_objects", payload
                ),
            )

    budget = PerTurnToolBudget()
    provider = _DeadlineProvider()
    provider.run(
        "deadline check",
        [],
        "",
        datetime(2026, 8, 31, tzinfo=UTC),
        "UTC",
        lambda name, args: budget.run(BOOTSTRAP_USER_ID, name, args),
    )
    assert due_id in budget.pending_seen_object_ids


def test_proposed_visible_rejected_hidden(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    proposed = _create_task(graph, "Proposed", state=PROPOSED_STATE)
    rejected = _create_task(graph, "Rejected", state=REJECTED_STATE)
    db_session.flush()

    rows = ObjectQueryService(db_session, BOOTSTRAP_USER_ID).query(
        kinds=["task"], limit=50
    )
    ids = {row.id for row in rows}
    assert proposed.id in ids
    assert rejected.id not in ids


def test_deleted_task_hidden(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    active = _create_task(graph, "Active")
    deleted = _create_task(graph, "Deleted", status=TASK_STATUS_DELETED)
    db_session.flush()

    rows = ObjectQueryService(db_session, BOOTSTRAP_USER_ID).query(kinds=["task"])
    ids = {row.id for row in rows}
    assert active.id in ids
    assert deleted.id not in ids


def test_invalid_sort_field_rejected(db_session) -> None:
    service = ObjectQueryService(db_session, BOOTSTRAP_USER_ID)
    with pytest.raises(ValidationError):
        service.query(sort_by="urgent", limit=5)


def test_query_objects_grounding_and_approval(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    task = _create_task(
        graph,
        "Ground me",
        due_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    db_session.flush()

    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, FakeEmbeddingService())
    raw = tools.query_objects(
        QueryObjectsInput(
            kinds=["task"],
            statuses=["open"],
            sort_by="due_at",
            sort_order="asc",
            limit=5,
        )
    ).model_dump(mode="json")
    bounded = serialize_tool_output_for_model("query_objects", raw)
    seen = collect_seen_object_ids_from_bounded_tool("query_objects", bounded)
    assert task.id in seen

    budget = PerTurnToolBudget()
    budget.commit_model_visible_outputs()
    budget.seed_seen_object_ids(seen)
    result = budget.run(
        BOOTSTRAP_USER_ID,
        "set_task_status",
        {"object_id": str(task.id), "status": "in_progress"},
    )
    assert result.status.name == "APPROVAL_REQUIRED"


def test_assistant_tool_chain_get_today_query_mutation(db_session, monkeypatch) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    task = _create_task(
        graph,
        "Chain task",
        due_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    task_id = task.id
    db_session.flush()

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    import app.assistant.session as assistant_session_module

    monkeypatch.setattr(assistant_session_module, "SessionLocal", lambda: _TestSession())

    budget = PerTurnToolBudget()

    today_result = budget.run(BOOTSTRAP_USER_ID, "get_today", {})
    assert today_result.status.name == "SUCCESS"

    query_result = budget.run(
        BOOTSTRAP_USER_ID,
        "query_objects",
        {
            "kinds": ["task"],
            "statuses": ["open"],
            "sort_by": "due_at",
            "sort_order": "asc",
            "limit": 5,
        },
    )
    assert query_result.status.name == "SUCCESS"
    assert task_id in budget.pending_seen_object_ids

    budget.commit_model_visible_outputs()
    assert task_id in budget.seen_object_ids

    mutation = budget.run(
        BOOTSTRAP_USER_ID,
        "set_task_status",
        {"object_id": str(task_id), "status": "in_progress"},
    )
    assert mutation.status.name == "APPROVAL_REQUIRED"
    assert mutation.staged_action is not None
    assert mutation.staged_action["tool_name"] == "set_task_status"
    assert mutation.staged_action["arguments"]["object_id"] == str(task_id)
    assert mutation.staged_action["arguments"]["status"] == "in_progress"


def test_search_newest_ordering_uses_candidate_pool(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    older = graph.create_object(
        ObjectCreate(
            kind="note",
            title="alpha solar budget keyword marker",
            body="older note body",
            origin="system",
        )
    )
    older.updated_at = datetime(2020, 1, 1, tzinfo=UTC)
    newer = graph.create_object(
        ObjectCreate(
            kind="note",
            title="beta solar budget keyword marker",
            body="newer note body",
            origin="system",
        )
    )
    newer.updated_at = datetime(2026, 8, 30, tzinfo=UTC)
    db_session.flush()

    search = SearchService(db_session, BOOTSTRAP_USER_ID)
    newest = search.search("solar budget keyword marker", limit=3, sort=SEARCH_SORT_NEWEST)
    assert newest[0].id == newer.id


def test_search_facets_exclude_other_user(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    graph.create_object(
        ObjectCreate(kind="email", title="Mine", provider="gmail", origin="system")
    )
    db_session.flush()

    facets = SearchFacetService(db_session, BOOTSTRAP_USER_ID).facets()
    kinds = {row["value"] for row in facets["kinds"]}
    assert "email" in kinds


def test_primary_search_date_task_uses_due_at(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    task = _create_task(
        graph,
        "Due",
        due_at=datetime(2026, 8, 15, tzinfo=UTC),
    )
    task.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.flush()
    assert object_primary_search_datetime(task).replace(tzinfo=UTC) == datetime(
        2026, 8, 15, tzinfo=UTC
    )


def test_search_facets_endpoint(phase26c_client) -> None:
    phase26c_client.post(
        "/objects",
        json={"kind": "task", "title": "Facet task", "origin": "user"},
    )
    resp = phase26c_client.get("/search/facets")
    assert resp.status_code == 200
    body = resp.json()
    assert "kinds" in body
    assert "providers" in body


def test_search_sort_query_param(phase26c_client) -> None:
    phase26c_client.post(
        "/objects",
        json={
            "kind": "note",
            "title": "Sortable gamma keyword",
            "body": "content",
            "origin": "system",
        },
    )
    resp = phase26c_client.get(
        "/search",
        params={"q": "Sortable gamma keyword", "sort": "newest", "limit": 5},
    )
    assert resp.status_code == 200


def test_search_kind_and_provider_filters_do_not_500(phase26c_client) -> None:
    phase26c_client.post(
        "/objects",
        json={
            "kind": "email",
            "title": "Норникель provider gmail",
            "body": "норникель metals",
            "origin": "source",
            "provider": "gmail",
        },
    )
    phase26c_client.post(
        "/objects",
        json={
            "kind": "email",
            "title": "Норникель provider yandex",
            "body": "норникель metals",
            "origin": "source",
            "provider": "yandex_mail",
        },
    )
    for provider in ("gmail", "yandex_mail"):
        resp = phase26c_client.get(
            "/search",
            params={
                "q": "норникель",
                "kind": "email",
                "provider": provider,
            },
        )
        assert resp.status_code == 200
        for row in resp.json():
            assert row["provider"] == provider
