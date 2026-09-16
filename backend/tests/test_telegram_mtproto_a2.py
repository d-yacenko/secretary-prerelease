"""Telegram Depth A2 — bounded group discovery and explicit selections."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from telethon.sessions import StringSession
from telethon.tl import types

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_account_store import TelegramMtprotoAccountStore
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoAccountNotConnectedError,
    TelegramMtprotoAuthorizationInvalidError,
    TelegramMtprotoProviderUnavailableError,
)
from app.connectors.telegram.mtproto_transport import (
    DISCOVERY_DIALOG_LIMIT,
    TelegramMtprotoGroupDescriptor,
    TelegramMtprotoGroupDiscoveryResult,
    TelethonMtprotoTransport,
)
from app.core.config import settings
from app.db.models import TelegramMtprotoAccount, TelegramMtprotoChatSelection, User
from app.services.telegram_mtproto_group_service import TelegramMtprotoGroupService

KEY = Fernet.generate_key().decode()
SESSION = "encrypted-session-material"
TELETHON_SESSION = StringSession().save()
API_HASH = "api-hash-secret"


class FakeDiscoveryTransport:
    def __init__(self, groups: tuple[TelegramMtprotoGroupDescriptor, ...] = ()) -> None:
        self.groups = groups
        self.sessions: list[str] = []
        self.limits: list[int] = []
        self.error: Exception | None = None

    async def discover_groups(
        self, session: str, limit: int
    ) -> TelegramMtprotoGroupDiscoveryResult:
        self.sessions.append(session)
        self.limits.append(limit)
        if self.error is not None:
            raise self.error
        return TelegramMtprotoGroupDiscoveryResult(self.groups, len(self.groups) >= limit)


def _user(db_session, name: str) -> User:
    user = User(id=uuid4(), display_name=name)
    db_session.add(user)
    db_session.flush()
    return user


def _account(
    db_session, user_id, session: str = SESSION, telegram_user_id: int = 987654321
) -> TelegramMtprotoAccount:
    account = TelegramMtprotoAccount(
        id=uuid4(),
        user_id=user_id,
        telegram_user_id=telegram_user_id,
        session_encrypted=CredentialEncryption(KEY).encrypt(session),
        username="alice",
        display_name="Alice",
    )
    db_session.add(account)
    db_session.flush()
    return account


def _descriptor(
    peer_id: int = -1001234567890,
    *,
    kind: str = "supergroup",
    title: str = "Example",
    username: str | None = "example",
    is_forum: bool = False,
    access_hash: int = 987654,
) -> TelegramMtprotoGroupDescriptor:
    entity_type = "channel" if kind == "supergroup" else "chat"
    reference = {"entity_type": entity_type, "id": abs(peer_id), "access_hash": access_hash}
    return TelegramMtprotoGroupDescriptor(
        peer_id=peer_id,
        kind=kind,
        title=title,
        username=username,
        is_forum=is_forum,
        provider_peer_reference=json.dumps(reference),
    )


def _service(db_session, fake: FakeDiscoveryTransport) -> TelegramMtprotoGroupService:
    return TelegramMtprotoGroupService(
        db_session,
        transport_factory=lambda: fake,
        encryption=CredentialEncryption(KEY),
    )


@pytest.fixture(autouse=True)
def configured_mtproto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_api_id", 123456)
    monkeypatch.setattr(settings, "telegram_api_hash", API_HASH)
    monkeypatch.setattr(settings, "secretary_credential_key", KEY)


async def test_discovery_uses_connected_users_decrypted_session(db_session) -> None:
    user = _user(db_session, "connected")
    _account(db_session, user.id)
    fake = FakeDiscoveryTransport((_descriptor(),))

    result = await _service(db_session, fake).list_groups(user.id)

    assert fake.sessions == [SESSION]
    assert fake.limits == [DISCOVERY_DIALOG_LIMIT]
    assert result.groups[0].selected is False
    assert result.groups[0].available is True


async def test_no_account_is_a_controlled_error(db_session) -> None:
    user = _user(db_session, "unconnected")

    with pytest.raises(TelegramMtprotoAccountNotConnectedError):
        await _service(db_session, FakeDiscoveryTransport()).list_groups(user.id)


async def test_discovery_persists_zero_unselected_rows(db_session) -> None:
    user = _user(db_session, "default-off")
    account = _account(db_session, user.id)
    fake = FakeDiscoveryTransport((_descriptor(), _descriptor(-12345, kind="group", title="Basic")))

    result = await _service(db_session, fake).list_groups(user.id)

    assert len(result.groups) == 2
    assert all(not group.selected for group in result.groups)
    assert db_session.scalar(
        select(func.count()).select_from(TelegramMtprotoChatSelection).where(
            TelegramMtprotoChatSelection.account_id == account.id
        )
    ) == 0


async def test_select_persists_one_encrypted_selection_and_is_idempotent(db_session) -> None:
    user = _user(db_session, "select")
    account = _account(db_session, user.id)
    fake = FakeDiscoveryTransport((_descriptor(),))
    service = _service(db_session, fake)

    await service.set_selection(user.id, -1001234567890, True)
    first = db_session.scalar(select(TelegramMtprotoChatSelection))
    assert first is not None
    assert "access_hash" not in first.provider_peer_reference_encrypted
    assert CredentialEncryption(KEY).decrypt(first.provider_peer_reference_encrypted) == (
        _descriptor().provider_peer_reference
    )

    fake.groups = (_descriptor(title="Renamed", access_hash=123),)
    await service.set_selection(user.id, -1001234567890, True)
    rows = list(
        db_session.scalars(
            select(TelegramMtprotoChatSelection).where(
                TelegramMtprotoChatSelection.account_id == account.id
            )
        )
    )
    assert len(rows) == 1
    assert rows[0].title == "Renamed"
    assert json.loads(
        CredentialEncryption(KEY).decrypt(rows[0].provider_peer_reference_encrypted)
    )["access_hash"] == 123


async def test_deselection_is_idempotent_and_does_not_call_telegram(db_session) -> None:
    user = _user(db_session, "deselect")
    account = _account(db_session, user.id)
    fake = FakeDiscoveryTransport((_descriptor(),))
    service = _service(db_session, fake)
    await service.set_selection(user.id, -1001234567890, True)
    calls_before = len(fake.sessions)

    assert await service.set_selection(user.id, -1001234567890, False) is None
    assert await service.set_selection(user.id, -1001234567890, False) is None
    assert len(fake.sessions) == calls_before
    assert db_session.scalar(
        select(TelegramMtprotoChatSelection).where(
            TelegramMtprotoChatSelection.account_id == account.id
        )
    ) is None


async def test_selected_group_absent_from_discovery_is_available_false(db_session) -> None:
    user = _user(db_session, "stale-selection")
    account = _account(db_session, user.id)
    stored = TelegramMtprotoAccountStore(db_session, CredentialEncryption(KEY))
    stored.save_selection(account.id, _descriptor(title="Previously selected"))
    fake = FakeDiscoveryTransport((_descriptor(-1009999999999, title="Other"),))

    result = await _service(db_session, fake).list_groups(user.id)

    stale = next(group for group in result.groups if group.peer_id == -1001234567890)
    assert stale.selected is True
    assert stale.available is False
    assert stale.title == "Previously selected"


async def test_user_isolation_keeps_selections_separate(db_session) -> None:
    first = _user(db_session, "first")
    second = _user(db_session, "second")
    first_account = _account(db_session, first.id)
    second_account = _account(
        db_session, second.id, session="second-session", telegram_user_id=123
    )
    fake = FakeDiscoveryTransport((_descriptor(),))
    service = _service(db_session, fake)
    await service.set_selection(first.id, -1001234567890, True)

    second_groups = await service.list_groups(second.id)

    assert second_groups.groups[0].selected is False
    assert db_session.scalar(
        select(TelegramMtprotoChatSelection).where(
            TelegramMtprotoChatSelection.account_id == second_account.id
        )
    ) is None
    assert db_session.scalar(
        select(TelegramMtprotoChatSelection).where(
            TelegramMtprotoChatSelection.account_id == first_account.id
        )
    ) is not None


def test_api_no_account_returns_controlled_409(auth_client) -> None:
    response = auth_client.get("/telegram/mtproto/groups")

    assert response.status_code == 409
    assert response.json() == {"detail": "Telegram MTProto account is not connected"}


def test_api_selection_and_discovery_do_not_expose_provider_state(
    auth_client, db_session, bootstrap_user_id, monkeypatch
) -> None:
    _account(db_session, bootstrap_user_id)
    fake = FakeDiscoveryTransport((_descriptor(),))
    monkeypatch.setattr(
        "app.services.telegram_mtproto_group_service._build_transport", lambda: fake
    )

    selected = auth_client.patch(
        "/telegram/mtproto/groups/-1001234567890", json={"selected": True}
    )
    listed = auth_client.get("/telegram/mtproto/groups")

    assert selected.status_code == 200
    assert selected.json() == {"peer_id": -1001234567890, "selected": True}
    assert listed.status_code == 200
    assert listed.json()["groups"][0]["selected"] is True
    for response in (selected, listed):
        assert "access_hash" not in response.text
        assert SESSION not in response.text
        assert API_HASH not in response.text


def test_api_rejects_arbitrary_peer_and_false_is_idempotent(
    auth_client, db_session, bootstrap_user_id, monkeypatch
) -> None:
    _account(db_session, bootstrap_user_id)
    fake = FakeDiscoveryTransport((_descriptor(),))
    monkeypatch.setattr(
        "app.services.telegram_mtproto_group_service._build_transport", lambda: fake
    )

    arbitrary = auth_client.patch("/telegram/mtproto/groups/-1001", json={"selected": True})
    deselected = auth_client.patch("/telegram/mtproto/groups/-1001", json={"selected": False})

    assert arbitrary.status_code == 404
    assert arbitrary.json() == {"detail": "Telegram group is not available"}
    assert deselected.status_code == 200
    assert deselected.json() == {"peer_id": -1001, "selected": False}
    assert len(fake.sessions) == 1


def test_api_validation_is_sanitized_for_selection(auth_client) -> None:
    response = auth_client.patch(
        "/telegram/mtproto/groups/-1001", json={"selected": "true"}
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid Telegram MTProto request"}
    assert "true" not in response.text


def _chat_dialog(
    chat_id: int, title: str, *, left: bool = False, deactivated: bool = False
) -> SimpleNamespace:
    entity = types.Chat(
        id=chat_id,
        title=title,
        photo=None,
        participants_count=1,
        date=None,
        version=1,
        left=left,
        deactivated=deactivated,
    )
    return SimpleNamespace(entity=entity, message=SimpleNamespace(body="must not be read"))


def _channel_dialog(
    channel_id: int,
    title: str,
    *,
    username: str | None = None,
    forum: bool = False,
    broadcast: bool = False,
    megagroup: bool = True,
    left: bool = False,
) -> SimpleNamespace:
    entity = types.Channel(
        id=channel_id,
        title=title,
        photo=None,
        date=None,
        username=username,
        forum=forum,
        broadcast=broadcast,
        megagroup=megagroup,
        left=left,
        access_hash=123456,
    )
    return SimpleNamespace(entity=entity, message=SimpleNamespace(body="must not be read"))


def _user_dialog(bot: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        entity=types.User(id=42, bot=bot, first_name="Private", last_name="User"),
        message=SimpleNamespace(body="must not be read"),
    )


@pytest.mark.asyncio
async def test_transport_filters_only_eligible_groups_and_disconnects(monkeypatch) -> None:
    dialogs = (
        _user_dialog(),
        _user_dialog(bot=True),
        _channel_dialog(1, "Broadcast", broadcast=True, megagroup=False),
        _chat_dialog(2, "Left", left=True),
        _chat_dialog(3, "Deactivated", deactivated=True),
        _chat_dialog(4, "Basic"),
        _channel_dialog(5, "Supergroup", username="public"),
        _channel_dialog(6, "Forum", forum=True),
    )
    clients: list[FakeTelethonDiscoveryClient] = []

    def factory(*args):
        client = FakeTelethonDiscoveryClient(dialogs)
        clients.append(client)
        return client

    monkeypatch.setattr("app.connectors.telegram.mtproto_transport.TelegramClient", factory)
    result = await TelethonMtprotoTransport(123, API_HASH).discover_groups(
        TELETHON_SESSION, 500
    )

    assert [group.title for group in result.groups] == ["Basic", "Supergroup", "Forum"]
    assert [group.peer_id for group in result.groups] == [-4, -1000000000005, -1000000000006]
    assert [group.kind for group in result.groups] == ["group", "supergroup", "supergroup"]
    assert result.groups[-1].is_forum is True
    assert all(group.peer_id != 42 for group in result.groups)
    assert clients[0].disconnect_calls == 1


@pytest.mark.asyncio
async def test_transport_scan_is_bounded_and_marks_truncated(monkeypatch) -> None:
    dialogs = tuple(_chat_dialog(index, f"Group {index}") for index in range(501))
    clients: list[FakeTelethonDiscoveryClient] = []

    def factory(*args):
        client = FakeTelethonDiscoveryClient(dialogs)
        clients.append(client)
        return client

    monkeypatch.setattr("app.connectors.telegram.mtproto_transport.TelegramClient", factory)
    result = await TelethonMtprotoTransport(123, API_HASH).discover_groups(
        TELETHON_SESSION, 500
    )

    assert len(result.groups) == 500
    assert result.truncated is True
    assert clients[0].limit == DISCOVERY_DIALOG_LIMIT
    assert clients[0].disconnect_calls == 1


@pytest.mark.asyncio
async def test_transport_disconnects_and_maps_revoked_authorization(monkeypatch) -> None:
    clients: list[FakeTelethonDiscoveryClient] = []

    def factory(*args):
        client = FakeTelethonDiscoveryClient((), authorized=False)
        clients.append(client)
        return client

    monkeypatch.setattr("app.connectors.telegram.mtproto_transport.TelegramClient", factory)
    with pytest.raises(TelegramMtprotoAuthorizationInvalidError):
        await TelethonMtprotoTransport(123, API_HASH).discover_groups(TELETHON_SESSION, 500)
    assert clients[0].disconnect_calls == 1


@pytest.mark.asyncio
async def test_transport_disconnects_and_sanitizes_provider_failure(monkeypatch) -> None:
    clients: list[FakeTelethonDiscoveryClient] = []

    def factory(*args):
        client = FakeTelethonDiscoveryClient((), error=RuntimeError("access hash payload"))
        clients.append(client)
        return client

    monkeypatch.setattr("app.connectors.telegram.mtproto_transport.TelegramClient", factory)
    with pytest.raises(TelegramMtprotoProviderUnavailableError) as exc_info:
        await TelethonMtprotoTransport(123, API_HASH).discover_groups(TELETHON_SESSION, 500)
    assert "access hash payload" not in str(exc_info.value)
    assert clients[0].disconnect_calls == 1


class FakeTelethonDiscoveryClient:
    def __init__(
        self,
        dialogs: tuple[SimpleNamespace, ...],
        *,
        authorized: bool = True,
        error: Exception | None = None,
    ) -> None:
        self.dialogs = dialogs
        self.authorized = authorized
        self.error = error
        self.limit = 0
        self.disconnect_calls = 0

    async def connect(self) -> None:
        return None

    async def is_user_authorized(self) -> bool:
        return self.authorized

    def iter_dialogs(self, limit: int):
        self.limit = limit

        async def iterator():
            if self.error is not None:
                raise self.error
            for dialog in self.dialogs:
                yield dialog

        return iterator()

    async def disconnect(self) -> None:
        self.disconnect_calls += 1


def test_migration_0043_is_the_single_alembic_head() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0043"]
