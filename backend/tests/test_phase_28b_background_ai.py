"""PHASE 28B-A — per-user background AI runtime."""

import uuid
from unittest.mock import patch
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete

from app.api.schemas import ObjectCreate
from app.db.engine import engine
from app.db.models import Job, Object, User, UserOpenAICredential, UserSettings
from app.jobs.constants import (
    JOB_STATUS_PENDING,
    JOB_TYPE_EMBED_OBJECT,
    JOB_TYPE_SYNC_GOOGLE_GMAIL,
)
from app.jobs.handlers import HANDLERS, handle_embed_object, handle_summarize_resource
from app.jobs.worker import process_one_job
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.embedding_text import EMBEDDING_DIMENSION, embed_job_payload
from app.services.background_ai_errors import BackgroundAIConfigurationError
from app.services.effective_user_settings_service import EffectiveUserSettingsService
from app.services.graph_service import GraphService
from app.services.job_queue_service import (
    JobQueueService,
    is_job_error_retryable,
    sanitize_job_error,
)
from app.services.representation_service import RepresentationService
from app.services.user_openai_credential_errors import UserOpenAICredentialConfigurationError
from app.services.user_openai_credential_store import UserOpenAICredentialStore
from app.users.bootstrap import BOOTSTRAP_USER_ID

USER_A_KEY = "sk-user-a-28b-background-ai-isolation"
USER_B_KEY = "sk-user-b-28b-background-ai-isolation"
DEPLOY_KEY = "sk-deployment-28b-background-ai-fallback"
LEAK_MARKER = "sk-leak-marker-28b-secret-do-not-log"


def _credential_key() -> str:
    return Fernet.generate_key().decode("utf-8")


def _delete_user_credential(user_id: UUID) -> None:
    from sqlalchemy.orm import Session as OrmSession

    conn = engine.connect()
    trans = conn.begin()
    session = OrmSession(bind=conn)
    session.execute(delete(UserOpenAICredential).where(UserOpenAICredential.user_id == user_id))
    trans.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _clean_committed_bootstrap_openai_credential() -> None:
    _delete_user_credential(BOOTSTRAP_USER_ID)
    yield
    _delete_user_credential(BOOTSTRAP_USER_ID)


@pytest.fixture
def credential_key(monkeypatch) -> str:
    key = _credential_key()
    from app.core.config import settings

    monkeypatch.setattr(settings, "secretary_credential_key", key)
    return key


@pytest.fixture
def user_b(db_session) -> UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="User B"))
    db_session.flush()
    return user_id


def _upsert_user_key(db_session, user_id: UUID, api_key: str, credential_key: str) -> None:
    store = UserOpenAICredentialStore(db_session, credential_key)
    store.upsert(user_id, api_key)
    db_session.flush()


def _create_object(
    db_session,
    user_id: UUID,
    title: str = "Obj",
    metadata: dict | None = None,
) -> Object:
    graph = GraphService(db_session, user_id)
    return graph.create_object(
        ObjectCreate(kind="document", title=title, origin="user", metadata=metadata or {})
    )


def _enqueue_embed(db_session, object_id: UUID, user_id: UUID) -> Job:
    return JobQueueService(db_session).enqueue(
        JOB_TYPE_EMBED_OBJECT,
        {"object_id": str(object_id)},
        user_id,
    )


_TRACKING_INSTANCES: list["_TrackingEmbeddingService"] = []
_TRACKING_INIT_API_KEYS: list[str] = []


class _TrackingEmbeddingService:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self.embed_calls = 0
        _TRACKING_INIT_API_KEYS.append(api_key)
        _TRACKING_INSTANCES.append(self)

    def embed(self, text: str) -> list[float]:
        self.embed_calls += 1
        return [0.1] * EMBEDDING_DIMENSION


