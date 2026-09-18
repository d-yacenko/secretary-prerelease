from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.connectors.telegram.constants import TELEGRAM_KIND, TELEGRAM_PROVIDER
from app.connectors.telegram.materialize import TelegramObjectMaterializer
from app.core.config import Settings, settings
from app.db.models import Job, Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection, User
from app.domain.telegram_mtproto_ai import (
    is_canonical_telegram_mtproto_object,
    telegram_mtproto_ai_eligible,
)
from app.services.context_service import ContextService
from app.services.errors import NotFoundError
from app.services.object_query_service import ObjectQueryService
from app.services.telegram_mtproto_recurring_sync_service import (
    TelegramMtprotoRecurringSyncService,
)


def _user(db_session) -> User:
    user = User(id=uuid4(), display_name="Q1 Telegram user")
    db_session.add(user)
    db_session.flush()
    return user


def _mtproto_object(
    db_session, user_id, *, account_id=None, peer_id=123, object_id=None
) -> Object:
    obj = Object(
        id=object_id or uuid4(),
        user_id=user_id,
        kind=TELEGRAM_KIND,
        provider=TELEGRAM_PROVIDER,
        external_id=f"mtproto|{uuid4()}",
        origin="source",
        state="observed",
        title="Q1 message",
        body="message body",
        metadata_={
            "transport": "mtproto",
            "account_id": str(account_id or uuid4()),
            "peer_id": str(peer_id),
        },
    )
    db_session.add(obj)
    db_session.flush()
    return obj


def test_settings_default_false() -> None:
    assert Settings().telegram_mtproto_ai_enabled is False


def test_compose_exposes_same_fail_closed_flag_to_api_and_worker() -> None:
    content = (Path(__file__).resolve().parents[2] / "infra" / "compose.yaml").read_text()
    key = "TELEGRAM_MTPROTO_AI_ENABLED: ${TELEGRAM_MTPROTO_AI_ENABLED:-false}"
    assert content.count(key) == 2


def test_mtproto_materialization_stores_without_embedding_job_when_disabled(
    db_session, monkeypatch
) -> None:
    user = _user(db_session)
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    result = TelegramObjectMaterializer(db_session).upsert_mtproto_message(
        user_id=user.id,
        normalized={
            "provider": TELEGRAM_PROVIDER,
            "kind": TELEGRAM_KIND,
            "external_id": f"mtproto|{uuid4()}",
            "origin": "source",
            "state": "observed",
            "title": "Stored",
            "body": "kept",
            "metadata": {"transport": "mtproto"},
        },
    )
    assert result.change == "created"
    assert result.jobs_enqueued == 0
    assert result.obj is not None
    assert db_session.scalar(select(func.count()).select_from(Job)) == 0
    result = TelegramObjectMaterializer(db_session).upsert_mtproto_message(
        user_id=user.id,
        normalized={
            "provider": TELEGRAM_PROVIDER,
            "kind": TELEGRAM_KIND,
            "external_id": result.obj.external_id,
            "origin": "source",
            "state": "observed",
            "title": "Updated",
            "body": "updated body",
            "metadata": {"transport": "mtproto"},
        },
    )
    assert result.change == "updated"
    assert result.jobs_enqueued == 0
    assert db_session.scalar(select(func.count()).select_from(Job)) == 0


def test_bot_api_and_other_provider_enqueue_as_before(db_session, monkeypatch) -> None:
    from app.services.pipeline_enqueue import enqueue_embed_object

    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    user = _user(db_session)
    for provider, kind in ((TELEGRAM_PROVIDER, TELEGRAM_KIND), ("google", "email")):
        obj = Object(
            user_id=user.id,
            provider=provider,
            kind=kind,
            external_id=f"{provider}|{uuid4()}",
            origin="source",
            state="observed",
            title="ordinary object",
            body="body",
            metadata_={},
        )
        db_session.add(obj)
        db_session.flush()
        enqueue_embed_object(db_session, obj.id, user.id)
    assert db_session.scalar(select(func.count()).select_from(Job)) == 2


def test_direct_context_cannot_bypass_disabled_mtproto_gate(db_session, monkeypatch) -> None:
    user = _user(db_session)
    obj = _mtproto_object(db_session, user.id)
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    with pytest.raises(NotFoundError):
        ContextService(db_session, user.id).build_context(object_id=obj.id)


