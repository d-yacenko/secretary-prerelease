import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db
from app.api.schemas import EdgeCreate, ObjectCreate
from app.auth.token_service import AuthTokenService
from app.db.models import Edge, Object, User
from app.main import app
from app.services.capture_service import PINNED_CONTEXT_ROLE
from app.services.context_service import DEFAULT_MAX_CHARS, ContextService
from app.services.graph_service import GraphService
from app.users.bootstrap import BOOTSTRAP_USER_ID


def _create_user(db_session, name: str = "Alt user") -> uuid.UUID:
    user = User(id=uuid.uuid4(), display_name=name)
    db_session.add(user)
    db_session.flush()
    return user.id


def test_unauthenticated_api_returns_401() -> None:
    client = TestClient(app)
    response = client.get("/me")
    assert response.status_code == 401


def test_invalid_token_returns_401(db_session) -> None:
    client = TestClient(app)
    response = client.get("/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_revoked_token_returns_401(db_session, issue_bearer) -> None:
    token = issue_bearer(BOOTSTRAP_USER_ID, label="revoke-me")
    AuthTokenService(db_session).revoke_by_prefix(BOOTSTRAP_USER_ID, "revoke-me")
    client = TestClient(app)
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_get_me_returns_safe_fields(auth_client) -> None:
    response = auth_client.get("/me")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(BOOTSTRAP_USER_ID)
    assert body["display_name"] == "Owner"
    assert "created_at" in body
    assert "token" not in body


def test_two_tokens_resolve_to_isolated_users(db_session, issue_bearer) -> None:
    user_b = _create_user(db_session, "User B")
    token_a = issue_bearer(BOOTSTRAP_USER_ID, label="user-a")
    token_b = issue_bearer(user_b, label="user-b")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        me_a = client.get("/me", headers={"Authorization": f"Bearer {token_a}"})
        me_b = client.get("/me", headers={"Authorization": f"Bearer {token_b}"})
        assert me_a.json()["id"] == str(BOOTSTRAP_USER_ID)
        assert me_b.json()["id"] == str(user_b)
    finally:
        app.dependency_overrides.clear()


def test_get_connections_returns_status_without_secrets(auth_client) -> None:
    response = auth_client.get("/connections")
    assert response.status_code == 200
    body = response.json()
    assert "google" in body
    assert "yandex_mail" in body
    assert "yandex_calendar" in body
    dumped = str(body)
    assert "access_token" not in dumped
    assert "refresh_token" not in dumped
    assert "app_password" not in dumped


def test_manual_capture_creates_task_with_pinned_context_and_dependency(
    db_session, auth_client
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    course_plan = graph.create_object(
        ObjectCreate(
            kind="document",
            title="Course plan",
            origin="user",
            state="confirmed",
            canonical_uri="personal://resource/course-plan",
        )
    )
    cloud_folder = graph.create_object(
        ObjectCreate(
            kind="folder",
            title="Training center materials",
            origin="user",
            state="confirmed",
            provider="google_drive",
            canonical_uri="https://drive.google.com/folder/training",
        )
    )
    gmail_source = graph.create_object(
        ObjectCreate(
            kind="email",
            title="Gmail thread",
            origin="source",
            state="confirmed",
            provider="gmail",
            external_id="msg-capture-regression",
            canonical_uri="gmail://msg-capture-regression",
        )
    )
    dependency = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Prerequisite task",
            origin="user",
            state="confirmed",
        )
    )
    db_session.flush()

    manual_text = (
        "Prepare the first three topics of the course.\n"
        "From our training center only I can teach these topics."
    )
    response = auth_client.post(
        "/capture/task",
        json={
            "text": manual_text,
            "context_object_ids": [
                str(course_plan.id),
                str(cloud_folder.id),
                str(gmail_source.id),
            ],
            "depends_on_ids": [str(dependency.id)],
        },
    )
    assert response.status_code == 201
    body = response.json()
    task_id = uuid.UUID(body["task_id"])
    assert len(body["context_edge_ids"]) == 3
    assert len(body["dependency_edge_ids"]) == 1

    task = db_session.get(Object, task_id)
    assert task is not None
    assert task.user_id == BOOTSTRAP_USER_ID
    assert task.kind == "task"
    assert task.origin == "user"
    assert task.state == "confirmed"
    assert task.body == manual_text

    ref_edges = db_session.scalars(
        select(Edge).where(
            Edge.source_id == task_id,
            Edge.type == "references",
            Edge.state == "confirmed",
        )
    ).all()
    assert len(ref_edges) == 3
    for edge in ref_edges:
        assert edge.metadata_["context_role"] == PINNED_CONTEXT_ROLE
        assert edge.metadata_["added_by"] == "user"

    dep_edges = db_session.scalars(
        select(Edge).where(
            Edge.source_id == task_id,
            Edge.type == "depends_on",
            Edge.state == "confirmed",
        )
    ).all()
    assert len(dep_edges) == 1
    assert dep_edges[0].target_id == dependency.id


