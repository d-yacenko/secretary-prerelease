"""PHASE 28A — user profile and per-user settings foundation."""

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.api.assistant as assistant_api_module
from app.api.deps import get_db, get_embedding_service
from app.core.config import normalize_allowed_assistant_models, settings
from app.db.models import User, UserOpenAICredential, UserSettings
from app.main import app
from app.services.assistant_service import (
    AssistantConfigurationError,
    create_assistant_provider_from_effective,
)
from app.services.effective_user_settings_service import (
    EffectiveUserSettings,
    EffectiveUserSettingsService,
)
from app.services.user_openai_credential_errors import UserOpenAICredentialConfigurationError
from app.services.user_openai_credential_store import UserOpenAICredentialStore
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import apply_embedding_service_overrides, AuthTestClient


def _credential_key() -> str:
    return Fernet.generate_key().decode("utf-8")


@pytest.fixture
def credential_key(monkeypatch) -> str:
    key = _credential_key()
    monkeypatch.setattr(settings, "secretary_credential_key", key)
    return key


@pytest.fixture
def profile_client(db_session, auth_headers, credential_key):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as raw:
        yield AuthTestClient(raw, auth_headers)
    app.dependency_overrides.clear()


@pytest.fixture
def second_user(db_session) -> tuple[UUID, dict[str, str]]:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Second user"))
    db_session.flush()
    from app.auth.token_service import AuthTokenService

    service = AuthTokenService(db_session)
    token, _ = service.issue_token(user_id, label="pytest-second")
    headers = {"Authorization": f"Bearer {token}"}
    return user_id, headers


