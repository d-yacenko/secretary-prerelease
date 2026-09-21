"""Telegram Depth A4.2 — durable dynamic scope and explicit peer sync."""

import inspect
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import ClassVar
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet
from sqlalchemy import select
from telethon.tl import types

from app.api import telegram_mtproto as telegram_api
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram import mtproto_transport
from app.connectors.telegram.mtproto_account_store import TelegramMtprotoAccountStore
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoAuthorizationInvalidError,
    TelegramMtprotoGroupNotSelectedError,
    TelegramMtprotoGroupUnavailableError,
    TelegramMtprotoPeerNotInActiveScopeError,
    TelegramMtprotoProviderReferenceInvalidError,
    TelegramMtprotoProviderUnavailableError,
    TelegramMtprotoScopeUnavailableError,
)
from app.connectors.telegram.mtproto_transport import (
    DISCOVERY_DIALOG_LIMIT,
    TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT,
    TelegramMtprotoDialogDescriptor,
    TelegramMtprotoFolderDescriptor,
    TelegramMtprotoFolderDialogsResult,
    TelegramMtprotoFolderDiscoveryResult,
    TelegramMtprotoHistoryEntry,
    TelegramMtprotoHistoryPage,
    _input_peer_from_reference,
)
from app.db.models import (
    Object,
    TelegramMtprotoAccount,
    TelegramMtprotoChatSelection,
    TelegramMtprotoSyncFolder,
    User,
)
from app.services.telegram_mtproto_history_service import TelegramMtprotoHistoryService
from app.services.telegram_mtproto_scope_service import TelegramMtprotoScopeService

KEY = Fernet.generate_key().decode()
SESSION = "a4.2-test-session"


def _dialog(peer_id: int, kind: str = "private") -> TelegramMtprotoDialogDescriptor:
    return TelegramMtprotoDialogDescriptor(
        peer_id=peer_id,
        kind=kind,
        title=f"Peer {peer_id}",
        username=None,
        is_muted=False,
        provider_peer_reference=json.dumps(
            {"entity_type": "user", "id": abs(peer_id), "access_hash": 99}
            if kind == "private"
            else {"entity_type": "chat", "id": abs(peer_id)}
        ),
    )


def _filter(folder_id: int = 7):
    return types.DialogFilter(
        id=folder_id,
        title=types.TextWithEntities("Configured", []),
        pinned_peers=[],
        include_peers=[types.InputPeerUser(1, 2)],
        exclude_peers=[],
    )


class _Transport:
    def __init__(self, *, truncated=False, discovery_truncated=False, dialogs=None):
        self.truncated = truncated
        self.discovery_truncated = discovery_truncated
        self.dialogs = tuple(dialogs or (_dialog(1),))
        self.history_called = False
        self.discovery_limits = []
        self.universe_limits = []

    async def discover_folders(self, session, limit):
        self.discovery_limits.append(limit)
        return TelegramMtprotoFolderDiscoveryResult(
            (TelegramMtprotoFolderDescriptor(7, "Configured", _filter()),),
            self.discovery_truncated,
        )

    async def fetch_dialog_universe(self, session, limit):
        self.universe_limits.append(limit)
        return TelegramMtprotoFolderDialogsResult(self.dialogs, self.truncated, {})

    async def fetch_history(self, *args, **kwargs):
        self.history_called = True
        raise AssertionError("scope reconciliation must not fetch history")


class _Store:
    def __init__(self, *, truncated=False):
        self.account = SimpleNamespace(id=uuid4())
        self.folder = SimpleNamespace(folder_id=7, folder_name="Configured", ignore_muted=True)
        self.reconciled = None
        self.transport = _Transport(truncated=truncated)

    def get_by_user_id(self, user_id):
        return self.account

    def decrypt_session(self, account):
        return "session"

    def list_sync_folders(self, account_id):
        return [self.folder]

    def refresh_sync_folder_names(self, account_id, names_by_id):
        return None

    def reconcile_scope(self, account_id, descriptors):
        self.reconciled = descriptors
        return (len(descriptors), len(descriptors), 0, 0)


class _DialogIteratorClient:
    dialogs: ClassVar[list] = []
    requested_limits: ClassVar[list] = []
    yielded = 0

    def __init__(self, *args):
        pass

    async def connect(self):
        return None

    async def is_user_authorized(self):
        return True

    def iter_dialogs(self, *, limit):
        type(self).requested_limits.append(limit)

        async def iterator():
            for dialog in type(self).dialogs:
                type(self).yielded += 1
                yield dialog

        return iterator()

    async def disconnect(self):
        return None