def test_manual_capture_context_prioritizes_pinned_over_semantic(
    db_session, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    pinned_doc = graph.create_object(
        ObjectCreate(
            kind="document",
            title="Pinned course syllabus",
            origin="user",
            state="confirmed",
            body="unique pinned syllabus marker alpha",
        )
    )
    semantic_doc = graph.create_object(
        ObjectCreate(
            kind="document",
            title="Semantic competitor document",
            origin="system",
            state="confirmed",
            body="unique semantic competitor marker beta query terms",
        )
    )
    task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Teach topics",
            origin="user",
            state="confirmed",
            body="Prepare course topics from training center",
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=pinned_doc.id,
            type="references",
            origin="user",
            state="confirmed",
            metadata={"context_role": PINNED_CONTEXT_ROLE, "added_by": "user"},
        )
    )
    db_session.flush()

    context = ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    result = context.build_context(
        object_id=task.id,
        query="unique semantic competitor marker beta query terms",
        max_chars=DEFAULT_MAX_CHARS,
    )
    why_included = [item.why_included for item in result.items]
    assert any("user-pinned" in reason for reason in why_included)
    pinned_index = next(
        i for i, item in enumerate(result.items) if item.object_id == pinned_doc.id
    )
    semantic_index = next(
        (
            i
            for i, item in enumerate(result.items)
            if item.object_id == semantic_doc.id
        ),
        len(result.items),
    )
    if semantic_index < len(result.items):
        assert pinned_index < semantic_index


def test_manual_capture_rejects_cross_user_context(
    db_session, auth_client, issue_bearer
) -> None:
    user_b = _create_user(db_session, "User B")
    graph_b = GraphService(db_session, user_b)
    foreign = graph_b.create_object(
        ObjectCreate(kind="document", title="Foreign doc", origin="user", state="confirmed")
    )
    db_session.flush()

    response = auth_client.post(
        "/capture/task",
        json={
            "text": "Try cross-user capture",
            "context_object_ids": [str(foreign.id)],
        },
    )
    assert response.status_code == 404
    tasks = db_session.scalars(
        select(Object).where(Object.kind == "task", Object.body == "Try cross-user capture")
    ).all()
    assert tasks == []


def test_manual_capture_does_not_require_openai(db_session, auth_client) -> None:
    with patch("app.llm.embedding_service.create_embedding_service") as factory:
        factory.side_effect = RuntimeError("OpenAI unavailable")
        response = auth_client.post(
            "/capture/task",
            json={"text": "Standalone capture without OpenAI"},
        )
    assert response.status_code == 201
    task_id = uuid.UUID(response.json()["task_id"])
    task = db_session.get(Object, task_id)
    assert task is not None
    assert task.body == "Standalone capture without OpenAI"


def test_google_oauth_start_requires_authentication(db_session) -> None:
    client = TestClient(app)
    response = client.get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 401


