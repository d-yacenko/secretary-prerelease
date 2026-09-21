"""Stage A Bot API behavioral isolation tests (DB/provider independent)."""

import asyncio
from uuid import uuid4

from fastapi import HTTPException
from pytest import MonkeyPatch, raises

from app.api.telegram import create_telegram_link, telegram_webhook
from app.services.communication_external_action_service import CommunicationExternalActionService
from app.services.connection_status_service import ConnectionStatusService
from app.tools.schemas import (
    SendMessageCanonicalInput,
    TelegramMtprotoSendRoute,
    TelegramSendRoute,
    ToolError,
)


def test_legacy_link_is_gone_without_auth_or_db():
    with raises(HTTPException) as error:
        create_telegram_link()
    assert error.value.status_code == 410
    assert "retired" in error.value.detail.lower()


def test_legacy_webhook_is_gone_without_dispatch(monkeypatch: MonkeyPatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("retired webhook must not dispatch")

    monkeypatch.setattr("app.api.telegram.TelegramWebhookService", fail, raising=False)
    with raises(HTTPException) as error:
        asyncio.run(telegram_webhook())
    assert error.value.status_code == 410
    assert "retired" in error.value.detail.lower()


def test_connection_status_is_explicitly_inactive():
    status = ConnectionStatusService(object(), uuid4())._telegram_status()
    assert status.configured is False
    assert status.identity_linked is False
    assert status.business_connected is False
    assert status.can_reply is False


def test_bot_anchor_cannot_prepare_or_send_and_never_opens_transport():
    service = CommunicationExternalActionService.__new__(CommunicationExternalActionService)
    anchor = type("Anchor", (), {"provider": "telegram", "id": uuid4()})()
    with raises(ToolError, match="retired"):
        service._prepare_telegram(None, anchor, "reply")
    payload = SendMessageCanonicalInput(
        provider="telegram",
        mode="reply",
        anchor_object_id=anchor.id,
        body="reply",
        operation_id="retired-bot-operation",
        route=TelegramSendRoute(
            account_id=uuid4(),
            business_connection_id="legacy",
            business_user_id="legacy-user",
            chat_id="1",
            source_message_id="1",
            reply_to_message_id="1",
        ),
    )
    service._telegram_mtproto_transport = None
    with raises(ToolError, match="retired"):
        service._send_telegram(payload)


def test_mtproto_send_route_remains_on_mtproto_path(monkeypatch: MonkeyPatch):
    service = CommunicationExternalActionService.__new__(CommunicationExternalActionService)
    expected = object()
    monkeypatch.setattr(service, "_send_telegram_mtproto", lambda payload: expected)
    payload = SendMessageCanonicalInput(
        provider="telegram",
        mode="compose",
        anchor_object_id=uuid4(),
        body="reply",
        operation_id="mtproto-operation",
        route=TelegramMtprotoSendRoute(account_id=uuid4(), peer_id=42),
    )
    assert service._send_telegram(payload) is expected