async def _fetch_universe_for_count(monkeypatch, count, *, classify=None):
    dialogs = [SimpleNamespace(index=index) for index in range(count)]
    _DialogIteratorClient.dialogs = dialogs
    _DialogIteratorClient.requested_limits = []
    _DialogIteratorClient.yielded = 0

    def convert(dialog):
        if classify is not None:
            return classify(dialog)
        return _dialog(dialog.index + 1), None

    monkeypatch.setattr(mtproto_transport, "TelegramClient", _DialogIteratorClient)
    monkeypatch.setattr(mtproto_transport, "StringSession", lambda value: value)
    monkeypatch.setattr(mtproto_transport, "_dialog_from_dialog", convert)
    result = await mtproto_transport.TelethonMtprotoTransport(1, "hash").fetch_dialog_universe(
        "session", TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT
    )
    return result, _DialogIteratorClient


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [499, 500, 2000])
async def test_scope_universe_boundary_is_complete(monkeypatch, count):
    result, client = await _fetch_universe_for_count(monkeypatch, count)
    assert result.truncated is False
    assert len(result.dialogs) == count
    assert client.requested_limits == [TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT + 1]
    assert client.yielded == count


@pytest.mark.asyncio
async def test_scope_universe_lookahead_marks_only_2001st_as_truncated(monkeypatch):
    result, client = await _fetch_universe_for_count(monkeypatch, 2001)
    assert result.truncated is True
    assert len(result.dialogs) == TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT
    assert client.yielded == TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT + 1


@pytest.mark.asyncio
async def test_scope_universe_skipped_counts_cover_retained_window_only(monkeypatch):
    def classify(dialog):
        if dialog.index % 2 == 0:
            return None, "bot"
        return _dialog(dialog.index + 1), None

    result, client = await _fetch_universe_for_count(monkeypatch, 2001, classify=classify)
    assert result.truncated is True
    assert len(result.dialogs) == 1000
    assert result.skipped_counts == {"bot": 1000}
    assert client.yielded == TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT + 1


@pytest.mark.asyncio
async def test_scope_service_uses_2000_universe_and_folders_keep_500(monkeypatch):
    store = _Store()
    service = TelegramMtprotoScopeService.__new__(TelegramMtprotoScopeService)
    service._session = object()
    service._encryption = object()
    service._transport_factory = lambda: store.transport
    monkeypatch.setattr(service, "_account_context", lambda user_id: (store.account, store, "session"))

    await service.preview_scope(uuid4())

    assert store.transport.universe_limits == [TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT]
    assert store.transport.discovery_limits == [DISCOVERY_DIALOG_LIMIT]


def test_manual_group_discovery_still_uses_500_bound():
    source = inspect.getsource(mtproto_transport.TelethonMtprotoTransport.discover_groups)
    assert DISCOVERY_DIALOG_LIMIT == 500
    assert "min(limit, DISCOVERY_DIALOG_LIMIT)" in source


@pytest.mark.asyncio
async def test_reconcile_is_durable_and_never_fetches_history(monkeypatch):
    store = _Store()
    service = TelegramMtprotoScopeService.__new__(TelegramMtprotoScopeService)
    service._session = object()
    service._encryption = object()
    service._transport_factory = lambda: store.transport
    monkeypatch.setattr(service, "_account_context", lambda user_id: (store.account, store, "session"))

    result = await service.reconcile_scope(uuid4())

    assert result.active == 1
    assert [item.peer_id for item in store.reconciled] == [1]
    assert store.transport.history_called is False


@pytest.mark.asyncio
async def test_incomplete_scope_fails_closed_without_reconciliation(monkeypatch):
    store = _Store(truncated=True)
    service = TelegramMtprotoScopeService.__new__(TelegramMtprotoScopeService)
    service._session = object()
    service._encryption = object()
    service._transport_factory = lambda: store.transport
    monkeypatch.setattr(service, "_account_context", lambda user_id: (store.account, store, "session"))

    with pytest.raises(TelegramMtprotoScopeUnavailableError):
        await service.reconcile_scope(uuid4())
    assert store.reconciled is None


