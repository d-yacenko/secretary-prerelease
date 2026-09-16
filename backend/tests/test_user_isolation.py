import json
import subprocess
import uuid
from datetime import UTC, timedelta
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.connectors.google.constants import GMAIL_READONLY_SCOPE
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleConnectorError
from app.connectors.google.gmail_sync import build_gmail_sync_service
from app.connectors.google.gmail_transport import GoogleTokenManager
from app.connectors.google.oauth_service import GoogleOAuthService
from app.connectors.google.oauth_state import OAuthStateService
from app.db.models import Object, User
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
from app.jobs.handlers import handle_embed_object
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.summarizer import FakeSummarizer
from app.services.context_service import ContextService
from app.services.errors import NotFoundError
from app.services.graph_service import GraphService
from app.services.job_queue_service import JobQueueService
from app.services.notification_service import NotificationService
from app.services.representation_service import RepresentationService
from app.services.search_service import SearchService
from app.services.view_service import ViewService
from app.users.bootstrap import BOOTSTRAP_USER_ID

REPO_ROOT = Path(__file__).resolve().parents[2]


def utcnow():
    from datetime import datetime

    return datetime.now(UTC)


def _create_user(db_session, name: str = "Alt user") -> uuid.UUID:
    user = User(id=uuid.uuid4(), display_name=name)
    db_session.add(user)
    db_session.flush()
    return user.id


def _sample_gmail_message(message_id: str) -> dict:
    return {
        "id": message_id,
        "threadId": "thread-1",
        "labelIds": ["INBOX"],
        "internalDate": "1724846400000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "Hello"},
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "user@example.com"},
            ],
            "body": {"data": "SGVsbG8gd29ybGQ="},
        },
    }


@pytest.fixture
def user_b_id(db_session) -> uuid.UUID:
    return _create_user(db_session, "User B")


@pytest.fixture
def fake_embedding() -> FakeEmbeddingService:
    return FakeEmbeddingService()


def test_user_b_cannot_get_user_a_object(db_session, user_b_id, fake_embedding) -> None:
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding)
    obj = graph_a.create_object(ObjectCreate(kind="task", title="User A task", origin="user"))
    graph_b = GraphService(db_session, user_b_id, fake_embedding)
    with pytest.raises(NotFoundError):
        graph_b.get_object(obj.id)


def test_user_b_cannot_update_user_a_object(db_session, user_b_id, fake_embedding) -> None:
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding)
    obj = graph_a.create_object(ObjectCreate(kind="task", title="Protected", origin="user"))
    graph_b = GraphService(db_session, user_b_id, fake_embedding)
    from app.api.schemas import ObjectUpdate

    with pytest.raises(NotFoundError):
        graph_b.update_object(obj.id, ObjectUpdate(title="Hacked"))


def test_search_never_returns_other_user_object(db_session, user_b_id, fake_embedding) -> None:
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding)
    graph_b = GraphService(db_session, user_b_id, fake_embedding)
    secret = graph_a.create_object(
        ObjectCreate(kind="task", title="unique-alpha-marker-secret", origin="user")
    )
    graph_b.create_object(
        ObjectCreate(kind="task", title="unique-beta-marker-other", origin="user")
    )
    results_a = SearchService(db_session, BOOTSTRAP_USER_ID).search(
        "unique-alpha-marker-secret"
    )
    results_b = SearchService(db_session, user_b_id).search(
        "unique-alpha-marker-secret"
    )
    assert any(r.id == secret.id for r in results_a)
    assert not any(r.id == secret.id for r in results_b)


def test_vector_search_filters_by_user_before_ranking(db_session, user_b_id) -> None:
    class StubEmbedding:
        def embed(self, text: str) -> list[float]:
            return [1.0, 0.0, 0.0]

    stub = StubEmbedding()
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID, stub)
    graph_b = GraphService(db_session, user_b_id, stub)
    obj_a = graph_a.create_object(
        ObjectCreate(kind="task", title="vector-a-only-title", origin="user")
    )
    graph_b.create_object(
        ObjectCreate(kind="task", title="vector-b-only-title", origin="user")
    )
    results = SearchService(db_session, user_b_id).search("vector-a-only-title")
    assert all(r.id != obj_a.id for r in results)


def test_context_service_excludes_other_user_content(db_session, user_b_id, fake_embedding) -> None:
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding)
    obj = graph_a.create_object(
        ObjectCreate(
            kind="email",
            title="Private",
            origin="source",
            body="secret-body-marker",
        )
    )
    with pytest.raises(NotFoundError):
        ContextService(db_session, user_b_id, fake_embedding).build_context(object_id=obj.id)


