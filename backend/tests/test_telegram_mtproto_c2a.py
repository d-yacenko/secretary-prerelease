"""Telegram MTProto C2A bounded recent-message reconciliation regressions."""

import json
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoAuthorizationInvalidError,
    TelegramMtprotoProviderUnavailableError,
    TelegramMtprotoReadRejectedError,
    classify_telegram_sync_failure,
)
from app.connectors.telegram.mtproto_transport import (
    TelegramMtprotoHistoryEntry,
    TelethonMtprotoTransport,
)
from app.core.config import Settings, settings
from app.db.models import Job, Object, TelegramMtprotoChatSelection
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
from app.services.telegram_mtproto_history_service import (
    TELEGRAM_MTPROTO_RECONCILE_CURSORS_KEY,
    TELEGRAM_MTPROTO_RECONCILE_HEAD_KEY,
    TELEGRAM_MTPROTO_RECONCILE_MODES_KEY,
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
    transport2 = _RecentTransport(error=TelegramMtprotoProviderUnavailableError("temporary"))
    with pytest.raises(TelegramMtprotoProviderUnavailableError):
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
    user, account, selection, _ = _fixture(db_session, credential_key)
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
    assert TELEGRAM_MTPROTO_RECONCILE_CURSORS_KEY in payload
    assert str(selection.peer_id) in payload[TELEGRAM_MTPROTO_RECONCILE_CURSORS_KEY]
    first_run = len(transport.calls)

    await service.reconcile_recent_messages(user.id, account.id, payload)
    assert len(transport.calls) > first_run
    assert len(transport.calls) <= 10


@pytest.mark.asyncio
async def test_rotating_recent_first_peers_prevents_busy_peer_starvation(
    db_session, credential_key
):
    user, account, selection, _ = _fixture(db_session, credential_key)
    encryption = CredentialEncryption(credential_key)
    second = TelegramMtprotoChatSelection(
        account_id=account.id,
        peer_id=-100,
        peer_kind="group",
        provider_peer_reference_encrypted=encryption.encrypt(
            json.dumps({"entity_type": "chat", "id": 100})
        ),
        title="Group",
        scope_active=True,
    )
    db_session.add(second)
    now = datetime.now(UTC)
    for message_id in range(42, 55):
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
    for message_id in (1, 2):
        db_session.add(
            Object(
                user_id=user.id,
                kind="chat_message",
                provider="telegram",
                external_id=f"mtproto|{account.id}|-100|{message_id}",
                origin="source",
                state="observed",
                title="Group: old",
                body="old",
                metadata_={
                    "transport": "mtproto",
                    "account_id": str(account.id),
                    "peer_id": -100,
                    "message_id": message_id,
                },
                occurred_at=now,
            )
        )
    db_session.flush()
    transport = _RecentTransport(
        lambda peer_id, message_id: {
            "peer_id": peer_id,
            "message_id": message_id,
            "text": "same",
            "occurred_at": now,
            "edited_at": None,
            "outgoing": False,
            "service": False,
        }
    )
    payload = {}
    service = _history(db_session, credential_key, transport)
    await service.reconcile_recent_messages(user.id, account.id, payload)

    assert len(transport.calls) <= 20
    assert sum(peer_id == selection.peer_id for peer_id, _ in transport.calls) <= 5
    assert sum(peer_id == -100 for peer_id, _ in transport.calls) == 2
    assert set(payload[TELEGRAM_MTPROTO_RECONCILE_CURSORS_KEY]) == {
        str(selection.peer_id),
        "-100",
    }


@pytest.mark.asyncio
async def test_provider_flood_wait_aborts_remaining_reconciliation_and_preserves_delay(
    db_session, credential_key
):
    user, account, _, _ = _fixture(db_session, credential_key)
    transport = _RecentTransport(error=TelegramMtprotoProviderUnavailableError("busy", 23))
    with pytest.raises(TelegramMtprotoProviderUnavailableError) as exc_info:
        await _history(db_session, credential_key, transport).reconcile_recent_messages(
            user.id, account.id, {}
        )
    assert exc_info.value.retry_after_seconds == 23
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_reconciliation_read_rejection_is_peer_local(db_session, credential_key):
    user, account, first_selection, first_obj = _fixture(db_session, credential_key)
    encryption = CredentialEncryption(credential_key)
    second_selection = TelegramMtprotoChatSelection(
        account_id=account.id,
        peer_id=-100,
        peer_kind="group",
        provider_peer_reference_encrypted=encryption.encrypt(
            json.dumps({"entity_type": "chat", "id": 100})
        ),
        title="Group",
        scope_active=True,
    )
    db_session.add(second_selection)
    second_obj = Object(
        user_id=user.id,
        kind="chat_message",
        provider="telegram",
        external_id=f"mtproto|{account.id}|-100|1",
        origin="source",
        state="observed",
        title="Group: hello",
        body="hello",
        metadata_={
            "transport": "mtproto",
            "account_id": str(account.id),
            "peer_id": -100,
            "message_id": 1,
        },
        occurred_at=datetime.now(UTC),
    )
    db_session.add(second_obj)
    db_session.flush()

    def result(peer_id, message_id):
        if peer_id == first_selection.peer_id:
            raise TelegramMtprotoReadRejectedError("lookup rejected")
        return _provider_message(second_obj, text="updated")

    transport = _RecentTransport(result)
    await _history(db_session, credential_key, transport).reconcile_recent_messages(
        user.id, account.id, {}
    )
    assert any(peer_id == -100 for peer_id, _ in transport.calls)
    db_session.refresh(first_obj)
    assert first_obj.deleted_at is None


@pytest.mark.asyncio
async def test_reconciliation_head_recheck_and_sweep_wrap_cover_old_rows(
    db_session, credential_key
):
    user, account, selection, original = _fixture(db_session, credential_key)
    now = datetime.now(UTC)
    for message_id in range(100, 106):
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
    seen: list[int] = []
    transport = _RecentTransport(
        lambda peer_id, message_id: (
            seen.append(message_id)
            or {
                "peer_id": peer_id,
                "message_id": message_id,
                "text": "same",
                "occurred_at": now,
                "edited_at": None,
                "outgoing": False,
                "service": False,
            }
        )
    )
    payload = {}
    service = _history(db_session, credential_key, transport)
    for _ in range(4):
        await service.reconcile_recent_messages(user.id, account.id, payload)
    assert len(seen) <= 20
    assert {message_id for message_id in seen} >= {41, 100, 101, 102, 103, 104, 105}
    assert seen[0] != 41 or 41 in seen
    assert original.id is not None


@pytest.mark.asyncio
async def test_reconciliation_malformed_message_id_advances_without_provider_call(
    db_session, credential_key
):
    user, account, selection, _ = _fixture(db_session, credential_key)
    malformed = Object(
        user_id=user.id,
        kind="chat_message",
        provider="telegram",
        external_id=f"mtproto|{account.id}|{selection.peer_id}|bad",
        origin="source",
        state="observed",
        title="Alice: malformed",
        body="bad",
        metadata_={
            "transport": "mtproto",
            "account_id": str(account.id),
            "peer_id": selection.peer_id,
            "message_id": True,
        },
        occurred_at=datetime.now(UTC),
    )
    db_session.add(malformed)
    db_session.flush()
    transport = _RecentTransport(_provider_message(malformed, message_id=41))
    await _history(db_session, credential_key, transport).reconcile_recent_messages(
        user.id, account.id, {}
    )
    assert all(message_id is not True for _, message_id in transport.calls)
    assert len(transport.calls) <= 5


@pytest.mark.asyncio
async def test_head_and_sweep_use_independent_state_and_both_progress(
    db_session, credential_key
):
    user, account, selection, _ = _fixture(db_session, credential_key)
    base = datetime.now(UTC)
    for offset, message_id in enumerate(range(100, 106)):
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
                occurred_at=base.replace(microsecond=offset),
            )
        )
    db_session.flush()
    transport = _RecentTransport(
        lambda peer_id, message_id: {
            "peer_id": peer_id,
            "message_id": message_id,
            "text": "same",
            "occurred_at": base,
            "edited_at": None,
            "outgoing": False,
            "service": False,
        }
    )
    payload = {}
    service = _history(db_session, credential_key, transport)
    await service.reconcile_recent_messages(user.id, account.id, payload)
    sweep_cursor = payload[TELEGRAM_MTPROTO_RECONCILE_CURSORS_KEY][str(selection.peer_id)]
    assert TELEGRAM_MTPROTO_RECONCILE_HEAD_KEY in payload
    assert payload[TELEGRAM_MTPROTO_RECONCILE_HEAD_KEY] == {}
    assert payload[TELEGRAM_MTPROTO_RECONCILE_MODES_KEY][str(selection.peer_id)] == "head"

    calls_before_head = len(transport.calls)
    await service.reconcile_recent_messages(user.id, account.id, payload)
    assert payload[TELEGRAM_MTPROTO_RECONCILE_CURSORS_KEY][str(selection.peer_id)] == sweep_cursor
    assert payload[TELEGRAM_MTPROTO_RECONCILE_HEAD_KEY][str(selection.peer_id)]
    assert payload[TELEGRAM_MTPROTO_RECONCILE_MODES_KEY][str(selection.peer_id)] == "sweep"
    assert len(transport.calls) == calls_before_head + 1

    await service.reconcile_recent_messages(user.id, account.id, payload)
    assert payload[TELEGRAM_MTPROTO_RECONCILE_CURSORS_KEY][str(selection.peer_id)] != sweep_cursor