def test_durable_selection_flags_and_legacy_deselect_contract():
    assert "manual_selected" in TelegramMtprotoChatSelection.__table__.c
    assert "scope_active" in TelegramMtprotoChatSelection.__table__.c


def test_private_provider_reference_becomes_input_peer_user():
    peer = _input_peer_from_reference('{"entity_type":"user","id":42,"access_hash":99}')
    assert isinstance(peer, types.InputPeerUser)
    assert peer.user_id == 42
    assert peer.access_hash == 99


def test_reconciliation_rows_deactivate_and_reenter_without_cursor_loss(db_session):
    user = User(id=uuid4(), display_name="A4.2 durable")
    db_session.add(user)
    db_session.flush()
    account = TelegramMtprotoAccount(
        id=uuid4(), user_id=user.id, telegram_user_id=uuid4().int % 2_000_000_000,
        session_encrypted="encrypted-session",
    )
    db_session.add(account)
    db_session.flush()
    store = TelegramMtprotoAccountStore(db_session, SimpleNamespace(encrypt=lambda value: f"enc:{value}"))
    descriptors = [_dialog(1), _dialog(-2, "group"), _dialog(-3, "supergroup")]
    store.reconcile_scope(account.id, descriptors)
    row = store.get_selection(account.id, 1)
    row.history_latest_message_id = 17
    row.history_complete = True
    row.manual_selected = True
    db_session.flush()

    store.reconcile_scope(account.id, [])
    assert row.scope_active is False
    assert row.history_latest_message_id == 17
    assert db_session.get(TelegramMtprotoChatSelection, row.id) is row

    store.reconcile_scope(account.id, [descriptors[0]])
    assert row.scope_active is True
    assert row.manual_selected is True
    assert row.history_latest_message_id == 17


def test_scoped_unavailable_peer_is_sanitized_409(monkeypatch):
    async def fail(*args, **kwargs):
        raise TelegramMtprotoGroupUnavailableError("provider details must not escape")

    class FakeHistory:
        def __init__(self, session):
            self.session = session

        sync_scope_peer = fail

    monkeypatch.setattr(telegram_api, "TelegramMtprotoHistoryService", FakeHistory)
    monkeypatch.setattr(telegram_api, "mtproto_is_configured", lambda: True)
    with pytest.raises(telegram_api.HTTPException) as raised:
        import asyncio

        asyncio.run(
            telegram_api.telegram_mtproto_scope_peer_sync(
                peer_id=42,
                session=object(),
                current_user=SimpleNamespace(user_id=uuid4()),
            )
        )
    assert raised.value.status_code == 409
    assert raised.value.detail == "Telegram peer is no longer available"


def test_migration_0046_is_single_head():
    config = Config("alembic.ini")
    assert ScriptDirectory.from_config(config).get_heads() == ["0046"]


def _db_account(db_session, name="A4.2 acceptance"):
    user = User(id=uuid4(), display_name=name)
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


def _scope_seed(db_session, *, active=True):
    user, account = _db_account(db_session)
    db_session.add(TelegramMtprotoSyncFolder(
        account_id=account.id, folder_id=7, folder_name="Configured"
    ))
    db_session.flush()
    store = TelegramMtprotoAccountStore(db_session, CredentialEncryption(KEY))
    store.reconcile_scope(account.id, [_dialog(1)])
    row = store.get_selection(account.id, 1)
    row.scope_active = active
    row.history_latest_message_id = 22
    row.history_backfill_before_message_id = 11
    row.history_cutoff_at = datetime.now(UTC) - timedelta(days=2)
    row.history_complete = False
    row.history_last_synced_at = datetime.now(UTC)
    db_session.flush()
    return user, account, store, row


def test_unsupported_scope_descriptor_is_not_persisted(db_session):
    _, account = _db_account(db_session, "A4.2 unsupported")
    store = TelegramMtprotoAccountStore(db_session, CredentialEncryption(KEY))
    store.reconcile_scope(account.id, [_dialog(9, "broadcast")])
    assert db_session.scalar(select(TelegramMtprotoChatSelection).where(
        TelegramMtprotoChatSelection.account_id == account.id
    )) is None


