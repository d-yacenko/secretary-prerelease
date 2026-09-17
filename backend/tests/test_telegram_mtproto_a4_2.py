"""Telegram Depth A4.2 — durable dynamic scope and explicit peer sync."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from telethon.tl import types

from app.connectors.telegram.mtproto_errors import TelegramMtprotoScopeUnavailableError
from app.connectors.telegram.mtproto_transport import (
    TelegramMtprotoDialogDescriptor,
    TelegramMtprotoFolderDescriptor,
    TelegramMtprotoFolderDialogsResult,
    TelegramMtprotoFolderDiscoveryResult,
)
from app.db.models import TelegramMtprotoChatSelection
from app.services.telegram_mtproto_scope_service import TelegramMtprotoScopeService


def _dialog(peer_id: int, kind: str = "private") -> TelegramMtprotoDialogDescriptor:
    return TelegramMtprotoDialogDescriptor(
        peer_id=peer_id,
        kind=kind,
        title=f"Peer {peer_id}",
        username=None,
        is_muted=False,
        provider_peer_reference=f"peer:{peer_id}",
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
    def __init__(self, *, truncated=False):
        self.truncated = truncated
        self.history_called = False

    async def discover_folders(self, session, limit):
        return TelegramMtprotoFolderDiscoveryResult(
            (TelegramMtprotoFolderDescriptor(7, "Configured", _filter()),), False
        )

    async def fetch_dialog_universe(self, session, limit):
        return TelegramMtprotoFolderDialogsResult((_dialog(1),), self.truncated, {})

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


def test_migration_0046_is_single_head():
    config = Config("alembic.ini")
    assert ScriptDirectory.from_config(config).get_heads() == ["0046"]
