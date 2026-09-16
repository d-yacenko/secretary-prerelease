"""PHASE 28B-C — per-user request-time graph embeddings."""

import uuid
from unittest.mock import patch
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api.deps import EMBEDDING_PROVIDER_UNAVAILABLE, get_db, get_user_embedding_service
from app.db.engine import engine
from app.db.models import User, UserOpenAICredential
from app.llm.embedding_text import EMBEDDING_DIMENSION
from app.main import app
from app.services.user_openai_credential_store import UserOpenAICredentialStore
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient

USER_A_KEY = "sk-user-a-28b-graph-embed-isolation"
USER_B_KEY = "sk-user-b-28b-graph-embed-isolation"
DEPLOY_KEY = "sk-deployment-28b-graph-embed-fallback"
LEAK_MARKER = "sk-leak-marker-28b-graph-embed-secret"


def _credential_key() -> str:
    return Fernet.generate_key().decode("utf-8")


@pytest.fixture
def credential_key(monkeypatch) -> str:
    key = _credential_key()
    from app.core.config import settings

    monkeypatch.setattr(settings, "secretary_credential_key", key)
    return key


@pytest.fixture
def graph_api_client(db_session, auth_headers):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


@pytest.fixture
def second_user(db_session) -> tuple[UUID, dict[str, str]]:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Graph embed user B"))
    db_session.flush()
    from app.auth.token_service import AuthTokenService

    service = AuthTokenService(db_session)
    token, _ = service.issue_token(user_id, label="pytest-graph-embed-b")
    return user_id, {"Authorization": f"Bearer {token}"}


def _delete_user_credential(user_id: UUID) -> None:
    from sqlalchemy.orm import Session as OrmSession

    conn = engine.connect()
    trans = conn.begin()
    session = OrmSession(bind=conn)
    session.execute(delete(UserOpenAICredential).where(UserOpenAICredential.user_id == user_id))
    trans.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _clean_committed_bootstrap_credential() -> None:
    _delete_user_credential(BOOTSTRAP_USER_ID)
    yield
    _delete_user_credential(BOOTSTRAP_USER_ID)


def _upsert_user_key(db_session, user_id: UUID, api_key: str, credential_key: str) -> None:
    UserOpenAICredentialStore(db_session, credential_key).upsert(user_id, api_key)
    db_session.flush()


def _object_payload(title: str = "Graph embed object") -> dict:
    return {"kind": "task", "title": title, "origin": "system"}


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


def test_post_objects_user_a_uses_personal_key(
    graph_api_client, db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        response = graph_api_client.post("/objects", json=_object_payload("User A object"))

    assert response.status_code == 201
    assert _TRACKING_INIT_API_KEYS == [USER_A_KEY]


def test_post_objects_user_b_uses_personal_key(
    graph_api_client, db_session, monkeypatch, credential_key, second_user
) -> None:
    from app.core.config import settings

    user_b_id, headers_b = second_user
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, user_b_id, USER_B_KEY, credential_key)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        response = graph_api_client.post(
            "/objects",
            json=_object_payload("User B object"),
            headers=headers_b,
        )

    assert response.status_code == 201
    assert _TRACKING_INIT_API_KEYS == [USER_B_KEY]


