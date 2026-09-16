import pytest
from datetime import UTC, datetime
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.schemas import EdgeCreate, ObjectCreate
from app.main import app
from app.services.errors import NotFoundError
from app.services.graph_service import GraphService
from app.services.search_service import SearchService
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture
def client(db_session, auth_headers):
    from tests.conftest import AuthTestClient

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


def test_search_finds_title_keyword_match(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    graph.create_object(
        ObjectCreate(
            kind="note",
            title="Quarterly budget planning meeting",
            body="Discuss revenue targets and expense review.",
            origin="system",
        )
    )
    graph.create_object(
        ObjectCreate(
            kind="note",
            title="Weekend hiking trip",
            body="Mountain trail and camping gear.",
            origin="system",
        )
    )

    search = SearchService(db_session, BOOTSTRAP_USER_ID)
    results = search.search("budget quarterly")

    assert len(results) >= 1
    assert results[0].title == "Quarterly budget planning meeting"


def test_search_project_id_graph_filter(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    project = graph.create_object(ObjectCreate(kind="project", title="Alpha", origin="system"))
    task = graph.create_object(ObjectCreate(kind="task", title="Alpha task", origin="system"))
    graph.create_object(ObjectCreate(kind="task", title="Other task", origin="system"))

    graph.create_edge(
        EdgeCreate(
            source_id=project.id,
            target_id=task.id,
            type="parent_of",
            origin="system",
            state="observed",
        )
    )

    search = SearchService(db_session, BOOTSTRAP_USER_ID)
    results = search.search("task", project_id=project.id, limit=10)
    titles = {item.title for item in results}
    assert "Alpha task" in titles
    assert "Other task" not in titles


def test_search_excludes_deleted_objects_by_default(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    active = graph.create_object(
        ObjectCreate(
            kind="note",
            title="Active searchable calendar note",
            body="visible keyword marker",
            origin="system",
        )
    )
    tombstone = graph.create_object(
        ObjectCreate(
            kind="note",
            title="Deleted searchable calendar note",
            body="visible keyword marker tombstone",
            origin="system",
        )
    )
    tombstone.deleted_at = datetime.now(UTC)
    tombstone.status = "deleted"
    db_session.flush()

    search = SearchService(db_session, BOOTSTRAP_USER_ID)
    results = search.search("visible keyword marker")
    ids = {item.id for item in results}
    assert active.id in ids
    assert tombstone.id not in ids

    with pytest.raises(NotFoundError):
        graph.get_object(tombstone.id)


def test_search_endpoint(client) -> None:
    client.post(
        "/objects",
        json={
            "kind": "note",
            "title": "Renewable solar energy roadmap",
            "origin": "system",
        },
    )
    response = client.get("/search", params={"q": "solar energy roadmap"})
    assert response.status_code == 200
    assert len(response.json()) >= 1