@pytest.mark.asyncio
async def test_recent_window_finds_new_and_second_recent_edits_before_sweep_wrap(
    db_session, credential_key
):
    user, account, selection, _ = _fixture(db_session, credential_key)
    base = datetime.now(UTC)
    objects = []
    for offset, message_id in enumerate((200, 201, 202, 203, 204)):
        obj = Object(
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
            occurred_at=base.replace(microsecond=offset),
        )
        objects.append(obj)
        db_session.add(obj)
    db_session.flush()
    transport = _RecentTransport(
        lambda peer_id, message_id: {
            "peer_id": peer_id,
            "message_id": message_id,
            "text": "updated" if message_id == 202 else "same",
            "occurred_at": base,
            "edited_at": None,
            "outgoing": False,
            "service": False,
        }
    )
    payload = {}
    service = _history(db_session, credential_key, transport)
    await service.reconcile_recent_messages(user.id, account.id, payload)
    db_session.refresh(objects[2])
    objects[2].body = "locally old"
    db_session.flush()
    await service.reconcile_recent_messages(user.id, account.id, payload)
    await service.reconcile_recent_messages(user.id, account.id, payload)
    assert 202 in [message_id for _, message_id in transport.calls]
    assert len(transport.calls) <= 15


@pytest.mark.asyncio
async def test_account_rotation_advances_after_last_serviced_peer_not_one_step(
    db_session, credential_key
):
    user, account, _, _ = _fixture(db_session, credential_key)
    encryption = CredentialEncryption(credential_key)
    now = datetime.now(UTC)
    peers = []
    for peer_number in range(25):
        peer_id = -1000 - peer_number
        peers.append(peer_id)
        db_session.add(
            TelegramMtprotoChatSelection(
                account_id=account.id,
                peer_id=peer_id,
                peer_kind="group",
                provider_peer_reference_encrypted=encryption.encrypt(
                    json.dumps({"entity_type": "chat", "id": 1000 + peer_number})
                ),
                title=f"Group {peer_number}",
                scope_active=True,
            )
        )
        db_session.add(
            Object(
                user_id=user.id,
                kind="chat_message",
                provider="telegram",
                external_id=f"mtproto|{account.id}|{peer_id}|1",
                origin="source",
                state="observed",
                title="Group: old",
                body="old",
                metadata_={
                    "transport": "mtproto",
                    "account_id": str(account.id),
                    "peer_id": peer_id,
                    "message_id": 1,
                },
                occurred_at=now,
            )
        )
    db_session.flush()
    transport = _RecentTransport(
        lambda peer_id, message_id: {
            "peer_id": peer_id,
            "message_id": message_id,
            "text": "same",
            "occurred_at": now,
            "edited_at": None,
            "outgoing": False,
            "service": False,
        }
    )
    payload = {}
    service = _history(db_session, credential_key, transport)
    await service.reconcile_recent_messages(user.id, account.id, payload)
    first_window = [peer_id for peer_id, _ in transport.calls]
    assert len(first_window) == 20
    await service.reconcile_recent_messages(user.id, account.id, payload)
    second_window = [peer_id for peer_id, _ in transport.calls[20:]]
    assert len(second_window) == 20
    assert second_window[0] == sorted(peers)[20]
    assert len(set(first_window)) == 20
    assert len(set(second_window)) == 20