def test_enabled_catchup_is_bounded_and_idempotent_for_active_owned_objects(
    db_session, monkeypatch
) -> None:
    user = _user(db_session)
    account = TelegramMtprotoAccount(
        id=uuid4(),
        user_id=user.id,
        telegram_user_id=uuid4().int % 2_000_000_000,
        session_encrypted="encrypted",
    )
    db_session.add(account)
    db_session.flush()
    selection = TelegramMtprotoChatSelection(
        account_id=account.id,
        peer_id=123,
        peer_kind="group",
        provider_peer_reference_encrypted="encrypted",
        title="Q1 group",
        manual_selected=False,
        scope_active=True,
    )
    db_session.add(selection)
    db_session.flush()
    _mtproto_object(db_session, user.id, account_id=account.id, peer_id=123)
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    service = TelegramMtprotoRecurringSyncService.__new__(TelegramMtprotoRecurringSyncService)
    service._session = db_session
    assert service._enqueue_embedding_catchup(user.id, account.id) == 1
    assert service._enqueue_embedding_catchup(user.id, account.id) == 0
    assert db_session.scalar(select(func.count()).select_from(Job)) == 1


def test_ordinary_visibility_is_independent_from_ai_quarantine(db_session, monkeypatch) -> None:
    user = _user(db_session)
    account = TelegramMtprotoAccount(
        user_id=user.id,
        telegram_user_id=uuid4().int % 2_000_000_000,
        session_encrypted="encrypted",
    )
    db_session.add(account)
    db_session.flush()
    db_session.add(
        TelegramMtprotoChatSelection(
            account_id=account.id,
            peer_id=123,
            peer_kind="group",
            provider_peer_reference_encrypted="encrypted",
            title="ordinary scope",
            manual_selected=False,
            scope_active=True,
        )
    )
    obj = _mtproto_object(db_session, user.id, account_id=account.id, peer_id=123)
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)

    assert obj in ObjectQueryService(db_session, user.id).query(
        kinds=[TELEGRAM_KIND], providers=[TELEGRAM_PROVIDER]
    )
    assert obj not in ObjectQueryService(db_session, user.id, ai_only=True).query(
        kinds=[TELEGRAM_KIND], providers=[TELEGRAM_PROVIDER]
    )


def test_catchup_scans_past_pending_rows_and_advances_cursor(db_session, monkeypatch) -> None:
    user = _user(db_session)
    account = TelegramMtprotoAccount(
        user_id=user.id,
        telegram_user_id=uuid4().int % 2_000_000_000,
        session_encrypted="encrypted",
    )
    db_session.add(account)
    db_session.flush()
    db_session.add(
        TelegramMtprotoChatSelection(
            account_id=account.id,
            peer_id=123,
            peer_kind="group",
            provider_peer_reference_encrypted="encrypted",
            title="catchup scope",
            manual_selected=False,
            scope_active=True,
        )
    )
    objects = []
    for index in range(11):
        obj = _mtproto_object(
            db_session,
            user.id,
            account_id=account.id,
            peer_id=123,
            object_id=UUID(int=index + 1),
        )
        objects.append(obj)
    db_session.flush()
    for obj in objects[:10]:
        db_session.add(
            Job(
                user_id=user.id,
                type="embed_object",
                status="pending",
                payload={"object_id": str(obj.id)},
            )
        )
    db_session.flush()
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    service = TelegramMtprotoRecurringSyncService.__new__(TelegramMtprotoRecurringSyncService)
    service._session = db_session
    payload = {}
    queued = service._enqueue_embedding_catchup(user.id, account.id, payload)

    assert queued == 1
    assert payload["telegram_embed_catchup_cursor"]


def test_queued_embed_becomes_safe_noop_when_ai_is_disabled(db_session, monkeypatch) -> None:
    user = _user(db_session)
    obj = _mtproto_object(db_session, user.id)
    from app.jobs.handlers import handle_embed_object
    from app.llm.embedding_text import embedding_input_signature

    payload = {
        "object_id": str(obj.id),
        "embedding_input_signature": embedding_input_signature(obj),
    }
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    handle_embed_object(db_session, None, payload, user.id)
    assert db_session.scalar(select(func.count()).select_from(Job)) == 0


def test_malformed_mtproto_metadata_is_not_canonical_or_eligible(db_session, monkeypatch) -> None:
    user = _user(db_session)
    obj = Object(
        user_id=user.id,
        provider=TELEGRAM_PROVIDER,
        kind=TELEGRAM_KIND,
        external_id=f"malformed|{uuid4()}",
        origin="source",
        state="observed",
        title="Malformed",
        body="body",
        metadata_={"transport": "mtproto"},
    )
    db_session.add(obj)
    db_session.flush()
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    assert is_canonical_telegram_mtproto_object(obj)
    assert telegram_mtproto_ai_eligible(db_session, obj) is False
