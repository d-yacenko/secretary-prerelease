"""One per-user generative model for text and reasoning workloads."""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.assistant_openai_config import (
    AssistantOpenAIConfigError,
    validated_assistant_openai_settings,
)
from app.core.config import (
    DEFAULT_ALLOWED_GENERATIVE_MODELS,
    DEFAULT_GENERATIVE_MODEL,
    Settings,
    normalize_allowed_assistant_models,
    settings,
)
from app.llm.auto_label_classifier import create_auto_label_classifier_from_effective
from app.llm.correlation_judge import create_correlation_judge_from_effective
from app.llm.openai_summarizer import (
    create_openai_conversation_stack_summarizer_from_effective,
    create_openai_summarizer_from_effective,
)
from app.llm.temporal_match_judge import create_temporal_match_judge_from_effective
from app.llm.temporal_signal_extractor import create_temporal_signal_extractor_from_effective
from app.main import app
from app.services.assistant_service import create_assistant_provider_from_effective
from app.services.effective_user_settings_service import (
    EffectiveUserSettings,
    EffectiveUserSettingsService,
)
from app.services.proactive_review_service import create_proactive_provider
from app.services.secretary_service import create_secretary_provider_from_effective
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
CANONICAL_MODELS = list(DEFAULT_ALLOWED_GENERATIVE_MODELS)


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