def test_all_supported_scope_rows_have_encrypted_provider_references(db_session):
    _, account = _db_account(db_session, "A4.2 supported kinds")
    descriptors = [
        _dialog(42, "private"),
        TelegramMtprotoDialogDescriptor(
            peer_id=-7, kind="group", title="Basic", username=None, is_muted=False,
            provider_peer_reference=json.dumps({"entity_type": "chat", "id": 7}),
        ),
        TelegramMtprotoDialogDescriptor(
            peer_id=-1007, kind="supergroup", title="Super", username=None, is_muted=False,
            provider_peer_reference=json.dumps(
                {"entity_type": "channel", "id": 1007, "access_hash": 88}
            ),
        ),
    ]
    store = TelegramMtprotoAccountStore(db_session, CredentialEncryption(KEY))
    store.reconcile_scope(account.id, descriptors)
    for descriptor in descriptors:
        row = store.get_selection(account.id, descriptor.peer_id)
        assert row.peer_kind == descriptor.kind
        assert row.manual_selected is False
        assert row.scope_active is True
        assert row.provider_peer_reference_encrypted != descriptor.provider_peer_reference
        assert CredentialEncryption(KEY).decrypt(row.provider_peer_reference_encrypted) == descriptor.provider_peer_reference


def test_full_cursor_state_survives_scope_reentry(db_session):
    _, _, store, row = _scope_seed(db_session)
    original = {name: getattr(row, name) for name in (
        "history_latest_message_id", "history_backfill_before_message_id",
        "history_cutoff_at", "history_complete", "history_last_synced_at"
    )}
    store.reconcile_scope(row.account_id, [])
    assert row.scope_active is False
    store.reconcile_scope(row.account_id, [_dialog(1)])
    assert row.scope_active is True
    assert {name: getattr(row, name) for name in original} == original


def test_manual_deselect_reselect_preserves_scope_and_all_cursors(db_session):
    _, _, store, row = _scope_seed(db_session)
    row.manual_selected = True
    original_id = row.id
    original = {
        name: getattr(row, name)
        for name in (
            "scope_active", "history_latest_message_id",
            "history_backfill_before_message_id", "history_cutoff_at",
            "history_complete", "history_last_synced_at",
        )
    }
    db_session.flush()
    store.delete_selection(row.account_id, row.peer_id)
    assert store.list_selections(row.account_id) == []
    assert row.id == original_id
    assert {name: getattr(row, name) for name in original} == original
    store.save_selection(row.account_id, SimpleNamespace(
        peer_id=row.peer_id, kind=row.peer_kind,
        provider_peer_reference=CredentialEncryption(KEY).decrypt(
            row.provider_peer_reference_encrypted
        ), title=row.title, username=row.username, is_forum=row.is_forum,
    ))
    assert row.manual_selected is True
    assert row.id == original_id
    assert {name: getattr(row, name) for name in original} == original


@pytest.mark.asyncio
async def test_inactive_scoped_peer_is_rejected_before_history(db_session):
    user, _, _, row = _scope_seed(db_session, active=False)
    transport = _Transport()
    with pytest.raises(TelegramMtprotoPeerNotInActiveScopeError):
        await TelegramMtprotoHistoryService(
            db_session, transport_factory=lambda: transport,
            encryption=CredentialEncryption(KEY),
        ).sync_scope_peer(user.id, row.peer_id)
    assert transport.history_called is False


@pytest.mark.asyncio
async def test_retained_deselected_row_blocks_legacy_sync_before_provider(db_session):
    user, _, store, row = _scope_seed(db_session, active=True)
    store.delete_selection(row.account_id, row.peer_id)
    transport = _Transport()
    with pytest.raises(TelegramMtprotoGroupNotSelectedError):
        await TelegramMtprotoHistoryService(
            db_session, transport_factory=lambda: transport,
            encryption=CredentialEncryption(KEY),
        ).sync_group(user.id, row.peer_id)
    assert transport.history_called is False


@pytest.mark.asyncio
async def test_scope_truncation_sources_leave_real_row_unchanged(db_session):
    user, _, _, row = _scope_seed(db_session)
    for transport in (_Transport(discovery_truncated=True), _Transport(truncated=True)):
        service = TelegramMtprotoScopeService(
            db_session, transport_factory=lambda transport=transport: transport,
            encryption=CredentialEncryption(KEY),
        )
        with pytest.raises(TelegramMtprotoScopeUnavailableError):
            await service.reconcile_scope(user.id)
        assert row.scope_active is True
        assert row.history_latest_message_id == 22


