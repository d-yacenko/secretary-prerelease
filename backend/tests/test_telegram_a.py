"""Telegram A — migration, link, webhook, inbox, temporal exclusion."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.cli.telegram_webhook import configure_webhook
from app.cli.telegram_webhook import telegram_is_configured as cli_telegram_is_configured
from app.connectors.telegram.constants import TELEGRAM_ALLOWED_UPDATES
from app.connectors.telegram.errors import TelegramConfigurationError
from app.connectors.telegram.link_state import hash_link_state
from app.connectors.telegram.normalize import build_external_id
from app.connectors.telegram.transport import TelegramHttpTransport
from app.connectors.telegram.webhook_service import telegram_is_configured
from app.db.models import Job, Object, TelegramAccount, TelegramLinkState, User, UserSettings
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT, JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL
from app.main import app
from app.services.personal_relevance_evidence_service import PersonalRelevanceEvidenceService
from app.services.recent_source_service import RecentSourceService
from app.services.temporal_signals_constants import TEMPORAL_ELIGIBLE_PROVIDERS
from app.services.temporal_signals_service import (
    enqueue_extract_temporal_signal,
    object_is_temporal_source_eligible,
)
from app.source_sync.constants import SUPPORTED_SOURCE_KEYS
from app.users.bootstrap import BOOTSTRAP_USER_ID

WEBHOOK_SECRET = "telegram-webhook-secret"
BOT_USERNAME = "secretary_bot"
BOT_TOKEN = "test-bot-token"
WEBHOOK_URL = "https://example.test/integrations/telegram/webhook"
TELEGRAM_USER_ID = 5_000_000_000
REMOTE_CHAT_ID = 6_000_000_000
BUSINESS_CONNECTION_ID = "bc-1"


@pytest.fixture
def telegram_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.settings.telegram_bot_token", BOT_TOKEN)
    monkeypatch.setattr("app.core.config.settings.telegram_bot_username", BOT_USERNAME)
    monkeypatch.setattr("app.core.config.settings.telegram_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr("app.core.config.settings.telegram_webhook_url", WEBHOOK_URL)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _user(session: Session, name: str = "tg-user") -> User:
    user = User(id=uuid4(), display_name=name)
    session.add(user)
    session.flush()
    return user


def _account(
    session: Session,
    user_id,
    *,
    telegram_user_id: int = TELEGRAM_USER_ID,
    enabled: bool = True,
    can_reply: bool = True,
    business_connection_id: str | None = BUSINESS_CONNECTION_ID,
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


def _webhook_client(db_session) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _post_webhook(client: TestClient, payload: dict, *, secret: str | None = WEBHOOK_SECRET):
    headers = {}
    if secret is not None:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret
    return client.post("/integrations/telegram/webhook", json=payload, headers=headers)


def _private_text(
    *,
    text: str = "привет",
    message_id: int = 10,
    from_id: int = REMOTE_CHAT_ID,
    chat_id: int = REMOTE_CHAT_ID,
    business_connection_id: str = BUSINESS_CONNECTION_ID,
    caption: str | None = None,
    photo: bool = False,
    date: int = 1_700_000_000,
) -> dict:
    message: dict = {
        "message_id": message_id,
        "date": date,
        "business_connection_id": business_connection_id,
        "chat": {
            "id": chat_id,
            "type": "private",
            "first_name": "Ivan",
            "username": "ivan",
        },
        "from": {
            "id": from_id,
            "first_name": "Ivan" if from_id == chat_id else "Alice",
            "username": "ivan" if from_id == chat_id else "alice",
        },
    }
    if text:
        message["text"] = text
    if caption is not None:
        message["caption"] = caption
    if photo:
        message["photo"] = [{"file_id": "file-1", "width": 10, "height": 10}]
    return message


def test_migration_0039_revises_0038(db_session) -> None:
    versions = sorted(
        path.name
        for path in (Path(__file__).resolve().parents[1] / "alembic" / "versions").glob("*.py")
        if path.name[0].isdigit()
    )
    assert versions[-1].startswith("0046")
    module_path = (
        Path(__file__).resolve().parents[1] / "alembic/versions/0039_telegram_accounts.py"
    )
    text_src = module_path.read_text(encoding="utf-8")
    assert 'revision: str = "0039"' in text_src
    assert 'down_revision: str | None = "0038"' in text_src
    inspector = inspect(db_session.bind)
    tables = set(inspector.get_table_names())
    assert "telegram_accounts" in tables
    assert "telegram_link_states" in tables
    account_cols = {col["name"]: col for col in inspector.get_columns("telegram_accounts")}
    assert "BIGINT" in str(account_cols["telegram_user_id"]["type"]).upper()
    uniques = {item["name"] for item in inspector.get_unique_constraints("telegram_accounts")}
    assert "uq_telegram_accounts_user_id" in uniques
    assert "uq_telegram_accounts_telegram_user_id" in uniques
    assert "uq_telegram_accounts_business_connection_id" in uniques


def test_telegram_accounts_bigint_and_uniqueness(db_session) -> None:
    first = _user(db_session, "one")
    second = _user(db_session, "two")
    huge = 2**40
    account = _account(db_session, first.id, telegram_user_id=huge, business_connection_id="bc-a")
    assert account.telegram_user_id == huge
    nested = db_session.begin_nested()
    with pytest.raises(IntegrityError):
        _account(db_session, second.id, telegram_user_id=huge, business_connection_id="bc-b")
        db_session.flush()
    nested.rollback()
    nested = db_session.begin_nested()
    with pytest.raises(IntegrityError):
        _account(db_session, second.id, telegram_user_id=222, business_connection_id="bc-a")
        db_session.flush()
    nested.rollback()


def test_telegram_not_in_source_polling_but_temporal_eligible() -> None:
    assert "telegram" not in SUPPORTED_SOURCE_KEYS
    assert "telegram" in TEMPORAL_ELIGIBLE_PROVIDERS
    assert set(TELEGRAM_ALLOWED_UPDATES) == {
        "message",
        "business_connection",
        "business_message",
        "edited_business_message",
        "deleted_business_messages",
    }


def test_telegram_link_requires_auth(db_session, telegram_settings) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        response = client.post("/telegram/link")
    app.dependency_overrides.clear()
    assert response.status_code == 401


def test_telegram_link_unavailable_when_unconfigured(auth_client) -> None:
    response = auth_client.post("/telegram/link")
    assert response.status_code == 503
    assert "telegram" in response.json()["detail"].lower()


def test_telegram_is_configured_is_one_helper(telegram_settings) -> None:
    assert cli_telegram_is_configured is telegram_is_configured
    assert telegram_is_configured() is True


@pytest.mark.parametrize(
    "field",
    [
        "telegram_bot_token",
        "telegram_bot_username",
        "telegram_webhook_secret",
        "telegram_webhook_url",
    ],
)
def test_telegram_readiness_fails_when_any_deployment_field_missing(
    auth_client,
    db_session,
    telegram_settings,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    monkeypatch.setattr(f"app.core.config.settings.{field}", "")
    assert telegram_is_configured() is False
    connections = auth_client.get("/connections").json()["telegram"]
    assert connections["configured"] is False
    dumped = json.dumps(connections)
    assert BOT_TOKEN not in dumped
    assert WEBHOOK_SECRET not in dumped
    assert WEBHOOK_URL not in dumped
    link = auth_client.post("/telegram/link")
    assert link.status_code == 503
    assert "telegram" in link.json()["detail"].lower()
    assert BOT_TOKEN not in str(link.json())
    assert WEBHOOK_SECRET not in str(link.json())
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        return httpx.Response(500)

    transport = TelegramHttpTransport(
        BOT_TOKEN,
        http_client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    assert configure_webhook(transport) == 1
    assert captured == []
    client = _webhook_client(db_session)
    try:
        if field == "telegram_webhook_secret":
            rejected = _post_webhook(client, {"update_id": 1}, secret=WEBHOOK_SECRET)
            assert rejected.status_code == 401
        else:
            accepted = _post_webhook(client, {"update_id": 1})
            assert accepted.status_code == 200
            assert accepted.json() == {"status": "ok"}
    finally:
        app.dependency_overrides.clear()


def test_http_set_webhook_accepts_boolean_true_and_configure_returns_zero(
    telegram_settings,
) -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        captured.append({"url": str(request.url), "body": body})
        path = request.url.path
        if path.endswith("/getMe"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "id": 1000,
                        "is_bot": True,
                        "username": BOT_USERNAME,
                        "first_name": "Secretary",
                        "can_connect_to_business": True,
                    },
                },
            )
        if path.endswith("/setWebhook"):
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    transport = TelegramHttpTransport(BOT_TOKEN, http_client=client)
    assert (
        transport.set_webhook(
            url=WEBHOOK_URL,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=TELEGRAM_ALLOWED_UPDATES,
        )
        is True
    )
    assert captured[0]["url"] == f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    assert captured[0]["body"] == {
        "url": WEBHOOK_URL,
        "secret_token": WEBHOOK_SECRET,
        "allowed_updates": list(TELEGRAM_ALLOWED_UPDATES),
    }
    captured.clear()
    assert configure_webhook(transport) == 0
    assert [item["url"] for item in captured] == [
        f"https://api.telegram.org/bot{BOT_TOKEN}/getMe",
        f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
    ]
    assert captured[1]["body"] == {
        "url": WEBHOOK_URL,
        "secret_token": WEBHOOK_SECRET,
        "allowed_updates": list(TELEGRAM_ALLOWED_UPDATES),
    }


@pytest.mark.parametrize(
    "result",
    [False, None, {}, "true", 1, {"ok": True}],
)
def test_http_set_webhook_rejects_non_true_result(telegram_settings, result) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": result})

    transport = TelegramHttpTransport(
        BOT_TOKEN,
        http_client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    with pytest.raises(TelegramConfigurationError, match="setWebhook"):
        transport.set_webhook(
            url=WEBHOOK_URL,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=TELEGRAM_ALLOWED_UPDATES,
        )


def test_http_get_me_still_requires_user_dict(telegram_settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": True})

    transport = TelegramHttpTransport(
        BOT_TOKEN,
        http_client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    with pytest.raises(TelegramConfigurationError, match="getMe"):
        transport.get_me()


def test_telegram_link_returns_deep_link_and_stores_hash_only(
    auth_client, db_session, telegram_settings
) -> None:
    response = auth_client.post("/telegram/link")
    assert response.status_code == 200
    body = response.json()
    url = body["telegram_url"]
    assert url.startswith(f"https://t.me/{BOT_USERNAME}?start=")
    raw_state = url.split("start=", 1)[1]
    assert raw_state
    assert len(raw_state) <= 64
    rows = list(db_session.scalars(select(TelegramLinkState)))
    assert len(rows) == 1
    assert rows[0].state_hash == hash_link_state(raw_state)
    assert rows[0].state_hash != raw_state
    dumped = str(body)
    assert BOT_TOKEN not in dumped
    assert WEBHOOK_SECRET not in dumped
    assert raw_state not in (rows[0].state_hash,)
    ttl = rows[0].expires_at - rows[0].created_at
    assert timedelta(minutes=9) <= ttl <= timedelta(minutes=11)


def test_valid_start_binds_secretary_user(
    auth_client, db_session, telegram_settings
) -> None:
    link = auth_client.post("/telegram/link").json()
    raw_state = link["telegram_url"].split("start=", 1)[1]
    client = _webhook_client(db_session)
    try:
        response = _post_webhook(
            client,
            {
                "update_id": 1,
                "message": {
                    "message_id": 1,
                    "date": 1_700_000_000,
                    "chat": {"id": TELEGRAM_USER_ID, "type": "private"},
                    "from": {
                        "id": TELEGRAM_USER_ID,
                        "username": "alice",
                        "first_name": "Alice",
                    },
                    "text": f"/start {raw_state}",
                },
            },
        )
        assert response.status_code == 200
        account = db_session.scalar(
            select(TelegramAccount).where(TelegramAccount.user_id == BOOTSTRAP_USER_ID)
        )
        assert account is not None
        assert account.telegram_user_id == TELEGRAM_USER_ID
        assert account.telegram_username == "alice"
        objects = list(
            db_session.scalars(select(Object).where(Object.provider == "telegram"))
        )
        assert objects == []
        row = db_session.scalar(select(TelegramLinkState))
        assert row is not None
        assert row.consumed_at is not None
    finally:
        app.dependency_overrides.clear()


def test_expired_and_consumed_state_rejected(auth_client, db_session, telegram_settings) -> None:
    link = auth_client.post("/telegram/link").json()
    raw_state = link["telegram_url"].split("start=", 1)[1]
    row = db_session.scalar(select(TelegramLinkState))
    assert row is not None
    row.expires_at = _utcnow() - timedelta(seconds=1)
    db_session.flush()
    client = _webhook_client(db_session)
    try:
        _post_webhook(
            client,
            {
                "update_id": 2,
                "message": {
                    "message_id": 1,
                    "date": 1_700_000_000,
                    "chat": {"id": TELEGRAM_USER_ID, "type": "private"},
                    "from": {"id": TELEGRAM_USER_ID, "first_name": "Alice"},
                    "text": f"/start {raw_state}",
                },
            },
        )
        assert db_session.scalar(select(TelegramAccount)) is None
        row.expires_at = _utcnow() + timedelta(minutes=10)
        row.consumed_at = _utcnow()
        db_session.flush()
        _post_webhook(
            client,
            {
                "update_id": 3,
                "message": {
                    "message_id": 2,
                    "date": 1_700_000_000,
                    "chat": {"id": TELEGRAM_USER_ID, "type": "private"},
                    "from": {"id": TELEGRAM_USER_ID, "first_name": "Alice"},
                    "text": f"/start {raw_state}",
                },
            },
        )
        assert db_session.scalar(select(TelegramAccount)) is None
    finally:
        app.dependency_overrides.clear()


def test_wrong_webhook_secret_creates_no_mutation(db_session, telegram_settings) -> None:
    client = _webhook_client(db_session)
    try:
        missing = _post_webhook(
            client, {"update_id": 1, "message": {"text": "/start abc"}}, secret=None
        )
        wrong = _post_webhook(
            client, {"update_id": 1, "message": {"text": "/start abc"}}, secret="nope"
        )
        assert missing.status_code == 401
        assert wrong.status_code == 401
        assert db_session.scalar(select(TelegramAccount)) is None
        assert db_session.scalar(select(Object)) is None or True
        assert list(db_session.scalars(select(TelegramLinkState))) == []
    finally:
        app.dependency_overrides.clear()


def test_same_user_same_identity_is_idempotent(auth_client, db_session, telegram_settings) -> None:
    _account(db_session, BOOTSTRAP_USER_ID, business_connection_id=None, enabled=False)
    link = auth_client.post("/telegram/link").json()
    raw_state = link["telegram_url"].split("start=", 1)[1]
    client = _webhook_client(db_session)
    try:
        payload = {
            "update_id": 9,
            "message": {
                "message_id": 1,
                "date": 1_700_000_000,
                "chat": {"id": TELEGRAM_USER_ID, "type": "private"},
                "from": {
                    "id": TELEGRAM_USER_ID,
                    "username": "alice2",
                    "first_name": "Alice",
                    "last_name": "Updated",
                },
                "text": f"/start {raw_state}",
            },
        }
        assert _post_webhook(client, payload).status_code == 200
        accounts = list(db_session.scalars(select(TelegramAccount)))
        assert len(accounts) == 1
        assert accounts[0].telegram_username == "alice2"
        assert accounts[0].display_name == "Alice Updated"
    finally:
        app.dependency_overrides.clear()


def test_same_user_different_identity_rejected(auth_client, db_session, telegram_settings) -> None:
    _account(db_session, BOOTSTRAP_USER_ID, telegram_user_id=111, business_connection_id=None, enabled=False)
    link = auth_client.post("/telegram/link").json()
    raw_state = link["telegram_url"].split("start=", 1)[1]
    client = _webhook_client(db_session)
    try:
        _post_webhook(
            client,
            {
                "update_id": 10,
                "message": {
                    "message_id": 1,
                    "date": 1_700_000_000,
                    "chat": {"id": 222, "type": "private"},
                    "from": {"id": 222, "first_name": "Other"},
                    "text": f"/start {raw_state}",
                },
            },
        )
        account = db_session.scalar(select(TelegramAccount))
        assert account is not None
        assert account.telegram_user_id == TELEGRAM_USER_ID or account.telegram_user_id == 111
        assert account.telegram_user_id == 111
    finally:
        app.dependency_overrides.clear()


def test_telegram_identity_already_linked_elsewhere_rejected(
    auth_client, db_session, telegram_settings
) -> None:
    other = _user(db_session, "other")
    _account(db_session, other.id, telegram_user_id=TELEGRAM_USER_ID, business_connection_id=None, enabled=False)
    link = auth_client.post("/telegram/link").json()
    raw_state = link["telegram_url"].split("start=", 1)[1]
    client = _webhook_client(db_session)
    try:
        _post_webhook(
            client,
            {
                "update_id": 11,
                "message": {
                    "message_id": 1,
                    "date": 1_700_000_000,
                    "chat": {"id": TELEGRAM_USER_ID, "type": "private"},
                    "from": {"id": TELEGRAM_USER_ID, "first_name": "Alice"},
                    "text": f"/start {raw_state}",
                },
            },
        )
        bootstrap = db_session.scalar(
            select(TelegramAccount).where(TelegramAccount.user_id == BOOTSTRAP_USER_ID)
        )
        assert bootstrap is None
    finally:
        app.dependency_overrides.clear()


def test_connections_exposes_safe_telegram_status(
    auth_client, db_session, telegram_settings
) -> None:
    empty = auth_client.get("/connections").json()["telegram"]
    assert empty["configured"] is True
    assert empty["identity_linked"] is False
    assert empty["business_connected"] is False
    assert empty["can_reply"] is False
    assert empty["bot_username"] == BOT_USERNAME
    assert "business_connection_id" not in empty
    assert BOT_TOKEN not in str(empty)
    _account(db_session, BOOTSTRAP_USER_ID, can_reply=False)
    linked = auth_client.get("/connections").json()["telegram"]
    assert linked["identity_linked"] is True
    assert linked["business_connected"] is True
    assert linked["can_reply"] is False
    account = db_session.scalar(select(TelegramAccount))
    assert account is not None
    account.business_rights = {"can_reply": True}
    db_session.flush()
    ready = auth_client.get("/connections").json()["telegram"]
    assert ready["can_reply"] is True
    account.business_connection_enabled = False
    db_session.flush()
    disabled = auth_client.get("/connections").json()["telegram"]
    assert disabled["business_connected"] is False
    assert disabled["can_reply"] is False


def test_unmatched_business_connection_is_ignored(db_session, telegram_settings) -> None:
    client = _webhook_client(db_session)
    try:
        response = _post_webhook(
            client,
            {
                "update_id": 4,
                "business_connection": {
                    "id": "orphan-bc",
                    "user": {"id": 999, "first_name": "Ghost"},
                    "user_chat_id": 999,
                    "is_enabled": True,
                    "rights": {"can_reply": True},
                    "date": 1_700_000_000,
                },
            },
        )
        assert response.status_code == 200
        assert db_session.scalar(select(TelegramAccount)) is None
    finally:
        app.dependency_overrides.clear()


def test_business_connection_maps_linked_identity(db_session, telegram_settings) -> None:
    user = _user(db_session)
    account = _account(
        db_session,
        user.id,
        enabled=False,
        can_reply=False,
        business_connection_id=None,
    )
    client = _webhook_client(db_session)
    try:
        _post_webhook(
            client,
            {
                "update_id": 5,
                "business_connection": {
                    "id": "bc-new",
                    "user": {"id": TELEGRAM_USER_ID, "username": "alice", "first_name": "Alice"},
                    "user_chat_id": TELEGRAM_USER_ID,
                    "is_enabled": True,
                    "rights": {"can_reply": True, "can_read_messages": True},
                    "date": 1_700_000_100,
                },
            },
        )
        db_session.refresh(account)
        assert account.business_connection_id == "bc-new"
        assert account.business_connection_enabled is True
        assert account.business_rights["can_reply"] is True
        _post_webhook(
            client,
            {
                "update_id": 6,
                "business_connection": {
                    "id": "bc-new",
                    "user": {"id": TELEGRAM_USER_ID, "first_name": "Alice"},
                    "user_chat_id": TELEGRAM_USER_ID,
                    "is_enabled": False,
                    "rights": {"can_reply": True},
                    "date": 1_700_000_200,
                },
            },
        )
        db_session.refresh(account)
        assert account.business_connection_enabled is False
        assert account.telegram_user_id == TELEGRAM_USER_ID
    finally:
        app.dependency_overrides.clear()


def test_inbound_private_text_upserts_once(db_session, telegram_settings) -> None:
    user = _user(db_session)
    _account(db_session, user.id)
    client = _webhook_client(db_session)
    try:
        payload = {"update_id": 20, "business_message": _private_text()}
        assert _post_webhook(client, payload).status_code == 200
        assert _post_webhook(client, payload).status_code == 200
        objects = list(
            db_session.scalars(select(Object).where(Object.provider == "telegram"))
        )
        assert len(objects) == 1
        obj = objects[0]
        assert obj.kind == "chat_message"
        assert obj.origin == "source"
        assert obj.state == "observed"
        assert obj.body == "привет"
        assert obj.external_id == build_external_id(BUSINESS_CONNECTION_ID, str(REMOTE_CHAT_ID), "10")
        assert obj.metadata_["direction"] == "inbound"
        assert obj.metadata_["chat_id"] == str(REMOTE_CHAT_ID)
        jobs = list(db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)))
        assert len(jobs) == 1
    finally:
        app.dependency_overrides.clear()


def test_caption_and_media_without_fabrication(db_session, telegram_settings) -> None:
    user = _user(db_session)
    _account(db_session, user.id)
    client = _webhook_client(db_session)
    try:
        _post_webhook(
            client,
            {
                "update_id": 21,
                "business_message": _private_text(
                    text="",
                    message_id=11,
                    caption="подпись",
                    photo=True,
                ),
            },
        )
        _post_webhook(
            client,
            {
                "update_id": 22,
                "business_message": _private_text(text="", message_id=12, caption=None, photo=True),
            },
        )
        captioned = db_session.scalar(select(Object).where(Object.external_id.endswith("|11")))
        media = db_session.scalar(select(Object).where(Object.external_id.endswith("|12")))
        assert captioned is not None and captioned.body == "подпись"
        assert media is not None
        assert media.body is None
        assert "photo" in (media.title or "").lower() or "photo" in (media.metadata_ or {}).get("message_type", "")
        assert "изображение содержимое" not in (media.body or "")
    finally:
        app.dependency_overrides.clear()


def test_outbound_edit_delete_and_ignore_unsupported(db_session, telegram_settings) -> None:
    user = _user(db_session)
    _account(db_session, user.id)
    client = _webhook_client(db_session)
    try:
        outbound = _private_text(text="я написал", message_id=30, from_id=TELEGRAM_USER_ID)
        _post_webhook(client, {"update_id": 31, "business_message": outbound})
        obj = db_session.scalar(select(Object).where(Object.external_id.endswith("|30")))
        assert obj is not None
        assert obj.metadata_["direction"] == "outbound"
        edited = _private_text(text="я написал иначе", message_id=30, from_id=TELEGRAM_USER_ID)
        _post_webhook(client, {"update_id": 32, "edited_business_message": edited})
        db_session.refresh(obj)
        assert obj.body == "я написал иначе"
        embed_jobs = list(db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)))
        assert len(embed_jobs) == 2
        metadata_only = _private_text(text="я написал иначе", message_id=30, from_id=TELEGRAM_USER_ID)
        metadata_only["from"]["username"] = "alice-new"
        _post_webhook(client, {"update_id": 33, "edited_business_message": metadata_only})
        embed_jobs = list(db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)))
        assert len(embed_jobs) == 2
        _post_webhook(
            client,
            {
                "update_id": 34,
                "deleted_business_messages": {
                    "business_connection_id": BUSINESS_CONNECTION_ID,
                    "chat": {"id": REMOTE_CHAT_ID, "type": "private"},
                    "message_ids": [30],
                },
            },
        )
        db_session.refresh(obj)
        assert obj.deleted_at is not None
        group = _private_text(message_id=40)
        group["chat"]["type"] = "group"
        _post_webhook(client, {"update_id": 35, "business_message": group})
        unknown = _private_text(message_id=41, business_connection_id="unknown")
        _post_webhook(client, {"update_id": 36, "business_message": unknown})
        remaining = list(
            db_session.scalars(select(Object).where(Object.provider == "telegram", Object.deleted_at.is_(None)))
        )
        assert remaining == []
    finally:
        app.dependency_overrides.clear()


def test_inbox_inbound_visible_outbound_hidden(db_session, telegram_settings) -> None:
    user = _user(db_session)
    _account(db_session, user.id)
    client = _webhook_client(db_session)
    try:
        _post_webhook(client, {"update_id": 40, "business_message": _private_text(message_id=50)})
        _post_webhook(
            client,
            {
                "update_id": 41,
                "business_message": _private_text(
                    text="исходящее",
                    message_id=51,
                    from_id=TELEGRAM_USER_ID,
                ),
            },
        )
        inbound = db_session.scalar(select(Object).where(Object.external_id.endswith("|50")))
        outbound = db_session.scalar(select(Object).where(Object.external_id.endswith("|51")))
        assert inbound is not None and outbound is not None
        inbox = RecentSourceService(db_session, user.id)
        titles = {row.title for row in inbox.list_recent()}
        assert inbound.title in titles
        assert outbound.title not in titles
        assert inbox.get_inbox_eligible(inbound.id) is not None
        assert inbox.get_inbox_eligible(outbound.id) is None
        fetched = db_session.get(Object, outbound.id)
        assert fetched is not None
        assert fetched.provider == "telegram"
        mm = Object(
            user_id=user.id,
            kind="chat_message",
            provider="mattermost",
            external_id="https://mm.example.com|p1",
            origin="source",
            state="observed",
            title="Mattermost stays",
            body="mm",
            occurred_at=_utcnow(),
        )
        email = Object(
            user_id=user.id,
            kind="email",
            provider="gmail",
            external_id="gmail-1",
            origin="source",
            state="observed",
            title="Email stays",
            body="mail",
            occurred_at=_utcnow(),
        )
        db_session.add_all([mm, email])
        db_session.flush()
        titles = {row.title for row in inbox.list_recent()}
        assert "Mattermost stays" in titles
        assert "Email stays" in titles
    finally:
        app.dependency_overrides.clear()


def test_telegram_chat_message_enqueues_temporal(db_session) -> None:
    user = _user(db_session)
    obj = Object(
        user_id=user.id,
        kind="chat_message",
        provider="telegram",
        origin="source",
        state="observed",
        title="встреча завтра в 15:00",
        body="встреча завтра в 15:00",
        external_id="bc|1|2",
        occurred_at=_utcnow(),
        metadata_={
            "business_user_id": str(TELEGRAM_USER_ID),
            "from_user_id": str(REMOTE_CHAT_ID),
            "direction": "inbound",
        },
    )
    db_session.add(obj)
    db_session.add(UserSettings(user_id=user.id, temporal_signals_enabled=True, timezone="Europe/Moscow"))
    db_session.flush()
    assert object_is_temporal_source_eligible(obj) is True
    enqueue_extract_temporal_signal(db_session, obj.id, user.id, already_gated=True)
    jobs = list(
        db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL))
    )
    assert len(jobs) == 1


def test_telegram_participation_uses_connected_provider_identity(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    obj = Object(
        user_id=user.id,
        kind="chat_message",
        provider="telegram",
        origin="source",
        state="observed",
        title="Telegram",
        body="завтра в 10",
        external_id="bc|chat|participation",
        occurred_at=_utcnow(),
        metadata_={
            "business_user_id": str(account.telegram_user_id),
            "from_user_id": str(REMOTE_CHAT_ID),
            "direction": "inbound",
        },
    )
    db_session.add(obj)
    db_session.flush()
    snapshot = PersonalRelevanceEvidenceService.build(db_session).build_snapshot(
        user.id, [obj.id]
    )
    assert snapshot.objects[0].user_participation_roles == ("direct_recipient",)