@pytest.fixture(autouse=True)
def _reset_tracking_embedding_service() -> None:
    _TRACKING_INSTANCES.clear()
    _TRACKING_INIT_API_KEYS.clear()
    yield
    _TRACKING_INSTANCES.clear()
    _TRACKING_INIT_API_KEYS.clear()


def test_resolve_openai_api_key_without_creating_settings_row(
    db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    service = EffectiveUserSettingsService.build(db_session)
    assert db_session.get(UserSettings, BOOTSTRAP_USER_ID) is None
    assert service.resolve_openai_api_key(BOOTSTRAP_USER_ID) == DEPLOY_KEY


def test_embed_job_uses_user_a_personal_key(
    db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)
    obj = _create_object(db_session, BOOTSTRAP_USER_ID, "User A doc")

    with patch(
        "app.llm.embedding_service.OpenAIEmbeddingService",
        _TrackingEmbeddingService,
    ), patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.ai_audit.context.SessionLocal", lambda: db_session
    ), patch(
        "app.services.representation_embedding_worker.SessionLocal", lambda: db_session
    ), patch.object(db_session, "close", lambda: None):
        handle_embed_object(db_session, None, embed_job_payload(obj), BOOTSTRAP_USER_ID)

    assert _TRACKING_INIT_API_KEYS == [USER_A_KEY]


def test_embed_job_uses_user_b_personal_key_not_user_a(
    db_session, monkeypatch, credential_key, user_b
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)
    _upsert_user_key(db_session, user_b, USER_B_KEY, credential_key)
    obj_a = _create_object(db_session, BOOTSTRAP_USER_ID, "A")
    obj_b = _create_object(db_session, user_b, "B")

    with patch(
        "app.llm.embedding_service.OpenAIEmbeddingService",
        _TrackingEmbeddingService,
    ), patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.ai_audit.context.SessionLocal", lambda: db_session
    ), patch(
        "app.services.representation_embedding_worker.SessionLocal", lambda: db_session
    ), patch.object(db_session, "close", lambda: None):
        handle_embed_object(db_session, None, embed_job_payload(obj_a), BOOTSTRAP_USER_ID)
        handle_embed_object(db_session, None, embed_job_payload(obj_b), user_b)

    assert _TRACKING_INIT_API_KEYS == [USER_A_KEY, USER_B_KEY]


def test_embed_job_runs_when_assistant_openai_deployment_config_invalid(
    db_session, monkeypatch, credential_key
) -> None:
    from app.core.assistant_openai_config import AssistantOpenAIConfigError
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    monkeypatch.setattr(settings, "openai_assistant_reasoning_effort", "not-valid-effort")
    obj = _create_object(db_session, BOOTSTRAP_USER_ID)

    with patch(
        "app.llm.embedding_service.OpenAIEmbeddingService",
        _TrackingEmbeddingService,
    ), patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.ai_audit.context.SessionLocal", lambda: db_session
    ), patch(
        "app.services.representation_embedding_worker.SessionLocal", lambda: db_session
    ), patch.object(db_session, "close", lambda: None):
        handle_embed_object(db_session, None, embed_job_payload(obj), BOOTSTRAP_USER_ID)

    assert _TRACKING_INIT_API_KEYS == [DEPLOY_KEY]
    with pytest.raises(AssistantOpenAIConfigError):
        EffectiveUserSettingsService.build(db_session).get_effective_settings(BOOTSTRAP_USER_ID)


def test_embed_job_deployment_fallback_without_personal_key(
    db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    obj = _create_object(db_session, BOOTSTRAP_USER_ID)

    with patch(
        "app.llm.embedding_service.OpenAIEmbeddingService",
        _TrackingEmbeddingService,
    ), patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.ai_audit.context.SessionLocal", lambda: db_session
    ), patch(
        "app.services.representation_embedding_worker.SessionLocal", lambda: db_session
    ), patch.object(db_session, "close", lambda: None):
        handle_embed_object(db_session, None, embed_job_payload(obj), BOOTSTRAP_USER_ID)

    assert _TRACKING_INIT_API_KEYS == [DEPLOY_KEY]


