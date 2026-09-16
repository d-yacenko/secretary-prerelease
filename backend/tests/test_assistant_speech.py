"""Voice Assistant A — server-side TTS endpoint."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ai_audit.constants import EVENT_MODEL_ROUND, WORKLOAD_SPEECH
from app.api.assistant import get_speech_provider
from app.api.deps import get_db
from app.assistant.speech_constants import (
    MAX_SPEECH_INPUT_CHARS,
    SPEECH_AUDIO_CONTENT_TYPE,
    SPEECH_PROVIDER_UNAVAILABLE,
    SPEECH_TEXT_EMPTY,
    SPEECH_TEXT_TOO_LONG,
)
from app.db.models import (
    AITrace,
    AITraceEvent,
    Edge,
    Job,
    Object,
    PendingActionPlan,
    Representation,
    UserSettings,
)
from app.llm.assistant_provider_errors import OPENAI_DAILY_BUDGET_EXHAUSTED
from app.llm.fake_speech_provider import FakeSpeechProvider
from app.llm.openai_speech_provider import OpenAISpeechProvider, SpeechProviderError
from app.main import app
from app.services.openai_daily_budget import (
    OpenAIDailyBudgetExhaustedError,
    OpenAIDailyBudgetGuard,
)
from app.services.speech_service import create_fake_speech_provider
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides


@pytest.fixture
def fake_speech_provider() -> FakeSpeechProvider:
    return create_fake_speech_provider()


@pytest.fixture
def speech_client(
    db_session,
    fake_embedding_service,
    auth_headers,
    fake_speech_provider,
):
    def override_get_db():
        yield db_session

    def override_provider():
        return fake_speech_provider

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    app.dependency_overrides[get_speech_provider] = override_provider
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers), fake_speech_provider
    app.dependency_overrides.clear()


def test_speech_unauthenticated_returns_401(db_session, fake_embedding_service) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        response = test_client.post("/assistant/speech", json={"text": "Привет"})
    app.dependency_overrides.clear()
    assert response.status_code == 401


def test_speech_blank_text_returns_typed_422(speech_client) -> None:
    client, provider = speech_client

    response = client.post("/assistant/speech", json={"text": "   "})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "speech_text_empty"
    assert detail["message"] == SPEECH_TEXT_EMPTY
    assert provider.calls == []


def test_speech_over_limit_returns_typed_422(speech_client) -> None:
    client, provider = speech_client

    response = client.post(
        "/assistant/speech",
        json={"text": "а" * (MAX_SPEECH_INPUT_CHARS + 1)},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "speech_text_too_long"
    assert detail["message"] == SPEECH_TEXT_TOO_LONG
    assert provider.calls == []


def test_speech_fake_provider_returns_audio_and_content_type(speech_client) -> None:
    client, provider = speech_client

    response = client.post("/assistant/speech", json={"text": "Какая свежая почта?"})

    assert response.status_code == 200
    assert response.content == b"fake-mp3-bytes"
    assert response.headers["content-type"].startswith(SPEECH_AUDIO_CONTENT_TYPE)
    assert provider.calls == ["Какая свежая почта?"]


def test_speech_user_openai_credential_is_used(
    db_session,
    fake_embedding_service,
    auth_headers,
    monkeypatch,
) -> None:
    from cryptography.fernet import Fernet

    from app.core.config import settings
    from app.services.user_openai_credential_store import UserOpenAICredentialStore

    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(settings, "secretary_credential_key", key)
    monkeypatch.setattr(settings, "openai_api_key", "sk-deployment-speech")
    UserOpenAICredentialStore(db_session, key).upsert(BOOTSTRAP_USER_ID, "sk-user-speech")
    db_session.flush()

    captured: list[str] = []

    class TrackingProvider:
        def __init__(self, api_key: str, model: str, voice: str) -> None:
            captured.append(api_key)
            self.model = model
            self.voice = voice

        def synthesize(self, text: str):
            from app.llm.openai_speech_provider import SpeechCallResult

            return SpeechCallResult(audio_bytes=b"ok")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with (
        patch("app.services.speech_service.OpenAISpeechProvider", TrackingProvider),
        TestClient(app) as raw,
    ):
        client = AuthTestClient(raw, auth_headers)
        response = client.post("/assistant/speech", json={"text": "Привет"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured == ["sk-user-speech"]


def _set_bootstrap_limit(db_session, limit: int) -> None:
    row = db_session.get(UserSettings, BOOTSTRAP_USER_ID)
    if row is None:
        row = UserSettings(user_id=BOOTSTRAP_USER_ID)
        db_session.add(row)
        db_session.flush()
    row.openai_daily_token_limit = limit
    db_session.flush()


def _seed_bootstrap_usage(db_session, input_tokens: int) -> None:
    from datetime import UTC, datetime

    from app.ai_audit.constants import EVENT_MODEL_ROUND as ROUND

    trace = AITrace(
        user_id=BOOTSTRAP_USER_ID,
        workload="assistant_interactive",
        started_at=datetime.now(UTC),
        success=True,
    )
    db_session.add(trace)
    db_session.flush()
    db_session.add(
        AITraceEvent(
            trace_id=trace.id,
            user_id=BOOTSTRAP_USER_ID,
            sequence=1,
            event_type=ROUND,
            metadata_={"input_tokens": input_tokens, "output_tokens": 0},
        )
    )
    db_session.flush()


def test_speech_exhausted_budget_returns_typed_429_and_skips_provider(
    db_session,
    fake_embedding_service,
    auth_headers,
    fake_speech_provider,
) -> None:
    _set_bootstrap_limit(db_session, 10)
    _seed_bootstrap_usage(db_session, 10)

    def override_get_db():
        yield db_session

    def override_provider():
        return OpenAIDailyBudgetGuard.build(
            db_session, BOOTSTRAP_USER_ID
        ).guard_speech_provider(fake_speech_provider)

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    app.dependency_overrides[get_speech_provider] = override_provider
    with TestClient(app) as raw:
        client = AuthTestClient(raw, auth_headers)
        response = client.post("/assistant/speech", json={"text": "Привет"})
    app.dependency_overrides.clear()

    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["code"] == OPENAI_DAILY_BUDGET_EXHAUSTED
    assert fake_speech_provider.calls == []


def test_speech_budget_is_checked_before_provider_call(db_session, fake_speech_provider) -> None:
    _set_bootstrap_limit(db_session, 10)
    _seed_bootstrap_usage(db_session, 10)
    guarded = OpenAIDailyBudgetGuard.build(
        db_session, BOOTSTRAP_USER_ID
    ).guard_speech_provider(fake_speech_provider)
    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        guarded.synthesize("Привет")
    assert fake_speech_provider.calls == []


def test_speech_provider_error_returns_502(speech_client) -> None:
    client, provider = speech_client

    def failing_synthesize(_text: str):
        raise SpeechProviderError("speech call failed")

    provider.synthesize = failing_synthesize

    response = client.post("/assistant/speech", json={"text": "Привет"})

    assert response.status_code == 502
    assert response.json()["detail"] == SPEECH_PROVIDER_UNAVAILABLE


def test_speech_does_not_mutate_objects_or_action_plans(speech_client, db_session) -> None:
    client, _ = speech_client
    before = {
        "objects": db_session.scalar(select(func.count()).select_from(Object)),
        "edges": db_session.scalar(select(func.count()).select_from(Edge)),
        "jobs": db_session.scalar(select(func.count()).select_from(Job)),
        "plans": db_session.scalar(select(func.count()).select_from(PendingActionPlan)),
        "representations": db_session.scalar(select(func.count()).select_from(Representation)),
    }

    response = client.post("/assistant/speech", json={"text": "Какая свежая почта?"})

    assert response.status_code == 200
    assert db_session.scalar(select(func.count()).select_from(Object)) == before["objects"]
    assert db_session.scalar(select(func.count()).select_from(Edge)) == before["edges"]
    assert db_session.scalar(select(func.count()).select_from(Job)) == before["jobs"]
    assert db_session.scalar(select(func.count()).select_from(PendingActionPlan)) == before["plans"]
    assert (
        db_session.scalar(select(func.count()).select_from(Representation))
        == before["representations"]
    )


def test_speech_emits_ai_audit_workload(speech_client, db_session) -> None:
    client, _ = speech_client

    response = client.post("/assistant/speech", json={"text": "Привет"})
    assert response.status_code == 200

    db_session.expire_all()
    trace = db_session.scalar(
        select(AITrace)
        .where(
            AITrace.user_id == BOOTSTRAP_USER_ID,
            AITrace.workload == WORKLOAD_SPEECH,
        )
        .order_by(AITrace.started_at.desc())
    )
    assert trace is not None
    events = list(
        db_session.scalars(select(AITraceEvent).where(AITraceEvent.trace_id == trace.id))
    )
    assert any(event.event_type == EVENT_MODEL_ROUND for event in events)


def test_openai_speech_provider_passes_model_voice_and_text(monkeypatch) -> None:
    captured: dict = {}

    class FakeSpeechApi:
        def create(self, **kwargs):
            captured.update(kwargs)
            return MagicMock(content=b"mp3-bytes", usage=None)

    class FakeAudio:
        def __init__(self):
            self.speech = FakeSpeechApi()

    class FakeClient:
        def __init__(self, api_key):
            self.audio = FakeAudio()

    monkeypatch.setattr("openai.OpenAI", lambda api_key: FakeClient(api_key))

    provider = OpenAISpeechProvider(
        api_key="sk-test",
        model="gpt-4o-mini-tts",
        voice="configured-voice",
    )
    result = provider.synthesize("Подготовлено письмо.")

    assert result.audio_bytes == b"mp3-bytes"
    assert result.content_type == SPEECH_AUDIO_CONTENT_TYPE
    assert result.input_tokens is None
    assert result.output_tokens is None
    assert captured["model"] == "gpt-4o-mini-tts"
    assert captured["voice"] == "configured-voice"
    assert captured["input"] == "Подготовлено письмо."
    assert captured["response_format"] == "mp3"


def test_prepare_speech_text_strips_markdown_keeps_semantics() -> None:
    from app.assistant.speech_text import prepare_speech_text

    spoken = prepare_speech_text(
        "# Заголовок\n\n**Важно:** проверьте [почту](https://example.com).\n\n"
        "```\nне читать забор\n```\n"
    )
    assert "Заголовок" in spoken
    assert "Важно" in spoken
    assert "проверьте почту" in spoken
    assert "не читать забор" in spoken
    assert "**" not in spoken
    assert "https://example.com" not in spoken
    assert "```" not in spoken


def test_speech_missing_configuration_returns_502(
    db_session,
    fake_embedding_service,
    auth_headers,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.openai_api_key", "")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as raw:
        client = AuthTestClient(raw, auth_headers)
        response = client.post("/assistant/speech", json={"text": "Привет"})
    app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json()["detail"] == SPEECH_PROVIDER_UNAVAILABLE


def test_blank_speech_without_openai_credential_returns_typed_422_not_502(
    db_session,
    fake_embedding_service,
    auth_headers,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.openai_api_key", "")
    monkeypatch.setattr("app.core.config.settings.openai_tts_model", "")
    monkeypatch.setattr("app.core.config.settings.openai_tts_voice", "")
    constructed: list[str] = []

    def tracking_build(*_args, **_kwargs):
        constructed.append("built")
        raise AssertionError("speech provider must not be constructed for invalid text")

    monkeypatch.setattr(
        "app.api.assistant.build_budget_guarded_speech_provider",
        tracking_build,
    )
    monkeypatch.setattr(
        "app.api.assistant.create_speech_provider_for_api_key",
        tracking_build,
    )

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as raw:
        client = AuthTestClient(raw, auth_headers)
        response = client.post("/assistant/speech", json={"text": "   "})
    app.dependency_overrides.clear()

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "speech_text_empty"
    assert detail["message"] == SPEECH_TEXT_EMPTY
    assert constructed == []


def test_over_limit_speech_without_openai_credential_returns_typed_422_not_502(
    db_session,
    fake_embedding_service,
    auth_headers,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.openai_api_key", "")
    monkeypatch.setattr("app.core.config.settings.openai_tts_model", "")
    monkeypatch.setattr("app.core.config.settings.openai_tts_voice", "")
    constructed: list[str] = []

    def tracking_build(*_args, **_kwargs):
        constructed.append("built")
        raise AssertionError("speech provider must not be constructed for invalid text")

    monkeypatch.setattr(
        "app.api.assistant.build_budget_guarded_speech_provider",
        tracking_build,
    )
    monkeypatch.setattr(
        "app.api.assistant.create_speech_provider_for_api_key",
        tracking_build,
    )

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as raw:
        client = AuthTestClient(raw, auth_headers)
        response = client.post(
            "/assistant/speech",
            json={"text": "а" * (MAX_SPEECH_INPUT_CHARS + 1)},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "speech_text_too_long"
    assert detail["message"] == SPEECH_TEXT_TOO_LONG
    assert constructed == []