def test_post_objects_user_a_and_b_use_separate_providers(
    graph_api_client, db_session, monkeypatch, credential_key, second_user
) -> None:
    from app.core.config import settings

    user_b_id, headers_b = second_user
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)
    _upsert_user_key(db_session, user_b_id, USER_B_KEY, credential_key)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        first = graph_api_client.post("/objects", json=_object_payload("A isolate"))
        second = graph_api_client.post(
            "/objects",
            json=_object_payload("B isolate"),
            headers=headers_b,
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert _TRACKING_INIT_API_KEYS == [USER_A_KEY, USER_B_KEY]
    assert len(_TRACKING_INSTANCES) == 2
    assert _TRACKING_INSTANCES[0].api_key != _TRACKING_INSTANCES[1].api_key


def test_post_objects_deployment_fallback_without_personal_credential(
    graph_api_client, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        response = graph_api_client.post("/objects", json=_object_payload("Deploy fallback"))

    assert response.status_code == 201
    assert _TRACKING_INIT_API_KEYS == [DEPLOY_KEY]


def test_post_objects_broken_personal_credential_no_deployment_fallback(
    graph_api_client, db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, LEAK_MARKER, credential_key)
    monkeypatch.setattr(settings, "secretary_credential_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        response = graph_api_client.post("/objects", json=_object_payload("Broken personal"))

    assert response.status_code == 502
    assert response.json()["detail"] == EMBEDDING_PROVIDER_UNAVAILABLE
    assert LEAK_MARKER not in response.text
    assert DEPLOY_KEY not in response.text
    assert _TRACKING_INIT_API_KEYS == []


def test_get_object_works_when_personal_credential_broken(
    graph_api_client, db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        created = graph_api_client.post("/objects", json=_object_payload("Readable object"))
    assert created.status_code == 201
    object_id = created.json()["id"]

    monkeypatch.setattr(settings, "secretary_credential_key", Fernet.generate_key().decode())

    response = graph_api_client.get(f"/objects/{object_id}")
    assert response.status_code == 200
    assert response.json()["id"] == object_id


def test_post_objects_fake_embedding_without_personal_or_deployment_key(
    graph_api_client, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "")

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        response = graph_api_client.post("/objects", json=_object_payload("Fake embed"))

    assert response.status_code == 201
    assert _TRACKING_INIT_API_KEYS == []


def test_post_objects_ignores_invalid_assistant_openai_deployment_config(
    graph_api_client, db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    monkeypatch.setattr(settings, "openai_assistant_reasoning_effort", "not-valid-effort")
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        response = graph_api_client.post("/objects", json=_object_payload("Narrow resolver"))

    assert response.status_code == 201
    assert _TRACKING_INIT_API_KEYS == [USER_A_KEY]


def test_patch_object_uses_authenticated_user_credential(
    graph_api_client, db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        created = graph_api_client.post("/objects", json=_object_payload("Patch target"))
    assert created.status_code == 201
    object_id = created.json()["id"]
    _TRACKING_INIT_API_KEYS.clear()
    _TRACKING_INSTANCES.clear()

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        response = graph_api_client.patch(
            f"/objects/{object_id}",
            json={"title": "Patched searchable title"},
        )

    assert response.status_code == 200
    assert _TRACKING_INIT_API_KEYS == [USER_A_KEY]


def test_get_user_embedding_service_uses_resolve_openai_api_key(
    db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings
    from app.core.current_user import CurrentUserContext

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)
    current_user = CurrentUserContext(user_id=BOOTSTRAP_USER_ID)

    with patch(
        "app.services.effective_user_settings_service.EffectiveUserSettingsService.get_effective_settings"
    ) as get_effective_mock, patch(
        "app.llm.embedding_service.OpenAIEmbeddingService",
        _TrackingEmbeddingService,
    ):
        service = get_user_embedding_service(session=db_session, current_user=current_user)
        get_effective_mock.assert_not_called()

    assert isinstance(service, _TrackingEmbeddingService)
    assert service.api_key == USER_A_KEY


def test_get_object_does_not_resolve_openai_credential(
    graph_api_client, db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)

    with patch("app.llm.embedding_service.OpenAIEmbeddingService", _TrackingEmbeddingService):
        created = graph_api_client.post("/objects", json=_object_payload("No resolve on read"))
    object_id = created.json()["id"]

    with patch(
        "app.services.effective_user_settings_service.EffectiveUserSettingsService.resolve_openai_api_key"
    ) as resolve_mock:
        response = graph_api_client.get(f"/objects/{object_id}")
        resolve_mock.assert_not_called()

    assert response.status_code == 200