def test_embed_job_fake_service_without_personal_or_deployment_key(
    db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "")
    obj = _create_object(db_session, BOOTSTRAP_USER_ID)

    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.services.representation_embedding_worker.SessionLocal", lambda: db_session
    ), patch.object(db_session, "close", lambda: None), patch(
        "app.jobs.handlers.create_embedding_service_for_api_key",
        wraps=lambda api_key: FakeEmbeddingService(),
    ) as factory_mock:
        handle_embed_object(db_session, None, embed_job_payload(obj), BOOTSTRAP_USER_ID)
        factory_mock.assert_called_once()

    db_session.refresh(obj)
    assert obj.embedding is not None


def test_embed_job_broken_personal_credential_no_fake_fallback(
    db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)
    monkeypatch.setattr(settings, "secretary_credential_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    obj = _create_object(db_session, BOOTSTRAP_USER_ID)

    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.services.representation_embedding_worker.SessionLocal", lambda: db_session
    ), patch.object(db_session, "close", lambda: None), patch(
        "app.llm.embedding_service.FakeEmbeddingService"
    ) as fake_cls:
        with pytest.raises(UserOpenAICredentialConfigurationError):
            handle_embed_object(db_session, None, embed_job_payload(obj), BOOTSTRAP_USER_ID)
        fake_cls.assert_not_called()


def test_embed_job_reuses_one_service_across_object_and_chunks(
    db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings
    from app.services.representation_service import SMALL_TEXT_MAX_CHARS

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    obj = _create_object(db_session, BOOTSTRAP_USER_ID)
    long_text = "chunk boundary stress text. " * 50
    assert len(long_text) > SMALL_TEXT_MAX_CHARS
    RepresentationService(db_session, BOOTSTRAP_USER_ID).ingest_text_content(obj.id, long_text)

    with patch(
        "app.llm.embedding_service.OpenAIEmbeddingService",
        _TrackingEmbeddingService,
    ), patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.ai_audit.context.SessionLocal", lambda: db_session
    ), patch(
        "app.services.representation_embedding_worker.SessionLocal", lambda: db_session
    ), patch.object(db_session, "close", lambda: None):
        handle_embed_object(db_session, None, embed_job_payload(obj), BOOTSTRAP_USER_ID)

    assert len(_TRACKING_INSTANCES) == 1
    assert _TRACKING_INSTANCES[0].embed_calls >= 2


_SUMMARIZER_CAPTURED: list[dict[str, str]] = []
_SUMMARIZER_INSTANCES: list = []


class _CapturingSummarizer:

    def __init__(
        self,
        api_key: str,
        model: str,
        reasoning_effort: str = "low",
        verbosity: str = "low",
        **kwargs,
    ) -> None:
        _SUMMARIZER_CAPTURED.append(
            {
                "api_key": api_key,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "verbosity": verbosity,
            }
        )
        _SUMMARIZER_INSTANCES.append(self)

    def summarize(self, text: str) -> str:
        return "summary"


@pytest.fixture(autouse=True)
def _reset_capturing_summarizer() -> None:
    _SUMMARIZER_CAPTURED.clear()
    _SUMMARIZER_INSTANCES.clear()
    yield
    _SUMMARIZER_CAPTURED.clear()
    _SUMMARIZER_INSTANCES.clear()