def test_user_without_settings_gets_deployment_defaults(profile_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_assistant_model", "gpt-5.6-luna")
    monkeypatch.setattr(settings, "openai_assistant_reasoning_effort", "low")
    monkeypatch.setattr(settings, "openai_assistant_verbosity", "medium")
    monkeypatch.setattr(settings, "secretary_timezone", "Europe/Moscow")
    response = profile_client.get("/me/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["timezone"] == "Europe/Moscow"
    assert body["assistant_model"] == "gpt-5.6-luna"
    assert body["assistant_reasoning_effort"] == "low"
    assert body["assistant_verbosity"] == "medium"
    assert body["openai_key_configured"] is False
    assert "gpt-5.6-luna" in body["allowed_assistant_models"]


def test_settings_row_one_per_user(profile_client, db_session) -> None:
    profile_client.patch("/me/settings", json={"timezone": "Europe/Amsterdam"})
    rows = db_session.scalars(select(UserSettings)).all()
    bootstrap_rows = [row for row in rows if row.user_id == BOOTSTRAP_USER_ID]
    assert len(bootstrap_rows) == 1


def test_patch_settings_updates_current_user_only(
    profile_client, db_session, second_user, credential_key
) -> None:
    user_b_id, user_b_headers = second_user
    profile_client.patch("/me/settings", json={"timezone": "Asia/Yekaterinburg"})
    response_b = profile_client.get("/me/settings", headers=user_b_headers)
    assert response_b.status_code == 200
    assert response_b.json()["timezone"] == settings.secretary_timezone
    row_a = db_session.get(UserSettings, BOOTSTRAP_USER_ID)
    row_b = db_session.get(UserSettings, user_b_id)
    assert row_a is not None
    assert row_a.timezone == "Asia/Yekaterinburg"
    assert row_b is None


def test_patch_me_updates_display_name(profile_client) -> None:
    response = profile_client.patch("/me", json={"display_name": "Новое имя"})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Новое имя"
    me = profile_client.get("/me")
    assert me.json()["display_name"] == "Новое имя"


def test_patch_me_cannot_modify_other_user(profile_client, second_user) -> None:
    _, user_b_headers = second_user
    profile_client.patch("/me", json={"display_name": "User A name"})
    response = profile_client.get("/me", headers=user_b_headers)
    assert response.json()["display_name"] == "Second user"


def test_valid_timezone_accepted(profile_client) -> None:
    response = profile_client.patch("/me/settings", json={"timezone": "Europe/Amsterdam"})
    assert response.status_code == 200
    assert response.json()["timezone"] == "Europe/Amsterdam"


def test_invalid_timezone_rejected(profile_client) -> None:
    response = profile_client.patch("/me/settings", json={"timezone": "Not/AZone"})
    assert response.status_code == 422


def test_assistant_model_outside_allowlist_rejected(profile_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_assistant_model", "gpt-5.6-luna")
    monkeypatch.setattr(settings, "openai_allowed_assistant_models", "gpt-5.6-luna")
    response = profile_client.patch(
        "/me/settings",
        json={"assistant_model": "gpt-5.6-terra"},
    )
    assert response.status_code == 422


def test_reasoning_validation(profile_client) -> None:
    bad = profile_client.patch("/me/settings", json={"assistant_reasoning_effort": "turbo"})
    assert bad.status_code == 422
    good = profile_client.patch("/me/settings", json={"assistant_reasoning_effort": "high"})
    assert good.status_code == 200
    assert good.json()["assistant_reasoning_effort"] == "high"


def test_verbosity_validation(profile_client) -> None:
    bad = profile_client.patch("/me/settings", json={"assistant_verbosity": "verbose"})
    assert bad.status_code == 422
    good = profile_client.patch("/me/settings", json={"assistant_verbosity": "medium"})
    assert good.status_code == 200
    assert good.json()["assistant_verbosity"] == "medium"


def test_openai_key_stored_encrypted(profile_client, db_session) -> None:
    plaintext = "sk-user-test-key-28a"
    response = profile_client.put("/me/credentials/openai", json={"api_key": plaintext})
    assert response.status_code == 200
    row = db_session.get(UserOpenAICredential, BOOTSTRAP_USER_ID)
    assert row is not None
    assert row.api_key_encrypted != plaintext
    assert "sk-user" not in row.api_key_encrypted


def test_get_settings_never_returns_plaintext_key(profile_client) -> None:
    profile_client.put("/me/credentials/openai", json={"api_key": "sk-secret-user-key"})
    response = profile_client.get("/me/settings")
    body = response.json()
    assert "api_key" not in body
    assert "sk-secret" not in str(body)


def test_put_key_returns_configured_only(profile_client) -> None:
    response = profile_client.put("/me/credentials/openai", json={"api_key": "sk-test"})
    assert response.status_code == 200
    assert response.json() == {"configured": True}


def test_replacing_openai_key_works(profile_client, db_session, credential_key) -> None:
    profile_client.put("/me/credentials/openai", json={"api_key": "sk-first"})
    profile_client.put("/me/credentials/openai", json={"api_key": "sk-second"})
    store = EffectiveUserSettingsService.build(db_session)
    effective = store.get_effective_settings(BOOTSTRAP_USER_ID)
    assert effective.openai_api_key == "sk-second"


def test_deleting_openai_key_works(profile_client, db_session) -> None:
    profile_client.put("/me/credentials/openai", json={"api_key": "sk-delete-me"})
    response = profile_client.delete("/me/credentials/openai")
    assert response.status_code == 200
    assert response.json() == {"configured": False}
    assert db_session.get(UserOpenAICredential, BOOTSTRAP_USER_ID) is None
    settings_resp = profile_client.get("/me/settings")
    assert settings_resp.json()["openai_key_configured"] is False


def test_user_key_overrides_deployment_fallback(
    profile_client, db_session, monkeypatch, credential_key
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "sk-deployment")
    profile_client.put("/me/credentials/openai", json={"api_key": "sk-user"})
    service = EffectiveUserSettingsService.build(db_session)
    effective = service.get_effective_settings(BOOTSTRAP_USER_ID)
    assert effective.openai_api_key == "sk-user"


def test_no_user_key_falls_back_to_deployment(
    profile_client, db_session, monkeypatch, credential_key
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "sk-deployment-only")
    service = EffectiveUserSettingsService.build(db_session)
    effective = service.get_effective_settings(BOOTSTRAP_USER_ID)
    assert effective.openai_api_key == "sk-deployment-only"


def test_user_a_credential_not_used_for_user_b(
    profile_client, db_session, second_user, monkeypatch, credential_key
) -> None:
    user_b_id, _ = second_user
    monkeypatch.setattr(settings, "openai_api_key", "sk-deployment")
    profile_client.put("/me/credentials/openai", json={"api_key": "sk-user-a"})
    service = EffectiveUserSettingsService.build(db_session)
    effective_b = service.get_effective_settings(user_b_id)
    assert effective_b.openai_api_key == "sk-deployment"
    assert effective_b.openai_key_configured is False


def test_create_assistant_provider_from_effective_uses_user_settings(
    db_session, monkeypatch, credential_key
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "sk-deployment")
    service = EffectiveUserSettingsService.build(db_session)
    service.update_settings(
        BOOTSTRAP_USER_ID,
        assistant_reasoning_effort="medium",
        assistant_verbosity="high",
    )
    service._credential_store.upsert(BOOTSTRAP_USER_ID, "sk-user-assistant")
    effective = service.get_effective_settings(BOOTSTRAP_USER_ID)
    provider = create_assistant_provider_from_effective(effective)
    assert provider._model == effective.assistant_model
    assert provider._reasoning_effort == "medium"
    assert provider._verbosity == "high"


def test_create_assistant_provider_from_effective_without_key_raises(
    db_session, monkeypatch, credential_key
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "")
    service = EffectiveUserSettingsService.build(db_session)
    effective = service.get_effective_settings(BOOTSTRAP_USER_ID)

    with pytest.raises(AssistantConfigurationError):
        create_assistant_provider_from_effective(effective)


def test_normalize_allowed_assistant_models_dedupes_and_includes_default() -> None:
    models = normalize_allowed_assistant_models("gpt-b, gpt-a, gpt-b", "gpt-default")
    assert models == ["gpt-default", "gpt-b", "gpt-a"]


def test_effective_model_falls_back_when_deployment_policy_narrows(
    profile_client, db_session, monkeypatch, credential_key
) -> None:
    monkeypatch.setattr(settings, "openai_assistant_model", "gpt-a")
    monkeypatch.setattr(settings, "openai_allowed_assistant_models", "gpt-a,gpt-b")
    profile_client.patch("/me/settings", json={"assistant_model": "gpt-b"})

    monkeypatch.setattr(settings, "openai_allowed_assistant_models", "gpt-a")
    response = profile_client.get("/me/settings")
    body = response.json()
    assert body["assistant_model"] == "gpt-a"
    assert body["allowed_assistant_models"].count("gpt-a") == 1
    row = db_session.get(UserSettings, BOOTSTRAP_USER_ID)
    assert row is not None
    assert row.assistant_model == "gpt-b"


def test_get_settings_model_always_in_allowlist_once(profile_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_assistant_model", "gpt-5.6-luna")
    monkeypatch.setattr(
        settings,
        "openai_allowed_assistant_models",
        "gpt-5.6-luna,gpt-5.6-terra,gpt-5.6-luna",
    )
    body = profile_client.get("/me/settings").json()
    assert body["assistant_model"] in body["allowed_assistant_models"]
    assert body["allowed_assistant_models"].count(body["assistant_model"]) == 1
    assert body["allowed_assistant_models"] == ["gpt-5.6-luna", "gpt-5.6-terra"]


def test_effective_settings_repr_hides_api_key(
    db_session, monkeypatch, credential_key
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "sk-deployment")
    service = EffectiveUserSettingsService.build(db_session)
    service._credential_store.upsert(BOOTSTRAP_USER_ID, "sk-repr-secret")
    effective = service.get_effective_settings(BOOTSTRAP_USER_ID)
    rendered = repr(effective)
    assert "sk-repr-secret" not in rendered
    assert "sk-deployment" not in rendered


def test_stored_credential_decrypt_failure_does_not_fallback_to_deployment(
    profile_client, db_session, monkeypatch, credential_key
) -> None:
    profile_client.put("/me/credentials/openai", json={"api_key": "sk-user-only"})
    monkeypatch.setattr(settings, "secretary_credential_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "openai_api_key", "sk-deployment")

    service = EffectiveUserSettingsService.build(db_session)
    with pytest.raises(UserOpenAICredentialConfigurationError):
        service.get_effective_settings(BOOTSTRAP_USER_ID)

    view = service.get_settings_view(BOOTSTRAP_USER_ID)
    assert view.openai_key_configured is True
    assert view.openai_api_key is None


def test_put_openai_credential_without_encryption_returns_503(
    profile_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", "")
    response = profile_client.put("/me/credentials/openai", json={"api_key": "sk-test"})
    assert response.status_code == 503


def test_get_settings_with_invalid_non_empty_master_key_returns_presence(
    profile_client, monkeypatch, credential_key
) -> None:
    profile_client.put("/me/credentials/openai", json={"api_key": "sk-stored-key"})
    monkeypatch.setattr(settings, "secretary_credential_key", "not-a-valid-fernet-key")
    response = profile_client.get("/me/settings")
    assert response.status_code == 200
    assert response.json()["openai_key_configured"] is True


def test_delete_credential_with_invalid_non_empty_master_key(
    profile_client, db_session, monkeypatch, credential_key
) -> None:
    profile_client.put("/me/credentials/openai", json={"api_key": "sk-stored-key"})
    monkeypatch.setattr(settings, "secretary_credential_key", "not-a-valid-fernet-key")
    response = profile_client.delete("/me/credentials/openai")
    assert response.status_code == 200
    assert response.json() == {"configured": False}
    assert db_session.get(UserOpenAICredential, BOOTSTRAP_USER_ID) is None


def test_put_with_invalid_non_empty_master_key_returns_503(profile_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", "not-a-valid-fernet-key")
    response = profile_client.put("/me/credentials/openai", json={"api_key": "sk-test"})
    assert response.status_code == 503
    assert "Fernet" not in response.text


def test_assistant_with_invalid_master_key_and_stored_credential_returns_502(
    db_session,
    fake_embedding_service,
    auth_headers,
    monkeypatch,
    credential_key,
) -> None:
    store = UserOpenAICredentialStore.build_from_settings(db_session)
    store.upsert(BOOTSTRAP_USER_ID, "sk-user-invalid-master")
    db_session.flush()
    monkeypatch.setattr(settings, "openai_api_key", "sk-deployment-fallback")
    monkeypatch.setattr(settings, "secretary_credential_key", "not-a-valid-fernet-key")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        client = AuthTestClient(test_client, auth_headers)
        response = client.post("/assistant/message", json={"message": "hello"})
    app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "assistant_configuration"


def test_put_oversized_openai_key_returns_422_without_echoing_key(profile_client) -> None:
    oversized = "x" * 300
    response = profile_client.put("/me/credentials/openai", json={"api_key": oversized})
    assert response.status_code == 422
    assert oversized not in response.text


def test_action_plan_resume_uses_user_openai_key_when_deployment_empty(
    db_session,
    fake_embedding_service,
    monkeypatch,
    credential_key,
) -> None:
    from app.assistant.action_plan_constants import PENDING_ACTION_PLAN_STATUS_EXECUTED
    from app.db.models import PendingActionPlan, User
    from app.services.assistant_service import create_fake_assistant_provider

    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="resume user key"))
    db_session.flush()

    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "openai_assistant_model", "gpt-5.6-luna")

    from app.auth.token_service import AuthTokenService

    token_service = AuthTokenService(db_session)
    token, _ = token_service.issue_token(user_id, label="pytest-resume-key")
    headers = {"Authorization": f"Bearer {token}"}

    store = UserOpenAICredentialStore.build_from_settings(db_session)
    store.upsert(user_id, "sk-user-resume-only")
    db_session.flush()

    plan = PendingActionPlan(
        user_id=user_id,
        status=PENDING_ACTION_PLAN_STATUS_EXECUTED,
        actions=[],
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        result={"tool_results": []},
    )
    db_session.add(plan)
    db_session.flush()

    captured: dict[str, str] = {}

    def capture_create(effective: EffectiveUserSettings):
        captured["api_key"] = effective.openai_api_key or ""
        return create_fake_assistant_provider()

    monkeypatch.setattr(
        assistant_api_module,
        "create_assistant_provider_from_effective",
        capture_create,
    )

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        client = AuthTestClient(test_client, headers)
        response = client.post(f"/assistant/action-plans/{plan.id}/resume")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured["api_key"] == "sk-user-resume-only"


def test_action_plan_resume_user_a_key_not_used_for_user_b(
    db_session,
    fake_embedding_service,
    monkeypatch,
    credential_key,
) -> None:
    from app.assistant.action_plan_constants import PENDING_ACTION_PLAN_STATUS_EXECUTED
    from app.db.models import PendingActionPlan, User

    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    db_session.add_all(
        [
            User(id=user_a, display_name="resume A"),
            User(id=user_b, display_name="resume B"),
        ]
    )
    db_session.flush()

    monkeypatch.setattr(settings, "openai_api_key", "")
    store = UserOpenAICredentialStore.build_from_settings(db_session)
    store.upsert(user_a, "sk-user-a-resume")
    db_session.flush()

    plan = PendingActionPlan(
        user_id=user_b,
        status=PENDING_ACTION_PLAN_STATUS_EXECUTED,
        actions=[],
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        result={"tool_results": []},
    )
    db_session.add(plan)
    db_session.flush()

    from app.auth.token_service import AuthTokenService

    token_service = AuthTokenService(db_session)
    token_b, _ = token_service.issue_token(user_b, label="pytest-resume-b")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        client = AuthTestClient(test_client, headers_b)
        response = client.post(f"/assistant/action-plans/{plan.id}/resume")
    app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "assistant_configuration"
