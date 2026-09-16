"""PHASE 28B-C2 — remaining per-user request-time / tool embeddings."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.deps import EMBEDDING_PROVIDER_UNAVAILABLE, get_db
from app.assistant.action_plan_constants import (
    PENDING_ACTION_PLAN_STATUS_EXECUTED,
    PENDING_ACTION_PLAN_STATUS_PENDING,
)
from app.assistant.session import run_assistant_tool
from app.db.engine import engine
from app.db.models import Job, Object, PendingActionPlan, User, UserOpenAICredential
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
from app.llm.embedding_text import EMBEDDING_DIMENSION
from app.main import app
from app.mcp.session import tool_session
from app.services.action_plan_service import ActionPlanService
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE
from app.services.user_openai_credential_store import UserOpenAICredentialStore
from app.users.bootstrap import BOOTSTRAP_USER_ID
from app.users.current_user_provider import reset_request_bearer_token, set_request_bearer_token
from tests.conftest import AuthTestClient

USER_A_KEY = "sk-user-a-28b-c2-task-embed-isolation"
USER_B_KEY = "sk-user-b-28b-c2-task-embed-isolation"
DEPLOY_KEY = "sk-deployment-28b-c2-embed-fallback"
LEAK_MARKER = "sk-leak-marker-28b-c2-embed-secret"


def _credential_key() -> str:
    return Fernet.generate_key().decode("utf-8")


@pytest.fixture
def credential_key(monkeypatch) -> str:
    key = _credential_key()
    from app.core.config import settings

    monkeypatch.setattr(settings, "secretary_credential_key", key)
    return key


@pytest.fixture
def task_api_client(db_session, auth_headers):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


@pytest.fixture
def second_user(db_session) -> tuple[UUID, dict[str, str], str]:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="C2 user B"))
    db_session.flush()
    from app.auth.token_service import AuthTokenService

    service = AuthTokenService(db_session)
    token, _ = service.issue_token(user_id, label="pytest-c2-b")
    return user_id, {"Authorization": f"Bearer {token}"}, token


def _delete_user_credential(user_id: UUID) -> None:
    from sqlalchemy.orm import Session as OrmSession

    conn = engine.connect()
    trans = conn.begin()
    session = OrmSession(bind=conn)
    session.execute(delete(UserOpenAICredential).where(UserOpenAICredential.user_id == user_id))
    trans.commit()
    conn.close()


@pytest.fixture
def assistant_tool_db_session(db_session, monkeypatch):
    class _Wrapper:
        def __init__(self) -> None:
            self._session = db_session

        def commit(self) -> None:
            db_session.flush()

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(db_session, name)

    monkeypatch.setattr("app.assistant.session.SessionLocal", lambda: _Wrapper())
    monkeypatch.setattr("app.services.assistant_service.SessionLocal", lambda: _Wrapper())
    return db_session


@pytest.fixture
def mcp_db_session(db_session, monkeypatch):
    class _Wrapper:
        def __init__(self) -> None:
            self._session = db_session

        def commit(self) -> None:
            db_session.flush()

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(db_session, name)

    monkeypatch.setattr("app.mcp.session.SessionLocal", lambda: _Wrapper())
    return db_session


@pytest.fixture(autouse=True)
def _clean_committed_bootstrap_credential() -> None:
    _delete_user_credential(BOOTSTRAP_USER_ID)
    yield
    _delete_user_credential(BOOTSTRAP_USER_ID)


def _upsert_user_key(db_session, user_id: UUID, api_key: str, credential_key: str) -> None:
    UserOpenAICredentialStore(db_session, credential_key).upsert(user_id, api_key)
    db_session.flush()


def _create_task(db_session, user_id: UUID, title: str = "Original", body: str = "Keep body"):
    from app.api.schemas import ObjectCreate

    graph = GraphService(db_session, user_id)
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            body=body,
            origin="user",
            state=CONFIRMED_STATE,
            status="open",
            due_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        )
    )


_TRACKING_INIT_API_KEYS: list[str] = []
_TRACKING_INSTANCES: list = []


class _TrackingEmbeddingService:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        _TRACKING_INIT_API_KEYS.append(api_key)
        _TRACKING_INSTANCES.append(self)

    def embed(self, text: str) -> list[float]:
        return [0.1] * EMBEDDING_DIMENSION


@pytest.fixture(autouse=True)
def _reset_tracking() -> None:
    _TRACKING_INIT_API_KEYS.clear()
    _TRACKING_INSTANCES.clear()
    yield
    _TRACKING_INIT_API_KEYS.clear()
    _TRACKING_INSTANCES.clear()


def test_patch_task_user_a_uses_personal_key(
    task_api_client, db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    task = _create_task(db_session, BOOTSTRAP_USER_ID)
    db_session.flush()
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        response = task_api_client.patch(f"/tasks/{task.id}", json={"title": "Renamed A"})

    assert response.status_code == 200
    assert _TRACKING_INIT_API_KEYS == [USER_A_KEY]


def test_patch_task_user_b_uses_personal_key(
    task_api_client, db_session, monkeypatch, credential_key, second_user
) -> None:
    from app.core.config import settings

    user_b_id, headers_b, _ = second_user
    task = _create_task(db_session, user_b_id, title="B task")
    db_session.flush()
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, user_b_id, USER_B_KEY, credential_key)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        response = task_api_client.patch(
            f"/tasks/{task.id}",
            json={"body": "Updated B body"},
            headers=headers_b,
        )

    assert response.status_code == 200
    assert _TRACKING_INIT_API_KEYS == [USER_B_KEY]


def test_patch_task_user_a_and_b_use_separate_providers(
    task_api_client, db_session, monkeypatch, credential_key, second_user
) -> None:
    from app.core.config import settings

    user_b_id, headers_b, _ = second_user
    task_a = _create_task(db_session, BOOTSTRAP_USER_ID)
    task_b = _create_task(db_session, user_b_id, title="B isolate")
    db_session.flush()
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)
    _upsert_user_key(db_session, user_b_id, USER_B_KEY, credential_key)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        first = task_api_client.patch(f"/tasks/{task_a.id}", json={"title": "A isolate"})
        second = task_api_client.patch(
            f"/tasks/{task_b.id}",
            json={"title": "B isolate"},
            headers=headers_b,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert _TRACKING_INIT_API_KEYS == [USER_A_KEY, USER_B_KEY]
    assert len(_TRACKING_INSTANCES) == 2
    assert _TRACKING_INSTANCES[0].api_key != _TRACKING_INSTANCES[1].api_key


def test_patch_task_deployment_fallback_without_personal_credential(
    task_api_client, db_session, monkeypatch
) -> None:
    from app.core.config import settings

    task = _create_task(db_session, BOOTSTRAP_USER_ID)
    db_session.flush()
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        response = task_api_client.patch(f"/tasks/{task.id}", json={"title": "Deploy title"})

    assert response.status_code == 200
    assert _TRACKING_INIT_API_KEYS == [DEPLOY_KEY]


def test_patch_task_broken_personal_credential_no_deployment_fallback(
    task_api_client, db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    task = _create_task(db_session, BOOTSTRAP_USER_ID)
    db_session.flush()
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, LEAK_MARKER, credential_key)
    monkeypatch.setattr(settings, "secretary_credential_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        response = task_api_client.patch(f"/tasks/{task.id}", json={"title": "Broken"})

    assert response.status_code == 502
    assert response.json()["detail"] == EMBEDDING_PROVIDER_UNAVAILABLE
    assert LEAK_MARKER not in response.text
    assert DEPLOY_KEY not in response.text
    assert _TRACKING_INIT_API_KEYS == []


def test_patch_task_broken_credential_status_delete_and_due_at_still_work(
    task_api_client, db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    task = _create_task(db_session, BOOTSTRAP_USER_ID)
    db_session.flush()
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        created = task_api_client.patch(f"/tasks/{task.id}", json={"title": "Pre-break"})
    assert created.status_code == 200

    monkeypatch.setattr(settings, "secretary_credential_key", Fernet.generate_key().decode())

    status = task_api_client.post(f"/tasks/{task.id}/status", json={"status": "done"})
    assert status.status_code == 200

    due_at = task_api_client.patch(f"/tasks/{task.id}", json={"due_at": None})
    assert due_at.status_code == 200

    delete = task_api_client.delete(f"/tasks/{task.id}")
    assert delete.status_code == 200


def test_patch_task_fake_embedding_without_personal_or_deployment_key(
    task_api_client, db_session, monkeypatch
) -> None:
    from app.core.config import settings

    task = _create_task(db_session, BOOTSTRAP_USER_ID)
    db_session.flush()
    monkeypatch.setattr(settings, "openai_api_key", "")

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        response = task_api_client.patch(f"/tasks/{task.id}", json={"title": "Fake embed"})

    assert response.status_code == 200
    assert _TRACKING_INIT_API_KEYS == []


def test_patch_task_due_at_only_does_not_resolve_embedding_credential(
    task_api_client, db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    task = _create_task(db_session, BOOTSTRAP_USER_ID)
    db_session.flush()
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)

    with patch(
        "app.services.user_embedding_resolver.resolve_embedding_service_for_user"
    ) as resolve_mock, patch(
        "app.llm.embedding_service.OpenAIEmbeddingService",
        _TrackingEmbeddingService,
    ):
        response = task_api_client.patch(f"/tasks/{task.id}", json={"due_at": None})
        resolve_mock.assert_not_called()

    assert response.status_code == 200


def test_assistant_tool_session_user_a_uses_personal_key(
    assistant_tool_db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(assistant_tool_db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        result = run_assistant_tool(BOOTSTRAP_USER_ID, "get_today", {})

    assert result.success
    assert _TRACKING_INIT_API_KEYS == [USER_A_KEY]


def test_assistant_tool_session_user_b_uses_personal_key(
    assistant_tool_db_session, monkeypatch, credential_key, second_user
) -> None:
    from app.core.config import settings

    user_b_id, _, _ = second_user
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(assistant_tool_db_session, user_b_id, USER_B_KEY, credential_key)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        result = run_assistant_tool(user_b_id, "get_today", {})

    assert result.success
    assert _TRACKING_INIT_API_KEYS == [USER_B_KEY]


def test_assistant_tool_session_user_a_and_b_are_isolated(
    assistant_tool_db_session, monkeypatch, credential_key, second_user
) -> None:
    from app.core.config import settings

    user_b_id, _, _ = second_user
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(assistant_tool_db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)
    _upsert_user_key(assistant_tool_db_session, user_b_id, USER_B_KEY, credential_key)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        run_assistant_tool(BOOTSTRAP_USER_ID, "get_today", {})
        run_assistant_tool(user_b_id, "get_today", {})

    assert _TRACKING_INIT_API_KEYS == [USER_A_KEY, USER_B_KEY]
    assert len(_TRACKING_INSTANCES) == 2


def test_assistant_tool_broken_credential_no_fallback_or_leak(
    assistant_tool_db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    _upsert_user_key(assistant_tool_db_session, BOOTSTRAP_USER_ID, LEAK_MARKER, credential_key)
    monkeypatch.setattr(settings, "secretary_credential_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        result = run_assistant_tool(BOOTSTRAP_USER_ID, "get_today", {})

    assert not result.success
    assert result.error == EMBEDDING_PROVIDER_UNAVAILABLE
    assert LEAK_MARKER not in (result.error or "")
    assert DEPLOY_KEY not in (result.error or "")
    assert _TRACKING_INIT_API_KEYS == []


def test_mcp_tool_session_uses_authenticated_user_personal_key(
    mcp_db_session, monkeypatch, credential_key, bootstrap_bearer
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(mcp_db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)

    reset = set_request_bearer_token(bootstrap_bearer)
    try:
        with (
            patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService),
            tool_session() as tools,
        ):
            assert tools is not None
    finally:
        reset_request_bearer_token(reset)

    assert _TRACKING_INIT_API_KEYS == [USER_A_KEY]


def test_mcp_tool_session_deployment_fallback_without_personal_credential(
    mcp_db_session, monkeypatch, bootstrap_bearer
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)

    reset = set_request_bearer_token(bootstrap_bearer)
    try:
        with (
            patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService),
            tool_session(),
        ):
            pass
    finally:
        reset_request_bearer_token(reset)

    assert _TRACKING_INIT_API_KEYS == [DEPLOY_KEY]


def test_mcp_broken_credential_not_bearer_auth(
    mcp_db_session, monkeypatch, credential_key, bootstrap_bearer
) -> None:
    from app.core.config import settings

    _upsert_user_key(mcp_db_session, BOOTSTRAP_USER_ID, LEAK_MARKER, credential_key)
    monkeypatch.setattr(settings, "secretary_credential_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)

    reset = set_request_bearer_token(bootstrap_bearer)
    try:
        with pytest.raises(RuntimeError, match=EMBEDDING_PROVIDER_UNAVAILABLE), tool_session():
            pass
    finally:
        reset_request_bearer_token(reset)


def test_mcp_missing_bearer_still_authentication_failure(mcp_db_session) -> None:
    reset = set_request_bearer_token(None)
    try:
        with pytest.raises(RuntimeError, match="Authorization: Bearer"), tool_session():
            pass
    finally:
        reset_request_bearer_token(reset)


def test_action_plan_approve_does_not_call_create_embedding_service(
    db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)

    plan = PendingActionPlan(
        user_id=BOOTSTRAP_USER_ID,
        status=PENDING_ACTION_PLAN_STATUS_PENDING,
        actions=[
            {
                "tool_name": "create_task",
                "permission": "INTERNAL_WRITE",
                "arguments": {"title": "Deferred embed task", "confidence": 0.8},
            }
        ],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(plan)
    db_session.flush()

    with patch("app.llm.embedding_service.create_embedding_service") as create_mock:
        view = ActionPlanService(db_session, BOOTSTRAP_USER_ID).approve(plan.id)

    create_mock.assert_not_called()
    assert view.status == PENDING_ACTION_PLAN_STATUS_EXECUTED


def test_action_plan_approve_with_broken_personal_credential_still_executes(
    db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, LEAK_MARKER, credential_key)
    monkeypatch.setattr(settings, "secretary_credential_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)

    plan = PendingActionPlan(
        user_id=BOOTSTRAP_USER_ID,
        status=PENDING_ACTION_PLAN_STATUS_PENDING,
        actions=[
            {
                "tool_name": "create_task",
                "permission": "INTERNAL_WRITE",
                "arguments": {"title": "Broken cred deferred", "confidence": 0.75},
            }
        ],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(plan)
    db_session.flush()

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        view = ActionPlanService(db_session, BOOTSTRAP_USER_ID).approve(plan.id)

    assert view.status == PENDING_ACTION_PLAN_STATUS_EXECUTED
    assert LEAK_MARKER not in (view.failure or "")
    assert _TRACKING_INIT_API_KEYS == []
    task = db_session.scalars(
        select(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.kind == "task",
            Object.title == "Broken cred deferred",
        )
    ).one()
    assert task.title == "Broken cred deferred"
    embed_jobs = db_session.scalars(
        select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT, Job.user_id == BOOTSTRAP_USER_ID)
    ).all()
    assert embed_jobs