def test_summarize_uses_user_key_and_effective_assistant_settings(
    db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    monkeypatch.setattr(settings, "openai_assistant_model", "gpt-deploy-model")
    monkeypatch.setattr(settings, "openai_assistant_reasoning_effort", "low")
    monkeypatch.setattr(settings, "openai_assistant_verbosity", "low")
    monkeypatch.setattr(
        settings,
        "openai_allowed_assistant_models",
        "gpt-user-model,gpt-deploy-model",
    )
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)
    row = EffectiveUserSettingsService.build(db_session).get_or_create_settings_row(BOOTSTRAP_USER_ID)
    row.assistant_model = "gpt-user-model"
    row.assistant_reasoning_effort = "high"
    row.assistant_verbosity = "medium"
    db_session.flush()

    obj = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        metadata={"content_revision": "rev-1"},
    )
    RepresentationService(db_session, BOOTSTRAP_USER_ID).ingest_text_content(obj.id, "body")

    with patch(
        "app.llm.openai_summarizer.OpenAISummarizer",
        _CapturingSummarizer,
    ), patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch.object(
        db_session, "close", lambda: None
    ):
        handle_summarize_resource(
            db_session,
            None,
            {"object_id": str(obj.id), "expected_revision": "rev-1"},
            BOOTSTRAP_USER_ID,
        )

    assert len(_SUMMARIZER_CAPTURED) == 1
    captured = _SUMMARIZER_CAPTURED[0]
    assert captured["api_key"] == USER_A_KEY
    assert captured["model"] == "gpt-user-model"
    assert captured["reasoning_effort"] == "high"
    assert captured["verbosity"] == "medium"


def test_summarize_user_a_and_b_use_separate_providers(
    db_session, monkeypatch, credential_key, user_b
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    monkeypatch.setattr(
        settings,
        "openai_allowed_assistant_models",
        "gpt-user-a,gpt-user-b,gpt-deploy-model",
    )
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)
    _upsert_user_key(db_session, user_b, USER_B_KEY, credential_key)
    row_a = EffectiveUserSettingsService.build(db_session).get_or_create_settings_row(BOOTSTRAP_USER_ID)
    row_a.assistant_model = "gpt-user-a"
    row_a.assistant_reasoning_effort = "low"
    row_a.assistant_verbosity = "low"
    row_b = EffectiveUserSettingsService.build(db_session).get_or_create_settings_row(user_b)
    row_b.assistant_model = "gpt-user-b"
    row_b.assistant_reasoning_effort = "high"
    row_b.assistant_verbosity = "medium"
    db_session.flush()

    obj_a = _create_object(db_session, BOOTSTRAP_USER_ID, metadata={"content_revision": "ra"})
    obj_b = _create_object(db_session, user_b, metadata={"content_revision": "rb"})
    RepresentationService(db_session, BOOTSTRAP_USER_ID).ingest_text_content(obj_a.id, "body a")
    RepresentationService(db_session, user_b).ingest_text_content(obj_b.id, "body b")

    with patch(
        "app.llm.openai_summarizer.OpenAISummarizer",
        _CapturingSummarizer,
    ), patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.ai_audit.context.SessionLocal", lambda: db_session
    ), patch.object(
        db_session, "close", lambda: None
    ):
        handle_summarize_resource(
            db_session,
            None,
            {"object_id": str(obj_a.id), "expected_revision": "ra"},
            BOOTSTRAP_USER_ID,
        )
        handle_summarize_resource(
            db_session,
            None,
            {"object_id": str(obj_b.id), "expected_revision": "rb"},
            user_b,
        )

    assert len(_SUMMARIZER_INSTANCES) == 2
    assert _SUMMARIZER_CAPTURED[0]["api_key"] == USER_A_KEY
    assert _SUMMARIZER_CAPTURED[0]["model"] == "gpt-user-a"
    assert _SUMMARIZER_CAPTURED[1]["api_key"] == USER_B_KEY
    assert _SUMMARIZER_CAPTURED[1]["model"] == "gpt-user-b"


