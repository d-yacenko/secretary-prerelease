"""Stage C Bot API cleanup: legacy surfaces are gone, history and MTProto stay safe."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.main import app
from app.services.communication_external_action_service import CommunicationExternalActionService
from app.tools.schemas import (
    SendMessageCanonicalInput,
    TelegramMtprotoSendRoute,
    TelegramSendRoute,
    ToolError,
)

ROOT = Path(__file__).parents[1]


def test_legacy_bot_routes_are_not_registered():
    routes = {route.path for route in app.routes}
    assert "/telegram/link" not in routes
    assert "/integrations/telegram/webhook" not in routes


def test_active_code_has_no_bot_transport_or_webhook_runtime():
    app_root = ROOT / "app"
    source = "\n".join(path.read_text() for path in app_root.rglob("*.py"))
    assert "TelegramHttpTransport" not in source
    assert "telegram_bot_token" not in source
    assert "telegram_webhook_secret" not in source
    assert "setWebhook" not in source


def test_historical_bot_anchor_fails_closed_without_mtproto_reroute():
    service = CommunicationExternalActionService.__new__(CommunicationExternalActionService)
    anchor = type("Anchor", (), {"provider": "telegram", "id": uuid4()})()
    with pytest.raises(ToolError, match="retired"):
        service._prepare_telegram(None, anchor, "reply")
    payload = SendMessageCanonicalInput(
        provider="telegram",
        mode="reply",
        anchor_object_id=anchor.id,
        body="reply",
        operation_id="legacy-bot-operation",
        route=TelegramSendRoute(
            account_id=uuid4(),
            business_connection_id="legacy",
            business_user_id="legacy-user",
            chat_id="1",
            source_message_id="1",
            reply_to_message_id="1",
        ),
    )
    with pytest.raises(ToolError, match="retired"):
        service._send_telegram(payload)


def test_mtproto_send_dispatch_remains_intact(monkeypatch):
    service = CommunicationExternalActionService.__new__(CommunicationExternalActionService)
    expected = object()
    monkeypatch.setattr(service, "_send_telegram_mtproto", lambda payload: expected)
    payload = SendMessageCanonicalInput(
        provider="telegram",
        mode="compose",
        anchor_object_id=uuid4(),
        body="message",
        operation_id="mtproto-operation",
        route=TelegramMtprotoSendRoute(account_id=uuid4(), peer_id=42),
    )
    assert service._send_telegram(payload) is expected


def test_active_config_keeps_mtproto_and_removes_bot_fields():
    config = (ROOT / "app/core/config.py").read_text()
    compose = (ROOT.parent / "infra/compose.yaml").read_text()
    example = (ROOT.parent / ".env.example").read_text()
    for text in (config, compose, example):
        assert "TELEGRAM_BOT_TOKEN" not in text
        assert "TELEGRAM_BOT_USERNAME" not in text
        assert "TELEGRAM_WEBHOOK_SECRET" not in text
        assert "TELEGRAM_WEBHOOK_URL" not in text
    assert "telegram_api_id" in config
    assert "TELEGRAM_API_ID" in compose
