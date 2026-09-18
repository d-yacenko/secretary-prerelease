"""Telegram MTProto C2B deterministic notification regressions."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_transport import (
    TelegramMtprotoHistoryEntry,
    TelegramMtprotoHistoryPage,
)
from app.core.config import settings
from app.db.models import Notification
from app.services.telegram_mtproto_history_service import TelegramMtprotoHistoryService
from tests.test_telegram_mtproto_c1a import _fixture


@pytest.fixture
def credential_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "secretary_credential_key", key)
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    return key


def _entry(message_id: int, *, outgoing: bool = False, edited_at=None) -> TelegramMtprotoHistoryEntry:
    return TelegramMtprotoHistoryEntry(
        message_id=message_id,
        occurred_at=datetime.now(UTC),
        text=f"message {message_id}",
        sender_peer_id=777 if outgoing else 888,
        reply_to_message_id=None,
        topic_id=None,
        edited_at=edited_at,
        is_service=False,
        outgoing=outgoing,
    )


class _ForwardTransport:
    def __init__(self, entries):
        self.entries = entries

    async def fetch_history(self, session, reference, **kwargs):
        return TelegramMtprotoHistoryPage(entries=tuple(self.entries), has_more=False)


class _RecentTransport:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def fetch_message(self, session, reference, *, peer_id, message_id):
        self.calls.append((peer_id, message_id))
        return self.result


def _service(db_session, key, transport):
    return TelegramMtprotoHistoryService(
        db_session,
        transport_factory=lambda: transport,
        encryption=CredentialEncryption(key),
    )


def _notifications(db_session, user_id):
    return list(
        db_session.scalars(
            select(Notification).where(Notification.user_id == user_id)
        )
    )


@pytest.mark.asyncio
async def test_initial_100_inbound_history_messages_create_no_notifications(
    db_session, credential_key
):
    user, _, selection, _ = _fixture(db_session, credential_key)
    transport = _ForwardTransport([_entry(message_id) for message_id in range(1, 101)])

    await _service(db_session, credential_key, transport).sync_scope_peer(
        user.id, selection.peer_id
    )

    assert _notifications(db_session, user.id) == []


@pytest.mark.asyncio
async def test_established_forward_cursor_creates_one_deterministic_inbound_event(
    db_session, credential_key
):
    user, account, selection, obj = _fixture(db_session, credential_key)
    selection.history_latest_message_id = 41
    entry = _entry(42)
    await _service(db_session, credential_key, _ForwardTransport([entry])).sync_scope_peer(
        user.id, selection.peer_id
    )

    notes = _notifications(db_session, user.id)
    assert len(notes) == 1
    note = notes[0]
    assert note.source_object_id != obj.id
    assert note.proposal_["type"] == "transport_event"
    assert note.proposal_["event_type"] == "message_created"
    assert note.proposal_["event_key"].endswith(":42:created")
    assert note.proposal_["account_id"] == str(account.id)
    assert note.proposal_["peer_id"] == selection.peer_id
    assert "provider_peer_reference" not in json.dumps(note.proposal_)
    assert "session" not in json.dumps(note.proposal_)

    await _service(db_session, credential_key, _ForwardTransport([entry])).sync_scope_peer(
        user.id, selection.peer_id
    )
    assert db_session.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == user.id)
    ) == 1


@pytest.mark.asyncio
async def test_outgoing_forward_message_creates_no_event(db_session, credential_key):
    user, _, selection, _ = _fixture(db_session, credential_key)
    selection.history_latest_message_id = 41
    await _service(
        db_session, credential_key, _ForwardTransport([_entry(42, outgoing=True)])
    ).sync_scope_peer(user.id, selection.peer_id)
    assert _notifications(db_session, user.id) == []


@pytest.mark.asyncio
async def test_remote_edit_is_deterministic_and_later_revision_is_new_event(
    db_session, credential_key
):
    user, account, selection, obj = _fixture(db_session, credential_key)
    first_edit = datetime.now(UTC) + timedelta(seconds=1)
    result = {
        "peer_id": selection.peer_id,
        "message_id": obj.metadata_["message_id"],
        "text": "edited once",
        "occurred_at": obj.occurred_at,
        "edited_at": first_edit,
        "sender_peer_id": 888,
        "outgoing": False,
        "service": False,
    }
    transport = _RecentTransport(result)
    service = _service(db_session, credential_key, transport)
    await service.reconcile_recent_messages(user.id, account.id, {})
    await service.reconcile_recent_messages(user.id, account.id, {})
    assert len(_notifications(db_session, user.id)) == 1
    assert _notifications(db_session, user.id)[0].proposal_["event_type"] == "message_edited"

    result["text"] = "edited twice"
    result["edited_at"] = first_edit + timedelta(seconds=1)
    await service.reconcile_recent_messages(user.id, account.id, {})
    assert len(_notifications(db_session, user.id)) == 2


@pytest.mark.asyncio
async def test_remote_confirmed_inbound_delete_tombstones_and_is_idempotent(
    db_session, credential_key
):
    user, account, _, obj = _fixture(db_session, credential_key)
    transport = _RecentTransport(None)
    service = _service(db_session, credential_key, transport)
    await service.reconcile_recent_messages(user.id, account.id, {})
    db_session.refresh(obj)
    assert obj.deleted_at is not None
    notes = _notifications(db_session, user.id)
    assert len(notes) == 1
    assert notes[0].proposal_["event_type"] == "message_deleted"

    await service.reconcile_recent_messages(user.id, account.id, {})
    assert len(_notifications(db_session, user.id)) == 1


@pytest.mark.asyncio
async def test_outgoing_remote_edit_has_no_transport_event(db_session, credential_key):
    user, account, selection, obj = _fixture(db_session, credential_key)
    obj.metadata_ = {**obj.metadata_, "direction": "outbound"}
    db_session.flush()
    result = {
        "peer_id": selection.peer_id,
        "message_id": obj.metadata_["message_id"],
        "text": "outgoing edit",
        "occurred_at": obj.occurred_at,
        "edited_at": datetime.now(UTC) + timedelta(seconds=1),
        "sender_peer_id": selection.peer_id,
        "outgoing": True,
        "service": False,
    }
    await _service(db_session, credential_key, _RecentTransport(result)).reconcile_recent_messages(
        user.id, account.id, {}
    )
    assert _notifications(db_session, user.id) == []