def test_summarize_deployment_fallback_without_personal_credential(
    db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    monkeypatch.setattr(settings, "openai_assistant_model", "gpt-deploy-only")
    obj = _create_object(db_session, BOOTSTRAP_USER_ID, metadata={"content_revision": "r"})
    RepresentationService(db_session, BOOTSTRAP_USER_ID).ingest_text_content(obj.id, "text")

    with patch(
        "app.llm.openai_summarizer.OpenAISummarizer",
        _CapturingSummarizer,
    ), patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch.object(
        db_session, "close", lambda: None
    ):
        handle_summarize_resource(
            db_session,
            None,
            {"object_id": str(obj.id), "expected_revision": "r"},
            BOOTSTRAP_USER_ID,
        )

    assert _SUMMARIZER_CAPTURED[0]["api_key"] == DEPLOY_KEY
    assert _SUMMARIZER_CAPTURED[0]["model"] == "gpt-deploy-only"


def test_summarize_missing_openai_key_raises_non_retryable_configuration_error(
    db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "")
    obj = _create_object(db_session, BOOTSTRAP_USER_ID, metadata={"content_revision": "r"})
    RepresentationService(db_session, BOOTSTRAP_USER_ID).ingest_text_content(obj.id, "text")

    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch.object(
        db_session, "close", lambda: None
    ), pytest.raises(BackgroundAIConfigurationError):
        handle_summarize_resource(
            db_session,
            None,
            {"object_id": str(obj.id), "expected_revision": "r"},
            BOOTSTRAP_USER_ID,
        )
    assert is_job_error_retryable(BackgroundAIConfigurationError("x")) is False


def test_summarize_broken_personal_credential_does_not_fallback(
    db_session, monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)
    monkeypatch.setattr(settings, "secretary_credential_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    obj = _create_object(db_session, BOOTSTRAP_USER_ID, metadata={"content_revision": "r"})
    RepresentationService(db_session, BOOTSTRAP_USER_ID).ingest_text_content(obj.id, "text")

    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch.object(
        db_session, "close", lambda: None
    ), pytest.raises(UserOpenAICredentialConfigurationError):
        handle_summarize_resource(
            db_session,
            None,
            {"object_id": str(obj.id), "expected_revision": "r"},
            BOOTSTRAP_USER_ID,
        )


_JUDGE_CAPTURED: list[dict[str, str]] = []
_JUDGE_INSTANCES: list = []


class _CapturingJudge:

    def __init__(
        self,
        api_key: str,
        model: str,
        reasoning_effort: str = "low",
        verbosity: str = "low",
        **kwargs,
    ) -> None:
        _JUDGE_CAPTURED.append(
            {
                "api_key": api_key,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "verbosity": verbosity,
            }
        )
        _JUDGE_INSTANCES.append(self)

    def judge(self, trigger_title, trigger_kind, trigger_summary, candidates):
        from app.services.correlation_models import CorrelationJudgeResult

        return CorrelationJudgeResult()


@pytest.fixture(autouse=True)
def _reset_capturing_judge() -> None:
    _JUDGE_CAPTURED.clear()
    _JUDGE_INSTANCES.clear()
    yield
    _JUDGE_CAPTURED.clear()
    _JUDGE_INSTANCES.clear()


def test_correlate_uses_user_key_and_effective_settings(
    db_session, monkeypatch, credential_key, user_b
) -> None:
    from app.core.config import settings
    from app.jobs.handlers import handle_correlate_object

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    monkeypatch.setattr(
        settings,
        "openai_allowed_assistant_models",
        "gpt-corr-a,gpt-5.6-luna",
    )
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)
    _upsert_user_key(db_session, user_b, USER_B_KEY, credential_key)
    row = EffectiveUserSettingsService.build(db_session).get_or_create_settings_row(BOOTSTRAP_USER_ID)
    row.assistant_model = "gpt-corr-a"
    row.assistant_reasoning_effort = "medium"
    row.assistant_verbosity = "high"
    db_session.flush()
    obj = _create_object(db_session, BOOTSTRAP_USER_ID)
    from app.services.correlation_input import correlation_input_signature

    with patch(
        "app.llm.correlation_judge.OpenAICorrelationJudge",
        _CapturingJudge,
    ), patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.ai_audit.context.SessionLocal",
        lambda: db_session,
    ), patch.object(
        db_session, "close", lambda: None
    ):
        handle_correlate_object(
            db_session,
            None,
            {
                "object_id": str(obj.id),
                "correlation_input_signature": correlation_input_signature(obj),
            },
            BOOTSTRAP_USER_ID,
        )

    assert _JUDGE_CAPTURED[0]["api_key"] == USER_A_KEY
    assert _JUDGE_CAPTURED[0]["model"] == "gpt-corr-a"
    assert _JUDGE_CAPTURED[0]["reasoning_effort"] == "low"
    assert _JUDGE_CAPTURED[0]["verbosity"] == "low"


