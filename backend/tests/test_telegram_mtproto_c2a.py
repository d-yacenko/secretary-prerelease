"""Telegram MTProto C2A bounded recent-message reconciliation regressions."""

from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_errors import TelegramMtprotoWriteUncertainError
from app.connectors.telegram.mtproto_transport import TelegramMtprotoHistoryEntry
from app.core.config import Settings, settings
from app.db.models import Job, Object
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
from app.services.telegram_mtproto_history_service import (
    TELEGRAM_MTPROTO_RECONCILE_CURSOR_KEY,
    TelegramMtprotoHistoryService,
    build_mtproto_presentation_title,
)
from tests.test_telegram_mtproto_c1a import _fixture


@pytest.fixture
def credential_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "secretary_credential_key", key)
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    return key


class _RecentTransport:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def fetch_message(self, session, reference, *, peer_id, message_id):
        self.calls.append((peer_id, message_id))
        if self.error is not None:
            raise self.error
        if callable(self.result):
            return self.result(peer_id, message_id)
        return self.result


def _history(db_session, key, transport):
    return TelegramMtprotoHistoryService(
        db_session,
        transport_factory=lambda: transport,
        encryption=CredentialEncryption(key),
    )


def _provider_message(obj, *, text="edited", **overrides):
    result = {
        "peer_id": obj.metadata_["peer_id"],
        "message_id": obj.metadata_["message_id"],
        "text": text,
        "occurred_at": obj.occurred_at,
        "edited_at": datetime.now(UTC),
        "reply_to_message_id": 7,
        "sender_peer_id": obj.metadata_["peer_id"],
        "outgoing": True,
        "topic_id": 3,
        "service": False,
    }
    result.update(overrides)
    return result


@pytest.mark.asyncio
async def test_recent_remote_edit_uses_a3_materializer_and_ai_quarantine(db_session, credential_key):
    user, account, _, obj = _fixture(db_session, credential_key)
    transport = _RecentTransport(_provider_message(obj, text="remote edit"))
    service = _history(db_session, credential_key, transport)

    await service.reconcile_recent_messages(user.id, account.id, {})

    db_session.refresh(obj)
    assert obj.body == "remote edit"
    assert obj.title == build_mtproto_presentation_title("Alice", "remote edit")
    assert obj.metadata_["direction"] == "outbound"
    assert obj.metadata_["reply_to_message_id"] == 7
    assert not db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)).all()


@pytest.mark.asyncio
async def test_recent_remote_edit_enqueues_normal_current_signature_when_ai_enabled(
    db_session, credential_key, monkeypatch
):
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    user, account, _, obj = _fixture(db_session, credential_key)
    transport = _RecentTransport(_provider_message(obj, text="semantic edit"))

    await _history(db_session, credential_key, transport).reconcile_recent_messages(
        user.id, account.id, {}
    )

    assert db_session.scalar(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)) is not None


@pytest.mark.asyncio
async def test_confirmed_absence_tombstones_same_row(db_session, credential_key):
    user, account, _, obj = _fixture(db_session, credential_key)
    transport = _RecentTransport(None)
    await _history(db_session, credential_key, transport).reconcile_recent_messages(
        user.id, account.id, {}
    )
    db_session.refresh(obj)
    assert obj.deleted_at is not None
    assert obj.id is not None



@pytest.mark.asyncio
async def test_transient_failure_does_not_tombstone(db_session, credential_key):
    user2, account2, _, obj2 = _fixture(db_session, credential_key)
    transport2 = _RecentTransport(error=TelegramMtprotoWriteUncertainError("temporary"))
    await _history(db_session, credential_key, transport2).reconcile_recent_messages(
        user2.id, account2.id, {}
    )
    db_session.refresh(obj2)
    assert obj2.deleted_at is None


@pytest.mark.asyncio
async def test_mismatched_provider_result_does_not_mutate(db_session, credential_key):
    user, account, _, obj = _fixture(db_session, credential_key)
    transport = _RecentTransport(_provider_message(obj, peer_id=-100, text="wrong"))

    await _history(db_session, credential_key, transport).reconcile_recent_messages(
        user.id, account.id, {}
    )

    db_session.refresh(obj)
    assert obj.body == "hello"
    assert obj.deleted_at is None


@pytest.mark.asyncio
async def test_reconciliation_is_bounded_per_peer_and_cursor_tracks_last_inspected(
    db_session, credential_key
):
    user, account, selection, first = _fixture(db_session, credential_key)
    now = datetime.now(UTC)
    for message_id in range(42, 49):
        db_session.add(
            Object(
                user_id=user.id,
                kind="chat_message",
                provider="telegram",
                external_id=f"mtproto|{account.id}|{selection.peer_id}|{message_id}",
                origin="source",
                state="observed",
                title="Alice: old",
                body="old",
                metadata_={
                    "transport": "mtproto",
                    "account_id": str(account.id),
                    "peer_id": selection.peer_id,
                    "message_id": message_id,
                },
                occurred_at=now,
            )
        )
    db_session.flush()
    transport = _RecentTransport(lambda peer_id, message_id: {
        "peer_id": peer_id,
        "message_id": message_id,
        "text": "same",
        "occurred_at": now,
        "edited_at": None,
        "outgoing": False,
        "service": False,
    })
    payload = {}
    service = _history(db_session, credential_key, transport)

    await service.reconcile_recent_messages(user.id, account.id, payload)
    assert len(transport.calls) <= 5
    assert payload[TELEGRAM_MTPROTO_RECONCILE_CURSOR_KEY] in {
        str(first.id),
        *(str(row.id) for row in db_session.scalars(select(Object).where(Object.user_id == user.id)))
    }
    first_run = len(transport.calls)

    await service.reconcile_recent_messages(user.id, account.id, payload)
    assert len(transport.calls) > first_run
    assert len(transport.calls) <= 10


def test_cadence_default_and_override_without_other_provider_changes(monkeypatch):
    assert Settings().source_sync_telegram_mtproto_interval_seconds == 60
    monkeypatch.setenv("SOURCE_SYNC_TELEGRAM_MTPROTO_INTERVAL_SECONDS", "90")
    assert Settings().source_sync_telegram_mtproto_interval_seconds == 90
    assert Settings().source_sync_gmail_interval_seconds == 120


def test_history_entry_has_rich_reconciliation_fields():
    entry = TelegramMtprotoHistoryEntry(
        message_id=1,
        occurred_at=datetime.now(UTC),
        text="body",
        sender_peer_id=2,
        reply_to_message_id=3,
        topic_id=4,
        edited_at=datetime.now(UTC),
        is_service=False,
        outgoing=True,
    )
    assert entry.outgoing is True
    assert entry.topic_id == 4
