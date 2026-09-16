"""PHASE 28B-B — per-user transcription credential."""

import io
import logging
import uuid
from unittest.mock import patch
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.assistant.transcription_constants import (
    TRANSCRIPTION_PROVIDER_FAILED,
    TRANSCRIPTION_PROVIDER_FAILED_MESSAGE,
    TRANSCRIPTION_PROVIDER_NOT_CONFIGURED,
    TRANSCRIPTION_PROVIDER_NOT_CONFIGURED_MESSAGE,
)
from app.api.assistant import get_transcription_provider
from app.api.deps import get_db, get_embedding_service
from app.db.engine import engine
from app.db.models import User, UserOpenAICredential
from app.main import app
from app.services.effective_user_settings_service import EffectiveUserSettingsService
from app.services.user_openai_credential_store import UserOpenAICredentialStore
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import apply_embedding_service_overrides, AuthTestClient

USER_A_KEY = "sk-user-a-28b-transcription-isolation"
USER_B_KEY = "sk-user-b-28b-transcription-isolation"
DEPLOY_KEY = "sk-deployment-28b-transcription-fallback"
LEAK_MARKER = "sk-leak-marker-28b-transcription-secret"


def _credential_key() -> str:
    return Fernet.generate_key().decode("utf-8")


@pytest.fixture
def credential_key(monkeypatch) -> str:
    key = _credential_key()
    from app.core.config import settings

    monkeypatch.setattr(settings, "secretary_credential_key", key)
    return key


@pytest.fixture
def transcribe_api_client(db_session, fake_embedding_service, auth_headers):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


@pytest.fixture
def second_user(db_session) -> tuple[UUID, dict[str, str]]:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Transcribe user B"))
    db_session.flush()
    from app.auth.token_service import AuthTokenService

    service = AuthTokenService(db_session)
    token, _ = service.issue_token(user_id, label="pytest-transcribe-b")
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


def _audio_file(content: bytes = b"audio-bytes") -> dict:
    return {
        "audio": ("clip.wav", io.BytesIO(content), "audio/wav"),
    }


_TRACKING_INIT_API_KEYS: list[str] = []
_TRACKING_INSTANCES: list = []


class _TrackingTranscriptionProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        _TRACKING_INIT_API_KEYS.append(api_key)
        _TRACKING_INSTANCES.append(self)

    def transcribe(self, audio_bytes: bytes, filename: str, content_type: str | None) -> str:
        return "transcribed text"


@pytest.fixture(autouse=True)
def _reset_tracking() -> None:
    _TRACKING_INIT_API_KEYS.clear()
    _TRACKING_INSTANCES.clear()
    yield
    _TRACKING_INIT_API_KEYS.clear()
    _TRACKING_INSTANCES.clear()


def test_transcribe_user_a_uses_personal_key(
    transcribe_api_client, db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)

    with patch(
        "app.services.transcription_service.OpenAITranscriptionProvider",
        _TrackingTranscriptionProvider,
    ):
        response = transcribe_api_client.post("/assistant/transcribe", files=_audio_file())

    assert response.status_code == 200
    assert _TRACKING_INIT_API_KEYS == [USER_A_KEY]


def test_transcribe_user_b_uses_personal_key(
    transcribe_api_client,
    db_session,
    monkeypatch,
    credential_key,
    second_user,
) -> None:
    from app.core.config import settings

    user_b_id, user_b_headers = second_user
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, user_b_id, USER_B_KEY, credential_key)

    with patch(
        "app.services.transcription_service.OpenAITranscriptionProvider",
        _TrackingTranscriptionProvider,
    ):
        response = transcribe_api_client.post(
            "/assistant/transcribe",
            files=_audio_file(),
            headers=user_b_headers,
        )

    assert response.status_code == 200
    assert _TRACKING_INIT_API_KEYS == [USER_B_KEY]


def test_transcribe_user_a_and_b_use_separate_providers(
    transcribe_api_client,
    db_session,
    monkeypatch,
    credential_key,
    second_user,
) -> None:
    from app.core.config import settings

    user_b_id, user_b_headers = second_user
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)
    _upsert_user_key(db_session, user_b_id, USER_B_KEY, credential_key)

    with patch(
        "app.services.transcription_service.OpenAITranscriptionProvider",
        _TrackingTranscriptionProvider,
    ):
        response_a = transcribe_api_client.post("/assistant/transcribe", files=_audio_file())
        response_b = transcribe_api_client.post(
            "/assistant/transcribe",
            files=_audio_file(b"bytes-b"),
            headers=user_b_headers,
        )

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert len(_TRACKING_INSTANCES) == 2
    assert _TRACKING_INIT_API_KEYS == [USER_A_KEY, USER_B_KEY]


