"""Teams A — send_message prepare/execute, replay, Mattermost/Telegram compatibility."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import select

from app.connectors.teams.errors import TeamsWriteDefiniteError, TeamsWriteUncertainError
from app.connectors.teams.materialize import TeamsObjectMaterializer
from app.connectors.teams.normalize import build_external_id
from app.connectors.teams.transport import FakeTeamsTransport
from app.db.models import ExternalActionAttempt, Object, User
from app.services.communication_external_action_service import (
    ATTEMPT_FAILED_DEFINITE,
    ATTEMPT_SUCCEEDED,
    ATTEMPT_UNCERTAIN,
    CommunicationExternalActionService,
)
from app.services.recent_source_service import RecentSourceService
from app.tools.registry import TOOL_REGISTRY
from app.tools.schemas import SendMessageCanonicalInput, SendMessageInput, ToolError
from tests.test_teams_a import (
    CHAT_ONE,
    TEAMS_USER_ID,
    TENANT_ID,
    _connect_account,
    _graph_message,
    _graph_reply_with_quote,
)
from tests.test_unified_communications_a import ALLOWED_URL

SOURCE_MESSAGE_ID = "src-1"


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def teams_settings(monkeypatch: pytest.MonkeyPatch, credential_key: str) -> str:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    monkeypatch.setattr("app.core.config.settings.microsoft_oauth_client_id", "client-id")
    monkeypatch.setattr("app.core.config.settings.microsoft_oauth_client_secret", "client-secret")
    monkeypatch.setattr(
        "app.core.config.settings.microsoft_redirect_uri",
        "http://localhost:18080/auth/teams/callback",
    )
    monkeypatch.setattr("app.core.config.settings.mattermost_allowed_base_urls", ALLOWED_URL)
    return credential_key


class _SessionProxy:
    def __init__(self, session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def commit(self) -> None:
        self._session.flush()

    def rollback(self) -> None:
        self._session.flush()

    def __getattr__(self, name):
        return getattr(self._session, name)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _service(session, user_id, fake: FakeTeamsTransport | None = None):
    return CommunicationExternalActionService(
        session,
        user_id,
        teams_transport=fake,
        attempt_session_factory=lambda: _SessionProxy(session),
    )


def _teams_object(
    session,
    user_id,
    account,
    *,
    message_id: str = SOURCE_MESSAGE_ID,
    chat_id: str = CHAT_ONE,
    chat_type: str = "oneOnOne",
    direction: str = "inbound",
    extra_meta: dict | None = None,
) -> Object:
    meta = {
        "account_id": str(account.id),
        "tenant_id": account.tenant_id,
        "teams_user_id": account.microsoft_user_id,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "message_id": message_id,
        "sender_id": "other" if direction == "inbound" else account.microsoft_user_id,
        "sender_display_name": "Petrushin",
        "chat_display_title": "Petrushin",
        "direction": direction,
        "created_at": _utcnow().isoformat(),
        "modified_at": None,
        "reply_to_message_id": None,
        "quoted_message_id": None,
    }
    if extra_meta:
        meta.update(extra_meta)
    obj = Object(
        user_id=user_id,
        kind="chat_message",
        provider="teams",
        external_id=build_external_id(
            account.tenant_id, account.microsoft_user_id, chat_id, message_id
        ),
        origin="source",
        state="observed",
        title="Petrushin: hello",
        body="hello",
        metadata_=meta,
        occurred_at=_utcnow(),
    )
    session.add(obj)
    session.flush()
    return obj


def test_send_message_public_schema_unchanged() -> None:
    fields = set(SendMessageInput.model_fields)
    assert fields == {"body", "conversation_object_id", "reply_to_object_id"}
    assert "send_teams" not in TOOL_REGISTRY
    assert "send_telegram" not in TOOL_REGISTRY
    assert "send_mattermost" not in TOOL_REGISTRY


def test_prepare_teams_compose_and_reply_freeze_route_from_object(db_session, teams_settings) -> None:
    user = User(id=uuid4(), display_name="teams")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, teams_settings, user.id)
    inbound = _teams_object(db_session, user.id, account)
    fake = FakeTeamsTransport()
    service = _service(db_session, user.id, fake)
    composed = service.prepare_send_message(
        SendMessageInput(body="новое сообщение", conversation_object_id=inbound.id)
    )
    assert composed.provider == "teams"
    assert composed.mode == "compose"
    assert composed.teams_route.chat_id == CHAT_ONE
    assert composed.teams_route.quoted_message_id is None
    assert composed.teams_route.tenant_id == TENANT_ID
    assert composed.teams_route.source_message_id == SOURCE_MESSAGE_ID
    dumped = json.dumps(composed.model_dump(mode="json"))
    assert "access-token" not in dumped
    assert "client-secret" not in dumped
    replied = service.prepare_send_message(
        SendMessageInput(body="ответ", reply_to_object_id=inbound.id)
    )
    assert replied.mode == "reply"
    assert replied.teams_route.quoted_message_id == SOURCE_MESSAGE_ID
    assert fake.send_message_calls == []
    assert fake.reply_with_quote_calls == []


def test_provider_ids_are_not_accepted_from_model_arguments() -> None:
    with pytest.raises(ValidationError):
        SendMessageInput.model_validate(
            {
                "body": "hi",
                "conversation_object_id": str(uuid4()),
                "chat_id": CHAT_ONE,
            }
        )


def test_prepare_rejects_wrong_user_account_provider_and_chat_type(db_session, teams_settings) -> None:
    user = User(id=uuid4(), display_name="teams")
    other = User(id=uuid4(), display_name="other")
    db_session.add_all([user, other])
    db_session.flush()
    account = _connect_account(db_session, teams_settings, user.id)
    inbound = _teams_object(db_session, user.id, account)
    fake = FakeTeamsTransport()
    service = _service(db_session, user.id, fake)
    inbound.metadata_ = {**inbound.metadata_, "chat_type": "meeting"}
    db_session.flush()
    with pytest.raises(ToolError, match="chat type"):
        service.prepare_send_message(SendMessageInput(body="hi", conversation_object_id=inbound.id))
    inbound.metadata_ = {
        **inbound.metadata_,
        "chat_type": "oneOnOne",
        "tenant_id": "44444444-4444-4444-4444-444444444444",
    }
    db_session.flush()
    with pytest.raises(ToolError, match="tenant"):
        service.prepare_send_message(SendMessageInput(body="hi", conversation_object_id=inbound.id))
    other_service = _service(db_session, other.id, fake)
    with pytest.raises(ToolError, match="not found"):
        other_service.prepare_send_message(
            SendMessageInput(body="hi", conversation_object_id=inbound.id)
        )


def test_approve_compose_and_reply_write_once(db_session, teams_settings) -> None:
    user = User(id=uuid4(), display_name="teams")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, teams_settings, user.id)
    inbound = _teams_object(db_session, user.id, account)
    fake = FakeTeamsTransport()
    fake.me = {"id": TEAMS_USER_ID}
    service = _service(db_session, user.id, fake)
    composed = service.prepare_send_message(
        SendMessageInput(body="новое", conversation_object_id=inbound.id)
    )
    fake.send_message_response = _graph_message(
        message_id="out-1",
        chat_id=CHAT_ONE,
        body="новое",
        created="2026-09-13T14:00:00Z",
        from_id=TEAMS_USER_ID,
    )
    first = service.send_message(composed)
    assert first.delivery_status == "sent"
    assert first.changed is True
    assert len(fake.send_message_calls) == 1
    assert fake.reply_with_quote_calls == []
    replay = service.send_message(composed)
    assert replay.delivery_status == "already_sent"
    assert len(fake.send_message_calls) == 1
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt is not None
    assert attempt.state == ATTEMPT_SUCCEEDED
    outbound = db_session.scalar(
        select(Object).where(
            Object.external_id == build_external_id(TENANT_ID, TEAMS_USER_ID, CHAT_ONE, "out-1")
        )
    )
    assert outbound is not None
    assert outbound.metadata_["direction"] == "outbound"
    feed = RecentSourceService(db_session, user.id).list_page()
    assert outbound.id not in {item.id for item in feed.items}

    replied = service.prepare_send_message(
        SendMessageInput(body="ответ", reply_to_object_id=inbound.id)
    )
    fake.reply_with_quote_response = _graph_reply_with_quote(
        message_id="out-2",
        chat_id=CHAT_ONE,
        body="ответ",
        created="2026-09-13T14:01:00Z",
        from_id=TEAMS_USER_ID,
        quoted_message_id=SOURCE_MESSAGE_ID,
        reply_to_id=None,
    )
    result = service.send_message(replied)
    assert result.delivery_status == "sent"
    assert fake.reply_with_quote_calls == [
        {"chat_id": CHAT_ONE, "quoted_message_id": SOURCE_MESSAGE_ID, "body": "ответ"}
    ]
    outbound_reply = db_session.scalar(
        select(Object).where(
            Object.external_id == build_external_id(TENANT_ID, TEAMS_USER_ID, CHAT_ONE, "out-2")
        )
    )
    assert outbound_reply is not None
    assert outbound_reply.body == "ответ"
    assert "attachment" not in (outbound_reply.body or "").lower()
    assert outbound_reply.metadata_["reply_to_message_id"] is None
    assert outbound_reply.metadata_["quoted_message_id"] == SOURCE_MESSAGE_ID


def test_uncertain_and_failed_definite_do_not_blind_retry(db_session, teams_settings) -> None:
    user = User(id=uuid4(), display_name="teams")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, teams_settings, user.id)
    inbound = _teams_object(db_session, user.id, account)
    fake = FakeTeamsTransport()
    service = _service(db_session, user.id, fake)

    frozen = service.prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=inbound.id)
    )
    fake.send_message_error = TeamsWriteUncertainError("timeout")
    with pytest.raises(ToolError, match="confirm"):
        service.send_message(frozen)
    fake.send_message_error = None
    with pytest.raises(ToolError, match="confirm"):
        service.send_message(frozen)
    assert len(fake.send_message_calls) == 1
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt.state == ATTEMPT_UNCERTAIN

    frozen2 = service.prepare_send_message(
        SendMessageInput(body="fail", conversation_object_id=inbound.id)
    )
    fake.send_message_calls.clear()
    fake.send_message_error = TeamsWriteDefiniteError("rejected")
    with pytest.raises(ToolError, match="rejected"):
        service.send_message(frozen2)
    fake.send_message_error = None
    with pytest.raises(ToolError, match="previously failed"):
        service.send_message(frozen2)
    assert len(fake.send_message_calls) == 1
    failed = db_session.scalars(
        select(ExternalActionAttempt).where(
            ExternalActionAttempt.operation_id == frozen2.operation_id
        )
    ).one()
    assert failed.state == ATTEMPT_FAILED_DEFINITE


def test_pre_provider_eligibility_failure_is_failed_definite(db_session, teams_settings) -> None:
    user = User(id=uuid4(), display_name="teams")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, teams_settings, user.id)
    inbound = _teams_object(db_session, user.id, account)
    fake = FakeTeamsTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=inbound.id)
    )
    db_session.delete(account)
    db_session.flush()
    with pytest.raises(ToolError, match="not connected"):
        service.send_message(frozen)
    assert fake.send_message_calls == []
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt is not None
    assert attempt.state == ATTEMPT_FAILED_DEFINITE


def test_outbound_not_duplicated_by_later_poll(db_session, teams_settings) -> None:
    user = User(id=uuid4(), display_name="teams")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, teams_settings, user.id)
    inbound = _teams_object(db_session, user.id, account)
    fake = FakeTeamsTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="гонка", conversation_object_id=inbound.id)
    )
    created = _graph_message(
        message_id="race-1",
        chat_id=CHAT_ONE,
        body="гонка",
        created="2026-09-13T14:00:00Z",
        from_id=TEAMS_USER_ID,
    )
    fake.send_message_response = created
    service.send_message(frozen)
    result = TeamsObjectMaterializer(db_session).upsert_message(
        user_id=user.id,
        account_id=account.id,
        tenant_id=TENANT_ID,
        microsoft_user_id=TEAMS_USER_ID,
        chat_id=CHAT_ONE,
        chat_type="oneOnOne",
        chat_display_title="Petrushin",
        message=created,
    )
    assert result.change == "unchanged"
    objects = list(
        db_session.scalars(
            select(Object).where(
                Object.external_id == build_external_id(TENANT_ID, TEAMS_USER_ID, CHAT_ONE, "race-1")
            )
        )
    )
    assert len(objects) == 1


def test_legacy_mattermost_canonical_still_parses_with_teams_union() -> None:
    payload = {
        "provider": "mattermost",
        "mode": "compose",
        "account_id": str(uuid4()),
        "server_url": "https://chat.example.test",
        "channel_id": "channel-1",
        "channel_type": "O",
        "channel_name": "town-square",
        "channel_display_name": "Town Square",
        "anchor_object_id": str(uuid4()),
        "source_post_id": "post-1",
        "root_id": None,
        "body": "hello",
        "operation_id": "abcde12345",
        "pending_post_id": "secretary:abcde12345",
    }
    parsed = SendMessageCanonicalInput.model_validate(payload)
    assert parsed.provider == "mattermost"
    assert parsed.mattermost_route.channel_id == "channel-1"
    assert parsed.pending_post_id == "secretary:abcde12345"


def test_teams_write_429_is_failed_definite_not_uncertain(db_session, teams_settings) -> None:
    user = User(id=uuid4(), display_name="teams")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, teams_settings, user.id)
    inbound = _teams_object(db_session, user.id, account)
    fake = FakeTeamsTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=inbound.id)
    )
    fake.send_message_error = TeamsWriteDefiniteError("Teams rate limited")
    with pytest.raises(ToolError, match="rate limited"):
        service.send_message(frozen)
    fake.send_message_error = None
    with pytest.raises(ToolError, match="previously failed"):
        service.send_message(frozen)
    assert len(fake.send_message_calls) == 1
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt.state == ATTEMPT_FAILED_DEFINITE


def test_send_blocked_when_reconnect_required(db_session, teams_settings) -> None:
    user = User(id=uuid4(), display_name="teams")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, teams_settings, user.id)
    inbound = _teams_object(db_session, user.id, account)
    fake = FakeTeamsTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=inbound.id)
    )
    from app.connectors.teams.account_store import TeamsAccountStore
    from app.core.config import settings

    store = TeamsAccountStore(
        db_session,
        TeamsAccountStore.build_encryption(settings.secretary_credential_key),
    )
    store.mark_reconnect_required(account)
    db_session.flush()
    with pytest.raises(ToolError, match="reconnect"):
        service.send_message(frozen)
    assert fake.send_message_calls == []
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt.state == ATTEMPT_FAILED_DEFINITE