def test_correlate_user_a_and_b_use_separate_judges(
    db_session, monkeypatch, credential_key, user_b
) -> None:
    from app.core.config import settings
    from app.jobs.handlers import handle_correlate_object

    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)
    monkeypatch.setattr(
        settings,
        "openai_allowed_assistant_models",
        "gpt-corr-a,gpt-corr-b,gpt-5.6-luna",
    )
    _upsert_user_key(db_session, BOOTSTRAP_USER_ID, USER_A_KEY, credential_key)
    _upsert_user_key(db_session, user_b, USER_B_KEY, credential_key)
    row_a = EffectiveUserSettingsService.build(db_session).get_or_create_settings_row(BOOTSTRAP_USER_ID)
    row_a.assistant_model = "gpt-corr-a"
    row_a.assistant_reasoning_effort = "low"
    row_a.assistant_verbosity = "low"
    row_b = EffectiveUserSettingsService.build(db_session).get_or_create_settings_row(user_b)
    row_b.assistant_model = "gpt-corr-b"
    row_b.assistant_reasoning_effort = "medium"
    row_b.assistant_verbosity = "high"
    db_session.flush()
    obj_a = _create_object(db_session, BOOTSTRAP_USER_ID)
    obj_b = _create_object(db_session, user_b)
    from app.services.correlation_input import correlation_input_signature

    with patch(
        "app.llm.correlation_judge.OpenAICorrelationJudge",
        _CapturingJudge,
    ), patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.ai_audit.context.SessionLocal",
        lambda: db_session,
    ), patch.object(
        db_session, "close", lambda: None
    ):
        handle_correlate_object(
            db_session,
            None,
            {
                "object_id": str(obj_a.id),
                "correlation_input_signature": correlation_input_signature(obj_a),
            },
            BOOTSTRAP_USER_ID,
        )
        handle_correlate_object(
            db_session,
            None,
            {
                "object_id": str(obj_b.id),
                "correlation_input_signature": correlation_input_signature(obj_b),
            },
            user_b,
        )

    assert len(_JUDGE_INSTANCES) == 2
    assert _JUDGE_CAPTURED[0]["api_key"] == USER_A_KEY
    assert _JUDGE_CAPTURED[0]["model"] == "gpt-corr-a"
    assert _JUDGE_CAPTURED[1]["api_key"] == USER_B_KEY
    assert _JUDGE_CAPTURED[1]["model"] == "gpt-corr-b"


def _persist_job(job_type: str, payload: dict, user_id: UUID) -> UUID:
    from sqlalchemy.orm import Session as OrmSession

    conn = engine.connect()
    trans = conn.begin()
    session = OrmSession(bind=conn)
    job = JobQueueService(session).enqueue(job_type, payload, user_id)
    job_id = job.id
    trans.commit()
    conn.close()
    return job_id


def _persist_object() -> UUID:
    from sqlalchemy.orm import Session as OrmSession

    conn = engine.connect()
    trans = conn.begin()
    session = OrmSession(bind=conn)
    obj = GraphService(session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="document",
            title=f"Credential job object {uuid.uuid4()}",
            origin="user",
        )
    )
    obj_id = obj.id
    trans.commit()
    conn.close()
    return obj_id