def test_user_b_cannot_link_to_user_a_object(db_session, user_b_id, fake_embedding) -> None:
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding)
    graph_b = GraphService(db_session, user_b_id, fake_embedding)
    target = graph_a.create_object(ObjectCreate(kind="task", title="Target", origin="user"))
    source = graph_b.create_object(ObjectCreate(kind="task", title="Source", origin="user"))
    with pytest.raises(NotFoundError):
        graph_b.create_edge(
            EdgeCreate(
                source_id=source.id,
                target_id=target.id,
                type="relates_to",
                origin="user",
                state="confirmed",
            )
        )


def test_notification_isolation(db_session, user_b_id) -> None:
    service_a = NotificationService(db_session, BOOTSTRAP_USER_ID)
    notification = service_a.create(
        title="Private",
        body=None,
        priority="normal",
        proposal={"type": "note", "confidence": 0.5, "evidence": []},
    )
    service_b = NotificationService(db_session, user_b_id)
    with pytest.raises(NotFoundError):
        service_b.get(notification.id)
    assert service_b.list_notifications() == []


def test_view_cannot_reference_other_user_object(db_session, user_b_id) -> None:
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID)
    obj = graph_a.create_object(ObjectCreate(kind="task", title="View target", origin="user"))
    views_b = ViewService(db_session, user_b_id)
    view = views_b.create_view(name="B view", view_type="board")
    with pytest.raises(NotFoundError):
        views_b.create_view_item(view.id, object_id=obj.id)


def test_jobs_belong_to_user(db_session) -> None:
    queue = JobQueueService(db_session)
    job = queue.enqueue(JOB_TYPE_EMBED_OBJECT, {"object_id": str(uuid.uuid4())}, BOOTSTRAP_USER_ID)
    assert job.user_id == BOOTSTRAP_USER_ID


def test_worker_rejects_mismatched_job_object_user(db_session, user_b_id, fake_embedding) -> None:
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding)
    obj = graph_a.create_object(ObjectCreate(kind="task", title="Job object", origin="user"))
    embedding_before = list(obj.embedding) if obj.embedding is not None else None
    handle_embed_object(
        db_session,
        fake_embedding,
        {"object_id": str(obj.id)},
        user_b_id,
    )
    db_session.refresh(obj)
    embedding_after = list(obj.embedding) if obj.embedding is not None else None
    assert embedding_after == embedding_before