def test_google_oauth_start_binds_state_to_authenticated_user(
    db_session, issue_bearer
) -> None:
    from sqlalchemy import select

    from app.db.models import OAuthState

    token = issue_bearer(BOOTSTRAP_USER_ID, label="google-oauth")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        with patch("app.api.google._google_oauth_service") as mock_oauth:
            mock_oauth.return_value.build_authorization_url.return_value = "http://redirect"
            response = client.get(
                "/auth/google/start",
                headers={"Authorization": f"Bearer {token}"},
                follow_redirects=False,
            )
        assert response.status_code in {302, 307}
        states = db_session.scalars(
            select(OAuthState).where(OAuthState.user_id == BOOTSTRAP_USER_ID)
        ).all()
        assert states
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def dual_auth_clients(db_session, issue_bearer):
    from tests.conftest import AuthTestClient

    user_b_id = _create_user(db_session, "HTTP User B")
    token_a = issue_bearer(BOOTSTRAP_USER_ID, label="http-user-a")
    token_b = issue_bearer(user_b_id, label="http-user-b")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    raw = TestClient(app)
    clients = {
        "a": AuthTestClient(raw, {"Authorization": f"Bearer {token_a}"}),
        "b": AuthTestClient(raw, {"Authorization": f"Bearer {token_b}"}),
        "user_b_id": user_b_id,
    }
    yield clients
    app.dependency_overrides.clear()


def test_capture_enqueues_embed_job_without_synchronous_openai(db_session, auth_client) -> None:
    from app.db.models import Job
    from app.jobs.constants import JOB_TYPE_EMBED_OBJECT

    with patch("app.llm.embedding_service.create_embedding_service") as factory:
        factory.side_effect = RuntimeError("OpenAI unavailable")
        response = auth_client.post(
            "/capture/task",
            json={"text": "enqueue embed without sync openai"},
        )
    assert response.status_code == 201
    task_id = response.json()["task_id"]
    jobs = [
        job
        for job in db_session.scalars(
            select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)
        ).all()
        if job.payload.get("object_id") == task_id
    ]
    assert len(jobs) == 1
    assert jobs[0].user_id == BOOTSTRAP_USER_ID


def test_captured_task_becomes_searchable_after_embed_handler(
    db_session, auth_client, fake_embedding_service
) -> None:
    from app.db.models import Job
    from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
    from app.jobs.handlers import handle_embed_object
    from app.services.search_service import SearchService

    marker = "capture-semantic-index-marker-unique"
    response = auth_client.post("/capture/task", json={"text": marker})
    assert response.status_code == 201
    task_id = uuid.UUID(response.json()["task_id"])
    jobs = [
        job
        for job in db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)).all()
        if job.payload.get("object_id") == str(task_id)
    ]
    assert len(jobs) == 1
    job = jobs[0]

    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.services.representation_embedding_worker.SessionLocal", lambda: db_session
    ), patch.object(db_session, "close", lambda: None):
        handle_embed_object(db_session, fake_embedding_service, job.payload, BOOTSTRAP_USER_ID)

    task = db_session.get(Object, task_id)
    assert task is not None
    assert task.embedding is not None
    results = SearchService(db_session, BOOTSTRAP_USER_ID).search(marker)
    assert any(result.id == task_id for result in results)


def test_capture_preserves_exact_body_whitespace(db_session, auth_client) -> None:
    text = "  \n  leading and trailing spaces  \n"
    response = auth_client.post("/capture/task", json={"text": text})
    assert response.status_code == 201
    task = db_session.get(Object, uuid.UUID(response.json()["task_id"]))
    assert task is not None
    assert task.body == text


def test_capture_rejects_blank_only_text(db_session, auth_client) -> None:
    response = auth_client.post("/capture/task", json={"text": "   \n\t  "})
    assert response.status_code == 422


def test_capture_rejects_oversized_text_and_title(db_session, auth_client) -> None:
    from app.services.capture_service import MAX_CAPTURE_TEXT_CHARS, MAX_CAPTURE_TITLE_CHARS

    too_long = "x" * (MAX_CAPTURE_TEXT_CHARS + 1)
    response = auth_client.post("/capture/task", json={"text": too_long})
    assert response.status_code == 422

    long_title = "t" * (MAX_CAPTURE_TITLE_CHARS + 1)
    response = auth_client.post(
        "/capture/task",
        json={"text": "valid body", "title": long_title},
    )
    assert response.status_code == 422