def test_transcribe_deployment_fallback_without_personal_credential(
    transcribe_api_client, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)

    with patch(
        "app.services.transcription_service.OpenAITranscriptionProvider",
        _TrackingTranscriptionProvider,
    ):
        response = transcribe_api_client.post("/assistant/transcribe", files=_audio_file())

    assert response.status_code == 200
    assert _TRACKING_INIT_API_KEYS == [DEPLOY_KEY]


def test_transcribe_broken_personal_credential_no_deployment_fallback(
    transcribe_api_client, db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, LEAK_MARKER, credential_key)
    monkeypatch.setattr(settings, "secretary_credential_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)

    response = transcribe_api_client.post("/assistant/transcribe", files=_audio_file())

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": TRANSCRIPTION_PROVIDER_NOT_CONFIGURED,
        "message": TRANSCRIPTION_PROVIDER_NOT_CONFIGURED_MESSAGE,
    }
    assert LEAK_MARKER not in response.text
    assert DEPLOY_KEY not in response.text


def test_transcribe_no_personal_or_deployment_key_returns_502(
    transcribe_api_client, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "")

    response = transcribe_api_client.post("/assistant/transcribe", files=_audio_file())

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": TRANSCRIPTION_PROVIDER_NOT_CONFIGURED,
        "message": TRANSCRIPTION_PROVIDER_NOT_CONFIGURED_MESSAGE,
    }


def test_transcribe_ignores_invalid_assistant_openai_deployment_config(
    transcribe_api_client, db_session, monkeypatch, credential_key
) -> None:
    from app.core.assistant_openai_config import AssistantOpenAIConfigError
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    monkeypatch.setattr(settings, "openai_assistant_reasoning_effort", "not-valid-effort")

    with patch(
        "app.services.transcription_service.OpenAITranscriptionProvider",
        _TrackingTranscriptionProvider,
    ):
        response = transcribe_api_client.post("/assistant/transcribe", files=_audio_file())

    assert response.status_code == 200
    assert _TRACKING_INIT_API_KEYS == [DEPLOY_KEY]
    with pytest.raises(AssistantOpenAIConfigError):
        EffectiveUserSettingsService.build(db_session).get_effective_settings(BOOTSTRAP_USER_ID)


def test_transcribe_blank_model_returns_502(
    transcribe_api_client, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    monkeypatch.setattr(settings, "openai_transcription_model", "   ")

    response = transcribe_api_client.post("/assistant/transcribe", files=_audio_file())

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": TRANSCRIPTION_PROVIDER_NOT_CONFIGURED,
        "message": TRANSCRIPTION_PROVIDER_NOT_CONFIGURED_MESSAGE,
    }


def test_transcribe_credential_failure_not_secretary_401(
    transcribe_api_client, db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)
    monkeypatch.setattr(settings, "secretary_credential_key", Fernet.generate_key().decode())

    response = transcribe_api_client.post("/assistant/transcribe", files=_audio_file())

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": TRANSCRIPTION_PROVIDER_NOT_CONFIGURED,
        "message": TRANSCRIPTION_PROVIDER_NOT_CONFIGURED_MESSAGE,
    }


def test_transcribe_secret_not_in_telemetry_log(
    transcribe_api_client, monkeypatch, credential_key, caplog
) -> None:
    from app.core.config import settings
    from app.llm.openai_transcription_provider import TranscriptionProviderError

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)

    class _FailingProvider(_TrackingTranscriptionProvider):
        def transcribe(self, audio_bytes: bytes, filename: str, content_type: str | None) -> str:
            raise TranscriptionProviderError(LEAK_MARKER)

    with patch(
        "app.services.transcription_service.OpenAITranscriptionProvider",
        _FailingProvider,
    ), caplog.at_level(logging.INFO, logger="app.assistant.transcription_telemetry"):
        response = transcribe_api_client.post("/assistant/transcribe", files=_audio_file())

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": TRANSCRIPTION_PROVIDER_FAILED,
        "message": TRANSCRIPTION_PROVIDER_FAILED_MESSAGE,
    }
    assert LEAK_MARKER not in response.text
    telemetry_logs = [r.message for r in caplog.records if "assistant_transcription" in r.message]
    assert telemetry_logs
    assert LEAK_MARKER not in telemetry_logs[0]


def test_get_transcription_provider_uses_resolve_openai_api_key(
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
        "app.services.transcription_service.OpenAITranscriptionProvider",
        _TrackingTranscriptionProvider,
    ):
        guarded = get_transcription_provider(session=db_session, current_user=current_user)
        get_effective_mock.assert_not_called()

    provider = guarded.inner
    assert isinstance(provider, _TrackingTranscriptionProvider)
    assert provider.api_key == USER_A_KEY