def test_google_account_belongs_to_user(db_session, user_b_id) -> None:
    key = Fernet.generate_key().decode()
    store = GoogleAccountStore(db_session, CredentialEncryption(key))
    account = store.upsert_tokens(
        user_id=user_b_id,
        email="b@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access",
        refresh_token="refresh",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    assert account.user_id == user_b_id


def test_oauth_state_binds_initiating_user(db_session, user_b_id) -> None:
    state_service = OAuthStateService(db_session)
    state = state_service.create_state(user_b_id)
    recovered = state_service.consume_state(state)
    assert recovered == user_b_id


def test_oauth_callback_uses_state_user_not_caller_supplied(db_session, user_b_id) -> None:
    state_service = OAuthStateService(db_session)
    state = state_service.create_state(user_b_id)
    owner_user_id = state_service.consume_state(state)
    assert owner_user_id == user_b_id
    assert owner_user_id != BOOTSTRAP_USER_ID


def test_gmail_sync_sets_object_user_id(
    db_session,
    user_b_id,
    tmp_path,
    fake_embedding,
) -> None:
    key = Fernet.generate_key().decode()
    oauth_file = tmp_path / "oauth.json"
    oauth_file.write_text(
        json.dumps({"web": {"client_id": "id", "client_secret": "secret"}}),
        encoding="utf-8",
    )
    store = GoogleAccountStore(db_session, CredentialEncryption(key))
    account = store.upsert_tokens(
        user_id=user_b_id,
        email="gmail@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    class FakeHttpClient:
        def get(self, url, params=None, headers=None, **kwargs):
            if url.endswith("/messages"):
                return httpx.Response(200, json={"messages": [{"id": "shared-msg"}]})
            return httpx.Response(200, json=_sample_gmail_message("shared-msg"))

        def post(self, url, data=None, **kwargs):
            raise AssertionError("unexpected post")

    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=key,
        client_file=str(oauth_file),
        redirect_uri="http://localhost:18080/auth/google/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=FakeHttpClient(),
    )
    sync_service.sync_account(account.id, user_b_id, limit=1)
    obj = db_session.scalar(
        select(Object).where(
            Object.external_id == "shared-msg",
            Object.provider == "gmail",
            Object.user_id == user_b_id,
        )
    )
    assert obj is not None


def test_same_gmail_external_id_allowed_for_two_users(
    db_session,
    user_b_id,
    tmp_path,
) -> None:
    key = Fernet.generate_key().decode()
    oauth_file = tmp_path / "oauth.json"
    oauth_file.write_text(
        json.dumps({"web": {"client_id": "id", "client_secret": "secret"}}),
        encoding="utf-8",
    )

    class FakeHttpClient:
        def get(self, url, params=None, headers=None, **kwargs):
            if url.endswith("/messages"):
                return httpx.Response(200, json={"messages": [{"id": "shared-x"}]})
            return httpx.Response(200, json=_sample_gmail_message("shared-x"))

        def post(self, url, data=None, **kwargs):
            raise AssertionError("unexpected post")

    for user_id in (BOOTSTRAP_USER_ID, user_b_id):
        store = GoogleAccountStore(db_session, CredentialEncryption(key))
        account = store.upsert_tokens(
            user_id=user_id,
            email=f"{user_id}@example.com",
            scopes=[GMAIL_READONLY_SCOPE],
            access_token="token",
            refresh_token="refresh",
            token_expiry=utcnow() + timedelta(hours=1),
        )
        db_session.flush()
        sync_service = build_gmail_sync_service(
            session=db_session,
            credential_key=key,
            client_file=str(oauth_file),
            redirect_uri="http://localhost:18080/auth/google/callback",
            sync_days=30,
            default_limit=50,
            max_limit=100,
            http_client=FakeHttpClient(),
        )
        sync_service.sync_account(account.id, user_id, limit=1)

    db_session.scalar(
        select(Object).where(
            Object.external_id == "shared-x",
            Object.provider == "gmail",
        )
    )
    objs = list(
        db_session.scalars(
            select(Object).where(
                Object.external_id == "shared-x",
                Object.provider == "gmail",
            )
        )
    )
    assert len(objs) == 2
    assert {obj.user_id for obj in objs} == {BOOTSTRAP_USER_ID, user_b_id}


def test_gmail_sync_cannot_access_other_users_google_account(
    db_session,
    user_b_id,
    tmp_path,
) -> None:
    key = Fernet.generate_key().decode()
    oauth_file = tmp_path / "oauth.json"
    oauth_file.write_text(
        json.dumps({"web": {"client_id": "id", "client_secret": "secret"}}),
        encoding="utf-8",
    )
    store = GoogleAccountStore(db_session, CredentialEncryption(key))
    account = store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="owner@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="token",
        refresh_token="refresh",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    class FakeHttpClient:
        def get(self, url, params=None, headers=None, **kwargs):
            return httpx.Response(200, json={"messages": []})

        def post(self, url, data=None, **kwargs):
            raise AssertionError("unexpected post")

    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=key,
        client_file=str(oauth_file),
        redirect_uri="http://localhost:18080/auth/google/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=FakeHttpClient(),
    )
    from app.connectors.google.errors import GoogleConnectorError

    with pytest.raises(GoogleConnectorError, match="google account not found"):
        sync_service.sync_account(account.id, user_b_id, limit=1)


def test_google_oauth_json_remains_gitignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-v", "secrets/google-oauth-client.json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "secrets/" in result.stdout


def test_bearer_token_resolves_to_authenticated_user(db_session, issue_bearer) -> None:
    from app.users.current_user_provider import (
        reset_request_bearer_token,
        resolve_current_user,
        set_request_bearer_token,
    )

    token = issue_bearer(BOOTSTRAP_USER_ID, label="isolation-test")
    reset = set_request_bearer_token(token)
    try:
        ctx = resolve_current_user(db_session)
        assert ctx.user_id == BOOTSTRAP_USER_ID
    finally:
        reset_request_bearer_token(reset)


def test_gmail_second_sync_skips_get_for_known_id_without_duplicate_work(
    db_session, tmp_path
) -> None:
    key = Fernet.generate_key().decode()
    oauth_file = tmp_path / "oauth.json"
    oauth_file.write_text(
        json.dumps({"web": {"client_id": "id", "client_secret": "secret"}}),
        encoding="utf-8",
    )
    store = GoogleAccountStore(db_session, CredentialEncryption(key))
    account = store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="owner@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="token",
        refresh_token="refresh",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()
    get_calls = 0

    class FakeHttpClient:
        def get(self, url, params=None, headers=None, **kwargs):
            nonlocal get_calls
            if url.endswith("/messages"):
                return httpx.Response(200, json={"messages": [{"id": "inc-1"}]})
            get_calls += 1
            return httpx.Response(200, json=_sample_gmail_message("inc-1"))

        def post(self, url, data=None, **kwargs):
            raise AssertionError("unexpected post")

    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=key,
        client_file=str(oauth_file),
        redirect_uri="http://localhost:18080/auth/google/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=FakeHttpClient(),
    )
    first = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)
    second = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)
    assert first["created"] == 1
    assert second["unchanged"] == 1
    assert get_calls == 1