def test_pinned_gmail_body_includes_bounded_excerpt(db_session, fake_embedding_service) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    email_body = "EMAIL_BODY_MARKER " + ("detailed lesson content. " * 80)
    assert len(email_body) > 1800
    email = graph.create_object(
        ObjectCreate(
            kind="email",
            title="Training inquiry",
            origin="source",
            state="confirmed",
            provider="gmail",
            external_id="pinned-gmail-body",
            canonical_uri="gmail://pinned-gmail-body",
            body=email_body,
        )
    )
    task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Follow up",
            origin="user",
            state="confirmed",
            body="Prepare response",
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=email.id,
            type="references",
            origin="user",
            state="confirmed",
            metadata={"context_role": PINNED_CONTEXT_ROLE, "added_by": "user"},
        )
    )
    db_session.flush()

    result = ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service).build_context(
        object_id=task.id,
        max_chars=DEFAULT_MAX_CHARS,
    )
    email_items = [item for item in result.items if item.object_id == email.id]
    assert email_items
    combined = "\n".join(item.content for item in email_items)
    assert "EMAIL_BODY_MARKER" in combined
    assert "gmail://pinned-gmail-body" in combined
    assert len(email_body) > len(combined)
    assert "truncated" in combined.lower()


def test_pinned_object_with_representations_uses_rep_content(
    db_session, fake_embedding_service
) -> None:
    from app.services.representation_service import RepresentationService

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    doc = graph.create_object(
        ObjectCreate(
            kind="document",
            title="Course syllabus",
            origin="user",
            state="confirmed",
            canonical_uri="personal://docs/syllabus",
            body="full body not dumped wholesale",
        )
    )
    RepresentationService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service).ingest_text_content(
        doc.id, "REPRESENTATION_MARKER syllabus excerpt"
    )
    task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Plan course",
            origin="user",
            state="confirmed",
            body="Use pinned syllabus",
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=doc.id,
            type="references",
            origin="user",
            state="confirmed",
            metadata={"context_role": PINNED_CONTEXT_ROLE, "added_by": "user"},
        )
    )
    db_session.flush()

    result = ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service).build_context(
        object_id=task.id,
        max_chars=DEFAULT_MAX_CHARS,
    )
    doc_items = [item for item in result.items if item.object_id == doc.id]
    assert doc_items
    combined = "\n".join(item.content for item in doc_items)
    assert "REPRESENTATION_MARKER" in combined
    assert "full body not dumped wholesale" not in combined


def test_http_user_a_cannot_get_user_b_object(dual_auth_clients, db_session) -> None:
    graph_b = GraphService(db_session, dual_auth_clients["user_b_id"])
    secret = graph_b.create_object(
        ObjectCreate(kind="task", title="User B secret", origin="user", state="confirmed")
    )
    db_session.flush()
    response = dual_auth_clients["a"].get(f"/objects/{secret.id}")
    assert response.status_code == 404


def test_http_search_does_not_return_other_user_objects(dual_auth_clients, db_session) -> None:
    marker = f"unique-http-search-{uuid.uuid4()}"
    graph_b = GraphService(db_session, dual_auth_clients["user_b_id"])
    secret = graph_b.create_object(
        ObjectCreate(
            kind="task",
            title=marker,
            origin="user",
            state="confirmed",
        )
    )
    db_session.flush()
    response = dual_auth_clients["a"].get("/search", params={"q": marker})
    assert response.status_code == 200
    titles = [row["title"] for row in response.json()]
    assert marker not in titles
    returned_ids = {row["id"] for row in response.json()}
    assert str(secret.id) not in returned_ids


