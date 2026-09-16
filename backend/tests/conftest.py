import os
import uuid
from uuid import UUID

os.environ.setdefault("MCP_ENABLED", "false")

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.token_service import AuthTokenService
from app.db.engine import engine
from app.db.models import User
from app.llm.embedding_service import FakeEmbeddingService
from app.main import app
from app.services.domain_tool_service import DomainToolService
from app.users.bootstrap import BOOTSTRAP_DISPLAY_NAME, BOOTSTRAP_USER_ID


def apply_embedding_service_overrides(service: FakeEmbeddingService) -> None:
    from app.api.deps import get_embedding_service, get_user_embedding_service

    app.dependency_overrides[get_embedding_service] = lambda: service
    app.dependency_overrides[get_user_embedding_service] = lambda: service


class AuthTestClient:
    def __init__(self, client: TestClient, headers: dict[str, str]) -> None:
        self._client = client
        self._headers = headers

    def _merge_headers(self, headers: dict[str, str] | None) -> dict[str, str]:
        merged = dict(self._headers)
        if headers:
            merged.update(headers)
        return merged

    def get(self, url: str, **kwargs):
        kwargs["headers"] = self._merge_headers(kwargs.get("headers"))
        return self._client.get(url, **kwargs)

    def post(self, url: str, **kwargs):
        kwargs["headers"] = self._merge_headers(kwargs.get("headers"))
        return self._client.post(url, **kwargs)

    def patch(self, url: str, **kwargs):
        kwargs["headers"] = self._merge_headers(kwargs.get("headers"))
        return self._client.patch(url, **kwargs)

    def delete(self, url: str, **kwargs):
        kwargs["headers"] = self._merge_headers(kwargs.get("headers"))
        return self._client.delete(url, **kwargs)

    def put(self, url: str, **kwargs):
        kwargs["headers"] = self._merge_headers(kwargs.get("headers"))
        return self._client.put(url, **kwargs)


@pytest.fixture(scope="session", autouse=True)
def _ensure_bootstrap_user_exists() -> None:
    if os.environ.get("SKIP_DB_FIXTURES") == "1":
        return
    with Session(engine) as session:
        if session.get(User, BOOTSTRAP_USER_ID) is None:
            session.add(
                User(id=BOOTSTRAP_USER_ID, display_name=BOOTSTRAP_DISPLAY_NAME)
            )
            session.commit()


@pytest.fixture
def bootstrap_user_id():
    return BOOTSTRAP_USER_ID


@pytest.fixture
def nornickel_user_id(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Nornickel corpus user"))
    db_session.flush()
    return user_id


@pytest.fixture
def db_session() -> Session:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def fake_embedding_service() -> FakeEmbeddingService:
    return FakeEmbeddingService()


@pytest.fixture
def bootstrap_bearer(db_session) -> str:
    service = AuthTokenService(db_session)
    plaintext, _ = service.issue_token(BOOTSTRAP_USER_ID, label="pytest-bootstrap")
    return plaintext


@pytest.fixture
def auth_headers(bootstrap_bearer: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {bootstrap_bearer}"}


@pytest.fixture
def issue_bearer(db_session):
    def _issue(user_id: UUID, label: str = "pytest-user") -> str:
        service = AuthTokenService(db_session)
        plaintext, _ = service.issue_token(user_id, label=label)
        return plaintext

    return _issue


@pytest.fixture
def auth_client(db_session, auth_headers) -> AuthTestClient:
    from app.api.deps import get_db

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as raw:
        yield AuthTestClient(raw, auth_headers)
    app.dependency_overrides.clear()


@pytest.fixture
def patched_mcp_tool_session(db_session, fake_embedding_service, monkeypatch):
    @contextmanager
    def test_tool_session():
        yield DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)

    monkeypatch.setattr("app.mcp.session.tool_session", test_tool_session)
    monkeypatch.setattr("app.mcp.gateway_runner.tool_session", test_tool_session)