def test_user_a_known_gmail_id_does_not_skip_fetch_for_user_b(
    db_session, user_b_id, tmp_path
) -> None:
    key = Fernet.generate_key().decode()
    oauth_file = tmp_path / "oauth.json"
    oauth_file.write_text(
        json.dumps({"web": {"client_id": "id", "client_secret": "secret"}}),
        encoding="utf-8",
    )
    get_calls = 0

    class FakeHttpClient:
        def get(self, url, params=None, headers=None, **kwargs):
            nonlocal get_calls
            if url.endswith("/messages"):
                return httpx.Response(200, json={"messages": [{"id": "cross-user-x"}]})
            get_calls += 1
            return httpx.Response(200, json=_sample_gmail_message("cross-user-x"))

        def post(self, url, data=None, **kwargs):
            raise AssertionError("unexpected post")

    store_a = GoogleAccountStore(db_session, CredentialEncryption(key))
    account_a = store_a.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="owner@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="token",
        refresh_token="refresh",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.flush()
    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=key,
        client_file=str(oauth_file),
        redirect_uri="http://localhost:18080/auth/google/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=FakeHttpClient(),
    )
    sync_service.sync_account(account_a.id, BOOTSTRAP_USER_ID, limit=1)
    assert get_calls == 1

    store_b = GoogleAccountStore(db_session, CredentialEncryption(key))
    account_b = store_b.upsert_tokens(
        user_id=user_b_id,
        email="user-b@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="token",
        refresh_token="refresh",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.flush()
    sync_service.sync_account(account_b.id, user_b_id, limit=1)
    assert get_calls == 2


def test_user_b_cannot_load_credentials_for_user_a_google_account(
    db_session, user_b_id, tmp_path
) -> None:
    key = Fernet.generate_key().decode()
    oauth_file = tmp_path / "oauth.json"
    oauth_file.write_text(
        json.dumps({"web": {"client_id": "id", "client_secret": "secret"}}),
        encoding="utf-8",
    )
    store = GoogleAccountStore(db_session, CredentialEncryption(key))
    account = store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="owner@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="token",
        refresh_token="refresh",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    assert store.load_credential_snapshot(account.id, user_b_id) is None

    token_manager = GoogleTokenManager(
        db_session,
        store,
        GoogleOAuthService(str(oauth_file), "http://localhost:18080/auth/google/callback"),
    )
    with pytest.raises(GoogleConnectorError, match="google account not found"):
        token_manager.get_valid_access_token(account.id, user_b_id)


def test_user_b_cannot_list_representations_for_user_a_object(
    db_session, user_b_id, fake_embedding
) -> None:
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding)
    obj = graph_a.create_object(
        ObjectCreate(kind="document", title="Private doc", origin="user")
    )
    RepresentationService(db_session, BOOTSTRAP_USER_ID, fake_embedding).ingest_text_content(
        obj.id, "private representation text"
    )
    with pytest.raises(NotFoundError):
        RepresentationService(db_session, user_b_id, fake_embedding).list_for_object(obj.id)


def test_user_b_cannot_ingest_representations_for_user_a_object(
    db_session, user_b_id, fake_embedding
) -> None:
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding)
    obj = graph_a.create_object(
        ObjectCreate(kind="document", title="Locked doc", origin="user")
    )
    with pytest.raises(NotFoundError):
        RepresentationService(db_session, user_b_id, fake_embedding).ingest_text_content(
            obj.id, "attempted ingest"
        )


def test_context_for_user_b_never_contains_user_a_representations(
    db_session, user_b_id, fake_embedding
) -> None:
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding)
    doc = graph_a.create_object(
        ObjectCreate(
            kind="document",
            title="Secret doc",
            origin="user",
            canonical_uri="file:///secret.md",
        )
    )
    RepresentationService(
        db_session,
        BOOTSTRAP_USER_ID,
        fake_embedding,
        summarizer=FakeSummarizer(max_chars=80),
    ).ingest_text_content(doc.id, "secret-marker-text " * 40)
    task_b = GraphService(db_session, user_b_id, fake_embedding).create_object(
        ObjectCreate(kind="task", title="User B task", origin="user")
    )
    context = ContextService(db_session, user_b_id, fake_embedding).build_context(
        object_id=task_b.id,
        query="secret-marker-text",
    )
    assert all("secret-marker-text" not in item.content for item in context.items)