@pytest.mark.asyncio
async def test_missing_configured_folder_leaves_real_row_unchanged(db_session):
    user, _, _, row = _scope_seed(db_session)

    class MissingFolderTransport(_Transport):
        async def discover_folders(self, session, limit):
            return TelegramMtprotoFolderDiscoveryResult((), False)

    service = TelegramMtprotoScopeService(
        db_session, transport_factory=MissingFolderTransport,
        encryption=CredentialEncryption(KEY),
    )
    with pytest.raises(TelegramMtprotoScopeUnavailableError):
        await service.reconcile_scope(user.id)
    assert row.scope_active is True
    assert row.history_latest_message_id == 22


@pytest.mark.asyncio
async def test_muted_scope_member_is_deactivated_without_deleting_row(db_session):
    user, _, _, row = _scope_seed(db_session)
    transport = _Transport(dialogs=(SimpleNamespace(**{
        **_dialog(1).__dict__, "is_muted": True
    }),))
    service = TelegramMtprotoScopeService(
        db_session, transport_factory=lambda: transport, encryption=CredentialEncryption(KEY)
    )
    await service.reconcile_scope(user.id)
    assert row.scope_active is False
    assert db_session.get(TelegramMtprotoChatSelection, row.id) is row
    assert row.history_latest_message_id == 22


class _HistoryTransport:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    async def fetch_history(self, session, provider_peer_reference, **kwargs):
        self.calls.append((session, provider_peer_reference, kwargs))
        return self.pages.pop(0) if self.pages else TelegramMtprotoHistoryPage((), False)


def _history_entry(message_id=1):
    return TelegramMtprotoHistoryEntry(
        message_id=message_id,
        occurred_at=datetime.now(UTC) - timedelta(days=1),
        text="private scoped message",
        sender_peer_id=42,
        reply_to_message_id=None,
        topic_id=None,
        edited_at=None,
        is_service=False,
    )


@pytest.mark.asyncio
async def test_private_scope_sync_uses_shared_engine_and_is_idempotent(db_session):
    user, account = _db_account(db_session, "A4.2 private history")
    reference = json.dumps({"entity_type": "user", "id": 42, "access_hash": 99})
    store = TelegramMtprotoAccountStore(db_session, CredentialEncryption(KEY))
    row = store.save_selection(account.id, SimpleNamespace(
        peer_id=42, kind="private", provider_peer_reference=reference,
        title="Private peer", username="private_user", is_forum=False,
    ))
    row.scope_active = True
    db_session.flush()
    entry = _history_entry()
    transport = _HistoryTransport([
        TelegramMtprotoHistoryPage((entry,), False),
        TelegramMtprotoHistoryPage((entry,), False),
    ])
    service = TelegramMtprotoHistoryService(
        db_session, transport_factory=lambda: transport, encryption=CredentialEncryption(KEY)
    )
    first = await service.sync_scope_peer(user.id, 42)
    second = await service.sync_scope_peer(user.id, 42)
    assert json.loads(transport.calls[0][1])["entity_type"] == "user"
    assert transport.calls[0][2]["limit"] > 0
    assert first.created == 1
    assert second.unchanged == 1
    assert row.history_latest_message_id == 1
    obj = db_session.scalar(select(Object).where(Object.user_id == user.id))
    assert obj.metadata_["peer_kind"] == "private"
    assert obj.metadata_["peer_title"] == "Private peer"
    assert obj.metadata_["peer_username"] == "private_user"
    assert obj.external_id == f"mtproto|{account.id}|42|1"


@pytest.mark.asyncio
async def test_supergroup_scope_sync_uses_shared_engine(db_session):
    user, account = _db_account(db_session, "A4.2 supergroup history")
    reference = json.dumps({"entity_type": "channel", "id": 1007, "access_hash": 88})
    store = TelegramMtprotoAccountStore(db_session, CredentialEncryption(KEY))
    row = store.save_selection(account.id, SimpleNamespace(
        peer_id=-1007, kind="supergroup", provider_peer_reference=reference,
        title="Supergroup", username="super", is_forum=False,
    ))
    row.scope_active = True
    db_session.flush()
    transport = _HistoryTransport([
        TelegramMtprotoHistoryPage((_history_entry(7),), False),
    ])
    result = await TelegramMtprotoHistoryService(
        db_session, transport_factory=lambda: transport,
        encryption=CredentialEncryption(KEY),
    ).sync_scope_peer(user.id, -1007)
    assert result.created == 1
    assert json.loads(transport.calls[0][1]) == json.loads(reference)
    assert transport.calls[0][2]["limit"] > 0
    assert row.history_latest_message_id == 7
    obj = db_session.scalar(select(Object).where(Object.user_id == user.id))
    assert obj.metadata_["peer_kind"] == "supergroup"
    assert obj.metadata_["group_title"] == "Supergroup"


