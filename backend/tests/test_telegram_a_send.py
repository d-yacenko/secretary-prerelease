"""Telegram A — send_message prepare/execute, races, legacy Mattermost canonical."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.connectors.mattermost.constants import MAX_MESSAGE_BODY_CHARS
from app.connectors.telegram.constants import MAX_TELEGRAM_MESSAGE_BODY_CHARS
from app.connectors.telegram.errors import TelegramWriteDefiniteError, TelegramWriteUncertainError
from app.connectors.telegram.normalize import build_external_id
from app.connectors.telegram.transport import FakeTelegramTransport, TelegramHttpTransport
from app.db.models import ExternalActionAttempt, Job, Object, TelegramAccount, User
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
from app.services.communication_external_action_service import (
    ATTEMPT_FAILED_DEFINITE,
    ATTEMPT_SUCCEEDED,
    ATTEMPT_UNCERTAIN,
    CommunicationExternalActionService,
)
from app.tools.registry import TOOL_REGISTRY
from app.tools.schemas import SendMessageCanonicalInput, SendMessageInput, ToolError

from tests.test_unified_communications_a import (
    ALLOWED_URL,
    _anchor_object,
    _connect_account,
    _execute_service,
)


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def mattermost_settings(monkeypatch: pytest.MonkeyPatch, credential_key: str) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    monkeypatch.setattr("app.core.config.settings.mattermost_allowed_base_urls", ALLOWED_URL)

BOT_TOKEN = "test-bot-token"
BOT_USERNAME = "secretary_bot"
BUSINESS_CONNECTION_ID = "bc-1"
CHAT_ID = "6000000000"
MESSAGE_ID = "10"
TELEGRAM_USER_ID = 5_000_000_000


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


@pytest.fixture
def telegram_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.settings.telegram_bot_token", BOT_TOKEN)
    monkeypatch.setattr("app.core.config.settings.telegram_bot_username", BOT_USERNAME)
    monkeypatch.setattr("app.core.config.settings.telegram_webhook_secret", "webhook-secret")
    monkeypatch.setattr(
        "app.core.config.settings.telegram_webhook_url",
        "https://example.test/integrations/telegram/webhook",
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _service(session, user_id, fake: FakeTelegramTransport | None = None):
    return CommunicationExternalActionService(
        session,
        user_id,
        telegram_transport=fake,
        attempt_session_factory=lambda: _SessionProxy(session),
    )


def _tg_account(
    session,
    user_id,
    *,
    enabled: bool = True,
    can_reply: bool = True,
    business_connection_id: str = BUSINESS_CONNECTION_ID,
    telegram_user_id: int = TELEGRAM_USER_ID,
) -> TelegramAccount:
    account = TelegramAccount(
        user_id=user_id,
        telegram_user_id=telegram_user_id,
        user_chat_id=telegram_user_id,
        telegram_username="alice",
        display_name="Alice",
        business_connection_id=business_connection_id,
        business_user_chat_id=telegram_user_id,
        business_rights={"can_reply": can_reply},
        business_connection_enabled=enabled,
        business_connected_at=_utcnow() if enabled else None,
    )
    session.add(account)
    session.flush()
    return account


def _tg_object(
    session,
    user_id,
    account: TelegramAccount,
    *,
    message_id: str = MESSAGE_ID,
    chat_id: str = CHAT_ID,
    direction: str = "inbound",
    occurred_at: datetime | None = None,
    extra_meta: dict | None = None,
    external_id: str | None = None,
    body: str = "hello",
) -> Object:
    connection_id = account.business_connection_id or BUSINESS_CONNECTION_ID
    meta = {
        "account_id": str(account.id),
        "business_connection_id": connection_id,
        "business_user_id": str(account.telegram_user_id),
        "chat_id": chat_id,
        "message_id": message_id,
        "from_user_id": chat_id if direction == "inbound" else str(account.telegram_user_id),
        "from_username": "ivan",
        "from_display_name": "Ivan",
        "chat_username": "ivan",
        "chat_display_name": "Ivan",
        "direction": direction,
        "reply_to_message_id": None,
        "sender_business_bot_id": None,
        "message_type": "text",
    }
    if extra_meta:
        meta.update(extra_meta)
    obj = Object(
        user_id=user_id,
        kind="chat_message",
        provider="telegram",
        external_id=external_id or build_external_id(connection_id, chat_id, message_id),
        origin="source",
        state="observed",
        title="Ivan: hello",
        body=body,
        metadata_=meta,
        occurred_at=occurred_at or _utcnow(),
    )
    session.add(obj)
    session.flush()
    return obj


def _success_message(route, *, reply: bool, text: str, bot: bool = False) -> dict:
    payload = {
        "message_id": 9001,
        "business_connection_id": route.business_connection_id,
        "chat": {"id": int(route.chat_id), "type": "private", "first_name": "Ivan"},
        "text": text,
        "date": 1_700_000_000,
        "from": {"id": TELEGRAM_USER_ID, "username": "alice", "first_name": "Alice"},
    }
    if bot:
        payload["sender_business_bot"] = {"id": 1000, "username": BOT_USERNAME}
    if reply:
        payload["reply_to_message"] = {"message_id": int(route.reply_to_message_id)}
    return payload


def test_telegram_not_registered_as_separate_tool() -> None:
    assert "telegram" not in TOOL_REGISTRY
    with pytest.raises(KeyError):
        TOOL_REGISTRY["send_telegram"]


def test_prepare_telegram_compose_and_reply_freeze_route(db_session, telegram_settings) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)
    composed = service.prepare_send_message(
        SendMessageInput(body="новое сообщение", conversation_object_id=inbound.id)
    )
    assert composed.provider == "telegram"
    assert composed.mode == "compose"
    assert composed.telegram_route.chat_id == CHAT_ID
    assert composed.telegram_route.business_connection_id == BUSINESS_CONNECTION_ID
    assert composed.telegram_route.reply_to_message_id is None
    assert composed.telegram_route.chat_display_name == "Ivan"
    dumped = composed.model_dump(mode="json")
    assert "route" in dumped
    assert BOT_TOKEN not in json.dumps(dumped)
    replied = service.prepare_send_message(
        SendMessageInput(body="ответ", reply_to_object_id=inbound.id)
    )
    assert replied.mode == "reply"
    assert replied.telegram_route.reply_to_message_id == MESSAGE_ID
    assert fake.send_message_calls == []


def test_prepare_telegram_fail_closed_cases(db_session, telegram_settings) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)

    account.business_connection_enabled = False
    db_session.flush()
    with pytest.raises(ToolError, match="business connection"):
        service.prepare_send_message(SendMessageInput(body="hi", conversation_object_id=inbound.id))
    account.business_connection_enabled = True
    account.business_rights = {"can_reply": False}
    db_session.flush()
    with pytest.raises(ToolError, match="reply permission"):
        service.prepare_send_message(SendMessageInput(body="hi", conversation_object_id=inbound.id))
    account.business_rights = {"can_reply": True}
    inbound.metadata_ = {**inbound.metadata_, "business_connection_id": "other"}
    flag_modified(inbound, "metadata_")
    db_session.flush()
    with pytest.raises(ToolError, match="business connection"):
        service.prepare_send_message(SendMessageInput(body="hi", conversation_object_id=inbound.id))
    inbound.metadata_ = {**inbound.metadata_, "business_connection_id": BUSINESS_CONNECTION_ID}
    inbound.external_id = "mismatch"
    flag_modified(inbound, "metadata_")
    db_session.flush()
    with pytest.raises(ToolError, match="external_id"):
        service.prepare_send_message(SendMessageInput(body="hi", conversation_object_id=inbound.id))
    inbound.external_id = build_external_id(BUSINESS_CONNECTION_ID, CHAT_ID, MESSAGE_ID)
    inbound.metadata_ = {**inbound.metadata_, "chat_id": "not-a-number"}
    flag_modified(inbound, "metadata_")
    db_session.flush()
    with pytest.raises(ToolError, match="provider IDs"):
        service.prepare_send_message(SendMessageInput(body="hi", conversation_object_id=inbound.id))
    assert fake.send_message_calls == []


def test_prepare_rejects_stale_inbound_and_oversize_telegram_body(
    db_session, telegram_settings
) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    old = _tg_object(
        db_session,
        user.id,
        account,
        occurred_at=_utcnow() - timedelta(hours=25),
    )
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)
    with pytest.raises(ToolError, match="eligible"):
        service.prepare_send_message(SendMessageInput(body="hi", conversation_object_id=old.id))
    _tg_object(db_session, user.id, account, message_id="11")
    with pytest.raises(ToolError, match="Telegram maximum"):
        service.prepare_send_message(
            SendMessageInput(
                body="x" * (MAX_TELEGRAM_MESSAGE_BODY_CHARS + 1),
                conversation_object_id=old.id,
            )
        )
    assert fake.send_message_calls == []


def test_mattermost_body_between_4096_and_8000_still_valid(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="mm")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account)
    body = "y" * (MAX_TELEGRAM_MESSAGE_BODY_CHARS + 10)
    assert len(body) <= MAX_MESSAGE_BODY_CHARS
    frozen = CommunicationExternalActionService(
        db_session,
        user.id,
        attempt_session_factory=lambda: _SessionProxy(db_session),
    ).prepare_send_message(
        SendMessageInput(body=body, conversation_object_id=anchor.id)
    )
    assert frozen.provider == "mattermost"
    assert len(frozen.body) == MAX_TELEGRAM_MESSAGE_BODY_CHARS + 10


def test_telegram_http_compose_and_reply_payloads(telegram_settings) -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "url": str(request.url),
                "body": json.loads(request.content),
            }
        )
        body = json.loads(request.content)
        result = {
            "message_id": 1,
            "business_connection_id": body["business_connection_id"],
            "chat": {"id": body["chat_id"], "type": "private"},
            "text": body["text"],
        }
        if "reply_parameters" in body:
            result["reply_to_message"] = {"message_id": body["reply_parameters"]["message_id"]}
        return httpx.Response(200, json={"ok": True, "result": result})

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    transport = TelegramHttpTransport(BOT_TOKEN, http_client=client)
    compose = transport.send_message(
        business_connection_id=BUSINESS_CONNECTION_ID,
        chat_id=CHAT_ID,
        text="hello",
    )
    assert captured[0]["url"].startswith("https://api.telegram.org/bot")
    assert captured[0]["url"].endswith("/sendMessage")
    assert captured[0]["body"] == {
        "business_connection_id": BUSINESS_CONNECTION_ID,
        "chat_id": int(CHAT_ID),
        "text": "hello",
    }
    assert "reply_parameters" not in captured[0]["body"]
    assert compose["message_id"] == 1
    reply = transport.send_message(
        business_connection_id=BUSINESS_CONNECTION_ID,
        chat_id=CHAT_ID,
        text="reply",
        reply_to_message_id=MESSAGE_ID,
    )
    assert captured[1]["body"]["reply_parameters"] == {"message_id": 10}
    assert reply["reply_to_message"]["message_id"] == 10


def test_send_success_materializes_and_is_idempotent(db_session, telegram_settings) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="новое", conversation_object_id=inbound.id)
    )
    fake.send_message_response = _success_message(frozen.telegram_route, reply=False, text="новое")
    first = service.send_message(frozen)
    assert first.delivery_status == "sent"
    assert first.provider == "telegram"
    assert first.changed is True
    assert first.provider_message_id == "9001"
    second = service.send_message(frozen)
    assert second.delivery_status == "already_sent"
    assert len(fake.send_message_calls) == 1
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt is not None
    assert attempt.tool_name == "send_message"
    assert attempt.state == ATTEMPT_SUCCEEDED
    created = db_session.scalar(
        select(Object).where(Object.external_id == build_external_id(BUSINESS_CONNECTION_ID, CHAT_ID, "9001"))
    )
    assert created is not None
    assert created.metadata_["direction"] == "outbound"


def test_send_reply_uses_exact_reply_parameters(db_session, telegram_settings) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="ответ", reply_to_object_id=inbound.id)
    )
    fake.send_message_response = _success_message(frozen.telegram_route, reply=True, text="ответ")
    service.send_message(frozen)
    assert fake.send_message_calls == [
        {
            "business_connection_id": BUSINESS_CONNECTION_ID,
            "chat_id": CHAT_ID,
            "text": "ответ",
            "reply_parameters": {"message_id": MESSAGE_ID},
        }
    ]


@pytest.mark.parametrize(
    "error,state",
    [
        (TelegramWriteDefiniteError("rejected"), ATTEMPT_FAILED_DEFINITE),
        (TelegramWriteUncertainError("timeout"), ATTEMPT_UNCERTAIN),
        (TelegramWriteUncertainError("5xx"), ATTEMPT_UNCERTAIN),
    ],
)
def test_send_failures_do_not_retry(db_session, telegram_settings, error, state) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=inbound.id)
    )
    fake.send_message_error = error
    with pytest.raises(ToolError):
        service.send_message(frozen)
    fake.send_message_error = None
    with pytest.raises(ToolError):
        service.send_message(frozen)
    assert len(fake.send_message_calls) == 1
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt is not None
    assert attempt.state == state


def test_success_validation_mismatches_are_uncertain(db_session, telegram_settings) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)

    def run(mutator, *, reply: bool = False) -> None:
        frozen = service.prepare_send_message(
            SendMessageInput(
                body="check",
                reply_to_object_id=inbound.id if reply else None,
                conversation_object_id=None if reply else inbound.id,
            )
        )
        created = _success_message(frozen.telegram_route, reply=reply, text="check", bot=True)
        mutator(created, frozen)
        fake.send_message_calls.clear()
        fake.send_message_response = created
        with pytest.raises(ToolError, match="confirm"):
            service.send_message(frozen)
        assert len(fake.send_message_calls) == 1
        with pytest.raises(ToolError):
            service.send_message(frozen)
        assert len(fake.send_message_calls) == 1

    run(lambda created, frozen: created.__setitem__("business_connection_id", "wrong"))
    run(lambda created, frozen: created["chat"].__setitem__("id", 1))
    run(lambda created, frozen: created.__setitem__("text", "changed"))
    run(lambda created, frozen: created["sender_business_bot"].__setitem__("username", "other_bot"))
    run(lambda created, frozen: created.__setitem__("reply_to_message", {"message_id": 99}))
    run(
        lambda created, frozen: created.pop("reply_to_message", None),
        reply=True,
    )
    run(
        lambda created, frozen: created["reply_to_message"].__setitem__("message_id", 99),
        reply=True,
    )


def test_exact_reply_target_succeeds(db_session, telegram_settings) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="ok", reply_to_object_id=inbound.id)
    )
    fake.send_message_response = _success_message(frozen.telegram_route, reply=True, text="ok")
    result = service.send_message(frozen)
    assert result.delivery_status == "sent"


def test_send_materialization_races_with_webhook(db_session, telegram_settings) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="гонка", conversation_object_id=inbound.id)
    )
    created = _success_message(frozen.telegram_route, reply=False, text="гонка")
    fake.send_message_response = created
    first = service.send_message(frozen)
    jobs_before = list(db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)))
    service._telegram_materializer.upsert_business_message(
        user_id=user.id,
        account_id=account.id,
        business_connection_id=BUSINESS_CONNECTION_ID,
        business_user_id=str(TELEGRAM_USER_ID),
        message=created,
        skip_hidden=False,
    )
    jobs_after = list(db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)))
    objects = list(
        db_session.scalars(
            select(Object).where(
                Object.external_id == build_external_id(BUSINESS_CONNECTION_ID, CHAT_ID, "9001")
            )
        )
    )
    assert len(objects) == 1
    assert objects[0].id == first.object_id
    assert len(jobs_after) == len(jobs_before)

    inbound2 = _tg_object(db_session, user.id, account, message_id="12")
    frozen2 = service.prepare_send_message(
        SendMessageInput(body="вторая гонка", conversation_object_id=inbound2.id)
    )
    created2 = _success_message(frozen2.telegram_route, reply=False, text="вторая гонка")
    created2["message_id"] = 9002
    service._telegram_materializer.upsert_business_message(
        user_id=user.id,
        account_id=account.id,
        business_connection_id=BUSINESS_CONNECTION_ID,
        business_user_id=str(TELEGRAM_USER_ID),
        message=created2,
        skip_hidden=False,
    )
    jobs_mid = list(db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)))
    fake.send_message_response = created2
    result = service.send_message(frozen2)
    jobs_end = list(db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)))
    assert result.object_id is not None
    assert len(jobs_end) == len(jobs_mid)


def test_succeeded_telegram_replay_ignores_expired_inbound(db_session, telegram_settings) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="новое", conversation_object_id=inbound.id)
    )
    fake.send_message_response = _success_message(frozen.telegram_route, reply=False, text="новое")
    first = service.send_message(frozen)
    assert first.delivery_status == "sent"
    inbound.occurred_at = _utcnow() - timedelta(hours=25)
    db_session.flush()
    second = service.send_message(frozen)
    assert second.delivery_status == "already_sent"
    assert len(fake.send_message_calls) == 1
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt is not None
    assert attempt.state == ATTEMPT_SUCCEEDED


def test_succeeded_telegram_replay_ignores_disabled_connection(db_session, telegram_settings) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="новое", conversation_object_id=inbound.id)
    )
    fake.send_message_response = _success_message(frozen.telegram_route, reply=False, text="новое")
    first = service.send_message(frozen)
    assert first.delivery_status == "sent"
    account.business_connection_enabled = False
    db_session.flush()
    second = service.send_message(frozen)
    assert second.delivery_status == "already_sent"
    assert len(fake.send_message_calls) == 1
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt is not None
    assert attempt.state == ATTEMPT_SUCCEEDED


def test_uncertain_telegram_replay_ignores_later_ineligibility(db_session, telegram_settings) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=inbound.id)
    )
    fake.send_message_error = TelegramWriteUncertainError("timeout")
    with pytest.raises(ToolError, match="confirm"):
        service.send_message(frozen)
    inbound.occurred_at = _utcnow() - timedelta(hours=25)
    account.business_connection_enabled = False
    db_session.flush()
    fake.send_message_error = None
    with pytest.raises(ToolError, match="confirm"):
        service.send_message(frozen)
    assert len(fake.send_message_calls) == 1
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt is not None
    assert attempt.state == ATTEMPT_UNCERTAIN


def test_failed_definite_telegram_replay_ignores_later_ineligibility(
    db_session, telegram_settings
) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=inbound.id)
    )
    fake.send_message_error = TelegramWriteDefiniteError("rejected")
    with pytest.raises(ToolError, match="rejected"):
        service.send_message(frozen)
    inbound.occurred_at = _utcnow() - timedelta(hours=25)
    account.business_rights = {"can_reply": False}
    flag_modified(account, "business_rights")
    db_session.flush()
    fake.send_message_error = None
    with pytest.raises(ToolError, match="previously failed"):
        service.send_message(frozen)
    assert len(fake.send_message_calls) == 1
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt is not None
    assert attempt.state == ATTEMPT_FAILED_DEFINITE


def test_first_execution_after_prepare_fails_definite_when_inbound_expires(
    db_session, telegram_settings
) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=inbound.id)
    )
    inbound.occurred_at = _utcnow() - timedelta(hours=25)
    db_session.flush()
    with pytest.raises(ToolError, match="eligible"):
        service.send_message(frozen)
    assert fake.send_message_calls == []
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt is not None
    assert attempt.state == ATTEMPT_FAILED_DEFINITE


def test_first_execution_after_prepare_fails_definite_when_can_reply_revoked(
    db_session, telegram_settings
) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=inbound.id)
    )
    account.business_rights = {"can_reply": False}
    flag_modified(account, "business_rights")
    db_session.flush()
    with pytest.raises(ToolError, match="reply permission"):
        service.send_message(frozen)
    assert fake.send_message_calls == []
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt is not None
    assert attempt.state == ATTEMPT_FAILED_DEFINITE


def test_first_execution_after_prepare_fails_definite_when_connection_disabled(
    db_session, telegram_settings
) -> None:
    user = User(id=uuid4(), display_name="tg")
    db_session.add(user)
    db_session.flush()
    account = _tg_account(db_session, user.id)
    inbound = _tg_object(db_session, user.id, account)
    fake = FakeTelegramTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=inbound.id)
    )
    account.business_connection_enabled = False
    db_session.flush()
    with pytest.raises(ToolError, match="business connection"):
        service.send_message(frozen)
    assert fake.send_message_calls == []
    attempt = db_session.scalar(select(ExternalActionAttempt))
    assert attempt is not None
    assert attempt.state == ATTEMPT_FAILED_DEFINITE


def test_legacy_flat_mattermost_canonical_from_production_shape_still_executes(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="legacy")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account)
    from app.connectors.mattermost.transport import FakeMattermostTransport

    fake = FakeMattermostTransport()
    service = _execute_service(db_session, user.id, fake)
    prepared = service.prepare_send_message(
        SendMessageInput(body="legacy body", conversation_object_id=anchor.id)
    )
    # Production acf035a... persisted the flat Mattermost canonical shape.
    legacy = {
        "provider": "mattermost",
        "mode": prepared.mode,
        "account_id": str(prepared.account_id),
        "server_url": prepared.server_url,
        "channel_id": prepared.channel_id,
        "channel_type": prepared.channel_type,
        "channel_name": prepared.channel_name,
        "channel_display_name": prepared.channel_display_name,
        "anchor_object_id": str(prepared.anchor_object_id),
        "source_post_id": prepared.source_post_id,
        "root_id": prepared.root_id,
        "body": prepared.body,
        "operation_id": prepared.operation_id,
        "pending_post_id": prepared.pending_post_id,
    }
    parsed = SendMessageCanonicalInput.model_validate(legacy)
    assert parsed.provider == "mattermost"
    assert isinstance(parsed.route, type(prepared.route))
    result = service.send_message(parsed)
    assert result.delivery_status == "sent"
    assert len(fake.create_post_calls) == 1
    assert "route" not in legacy
