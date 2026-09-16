import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from app.api.deps import get_db, get_embedding_service
from app.api.schemas import EdgeCreate, ObjectCreate, ObjectUpdate
from app.db.models import User
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.summarizer import FakeSummarizer
from app.main import app
from app.services.context_service import ContextService
from app.services.graph_service import GraphService
from app.services.provenance import AGENT_ORIGIN, PROPOSED_STATE
from app.services.representation_service import KIND_CHUNK, KIND_SUMMARY, RepresentationService
from app.users.bootstrap import BOOTSTRAP_USER_ID


class FailingEmbeddingService:
    def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding provider unavailable")


@pytest.fixture
def client(db_session, auth_headers):
    from tests.conftest import apply_embedding_service_overrides, AuthTestClient

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(FakeEmbeddingService())
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


def test_source_email_has_observed_state(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    email = graph.create_object(
        ObjectCreate(
            kind="email",
            title="Meeting tomorrow",
            origin="source",
            body="Let's meet tomorrow at 13:30",
        )
    )
    assert email.origin == "source"
    assert email.state == "observed"


def test_agent_proposed_object_requires_confidence(db_session) -> None:
    with pytest.raises(PydanticValidationError):
        ObjectCreate(kind="event", title="Possible meeting", origin=AGENT_ORIGIN)


def test_agent_proposed_object_with_confidence(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    event = graph.create_object(
        ObjectCreate(
            kind="event",
            title="Possible meeting",
            origin=AGENT_ORIGIN,
            confidence=0.82,
        )
    )
    assert event.origin == AGENT_ORIGIN
    assert event.state == PROPOSED_STATE
    assert event.confidence == 0.82


def test_confirmation_preserves_agent_origin_and_confidence(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    event = graph.create_object(
        ObjectCreate(
            kind="event",
            title="Possible meeting",
            origin=AGENT_ORIGIN,
            confidence=0.82,
        )
    )
    updated = graph.update_object(event.id, ObjectUpdate(state="confirmed"))
    assert updated.origin == AGENT_ORIGIN
    assert updated.state == "confirmed"
    assert updated.confidence == 0.82


def test_rejection_keeps_stored_object(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    event = graph.create_object(
        ObjectCreate(
            kind="event",
            title="Rejected meeting",
            origin=AGENT_ORIGIN,
            confidence=0.55,
        )
    )
    rejected = graph.update_object(event.id, ObjectUpdate(state="rejected"))
    db_session.refresh(rejected)
    assert rejected.state == "rejected"
    stored = graph.get_object(event.id)
    assert stored.title == "Rejected meeting"


def test_confidence_outside_range_rejected(db_session) -> None:
    with pytest.raises(PydanticValidationError):
        ObjectCreate(
            kind="event",
            title="Bad confidence",
            origin=AGENT_ORIGIN,
            confidence=1.5,
        )


def test_object_api_response_contains_provenance(client) -> None:
    response = client.post(
        "/objects",
        json={
            "kind": "email",
            "title": "Source mail",
            "origin": "source",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["origin"] == "source"
    assert body["state"] == "observed"
    assert "confidence" in body


def test_context_item_contains_provenance(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    email = graph.create_object(
        ObjectCreate(
            kind="email",
            title="Observed email",
            origin="source",
            body="Source content",
        )
    )
    result = ContextService(db_session, BOOTSTRAP_USER_ID, FakeEmbeddingService()).build_context(object_id=email.id)
    target_item = result.items[0]
    assert target_item.origin == "source"
    assert target_item.state == "observed"


def test_rejected_relation_excluded_from_context(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = graph.create_object(ObjectCreate(kind="task", title="Active task", origin="user"))
    proposal = graph.create_object(
        ObjectCreate(
            kind="event",
            title="Rejected meeting",
            origin=AGENT_ORIGIN,
            confidence=0.78,
            state="rejected",
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=proposal.id,
            type="related_to",
            origin=AGENT_ORIGIN,
            state="rejected",
            confidence=0.78,
        )
    )

    result = ContextService(db_session, BOOTSTRAP_USER_ID, FakeEmbeddingService()).build_context(object_id=task.id)
    titles = {item.title for item in result.items}
    assert "Active task" in titles
    assert "Rejected meeting" not in titles


def test_agent_proposed_edge_without_confidence_rejected_by_api(client) -> None:
    task = client.post(
        "/objects",
        json={"kind": "task", "title": "Task", "origin": "user"},
    ).json()
    event = client.post(
        "/objects",
        json={
            "kind": "event",
            "title": "Meeting",
            "origin": AGENT_ORIGIN,
            "confidence": 0.7,
        },
    ).json()
    response = client.post(
        "/edges",
        json={
            "source_id": task["id"],
            "target_id": event["id"],
            "type": "related_to",
            "origin": AGENT_ORIGIN,
            "state": PROPOSED_STATE,
        },
    )
    assert response.status_code == 422


def test_search_lexical_fallback_on_embedding_failure(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, FailingEmbeddingService())
    graph.create_object(
        ObjectCreate(kind="note", title="Unique lexical budget keyword", origin="system")
    )
    from app.services.search_service import SearchService

    results = SearchService(db_session, BOOTSTRAP_USER_ID).search("lexical budget keyword")
    assert len(results) == 1
    assert results[0].title == "Unique lexical budget keyword"


def test_context_omits_chunks_when_embedding_fails(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, FakeEmbeddingService())
    doc = graph.create_object(
        ObjectCreate(
            kind="document",
            title="Chunk doc",
            origin="system",
            canonical_uri="file:///chunk.md",
        )
    )
    RepresentationService(
        db_session,
        BOOTSTRAP_USER_ID,
        embedding_service=FakeEmbeddingService(),
        summarizer=FakeSummarizer(max_chars=80),
    ).ingest_text_content(doc.id, "budget planning revenue " * 120)

    result = ContextService(db_session, BOOTSTRAP_USER_ID, FailingEmbeddingService()).build_context(
        object_id=doc.id,
        query="budget revenue",
    )
    repr_kinds = {item.representation_kind for item in result.items if item.representation_kind}
    assert KIND_SUMMARY in repr_kinds
    assert KIND_CHUNK not in repr_kinds


def test_long_document_target_context_includes_summary_and_chunks(db_session) -> None:
    unique_marker = f"xylophone-target-long-{uuid.uuid4()}"
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="provenance-long-doc"))
    db_session.flush()

    graph = GraphService(db_session, user_id, FakeEmbeddingService())
    doc = graph.create_object(
        ObjectCreate(
            kind="document",
            title="Long target document",
            origin="system",
            canonical_uri="file:///target-long.md",
        )
    )
    RepresentationService(
        db_session,
        user_id,
        embedding_service=FakeEmbeddingService(),
        summarizer=FakeSummarizer(max_chars=80),
    ).ingest_text_content(doc.id, f"{unique_marker} budget revenue expense planning " * 100)

    result = ContextService(db_session, user_id, FakeEmbeddingService()).build_context(
        object_id=doc.id,
        query=f"{unique_marker} budget revenue",
    )
    object_items = [item for item in result.items if item.representation_kind is None]
    repr_kinds = {item.representation_kind for item in result.items if item.representation_kind}

    assert len(object_items) == 1
    assert object_items[0].object_id == doc.id
    assert "file:///target-long.md" in object_items[0].content
    assert KIND_SUMMARY in repr_kinds
    assert KIND_CHUNK in repr_kinds


def test_max_chars_never_exceeded_with_truncation(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Truncation task",
            origin="user",
            body="x" * 500,
        )
    )
    max_chars = 40
    result = ContextService(db_session, BOOTSTRAP_USER_ID, FakeEmbeddingService()).build_context(
        object_id=task.id,
        max_chars=max_chars,
    )
    assert result.total_chars <= max_chars
    assert result.truncated
    assert len(result.items) == 1
    assert result.items[0].title == "Truncation task"