def _pin_canonical_defaults(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_assistant_model", DEFAULT_GENERATIVE_MODEL)
    monkeypatch.setattr(
        settings,
        "openai_allowed_assistant_models",
        ",".join(CANONICAL_MODELS),
    )
    monkeypatch.setattr(settings, "openai_assistant_reasoning_effort", "low")
    monkeypatch.setattr(settings, "openai_assistant_verbosity", "low")


def _effective(model: str) -> EffectiveUserSettings:
    return EffectiveUserSettings(
        timezone="Europe/Amsterdam",
        assistant_model=model,
        assistant_reasoning_effort="medium",
        assistant_verbosity="low",
        assistant_max_rounds=6,
        assistant_max_rounds_override=None,
        openai_key_configured=True,
        allowed_assistant_models=CANONICAL_MODELS,
        openai_api_key="sk-user",
    )


def test_default_generative_model_and_allowlist() -> None:
    assert Settings.model_fields["openai_assistant_model"].default == "gpt-6-luna"
    raw_allowlist = Settings.model_fields["openai_allowed_assistant_models"].default
    assert normalize_allowed_assistant_models(raw_allowlist, "gpt-6-luna") == CANONICAL_MODELS
    assert "openai_model" not in Settings.model_fields


def test_explicit_deployment_default_keeps_insertion_semantics() -> None:
    models = normalize_allowed_assistant_models(",".join(CANONICAL_MODELS), "gpt-5.6-terra")
    assert models == CANONICAL_MODELS
    inserted = normalize_allowed_assistant_models(",".join(CANONICAL_MODELS), "gpt-custom")
    assert inserted[0] == "gpt-custom"
    assert inserted[1:] == CANONICAL_MODELS


def test_patch_accepts_canonical_models_and_rejects_unknown(profile_client, monkeypatch) -> None:
    _pin_canonical_defaults(monkeypatch)
    for model in CANONICAL_MODELS:
        response = profile_client.patch("/me/settings", json={"assistant_model": model})
        assert response.status_code == 200
        assert response.json()["assistant_model"] == model
    for rejected in ("gpt-6-terra", "gpt-not-a-model"):
        response = profile_client.patch("/me/settings", json={"assistant_model": rejected})
        assert response.status_code == 422


def test_stored_gpt56_overrides_remain_effective(profile_client, db_session, monkeypatch) -> None:
    _pin_canonical_defaults(monkeypatch)
    service = EffectiveUserSettingsService.build(db_session)
    row = service.get_or_create_settings_row(BOOTSTRAP_USER_ID)
    for stored in ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"):
        row.assistant_model = stored
        db_session.flush()
        body = profile_client.get("/me/settings").json()
        assert body["assistant_model"] == stored


def test_missing_override_uses_gpt6_luna(profile_client, monkeypatch) -> None:
    _pin_canonical_defaults(monkeypatch)
    body = profile_client.get("/me/settings").json()
    assert body["assistant_model"] == "gpt-6-luna"


def test_generative_factories_use_effective_model(monkeypatch) -> None:
    _pin_canonical_defaults(monkeypatch)
    effective = _effective("gpt-6-sol")
    providers = [
        create_assistant_provider_from_effective(effective),
        create_proactive_provider(effective),
        create_openai_summarizer_from_effective(effective),
        create_openai_conversation_stack_summarizer_from_effective(effective),
        create_auto_label_classifier_from_effective(effective),
        create_correlation_judge_from_effective(effective),
        create_temporal_signal_extractor_from_effective(effective),
        create_temporal_match_judge_from_effective(effective),
        create_secretary_provider_from_effective(effective),
    ]
    assert [provider._model for provider in providers] == ["gpt-6-sol"] * len(providers)


def test_astra_none_rejected_other_efforts_accepted(profile_client, monkeypatch) -> None:
    _pin_canonical_defaults(monkeypatch)
    rejected = profile_client.patch(
        "/me/settings",
        json={"assistant_model": "gpt-6-astra", "assistant_reasoning_effort": "none"},
    )
    assert rejected.status_code == 422
    for effort in ("low", "medium", "high"):
        accepted = profile_client.patch(
            "/me/settings",
            json={"assistant_model": "gpt-6-astra", "assistant_reasoning_effort": effort},
        )
        assert accepted.status_code == 200
        assert accepted.json()["assistant_model"] == "gpt-6-astra"
        assert accepted.json()["assistant_reasoning_effort"] == effort

    profile_client.patch(
        "/me/settings",
        json={"assistant_model": "gpt-6-luna", "assistant_reasoning_effort": "none"},
    )
    blocked = profile_client.patch("/me/settings", json={"assistant_model": "gpt-6-astra"})
    assert blocked.status_code == 422
    body = profile_client.get("/me/settings").json()
    assert body["assistant_model"] == "gpt-6-luna"
    assert body["assistant_reasoning_effort"] == "none"


def test_deployment_astra_none_rejected() -> None:
    config = Settings(
        openai_assistant_model="gpt-6-astra",
        openai_assistant_reasoning_effort="none",
        openai_allowed_assistant_models=",".join(CANONICAL_MODELS),
    )
    with pytest.raises(AssistantOpenAIConfigError, match="gpt-6-astra"):
        validated_assistant_openai_settings(config)


def test_runtime_sources_do_not_use_legacy_openai_model() -> None:
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "settings.openai_model" not in text
        assert "OPENAI_MODEL" not in text
    compose = (ROOT / "infra" / "compose.yaml").read_text(encoding="utf-8")
    assert "OPENAI_MODEL" not in compose
    assignments = [line.strip() for line in compose.splitlines()]
    for key in (
        "OPENAI_ASSISTANT_MODEL:",
        "OPENAI_ALLOWED_ASSISTANT_MODELS:",
        "OPENAI_ASSISTANT_REASONING_EFFORT:",
        "OPENAI_ASSISTANT_VERBOSITY:",
        "OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS:",
    ):
        assert sum(line.startswith(key) for line in assignments) == 2
    assert "OPENAI_EMBEDDING_MODEL:" in compose
    assert "OPENAI_TTS_MODEL:" in compose
    assert "OPENAI_TTS_VOICE:" in compose
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in example.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not stripped.startswith("OPENAI_MODEL")
    defaults = Settings.model_fields
    assert defaults["openai_embedding_model"].default == "text-embedding-3-small"
    assert defaults["openai_transcription_model"].default == "gpt-4o-mini-transcribe"
    assert defaults["openai_tts_model"].default == "gpt-4o-mini-tts"
    assert defaults["openai_tts_voice"].default == "alloy"