def _delete_object(object_id: UUID) -> None:
    from sqlalchemy.orm import Session as OrmSession

    conn = engine.connect()
    trans = conn.begin()
    session = OrmSession(bind=conn)
    obj = session.get(Object, object_id)
    if obj is not None:
        session.delete(obj)
    trans.commit()
    conn.close()


def _delete_job(job_id: UUID) -> None:
    from sqlalchemy.orm import Session as OrmSession

    conn = engine.connect()
    trans = conn.begin()
    session = OrmSession(bind=conn)
    session.execute(delete(Job).where(Job.id == job_id))
    trans.commit()
    conn.close()


def _clear_pending_jobs() -> None:
    from sqlalchemy.orm import Session as OrmSession

    conn = engine.connect()
    trans = conn.begin()
    session = OrmSession(bind=conn)
    session.execute(delete(Job).where(Job.status == JOB_STATUS_PENDING))
    trans.commit()
    conn.close()


def test_source_sync_job_does_not_resolve_openai_credential() -> None:
    _clear_pending_jobs()
    job_id = _persist_job(
        JOB_TYPE_SYNC_GOOGLE_GMAIL,
        {"account_id": str(uuid.uuid4())},
        BOOTSTRAP_USER_ID,
    )

    noop = lambda session, embedding_service, payload, user_id: None
    try:
        with patch.dict(HANDLERS, {JOB_TYPE_SYNC_GOOGLE_GMAIL: noop}), patch(
            "app.services.effective_user_settings_service.EffectiveUserSettingsService.build"
        ) as build_mock:
            assert process_one_job()
            build_mock.assert_not_called()
    finally:
        _delete_job(job_id)


def _persist_user_credential(user_id: UUID, api_key: str, credential_key: str) -> None:
    from sqlalchemy.orm import Session as OrmSession

    conn = engine.connect()
    trans = conn.begin()
    session = OrmSession(bind=conn)
    UserOpenAICredentialStore(session, credential_key).upsert(user_id, api_key)
    trans.commit()
    conn.close()


def test_credential_failure_sanitized_job_error_and_non_retryable(
    monkeypatch, credential_key
) -> None:
    from app.core.config import settings

    _persist_user_credential(BOOTSTRAP_USER_ID, LEAK_MARKER, credential_key)
    monkeypatch.setattr(settings, "secretary_credential_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "openai_api_key", DEPLOY_KEY)

    _clear_pending_jobs()
    obj_id = _persist_object()
    from sqlalchemy.orm import Session as OrmSession

    conn = engine.connect()
    session = OrmSession(bind=conn)
    obj = session.get(Object, obj_id)
    assert obj is not None
    payload = embed_job_payload(obj)
    conn.close()
    job_id = _persist_job(JOB_TYPE_EMBED_OBJECT, payload, BOOTSTRAP_USER_ID)

    assert process_one_job()

    conn = engine.connect()
    session = OrmSession(bind=conn)
    stored = session.get(Job, job_id)
    conn.close()
    assert stored is not None
    assert stored.attempts >= 1
    assert stored.last_error is not None
    assert LEAK_MARKER not in (stored.last_error or "")
    assert DEPLOY_KEY not in (stored.last_error or "")
    assert LEAK_MARKER not in str(stored.payload)
    assert is_job_error_retryable(UserOpenAICredentialConfigurationError("x")) is False
    _delete_job(job_id)
    _delete_object(obj_id)
    _delete_user_credential(BOOTSTRAP_USER_ID)


def test_sanitize_job_error_strips_sk_prefix() -> None:
    assert LEAK_MARKER not in sanitize_job_error(RuntimeError(LEAK_MARKER))
    assert sanitize_job_error(RuntimeError(LEAK_MARKER)) == "RuntimeError"