def test_http_user_a_cannot_get_neighbors_for_user_b_object(
    dual_auth_clients, db_session
) -> None:
    graph_b = GraphService(db_session, dual_auth_clients["user_b_id"])
    secret = graph_b.create_object(
        ObjectCreate(kind="task", title="Neighbor secret", origin="user", state="confirmed")
    )
    db_session.flush()
    response = dual_auth_clients["a"].get(f"/objects/{secret.id}/neighbors")
    assert response.status_code == 404


def test_http_user_a_cannot_get_context_for_user_b_object(dual_auth_clients, db_session) -> None:
    graph_b = GraphService(db_session, dual_auth_clients["user_b_id"])
    secret = graph_b.create_object(
        ObjectCreate(kind="task", title="Context secret", origin="user", state="confirmed")
    )
    db_session.flush()
    response = dual_auth_clients["a"].get(f"/objects/{secret.id}/context")
    assert response.status_code == 404


def test_http_user_a_cannot_create_edge_to_user_b_object(dual_auth_clients, db_session) -> None:
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID)
    graph_b = GraphService(db_session, dual_auth_clients["user_b_id"])
    source = graph_a.create_object(
        ObjectCreate(kind="task", title="Edge source", origin="user", state="confirmed")
    )
    target = graph_b.create_object(
        ObjectCreate(kind="task", title="Edge target", origin="user", state="confirmed")
    )
    db_session.flush()
    response = dual_auth_clients["a"].post(
        "/edges",
        json={
            "source_id": str(source.id),
            "target_id": str(target.id),
            "type": "depends_on",
            "origin": "user",
            "state": "confirmed",
        },
    )
    assert response.status_code == 404


def test_http_user_b_token_creates_objects_owned_by_b(dual_auth_clients, db_session) -> None:
    response = dual_auth_clients["b"].post(
        "/objects",
        json={"kind": "task", "title": "Owned by B", "origin": "user", "state": "confirmed"},
    )
    assert response.status_code == 201
    obj = db_session.get(Object, uuid.UUID(response.json()["id"]))
    assert obj is not None
    assert obj.user_id == dual_auth_clients["user_b_id"]


def test_google_oauth_start_with_user_b_token_binds_state_to_b(
    db_session, issue_bearer
) -> None:
    from sqlalchemy import select

    from app.db.models import OAuthState

    user_b_id = _create_user(db_session, "OAuth User B")
    token_b = issue_bearer(user_b_id, label="google-oauth-b")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        with patch("app.api.google._google_oauth_service") as mock_oauth:
            mock_oauth.return_value.build_authorization_url.return_value = "http://redirect"
            response = client.get(
                "/auth/google/start",
                headers={"Authorization": f"Bearer {token_b}"},
                follow_redirects=False,
            )
        assert response.status_code in {302, 307}
        state = db_session.scalar(
            select(OAuthState).where(OAuthState.user_id == user_b_id)
        )
        assert state is not None
        bootstrap_states = db_session.scalars(
            select(OAuthState).where(OAuthState.user_id == BOOTSTRAP_USER_ID)
        ).all()
        assert all(row.id != state.id for row in bootstrap_states)
    finally:
        app.dependency_overrides.clear()


def test_connections_reflect_only_authenticated_user_records(
    db_session, dual_auth_clients, monkeypatch
) -> None:
    from datetime import timedelta

    from cryptography.fernet import Fernet

    from app.connectors.google.constants import GMAIL_READONLY_SCOPE
    from app.connectors.google.credentials import GoogleAccountStore
    from app.connectors.google.encryption import CredentialEncryption
    from app.core.config import settings

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "secretary_credential_key", key)
    store = GoogleAccountStore(db_session, CredentialEncryption(key))
    store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="owner-only@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="token",
        refresh_token="refresh",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.flush()

    owner_resp = dual_auth_clients["a"].get("/connections")
    assert owner_resp.status_code == 200
    assert owner_resp.json()["google"]["connected"] is True
    assert owner_resp.json()["google"]["email"] == "owner-only@example.com"

    other_resp = dual_auth_clients["b"].get("/connections")
    assert other_resp.status_code == 200
    assert other_resp.json()["google"]["connected"] is False
    assert other_resp.json()["google"]["email"] is None
