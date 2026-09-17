"""Telegram Depth A4.1 — folder configuration and read-only scope preview."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet
from telethon.sessions import StringSession
from telethon.tl import types

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_account_store import TelegramMtprotoAccountStore
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoAuthorizationInvalidError,
    TelegramMtprotoFolderConfigurationError,
    TelegramMtprotoProviderUnavailableError,
    TelegramMtprotoScopeUnavailableError,
)
from app.connectors.telegram.mtproto_transport import (
    TelegramMtprotoDialogDescriptor,
    TelegramMtprotoFolderDescriptor,
    TelegramMtprotoFolderDialogsResult,
    TelegramMtprotoFolderDiscoveryResult,
    TelethonMtprotoTransport,
    _custom_filter_definitions,
    _dialog_from_dialog,
    _is_archived,
    _is_currently_muted,
    dialog_matches_filter,
)
from app.core.config import settings
from app.db.models import TelegramMtprotoAccount, TelegramMtprotoSyncFolder, User
from app.services.telegram_mtproto_scope_service import TelegramMtprotoScopeService

KEY = Fernet.generate_key().decode()
SESSION = "session-for-a4-tests"


class FakeFolderTransport:
    def __init__(self, folders, dialogs=None):
        self.folders = tuple(folders)
        self.dialogs = dialogs or {}
        self.folder_calls = []
        self.dialog_calls = []

    async def discover_folders(self, session, limit):
        self.folder_calls.append((session, limit))
        return TelegramMtprotoFolderDiscoveryResult(self.folders, False)

    async def fetch_folder_dialogs(self, session, folder_id, limit):
        self.dialog_calls.append((session, folder_id, limit))
        return self.dialogs.get(folder_id, TelegramMtprotoFolderDialogsResult((), False, {}))

    async def fetch_dialog_universe(self, session, limit):
        self.dialog_calls.append((session, None, limit))
        all_dialogs = tuple(item for result in self.dialogs.values() for item in result.dialogs)
        skipped = {}
        for result in self.dialogs.values():
            for key, value in result.skipped_counts.items():
                skipped[key] = skipped.get(key, 0) + value
        return TelegramMtprotoFolderDialogsResult(all_dialogs, any(item.truncated for item in self.dialogs.values()), skipped)

    async def fetch_history(self, *args, **kwargs):
        raise AssertionError("A4.1 scope preview must not call fetch_history")


def _account(db_session):
    user = User(id=uuid4(), display_name="A4 user")
    db_session.add(user)
    db_session.flush()
    account = TelegramMtprotoAccount(
        id=uuid4(),
        user_id=user.id,
        telegram_user_id=uuid4().int % 2_000_000_000,
        session_encrypted=CredentialEncryption(KEY).encrypt(SESSION),
    )
    db_session.add(account)
    db_session.flush()
    return user, account


def _dialog(peer_id, kind="private", *, muted=False, title="Peer"):
    return TelegramMtprotoDialogDescriptor(
        peer_id=peer_id,
        kind=kind,
        title=title,
        username=None,
        is_muted=muted,
        provider_peer_reference=json.dumps({"entity_type": "user", "id": abs(peer_id), "access_hash": 1}),
    )


def _service(db_session, transport):
    return TelegramMtprotoScopeService(
        db_session,
        transport_factory=lambda: transport,
        encryption=CredentialEncryption(KEY),
    )


@pytest.fixture(autouse=True)
def configured_mtproto(monkeypatch):
    monkeypatch.setattr(settings, "telegram_api_id", 123)
    monkeypatch.setattr(settings, "telegram_api_hash", "api-hash")
    monkeypatch.setattr(settings, "secretary_credential_key", KEY)


def test_migration_0046_is_single_head():
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0046"]


def _filter(filter_id=7, name="Team", **kwargs):
    return types.DialogFilter(
        id=filter_id,
        title=types.TextWithEntities(name, []),
        pinned_peers=kwargs.pop("pinned_peers", []),
        include_peers=kwargs.pop("include_peers", []),
        exclude_peers=kwargs.pop("exclude_peers", []),
        **kwargs,
    )


def test_dialog_filters_wrapper_and_default_are_parsed():
    custom = _filter()
    chatlist = types.DialogFilterChatlist(8, types.TextWithEntities("List", []), [], [])
    response = SimpleNamespace(filters=[types.DialogFilterDefault(), custom, chatlist])
    parsed = _custom_filter_definitions(response)
    assert [item.id for item in parsed] == [7, 8]
    assert _custom_filter_definitions([custom]) == (custom,)


def test_filter_membership_uses_explicit_exclude_include_and_categories():
    private = _dialog(1)
    group = _dialog(-2, "group")
    assert dialog_matches_filter(_filter(groups=True), group)
    assert dialog_matches_filter(_filter(include_peers=[types.InputPeerUser(1, 2)]), private)
    assert not dialog_matches_filter(_filter(include_peers=[types.InputPeerUser(1, 2)], exclude_peers=[types.InputPeerUser(1, 2)]), private)
    assert dialog_matches_filter(_filter(contacts=True), _dialog(1)) is False
    contact = _dialog(1)
    contact = TelegramMtprotoDialogDescriptor(**{**contact.__dict__, "is_contact": True})
    assert dialog_matches_filter(_filter(contacts=True), contact)


def test_non_contacts_pinned_and_chatlist_semantics():
    non_contact = _dialog(1)
    contact = replace(non_contact, is_contact=True)
    assert dialog_matches_filter(_filter(non_contacts=True), non_contact)
    assert not dialog_matches_filter(_filter(non_contacts=True), contact)
    pinned = _dialog(2, "private")
    pinned_filter = _filter(pinned_peers=[types.InputPeerUser(2, 2)])
    assert dialog_matches_filter(pinned_filter, pinned)
    assert not dialog_matches_filter(
        _filter(pinned_peers=[types.InputPeerUser(2, 2)], exclude_peers=[types.InputPeerUser(2, 2)]), pinned
    )
    chatlist = types.DialogFilterChatlist(9, types.TextWithEntities("List", []), [types.InputPeerUser(2, 2)], [])
    assert dialog_matches_filter(chatlist, pinned)
    assert not dialog_matches_filter(chatlist, _dialog(3))
    assert not dialog_matches_filter(chatlist, replace(pinned, peer_id=3, is_contact=True))


def test_exclude_read_and_archived_semantics():
    read_filter = _filter(groups=True, exclude_read=True)
    assert not dialog_matches_filter(read_filter, _dialog(1, "group"))
    assert dialog_matches_filter(read_filter, replace(_dialog(1, "group"), unread_count=1))
    assert dialog_matches_filter(read_filter, replace(_dialog(1, "group"), unread_mark=True))
    archive_filter = _filter(groups=True, exclude_archived=True)
    assert not dialog_matches_filter(archive_filter, replace(_dialog(1, "group"), is_archived=True))
    assert dialog_matches_filter(archive_filter, _dialog(1, "group"))


def test_raw_mute_read_and_archive_facts():
    now = datetime.now(UTC)
    dialog = SimpleNamespace(
        dialog=SimpleNamespace(
            notify_settings=SimpleNamespace(mute_until=int((now + timedelta(minutes=5)).timestamp())),
            folder_id=1,
            unread_mark=True,
        ),
        unread_count=0,
    )
    assert _is_currently_muted(dialog, now=now)
    assert _is_archived(dialog)
    dialog.dialog.notify_settings.mute_until = int((now - timedelta(minutes=1)).timestamp())
    assert not _is_currently_muted(dialog, now=now)
    dialog.dialog.notify_settings.mute_until = 0
    assert not _is_currently_muted(dialog, now=now)
    dialog.dialog.notify_settings = SimpleNamespace()
    assert not _is_currently_muted(dialog, now=now)
    muted_group = TelegramMtprotoDialogDescriptor(1, "group", "g", None, True, "ref", unread_count=0, unread_mark=True, is_archived=True)
    assert not dialog_matches_filter(_filter(groups=True, exclude_muted=True), muted_group)


@pytest.mark.asyncio
async def test_final_secretary_mute_override_for_explicit_peer(db_session):
    user, account = _account(db_session)
    store = TelegramMtprotoAccountStore(db_session, CredentialEncryption(KEY))
    store.replace_sync_folders(account.id, [(7, "A")])
    transport = FakeFolderTransport(
        [TelegramMtprotoFolderDescriptor(7, "A", _filter(include_peers=[types.InputPeerUser(1, 2)]))],
        {7: TelegramMtprotoFolderDialogsResult((_dialog(1, muted=True),), False, {})},
    )
    result = await _service(db_session, transport).preview_scope(user.id)
    assert result.dialogs == ()


@pytest.mark.asyncio
async def test_transport_uses_unfiltered_bounded_dialog_scan_and_raw_facts(monkeypatch):
    now = datetime.now(UTC)
    raw = SimpleNamespace(
        entity=types.User(id=1, access_hash=2, first_name="User", contact=True),
        name="User",
        unread_count=2,
        dialog=SimpleNamespace(
            notify_settings=SimpleNamespace(mute_until=int((now + timedelta(minutes=5)).timestamp())),
            unread_mark=False,
            folder_id=1,
        ),
    )
    calls = []

    class FakeClient:
        async def connect(self):
            pass

        async def is_user_authorized(self):
            return True

        def iter_dialogs(self, **kwargs):
            calls.append(kwargs)

            async def iterator():
                yield raw

            return iterator()

        async def disconnect(self):
            pass

    monkeypatch.setattr("app.connectors.telegram.mtproto_transport.TelegramClient", lambda *args: FakeClient())
    result = await TelethonMtprotoTransport(123, "hash").fetch_dialog_universe(StringSession().save(), 500)
    assert calls == [{"limit": 500}]
    assert result.dialogs[0].is_muted is True
    assert result.dialogs[0].is_archived is True
    assert result.dialogs[0].is_contact is True
    assert result.dialogs[0].unread_count == 2


def test_raw_bot_and_broadcast_are_sanitized_skips():
    bot = SimpleNamespace(entity=types.User(id=2, access_hash=2, first_name="Bot", bot=True), name="Bot")
    broadcast = SimpleNamespace(entity=types.Channel(id=3, title="Channel", photo=None, date=None, broadcast=True, access_hash=3), name="Channel")
    assert _dialog_from_dialog(bot) == (None, "bot")
    assert _dialog_from_dialog(broadcast) == (None, "broadcast")


@pytest.mark.asyncio
@pytest.mark.parametrize("error,expected", [
    (RuntimeError("provider secret body"), TelegramMtprotoProviderUnavailableError),
])
async def test_folder_transport_provider_failure_is_sanitized(monkeypatch, error, expected):
    class FakeClient:
        async def connect(self):
            pass

        async def is_user_authorized(self):
            return True

        def iter_dialogs(self, **kwargs):
            async def iterator():
                raise error
                yield

            return iterator()

        async def disconnect(self):
            pass

    monkeypatch.setattr("app.connectors.telegram.mtproto_transport.TelegramClient", lambda *args: FakeClient())
    with pytest.raises(expected) as exc_info:
        await TelethonMtprotoTransport(123, "hash").fetch_dialog_universe(StringSession().save(), 500)
    assert "provider secret body" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_folder_transport_authorization_and_flood_wait_are_mapped(monkeypatch):
    from telethon.errors import FloodWaitError

    class UnauthorizedClient:
        async def connect(self):
            pass

        async def is_user_authorized(self):
            return False

        async def disconnect(self):
            pass

    monkeypatch.setattr("app.connectors.telegram.mtproto_transport.TelegramClient", lambda *args: UnauthorizedClient())
    with pytest.raises(TelegramMtprotoAuthorizationInvalidError) as exc_info:
        await TelethonMtprotoTransport(123, "hash").fetch_dialog_universe(StringSession().save(), 500)
    assert "session" not in str(exc_info.value)

    class FloodClient(UnauthorizedClient):
        async def is_user_authorized(self):
            raise FloodWaitError(None, 17)

    monkeypatch.setattr("app.connectors.telegram.mtproto_transport.TelegramClient", lambda *args: FloodClient())
    with pytest.raises(Exception) as flood_info:
        await TelethonMtprotoTransport(123, "hash").fetch_dialog_universe(StringSession().save(), 500)
    assert getattr(flood_info.value, "retry_after_seconds", None) == 17


@pytest.mark.asyncio
async def test_names_trim_and_persist_stable_id_and_name(db_session):
    user, account = _account(db_session)
    transport = FakeFolderTransport([TelegramMtprotoFolderDescriptor(7, "Работа")])
    folders = await _service(db_session, transport).replace_folders(user.id, ["  Работа  "])
    assert folders[0].folder_id == 7
    saved = db_session.query(TelegramMtprotoSyncFolder).one()
    assert (saved.folder_id, saved.folder_name, saved.ignore_muted) == (7, "Работа", True)
    assert saved.account_id == account.id


@pytest.mark.asyncio
async def test_missing_name_leaves_previous_configuration_unchanged(db_session):
    user, account = _account(db_session)
    store = TelegramMtprotoAccountStore(db_session, CredentialEncryption(KEY))
    store.replace_sync_folders(account.id, [(7, "Existing")])
    transport = FakeFolderTransport([TelegramMtprotoFolderDescriptor(8, "Other")])
    with pytest.raises(TelegramMtprotoFolderConfigurationError):
        await _service(db_session, transport).replace_folders(user.id, ["Missing"])
    saved = store.list_sync_folders(account.id)
    assert [(item.folder_id, item.folder_name) for item in saved] == [(7, "Existing")]


@pytest.mark.asyncio
async def test_ambiguous_name_leaves_previous_configuration_unchanged(db_session):
    user, account = _account(db_session)
    store = TelegramMtprotoAccountStore(db_session, CredentialEncryption(KEY))
    store.replace_sync_folders(account.id, [(7, "Existing")])
    transport = FakeFolderTransport(
        [TelegramMtprotoFolderDescriptor(8, "Team"), TelegramMtprotoFolderDescriptor(9, "Team")]
    )
    with pytest.raises(TelegramMtprotoFolderConfigurationError):
        await _service(db_session, transport).replace_folders(user.id, ["Team"])
    assert [item.folder_id for item in store.list_sync_folders(account.id)] == [7]


@pytest.mark.asyncio
async def test_empty_configuration_disables_scope_without_scanning(db_session):
    user, account = _account(db_session)
    store = TelegramMtprotoAccountStore(db_session, CredentialEncryption(KEY))
    store.replace_sync_folders(account.id, [(7, "Existing")])
    transport = FakeFolderTransport([])
    service = _service(db_session, transport)
    await service.replace_folders(user.id, [])
    result = await service.preview_scope(user.id)
    assert result.dialogs == ()
    assert transport.folder_calls == []
    assert store.list_sync_folders(account.id) == []


@pytest.mark.asyncio
async def test_scope_unions_peers_filters_muted_and_skips_unsupported(db_session):
    user, account = _account(db_session)
    store = TelegramMtprotoAccountStore(db_session, CredentialEncryption(KEY))
    store.replace_sync_folders(account.id, [(7, "A"), (8, "B")])
    transport = FakeFolderTransport(
        [
            TelegramMtprotoFolderDescriptor(7, "A", _filter(groups=True, include_peers=[types.InputPeerUser(1, 2)])),
            TelegramMtprotoFolderDescriptor(8, "Renamed", _filter(groups=True)),
        ],
        {
            7: TelegramMtprotoFolderDialogsResult((_dialog(1), _dialog(2, "group", muted=True)), False, {"bot": 1}),
            8: TelegramMtprotoFolderDialogsResult((_dialog(1), _dialog(3, "supergroup")), True, {"broadcast": 2}),
        },
    )
    result = await _service(db_session, transport).preview_scope(user.id)
    assert {item.peer_id for item in result.dialogs} == {1, 3}
    assert {item.kind for item in result.dialogs} == {"private", "supergroup"}
    assert result.truncated is True
    assert result.skipped_counts == {"bot": 1, "broadcast": 2}
    assert len(transport.dialog_calls) == 1
    saved_by_id = {item.folder_id: item for item in store.list_sync_folders(account.id)}
    assert saved_by_id[8].folder_name == "Renamed"


@pytest.mark.asyncio
async def test_missing_persisted_folder_fails_closed(db_session):
    user, account = _account(db_session)
    TelegramMtprotoAccountStore(db_session, CredentialEncryption(KEY)).replace_sync_folders(account.id, [(7, "Gone")])
    transport = FakeFolderTransport([TelegramMtprotoFolderDescriptor(8, "Other")])
    with pytest.raises(TelegramMtprotoScopeUnavailableError):
        await _service(db_session, transport).preview_scope(user.id)


@pytest.mark.asyncio
async def test_false_ignore_muted_is_rejected(db_session):
    user, _ = _account(db_session)
    with pytest.raises(TelegramMtprotoFolderConfigurationError):
        await _service(db_session, FakeFolderTransport([])).replace_folders(user.id, [], ignore_muted=False)
