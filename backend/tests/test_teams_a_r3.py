"""Teams A-R3 — Graph replyWithQuote provenance vs Secretary quoted_message_id."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.connectors.teams.html_text import teams_body_to_plain_text
from app.connectors.teams.materialize import TeamsObjectMaterializer
from app.connectors.teams.normalize import (
    extract_message_reference_ids,
    quoted_message_id_from_attachments,
)
from app.connectors.teams.transport import FakeTeamsTransport
from app.db.models import ExternalActionAttempt, Object, User
from app.services.communication_external_action_service import (
    ATTEMPT_SUCCEEDED,
    ATTEMPT_UNCERTAIN,
    CommunicationExternalActionService,
)
from app.tools.schemas import SendMessageInput, ToolError
from tests.test_teams_a import (
    CHAT_ONE,
    TEAMS_USER_ID,
    TENANT_ID,
    _connect_account,
    _graph_message,
    _graph_reply_with_quote,
    _sync_service,
    _user,
)
from tests.test_teams_a_send import SOURCE_MESSAGE_ID, _service, _SessionProxy, _teams_object
from tests.test_unified_communications_a import ALLOWED_URL


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


def test_html_attachment_markup_is_stripped_from_body() -> None:
    text = teams_body_to_plain_text(
        content_type="html",
        content='<p>ответ</p><attachment id="quoted-message-ref"></attachment>',
    )
    assert text == "ответ"
    assert "attachment" not in text.lower()


def test_malformed_message_reference_does_not_create_false_link() -> None:
    payload = _graph_reply_with_quote(
        message_id="in-1",
        chat_id=CHAT_ONE,
        body="hi",
        created="2026-09-13T12:01:00Z",
        from_id="other",
        quoted_message_id=SOURCE_MESSAGE_ID,
        attachment_content="not-json",
    )
    assert extract_message_reference_ids(payload) == []
    assert quoted_message_id_from_attachments(payload) is None
    payload["attachments"] = [
        {"contentType": "file", "content": json.dumps({"messageId": SOURCE_MESSAGE_ID})},
        {"contentType": "messageReference", "content": json.dumps({"preview": "x"})},
        {"contentType": "messageReference", "content": ["oops"]},
        {"contentType": "messageReference"},
        "skip-me",
    ]
    assert quoted_message_id_from_attachments(payload) is None


def test_approved_reply_with_quote_graph_contract_preserves_frozen_target(
    db_session, teams_settings
) -> None:
    user = User(id=uuid4(), display_name="teams")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, teams_settings, user.id)
    inbound = _teams_object(db_session, user.id, account)
    fake = FakeTeamsTransport()
    fake.me = {"id": TEAMS_USER_ID}
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="ответ", reply_to_object_id=inbound.id)
    )
    fake.reply_with_quote_response = _graph_reply_with_quote(
        message_id="out-quote",
        chat_id=CHAT_ONE,
        body="ответ",
        created="2026-09-13T14:01:00Z",
        from_id=TEAMS_USER_ID,
        quoted_message_id=SOURCE_MESSAGE_ID,
        reply_to_id=None,
    )
    result = service.send_message(frozen)
    assert result.delivery_status == "sent"
    assert fake.reply_with_quote_calls == [
        {"chat_id": CHAT_ONE, "quoted_message_id": SOURCE_MESSAGE_ID, "body": "ответ"}
    ]
    outbound = db_session.scalar(
        select(Object).where(Object.id == result.object_id)
    )
    assert outbound is not None
    assert outbound.body == "ответ"
    assert outbound.metadata_["reply_to_message_id"] is None
    assert outbound.metadata_["quoted_message_id"] == SOURCE_MESSAGE_ID
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt.state == ATTEMPT_SUCCEEDED


def test_reply_without_attachment_detail_still_keeps_frozen_quote(
    db_session, teams_settings
) -> None:
    user = User(id=uuid4(), display_name="teams")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, teams_settings, user.id)
    inbound = _teams_object(db_session, user.id, account)
    fake = FakeTeamsTransport()
    fake.me = {"id": TEAMS_USER_ID}
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="ответ", reply_to_object_id=inbound.id)
    )
    fake.reply_with_quote_response = _graph_reply_with_quote(
        message_id="out-no-att",
        chat_id=CHAT_ONE,
        body="ответ",
        created="2026-09-13T14:01:00Z",
        from_id=TEAMS_USER_ID,
        quoted_message_id=SOURCE_MESSAGE_ID,
        reply_to_id=None,
        include_attachment=False,
    )
    result = service.send_message(frozen)
    assert result.delivery_status == "sent"
    outbound = db_session.scalar(select(Object).where(Object.id == result.object_id))
    assert outbound.metadata_["quoted_message_id"] == SOURCE_MESSAGE_ID
    assert outbound.metadata_["reply_to_message_id"] is None


def test_passive_poll_does_not_duplicate_or_erase_quote_provenance(
    db_session, teams_settings
) -> None:
    user = User(id=uuid4(), display_name="teams")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, teams_settings, user.id)
    inbound = _teams_object(db_session, user.id, account)
    fake = FakeTeamsTransport()
    fake.me = {"id": TEAMS_USER_ID}
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="ответ", reply_to_object_id=inbound.id)
    )
    created = _graph_reply_with_quote(
        message_id="out-poll",
        chat_id=CHAT_ONE,
        body="ответ",
        created="2026-09-13T14:01:00Z",
        from_id=TEAMS_USER_ID,
        quoted_message_id=SOURCE_MESSAGE_ID,
        reply_to_id=None,
    )
    fake.reply_with_quote_response = created
    service.send_message(frozen)
    poll_without_quote = _graph_message(
        message_id="out-poll",
        chat_id=CHAT_ONE,
        body="ответ",
        created="2026-09-13T14:01:00Z",
        from_id=TEAMS_USER_ID,
    )
    result = TeamsObjectMaterializer(db_session).upsert_message(
        user_id=user.id,
        account_id=account.id,
        tenant_id=TENANT_ID,
        microsoft_user_id=TEAMS_USER_ID,
        chat_id=CHAT_ONE,
        chat_type="oneOnOne",
        chat_display_title="Petrushin",
        message=poll_without_quote,
    )
    assert result.change in {"unchanged", "updated"}
    objects = list(
        db_session.scalars(
            select(Object).where(Object.external_id == result.obj.external_id)
        )
    )
    assert len(objects) == 1
    assert objects[0].metadata_["quoted_message_id"] == SOURCE_MESSAGE_ID
    conflicting = _graph_reply_with_quote(
        message_id="out-poll",
        chat_id=CHAT_ONE,
        body="ответ",
        created="2026-09-13T14:01:00Z",
        from_id=TEAMS_USER_ID,
        quoted_message_id="other-quoted",
        reply_to_id=None,
    )
    TeamsObjectMaterializer(db_session).upsert_message(
        user_id=user.id,
        account_id=account.id,
        tenant_id=TENANT_ID,
        microsoft_user_id=TEAMS_USER_ID,
        chat_id=CHAT_ONE,
        chat_type="oneOnOne",
        chat_display_title="Petrushin",
        message=conflicting,
    )
    db_session.refresh(objects[0])
    assert objects[0].metadata_["quoted_message_id"] == SOURCE_MESSAGE_ID


def test_inbound_reply_with_quote_extracts_quote_provenance(db_session, teams_settings) -> None:
    user = _user(db_session)
    floor = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    account = _connect_account(db_session, teams_settings, user.id, sync_start=floor)
    fake = FakeTeamsTransport()
    fake.chats = [{"id": CHAT_ONE, "chatType": "oneOnOne", "members": []}]
    fake.messages_by_chat[CHAT_ONE] = [
        _graph_reply_with_quote(
            message_id="in-quote",
            chat_id=CHAT_ONE,
            body="quoted reply",
            created="2026-09-13T12:02:00Z",
            from_id="other",
            quoted_message_id=SOURCE_MESSAGE_ID,
            reply_to_id=None,
        )
    ]
    _sync_service(db_session, teams_settings, fake).sync_account(account.id, user.id)
    obj = db_session.scalar(select(Object).where(Object.user_id == user.id))
    assert obj is not None
    assert obj.body == "quoted reply"
    assert obj.metadata_["reply_to_message_id"] is None
    assert obj.metadata_["quoted_message_id"] == SOURCE_MESSAGE_ID
    assert obj.metadata_["direction"] == "inbound"


def test_mismatched_message_reference_on_write_is_uncertain_and_not_retried(
    db_session, teams_settings
) -> None:
    user = User(id=uuid4(), display_name="teams")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, teams_settings, user.id)
    inbound = _teams_object(db_session, user.id, account)
    fake = FakeTeamsTransport()
    fake.me = {"id": TEAMS_USER_ID}
    service = CommunicationExternalActionService(
        db_session,
        user.id,
        teams_transport=fake,
        attempt_session_factory=lambda: _SessionProxy(db_session),
    )
    frozen = service.prepare_send_message(
        SendMessageInput(body="ответ", reply_to_object_id=inbound.id)
    )
    fake.reply_with_quote_response = _graph_reply_with_quote(
        message_id="out-mismatch",
        chat_id=CHAT_ONE,
        body="ответ",
        created="2026-09-13T14:01:00Z",
        from_id=TEAMS_USER_ID,
        quoted_message_id="someone-else",
        reply_to_id=None,
    )
    with pytest.raises(ToolError, match="confirm"):
        service.send_message(frozen)
    with pytest.raises(ToolError, match="confirm"):
        service.send_message(frozen)
    assert len(fake.reply_with_quote_calls) == 1
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt.state == ATTEMPT_UNCERTAIN
    outbound = db_session.scalars(
        select(Object).where(
            Object.user_id == user.id,
            Object.id != inbound.id,
        )
    ).all()
    assert outbound == []


def test_compose_does_not_get_false_quoted_target(db_session, teams_settings) -> None:
    user = User(id=uuid4(), display_name="teams")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, teams_settings, user.id)
    inbound = _teams_object(db_session, user.id, account)
    fake = FakeTeamsTransport()
    fake.me = {"id": TEAMS_USER_ID}
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="новое", conversation_object_id=inbound.id)
    )
    fake.send_message_response = _graph_message(
        message_id="out-compose",
        chat_id=CHAT_ONE,
        body="новое",
        created="2026-09-13T14:00:00Z",
        from_id=TEAMS_USER_ID,
    )
    result = service.send_message(frozen)
    assert result.delivery_status == "sent"
    outbound = db_session.scalar(select(Object).where(Object.id == result.object_id))
    assert outbound.metadata_.get("quoted_message_id") is None
    assert outbound.metadata_.get("reply_to_message_id") is None

    frozen_false = service.prepare_send_message(
        SendMessageInput(body="ложный", conversation_object_id=inbound.id)
    )
    fake.send_message_response = _graph_reply_with_quote(
        message_id="out-false-quote",
        chat_id=CHAT_ONE,
        body="ложный",
        created="2026-09-13T14:02:00Z",
        from_id=TEAMS_USER_ID,
        quoted_message_id=SOURCE_MESSAGE_ID,
        reply_to_id=None,
    )
    with pytest.raises(ToolError, match="confirm"):
        service.send_message(frozen_false)
    assert len(fake.send_message_calls) == 2
    replay_calls = len(fake.send_message_calls)
    with pytest.raises(ToolError, match="confirm"):
        service.send_message(frozen_false)
    assert len(fake.send_message_calls) == replay_calls
