"""Telegram Depth A3 — bounded selected-group history import."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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

from app.api.telegram_mtproto import INVALID_MTPROTO_REQUEST_DETAIL
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.constants import TELEGRAM_KIND, TELEGRAM_PROVIDER
from app.connectors.telegram.materialize import TelegramObjectMaterializer
from app.connectors.telegram.mtproto_account_store import TelegramMtprotoAccountStore
from app.connectors.telegram.mtproto_errors import TelegramMtprotoProviderUnavailableError
from app.connectors.telegram.mtproto_transport import (
    TELEGRAM_MTPROTO_HISTORY_PAGE_SIZE,
    TelegramMtprotoGroupDescriptor,
    TelegramMtprotoHistoryEntry,
    TelegramMtprotoHistoryPage,
    TelethonMtprotoTransport,
    _input_peer_from_reference,
)
from app.core.config import settings
from app.db.models import Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection, User
from app.services.telegram_mtproto_history_service import (
    TELEGRAM_MTPROTO_HISTORY_MAX_MESSAGES_PER_RUN,
    TELEGRAM_MTPROTO_SCOPE_BOOTSTRAP_MESSAGES,
    TelegramMtprotoHistoryService,
)

KEY = Fernet.generate_key().decode()
SESSION = "session-only-inside-fake-transport"
API_HASH = "api-hash-only-in-settings"


@pytest.fixture(autouse=True)
def _enable_mtproto_ai_for_legacy_a3_regressions(monkeypatch):
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)


class FakeHistoryTransport:
    def __init__(self, pages: list[TelegramMtprotoHistoryPage]) -> None:
        self.pages = pages
        self.calls: list[dict] = []

    async def fetch_history(self, session, provider_peer_reference, **kwargs):
        self.calls.append(
            {
                "session": session,
                "reference": provider_peer_reference,
                **kwargs,
            }
        )
        if not self.pages:
            return TelegramMtprotoHistoryPage((), False)
        return self.pages.pop(0)


def _user(db_session, name: str = "history-user") -> User:
    user = User(id=uuid4(), display_name=name)
    db_session.add(user)
    db_session.flush()
    return user


def _account(db_session, user_id, *, account_id=None) -> TelegramMtprotoAccount:
    account = TelegramMtprotoAccount(
        id=account_id or uuid4(),
        user_id=user_id,
        telegram_user_id=uuid4().int % 2_000_000_000,
        session_encrypted=CredentialEncryption(KEY).encrypt(SESSION),
        username="history-user",
        display_name="History User",
    )
    db_session.add(account)
    db_session.flush()
    return account


def _descriptor(
    peer_id: int = -1001234567890,
    *,
    kind: str = "supergroup",
    title: str = "Selected group",
    access_hash: int = 987654,
) -> TelegramMtprotoGroupDescriptor:
    if kind == "group":
        reference = {"entity_type": "chat", "id": abs(peer_id)}
    else:
        reference = {
            "entity_type": "channel",
            "id": abs(peer_id),
            "access_hash": access_hash,
        }
    return TelegramMtprotoGroupDescriptor(
        peer_id=peer_id,
        kind=kind,
        title=title,
        username="selected",
        is_forum=False,
        provider_peer_reference=json.dumps(reference),
    )


def _selection(db_session, account, descriptor=None):
    descriptor = descriptor or _descriptor()
    selection = TelegramMtprotoAccountStore(db_session, CredentialEncryption(KEY)).save_selection(
        account.id, descriptor
    )
    selection.scope_active = True
    db_session.flush()
    return selection


def _entry(message_id: int, text: str | None = "text", *, days_ago=1, service=False):
    return TelegramMtprotoHistoryEntry(
        message_id=message_id,
        occurred_at=datetime.now(UTC) - timedelta(days=days_ago),
        text=text,
        sender_peer_id=-42,
        reply_to_message_id=None,
        topic_id=None,
        edited_at=None,
        is_service=service,
    )


def _page(entries, *, has_more=False):
    return TelegramMtprotoHistoryPage(tuple(entries), has_more)


def _service(db_session, transport):
    return TelegramMtprotoHistoryService(
        db_session,
        transport_factory=lambda: transport,
        encryption=CredentialEncryption(KEY),
    )


@pytest.fixture(autouse=True)
def configured_mtproto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_api_id", 123456)
    monkeypatch.setattr(settings, "telegram_api_hash", API_HASH)
    monkeypatch.setattr(settings, "secretary_credential_key", KEY)


async def test_unselected_group_does_not_call_history_provider(db_session):
    user = _user(db_session)
    _account(db_session, user.id)
    transport = FakeHistoryTransport([])

    from app.connectors.telegram.mtproto_errors import TelegramMtprotoGroupNotSelectedError

    with pytest.raises(TelegramMtprotoGroupNotSelectedError):
        await _service(db_session, transport).sync_group(user.id, -1001234567890)
    assert transport.calls == []


@pytest.mark.parametrize("peer_id", ["0", "1", str(-(2**63) - 1), str(2**63 + 1)])
def test_sync_rejects_unbounded_peer_ids_with_sanitized_validation(
    auth_client, peer_id, monkeypatch
):
    monkeypatch.setattr(settings, "secretary_credential_key", KEY)
    calls = []

    async def fail_if_called(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("invalid peer reached history service")

    monkeypatch.setattr(TelegramMtprotoHistoryService, "sync_group", fail_if_called)
    response = auth_client.post(f"/telegram/mtproto/groups/{peer_id}/sync")

    assert response.status_code == 422
    assert response.json() == {"detail": INVALID_MTPROTO_REQUEST_DETAIL}
    assert peer_id not in response.text
    assert calls == []


def test_sync_without_account_is_controlled(auth_client):
    response = auth_client.post("/telegram/mtproto/groups/-1001234567890/sync")

    assert response.status_code == 409
    assert response.json() == {"detail": "Telegram MTProto account is not connected"}


async def test_history_uses_selected_users_decrypted_session_and_reference(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    transport = FakeHistoryTransport([_page([_entry(1)])])

    await _service(db_session, transport).sync_group(user.id, selection.peer_id)

    assert transport.calls[0]["session"] == SESSION
    assert json.loads(transport.calls[0]["reference"])["entity_type"] == "channel"
    assert transport.calls[0]["limit"] == TELEGRAM_MTPROTO_HISTORY_PAGE_SIZE


async def test_initial_sync_is_bounded_chronological_and_sets_cursors(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    transport = FakeHistoryTransport(
        [
            _page([_entry(3), _entry(2), _entry(1)], has_more=True),
            _page([_entry(0, "outside", days_ago=20)], has_more=False),
        ]
    )

    result = await _service(db_session, transport).sync_group(user.id, selection.peer_id)

    assert result.scanned == 4
    assert result.materialized == 3
    assert result.skipped == 1
    assert result.history_complete is True
    refreshed = db_session.get(TelegramMtprotoChatSelection, selection.id)
    assert refreshed.history_latest_message_id == 3
    assert refreshed.history_backfill_before_message_id is None
    assert refreshed.history_cutoff_at is not None
    objects = list(
        db_session.scalars(
            select(Object).where(Object.user_id == user.id).order_by(Object.external_id)
        )
    )
    assert [obj.metadata_["message_id"] for obj in objects] == [1, 2, 3]


async def test_fresh_scope_bootstrap_is_one_newest_first_page(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    entries = [_entry(message_id) for message_id in range(1, 21)]
    transport = FakeHistoryTransport([_page(entries, has_more=True), _page([_entry(0)])])

    result = await _service(db_session, transport).sync_scope_peer(user.id, selection.peer_id)

    assert result.scanned == TELEGRAM_MTPROTO_SCOPE_BOOTSTRAP_MESSAGES
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["limit"] == TELEGRAM_MTPROTO_SCOPE_BOOTSTRAP_MESSAGES
    assert call["reverse"] is False
    assert call["min_message_id"] is None
    assert call["max_message_id"] is None
    assert selection.history_latest_message_id == 20
    assert selection.history_backfill_before_message_id is None
    assert selection.history_complete is True


async def test_fresh_scope_empty_page_is_complete_without_second_fetch(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    transport = FakeHistoryTransport([_page([], has_more=True), _page([_entry(2)])])

    result = await _service(db_session, transport).sync_scope_peer(user.id, selection.peer_id)

    assert result.scanned == 0
    assert len(transport.calls) == 1
    assert selection.history_latest_message_id is None
    assert selection.history_backfill_before_message_id is None
    assert selection.history_complete is True


async def test_fresh_scope_skipped_entries_do_not_trigger_backfill(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    entries = [_entry(message_id, None if message_id < 20 else "kept") for message_id in range(1, 21)]
    transport = FakeHistoryTransport([_page(entries, has_more=True), _page([_entry(30)])])

    result = await _service(db_session, transport).sync_scope_peer(user.id, selection.peer_id)

    assert result.materialized == 1
    assert len(transport.calls) == 1
    assert selection.history_latest_message_id == 20
    assert selection.history_backfill_before_message_id is None
    assert selection.history_complete is True


async def test_existing_scope_is_incremental_and_preserves_legacy_backfill_state(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    selection.history_latest_message_id = 10
    selection.history_backfill_before_message_id = 5
    selection.history_complete = False
    selection.history_cutoff_at = datetime.now(UTC) - timedelta(days=14)
    db_session.flush()
    transport = FakeHistoryTransport([_page([_entry(11)], has_more=True), _page([_entry(4)])])

    await _service(db_session, transport).sync_scope_peer(user.id, selection.peer_id)

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["reverse"] is True
    assert call["min_message_id"] == 10
    assert call["max_message_id"] is None
    assert selection.history_latest_message_id == 11
    assert selection.history_backfill_before_message_id == 5
    assert selection.history_complete is False


async def test_incremental_reads_oldest_unseen_page_without_skipping(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    selection.history_latest_message_id = 10
    selection.history_cutoff_at = datetime.now(UTC) - timedelta(days=14)
    selection.history_complete = True
    db_session.flush()
    first_page = [_entry(message_id) for message_id in range(11, 111)]
    second_page = [_entry(message_id) for message_id in range(111, 211)]
    transport = FakeHistoryTransport([_page(first_page, has_more=True), _page(second_page)])

    first = await _service(db_session, transport).sync_group(user.id, selection.peer_id)
    second = await _service(db_session, transport).sync_group(user.id, selection.peer_id)

    assert first.scanned == TELEGRAM_MTPROTO_HISTORY_PAGE_SIZE
    assert second.scanned == TELEGRAM_MTPROTO_HISTORY_PAGE_SIZE
    assert transport.calls[0]["min_message_id"] == 10
    assert transport.calls[0]["reverse"] is True
    assert transport.calls[1]["min_message_id"] == 110
    assert db_session.get(TelegramMtprotoChatSelection, selection.id).history_latest_message_id == 210


async def test_run_never_scans_more_than_two_pages(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    transport = FakeHistoryTransport(
        [_page([_entry(i) for i in range(1, 101)], has_more=True),
         _page([_entry(i) for i in range(101, 201)], has_more=True),
         _page([_entry(201)])]
    )

    result = await _service(db_session, transport).sync_group(user.id, selection.peer_id)

    assert result.scanned == TELEGRAM_MTPROTO_HISTORY_MAX_MESSAGES_PER_RUN
    assert len(transport.calls) == 2


async def test_backfill_is_exclusive_and_stops_at_cutoff(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    selection.history_latest_message_id = 10
    selection.history_backfill_before_message_id = 5
    selection.history_cutoff_at = datetime.now(UTC) - timedelta(days=14)
    selection.history_complete = False
    db_session.flush()
    transport = FakeHistoryTransport(
        [
            _page([]),
            _page([_entry(4), _entry(3, days_ago=20)], has_more=True),
        ]
    )

    result = await _service(db_session, transport).sync_group(user.id, selection.peer_id)

    assert result.scanned == 2
    assert transport.calls[1]["max_message_id"] == 5
    assert transport.calls[1]["reverse"] is False
    refreshed = db_session.get(TelegramMtprotoChatSelection, selection.id)
    assert refreshed.history_backfill_before_message_id is None
    assert refreshed.history_complete is True


async def test_skipped_entries_advance_cursor(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    transport = FakeHistoryTransport(
        [_page([_entry(3, None), _entry(2, "", service=True), _entry(1, "kept")])]
    )

    result = await _service(db_session, transport).sync_group(user.id, selection.peer_id)

    assert result.scanned == 3
    assert result.materialized == 1
    assert result.skipped == 2
    assert db_session.get(TelegramMtprotoChatSelection, selection.id).history_latest_message_id == 3


async def test_materialization_failure_does_not_advance_cursor(db_session, monkeypatch):
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    transport = FakeHistoryTransport([_page([_entry(1)])])

    def fail(*args, **kwargs):
        raise RuntimeError("materialization failed")

    monkeypatch.setattr(TelegramObjectMaterializer, "upsert_mtproto_message", fail)
    with pytest.raises(RuntimeError):
        await _service(db_session, transport).sync_group(user.id, selection.peer_id)
    refreshed = db_session.get(TelegramMtprotoChatSelection, selection.id)
    assert refreshed.history_latest_message_id is None


async def test_repeated_import_is_idempotent_and_text_edit_is_semantic_update(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    first_entry = _entry(1, "first")
    transport = FakeHistoryTransport(
        [_page([first_entry]), _page([first_entry]), _page([_entry(1, "edited")])]
    )

    first = await _service(db_session, transport).sync_group(user.id, selection.peer_id)
    second = await _service(db_session, transport).sync_group(user.id, selection.peer_id)
    third = await _service(db_session, transport).sync_group(user.id, selection.peer_id)

    assert (first.created, first.jobs_enqueued) == (1, 1)
    assert (second.unchanged, second.jobs_enqueued) == (1, 0)
    assert (third.updated, third.jobs_enqueued) == (1, 1)
    assert db_session.scalar(
        select(func.count()).select_from(Object).where(Object.user_id == user.id)
    ) == 1


async def test_sensitive_provider_reference_never_enters_object_metadata(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    transport = FakeHistoryTransport([_page([_entry(1)])])

    await _service(db_session, transport).sync_group(user.id, selection.peer_id)

    obj = db_session.scalar(select(Object).where(Object.user_id == user.id))
    encoded = json.dumps(obj.metadata_)
    assert "access_hash" not in encoded
    assert "provider_peer_reference" not in encoded
    assert SESSION not in encoded
    assert API_HASH not in encoded
    encrypted = selection.provider_peer_reference_encrypted
    assert "access_hash" not in encrypted
    assert "access_hash" in CredentialEncryption(KEY).decrypt(encrypted)


def test_input_peer_reconstruction_requires_and_uses_access_hash():
    basic = _input_peer_from_reference('{"entity_type":"chat","id":123}')
    channel = _input_peer_from_reference(
        '{"entity_type":"channel","id":123,"access_hash":456}'
    )
    assert isinstance(basic, types.InputPeerChat)
    assert isinstance(channel, types.InputPeerChannel)
    assert channel.access_hash == 456


@pytest.mark.parametrize("reference", [
    '{"entity_type":"channel","id":123}',
    '{"entity_type":"channel","id":123,"access_hash":true}',
    '{"entity_type":"channel","id":123,"access_hash":"456"}',
])
def test_malformed_provider_reference_is_rejected(reference):
    from app.connectors.telegram.mtproto_errors import TelegramMtprotoProviderReferenceInvalidError

    with pytest.raises(TelegramMtprotoProviderReferenceInvalidError):
        _input_peer_from_reference(reference)


@pytest.mark.asyncio
async def test_transport_disconnects_on_success_and_failure(monkeypatch):
    clients = []

    class FakeClient:
        def __init__(self, *args):
            self.disconnected = False
            clients.append(self)

        async def connect(self):
            return None

        async def is_user_authorized(self):
            return True

        async def disconnect(self):
            self.disconnected = True

        async def iter_messages(self, *args, **kwargs):
            if kwargs.get("reverse"):
                raise RuntimeError("provider failure")
            yield SimpleNamespace(id=1, message="text", date=datetime.now(UTC))

    monkeypatch.setattr("app.connectors.telegram.mtproto_transport.TelegramClient", FakeClient)
    transport = TelethonMtprotoTransport(123, API_HASH)
    valid_session = StringSession().save()
    await transport.fetch_history(valid_session, '{"entity_type":"chat","id":123}', limit=1)
    with pytest.raises(TelegramMtprotoProviderUnavailableError):
        await transport.fetch_history(
            valid_session, '{"entity_type":"chat","id":123}', limit=1, reverse=True
        )
    assert all(client.disconnected for client in clients)


def test_mtproto_external_id_is_namespaced_from_business_id(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    materializer = TelegramObjectMaterializer(db_session)
    business = Object(
        user_id=user.id,
        kind=TELEGRAM_KIND,
        provider=TELEGRAM_PROVIDER,
        external_id="business-connection|123|1",
        origin="source",
        state="observed",
        title="business",
        body="same numeric message",
        metadata_={},
    )
    db_session.add(business)
    db_session.flush()
    normalized = {
        "provider": TELEGRAM_PROVIDER,
        "kind": TELEGRAM_KIND,
        "origin": "source",
        "state": "observed",
        "external_id": f"mtproto|{account.id}|{selection.peer_id}|1",
        "title": "Selected group: same numeric message",
        "body": "same numeric message",
        "occurred_at": datetime.now(UTC),
        "metadata": {"transport": "mtproto", "message_id": 1},
    }
    result = materializer.upsert_mtproto_message(user_id=user.id, normalized=normalized)
    assert result.change == "created"
    assert db_session.scalar(
        select(func.count()).select_from(Object).where(Object.user_id == user.id)
    ) == 2


def test_migration_0044_is_the_single_alembic_head():
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["0046"]