@pytest.mark.asyncio
async def test_telethon_flood_wait_read_is_transient_and_preserves_retry_after(monkeypatch):
    from telethon.errors import FloodWaitError
    from telethon.sessions import StringSession

    class FloodClient:
        def __init__(self, *args):
            pass

        async def connect(self):
            return None

        async def is_user_authorized(self):
            return True

        async def get_messages(self, peer, ids):
            raise FloodWaitError(None, 19)

        async def disconnect(self):
            return None

    monkeypatch.setattr("app.connectors.telegram.mtproto_transport.TelegramClient", FloodClient)
    with pytest.raises(TelegramMtprotoProviderUnavailableError) as exc_info:
        await TelethonMtprotoTransport(1, "hash").fetch_message(
            StringSession().save(), json.dumps({"entity_type": "user", "id": 777, "access_hash": 99}),
            peer_id=777, message_id=41,
        )
    assert exc_info.value.retry_after_seconds == 19
    assert classify_telegram_sync_failure(exc_info.value) == ("transient", True, 19)


@pytest.mark.asyncio
async def test_telethon_auth_invalid_read_is_authentication(monkeypatch):
    from telethon.sessions import StringSession

    class UnauthorizedClient:
        def __init__(self, *args):
            pass

        async def connect(self):
            return None

        async def is_user_authorized(self):
            return False

        async def disconnect(self):
            return None

    monkeypatch.setattr(
        "app.connectors.telegram.mtproto_transport.TelegramClient", UnauthorizedClient
    )
    with pytest.raises(TelegramMtprotoAuthorizationInvalidError) as exc_info:
        await TelethonMtprotoTransport(1, "hash").fetch_message(
            StringSession().save(), json.dumps({"entity_type": "user", "id": 777, "access_hash": 99}),
            peer_id=777, message_id=41,
        )
    assert classify_telegram_sync_failure(exc_info.value) == ("authentication", False, None)


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