@pytest.mark.asyncio
async def test_complete_empty_scope_deactivates_but_retains_row(db_session):
    user, _, _, row = _scope_seed(db_session)
    db_session.query(TelegramMtprotoSyncFolder).filter(
        TelegramMtprotoSyncFolder.account_id == row.account_id
    ).delete(synchronize_session=False)
    db_session.flush()
    await TelegramMtprotoScopeService(
        db_session, transport_factory=lambda: _Transport(), encryption=CredentialEncryption(KEY)
    ).reconcile_scope(user.id)
    assert row.scope_active is False
    assert db_session.get(TelegramMtprotoChatSelection, row.id) is row
    assert row.history_latest_message_id == 22


def test_scoped_zero_peer_is_rejected_before_service(monkeypatch):
    monkeypatch.setattr(telegram_api, "mtproto_is_configured", lambda: True)
    called = False

    class FakeHistory:
        def __init__(self, session):
            nonlocal called
            called = True

    monkeypatch.setattr(telegram_api, "TelegramMtprotoHistoryService", FakeHistory)
    with pytest.raises(telegram_api.HTTPException) as raised:
        import asyncio

        asyncio.run(telegram_api.telegram_mtproto_scope_peer_sync(
            peer_id=0, session=object(), current_user=SimpleNamespace(user_id=uuid4())
        ))
    assert raised.value.status_code == 422
    assert called is False


def _history_summary(peer_id):
    return SimpleNamespace(
        peer_id=peer_id, scanned=0, materialized=0, created=0, updated=0,
        unchanged=0, skipped=0, jobs_enqueued=0, history_complete=True,
    )


def test_scoped_http_signed_peer_boundaries(auth_client, monkeypatch):
    monkeypatch.setattr(telegram_api, "mtproto_is_configured", lambda: True)
    calls = []

    class FakeHistory:
        def __init__(self, session):
            pass

        async def sync_scope_peer(self, user_id, peer_id):
            calls.append(peer_id)
            return _history_summary(peer_id)

    monkeypatch.setattr(telegram_api, "TelegramMtprotoHistoryService", FakeHistory)
    for peer_id in (42, -42):
        response = auth_client.post(f"/telegram/mtproto/sync-scope/peers/{peer_id}/sync")
        assert response.status_code == 200
    assert calls == [42, -42]
    for peer_id in (0, -(2**63) - 1, 2**63):
        response = auth_client.post(f"/telegram/mtproto/sync-scope/peers/{peer_id}/sync")
        assert response.status_code == 422
    assert calls == [42, -42]


@pytest.mark.parametrize(
    ("error", "status_code", "detail", "headers"),
    [
        (
            TelegramMtprotoProviderReferenceInvalidError("secret provider text"),
            409,
            "Telegram peer is no longer available",
            {},
        ),
        (
            TelegramMtprotoAuthorizationInvalidError("Telegram authorization is invalid"),
            409,
            "Telegram authorization is invalid",
            {},
        ),
        (
            TelegramMtprotoProviderUnavailableError("secret provider text", 37),
            503,
            "Telegram provider is temporarily unavailable",
            {"retry-after": "37"},
        ),
    ],
)
def test_scoped_http_error_mappings_are_sanitized(
    auth_client, monkeypatch, error, status_code, detail, headers
):
    monkeypatch.setattr(telegram_api, "mtproto_is_configured", lambda: True)

    class FakeHistory:
        def __init__(self, session):
            pass

        async def sync_scope_peer(self, user_id, peer_id):
            raise error

    monkeypatch.setattr(telegram_api, "TelegramMtprotoHistoryService", FakeHistory)
    response = auth_client.post("/telegram/mtproto/sync-scope/peers/42/sync")
    assert response.status_code == status_code
    assert response.json()["detail"] == detail
    assert "secret" not in response.text
    for name, value in headers.items():
        assert response.headers[name] == value
