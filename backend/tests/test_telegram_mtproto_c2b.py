"""Telegram MTProto C2B deterministic notification regressions."""

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoPeerNotInActiveScopeError,
    TelegramMtprotoProviderUnavailableError,
)
from app.connectors.telegram.mtproto_transport import (
    TelegramMtprotoHistoryEntry,
    TelegramMtprotoHistoryPage,
)
from app.core.config import settings
from app.db.models import Edge, Job, Notification, Object
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
from app.services.recent_source_service import RecentSourceService
from app.services.telegram_mtproto_history_service import TelegramMtprotoHistoryService
from app.services.telegram_mtproto_notification_service import (
    TelegramMtprotoNotificationPersistenceError,
    TelegramMtprotoTransportNotificationService,
)
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
async def test_bounded_backfill_and_replayed_history_create_no_notifications(
    db_session, credential_key
):
    user, _, selection, _ = _fixture(db_session, credential_key)
    selection.history_latest_message_id = 100
    selection.history_backfill_before_message_id = 101
    selection.history_complete = False
    transport = _ForwardTransport([_entry(message_id) for message_id in range(1, 101)])
    service = _service(db_session, credential_key, transport)

    await service.sync_scope_peer(user.id, selection.peer_id)
    await service.sync_scope_peer(user.id, selection.peer_id)

    assert _notifications(db_session, user.id) == []


@pytest.mark.asyncio
async def test_established_forward_cursor_materializes_inbound_without_notification(
    db_session, credential_key
):
    user, account, selection, obj = _fixture(db_session, credential_key)
    selection.history_latest_message_id = 41
    entry = _entry(42)
    await _service(db_session, credential_key, _ForwardTransport([entry])).sync_scope_peer(
        user.id, selection.peer_id
    )

    created = db_session.scalar(
        select(Object).where(
            Object.user_id == user.id,
            Object.external_id == f"mtproto|{account.id}|{selection.peer_id}|42",
        )
    )
    assert created is not None
    assert created.id != obj.id
    assert created.metadata_["direction"] == "inbound"
    assert RecentSourceService(db_session, user.id).get_inbox_eligible(created.id) is created
    assert _notifications(db_session, user.id) == []

    await _service(db_session, credential_key, _ForwardTransport([entry])).sync_scope_peer(
        user.id, selection.peer_id
    )
    assert _notifications(db_session, user.id) == []
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(Object)
            .where(
                Object.user_id == user.id,
                Object.external_id == f"mtproto|{account.id}|{selection.peer_id}|42",
            )
        )
        == 1
    )


@pytest.mark.asyncio
async def test_outgoing_forward_message_creates_no_event(db_session, credential_key):
    user, _, selection, _ = _fixture(db_session, credential_key)
    selection.history_latest_message_id = 41
    await _service(
        db_session, credential_key, _ForwardTransport([_entry(42, outgoing=True)])
    ).sync_scope_peer(user.id, selection.peer_id)
    assert _notifications(db_session, user.id) == []


@pytest.mark.asyncio
async def test_two_newer_inbound_messages_create_objects_without_notifications(
    db_session, credential_key
):
    user, account, selection, _ = _fixture(db_session, credential_key)
    selection.history_latest_message_id = 41
    await _service(
        db_session,
        credential_key,
        _ForwardTransport([_entry(42), _entry(43)]),
    ).sync_scope_peer(user.id, selection.peer_id)

    external_ids = {
        db_session.scalar(
            select(Object.external_id).where(
                Object.user_id == user.id,
                Object.external_id == f"mtproto|{account.id}|{selection.peer_id}|{message_id}",
            )
        )
        for message_id in (42, 43)
    }
    assert external_ids == {
        f"mtproto|{account.id}|{selection.peer_id}|42",
        f"mtproto|{account.id}|{selection.peer_id}|43",
    }
    assert _notifications(db_session, user.id) == []


@pytest.mark.asyncio
async def test_service_message_creates_no_event(db_session, credential_key):
    user, _, selection, _ = _fixture(db_session, credential_key)
    selection.history_latest_message_id = 41
    service_entry = TelegramMtprotoHistoryEntry(
        message_id=42,
        occurred_at=datetime.now(UTC),
        text="service",
        sender_peer_id=888,
        reply_to_message_id=None,
        topic_id=None,
        edited_at=None,
        is_service=True,
        outgoing=False,
    )
    await _service(
        db_session, credential_key, _ForwardTransport([service_entry])
    ).sync_scope_peer(user.id, selection.peer_id)

    assert _notifications(db_session, user.id) == []


@pytest.mark.asyncio
async def test_inactive_scope_creates_no_event(db_session, credential_key):
    user, _, selection, _ = _fixture(db_session, credential_key, scope_active=False)
    with pytest.raises(TelegramMtprotoPeerNotInActiveScopeError):
        await _service(
            db_session, credential_key, _ForwardTransport([_entry(42)])
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


@pytest.mark.asyncio
async def test_metadata_only_edit_creates_no_event(db_session, credential_key):
    user, account, selection, obj = _fixture(db_session, credential_key)
    result = {
        "peer_id": selection.peer_id,
        "message_id": obj.metadata_["message_id"],
        "text": obj.body,
        "occurred_at": obj.occurred_at,
        "edited_at": datetime.now(UTC) + timedelta(seconds=1),
        "sender_peer_id": 888,
        "outgoing": False,
        "service": False,
    }
    await _service(
        db_session, credential_key, _RecentTransport(result)
    ).reconcile_recent_messages(user.id, account.id, {})

    assert _notifications(db_session, user.id) == []


@pytest.mark.asyncio
async def test_content_edit_without_edited_at_converges_without_event(db_session, credential_key):
    user, account, selection, obj = _fixture(db_session, credential_key)
    result = {
        "peer_id": selection.peer_id,
        "message_id": obj.metadata_["message_id"],
        "text": "content changed",
        "occurred_at": obj.occurred_at,
        "edited_at": None,
        "sender_peer_id": 888,
        "outgoing": False,
        "service": False,
    }
    await _service(
        db_session, credential_key, _RecentTransport(result)
    ).reconcile_recent_messages(user.id, account.id, {})

    assert obj.body == "content changed"
    assert _notifications(db_session, user.id) == []


@pytest.mark.asyncio
async def test_ai_false_event_has_no_embedding_job(db_session, credential_key):
    user, _, selection, _ = _fixture(db_session, credential_key)
    selection.history_latest_message_id = 41
    await _service(
        db_session,
        credential_key,
        _ForwardTransport([_entry(42)]),
    ).sync_scope_peer(user.id, selection.peer_id)

    assert _notifications(db_session, user.id) == []
    assert db_session.scalar(
        select(func.count()).select_from(Object).where(Object.user_id == user.id)
    ) == 2
    assert db_session.scalar(
        select(func.count()).select_from(Job).where(
            Job.user_id == user.id, Job.type == JOB_TYPE_EMBED_OBJECT
        )
    ) == 0


@pytest.mark.asyncio
async def test_outgoing_remote_delete_creates_no_event(db_session, credential_key):
    user, account, _, obj = _fixture(db_session, credential_key)
    obj.metadata_ = {**obj.metadata_, "direction": "outbound"}
    db_session.flush()
    await _service(
        db_session, credential_key, _RecentTransport(None)
    ).reconcile_recent_messages(user.id, account.id, {})

    assert obj.deleted_at is not None
    assert _notifications(db_session, user.id) == []


@pytest.mark.asyncio
async def test_transient_lookup_does_not_tombstone_or_notify(db_session, credential_key):
    user, account, _, obj = _fixture(db_session, credential_key)

    class _TransientTransport(_RecentTransport):
        async def fetch_message(self, session, reference, *, peer_id, message_id):
            raise TelegramMtprotoProviderUnavailableError(
                "temporary", retry_after_seconds=7
            )

    with pytest.raises(TelegramMtprotoProviderUnavailableError):
        await _service(
            db_session, credential_key, _TransientTransport(None)
        ).reconcile_recent_messages(user.id, account.id, {})

    assert obj.deleted_at is None
    assert _notifications(db_session, user.id) == []


@pytest.mark.asyncio
async def test_mismatched_provider_result_does_not_tombstone_or_notify(
    db_session, credential_key
):
    user, account, selection, obj = _fixture(db_session, credential_key)
    result = {
        "peer_id": selection.peer_id + 1,
        "message_id": obj.metadata_["message_id"],
        "text": "wrong peer",
        "occurred_at": obj.occurred_at,
        "edited_at": datetime.now(UTC),
        "sender_peer_id": 888,
        "outgoing": False,
        "service": False,
    }
    await _service(
        db_session, credential_key, _RecentTransport(result)
    ).reconcile_recent_messages(user.id, account.id, {})

    assert obj.deleted_at is None
    assert _notifications(db_session, user.id) == []


def test_notification_pk_conflict_recovers_existing_row(db_session, credential_key, monkeypatch):
    user, account, selection, obj = _fixture(db_session, credential_key)
    service = TelegramMtprotoTransportNotificationService(db_session)
    first = service.message_created(
        user_id=user.id,
        account_id=account.id,
        peer_id=selection.peer_id,
        message_id=42,
        obj=obj,
        occurred_at=obj.occurred_at,
        conversation_title=selection.title,
    )
    original_scalar = db_session.scalar
    calls = 0

    def hide_first_lookup(statement, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return original_scalar(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "scalar", hide_first_lookup)
    recovered = service.message_created(
        user_id=user.id,
        account_id=account.id,
        peer_id=selection.peer_id,
        message_id=42,
        obj=obj,
        occurred_at=obj.occurred_at,
        conversation_title=selection.title,
    )
    assert recovered.id == first.id
    assert len(_notifications(db_session, user.id)) == 1


@pytest.mark.asyncio
async def test_remote_edit_notification_failure_is_observable_and_rollbackable(
    db_session, credential_key, monkeypatch
):
    user, account, selection, obj = _fixture(db_session, credential_key)
    original_body = obj.body
    result = {
        "peer_id": selection.peer_id,
        "message_id": obj.metadata_["message_id"],
        "text": "must rollback",
        "occurred_at": obj.occurred_at,
        "edited_at": datetime.now(UTC) + timedelta(seconds=1),
        "sender_peer_id": 888,
        "outgoing": False,
        "service": False,
    }

    def fail_event(*args, **kwargs):
        raise TelegramMtprotoNotificationPersistenceError("injected")

    monkeypatch.setattr(
        TelegramMtprotoTransportNotificationService, "message_edited", fail_event
    )
    with pytest.raises(TelegramMtprotoNotificationPersistenceError):
        await _service(db_session, credential_key, _RecentTransport(result)).reconcile_recent_messages(
            user.id, account.id, {}
        )
    assert obj.body == original_body
    assert _notifications(db_session, user.id) == []


@pytest.mark.asyncio
async def test_remote_delete_notification_failure_is_observable_and_rollbackable(
    db_session, credential_key, monkeypatch
):
    user, account, _, obj = _fixture(db_session, credential_key)

    def fail_event(*args, **kwargs):
        raise TelegramMtprotoNotificationPersistenceError("injected")

    monkeypatch.setattr(
        TelegramMtprotoTransportNotificationService, "message_deleted", fail_event
    )
    with pytest.raises(TelegramMtprotoNotificationPersistenceError):
        await _service(db_session, credential_key, _RecentTransport(None)).reconcile_recent_messages(
            user.id, account.id, {}
        )
    assert obj.deleted_at is None
    assert _notifications(db_session, user.id) == []


@pytest.mark.asyncio
async def test_savepoint_failure_during_edit_is_typed_and_not_silent(
    db_session, credential_key, monkeypatch
):
    user, account, selection, obj = _fixture(db_session, credential_key)
    original_body = obj.body
    result = {
        "peer_id": selection.peer_id,
        "message_id": obj.metadata_["message_id"],
        "text": "savepoint edit",
        "occurred_at": obj.occurred_at,
        "edited_at": datetime.now(UTC) + timedelta(seconds=1),
        "sender_peer_id": 888,
        "outgoing": False,
        "service": False,
    }

    def fail_savepoint():
        raise RuntimeError("savepoint unavailable")

    monkeypatch.setattr(db_session, "begin_nested", fail_savepoint)
    with pytest.raises(TelegramMtprotoNotificationPersistenceError):
        await _service(
            db_session, credential_key, _RecentTransport(result)
        ).reconcile_recent_messages(user.id, account.id, {})

    assert obj.body == original_body
    assert _notifications(db_session, user.id) == []


@pytest.mark.asyncio
async def test_savepoint_failure_during_delete_is_typed_and_not_silent(
    db_session, credential_key, monkeypatch
):
    user, account, _, obj = _fixture(db_session, credential_key)

    def fail_savepoint():
        raise RuntimeError("savepoint unavailable")

    monkeypatch.setattr(db_session, "begin_nested", fail_savepoint)
    with pytest.raises(TelegramMtprotoNotificationPersistenceError):
        await _service(
            db_session, credential_key, _RecentTransport(None)
        ).reconcile_recent_messages(user.id, account.id, {})

    assert obj.deleted_at is None
    assert _notifications(db_session, user.id) == []


def test_transport_event_notification_api_lifecycle(db_session, auth_headers):
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.main import app
    from app.users.bootstrap import BOOTSTRAP_USER_ID
    from tests.conftest import AuthTestClient

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    client = AuthTestClient(TestClient(app), auth_headers)
    from app.db.models import Notification

    rows = []
    for suffix in ("read", "accept", "ignore", "resolve"):
        row = Notification(
            user_id=BOOTSTRAP_USER_ID,
            title=f"Telegram event {suffix}",
            body="body",
            priority="normal",
            status="new",
            proposal_={
                "type": "transport_event",
                "provider": "telegram",
                "transport": "mtproto",
                "event_type": "message_created",
                "event_key": f"test:{suffix}",
            },
        )
        db_session.add(row)
        rows.append(row)
    db_session.flush()
    before_objects = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.user_id == BOOTSTRAP_USER_ID)
    )
    before_edges = db_session.scalar(
        select(func.count()).select_from(Edge).where(Edge.user_id == BOOTSTRAP_USER_ID)
    )
    before_jobs = db_session.scalar(
        select(func.count()).select_from(Job).where(Job.user_id == BOOTSTRAP_USER_ID)
    )
    listed = client.get("/notifications")
    assert listed.status_code == 200
    assert all(str(row.id) in {item["id"] for item in listed.json()["notifications"]} for row in rows)
    assert client.post(f"/notifications/{rows[0].id}/read").status_code == 200
    assert client.post(f"/notifications/{rows[1].id}/accept").json()["status"] == "accepted"
    assert client.post(f"/notifications/{rows[2].id}/ignore").json()["status"] == "ignored"
    assert client.post(f"/notifications/{rows[3].id}/resolve").json()["status"] == "resolved"
    assert db_session.scalar(
        select(func.count()).select_from(Object).where(Object.user_id == BOOTSTRAP_USER_ID)
    ) == before_objects
    assert db_session.scalar(
        select(func.count()).select_from(Edge).where(Edge.user_id == BOOTSTRAP_USER_ID)
    ) == before_edges
    assert db_session.scalar(
        select(func.count()).select_from(Job).where(Job.user_id == BOOTSTRAP_USER_ID)
    ) == before_jobs
    app.dependency_overrides.clear()


def test_inbox_hides_historical_message_created_and_keeps_source_object(
    db_session, credential_key, auth_headers
):
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.db.models import TelegramMtprotoAccount, TelegramMtprotoChatSelection
    from app.main import app
    from app.services.notification_service import NotificationService
    from app.users.bootstrap import BOOTSTRAP_USER_ID
    from tests.conftest import AuthTestClient

    encryption = CredentialEncryption(credential_key)
    account = TelegramMtprotoAccount(
        user_id=BOOTSTRAP_USER_ID,
        telegram_user_id=990001,
        session_encrypted=encryption.encrypt("session-material"),
        username="inbox",
        display_name="Inbox",
    )
    db_session.add(account)
    db_session.flush()
    peer_id = 4242
    selection = TelegramMtprotoChatSelection(
        account_id=account.id,
        peer_id=peer_id,
        peer_kind="private",
        provider_peer_reference_encrypted=encryption.encrypt('{"entity_type":"user","id":4242}'),
        title="Inbox chat",
        username="inbox",
        manual_selected=False,
        scope_active=True,
    )
    db_session.add(selection)
    source = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider="telegram",
        external_id=f"mtproto|{account.id}|{peer_id}|7",
        origin="source",
        state="observed",
        title="Inbox chat: hello",
        body="hello from telegram",
        metadata_={
            "transport": "mtproto",
            "account_id": str(account.id),
            "peer_id": peer_id,
            "message_id": 7,
            "direction": "inbound",
        },
        occurred_at=datetime.now(UTC),
    )
    db_session.add(source)
    db_session.flush()

    def add_note(title: str, proposal: dict) -> Notification:
        row = Notification(
            user_id=BOOTSTRAP_USER_ID,
            title=title,
            body="body",
            priority="normal",
            status="new",
            source_object_id=source.id,
            proposal_=proposal,
        )
        db_session.add(row)
        return row

    created = add_note(
        "created",
        {
            "type": "transport_event",
            "provider": "telegram",
            "transport": "mtproto",
            "event_type": "message_created",
        },
    )
    edited = add_note(
        "edited",
        {
            "type": "transport_event",
            "provider": "telegram",
            "transport": "mtproto",
            "event_type": "message_edited",
        },
    )
    deleted = add_note(
        "deleted",
        {
            "type": "transport_event",
            "provider": "telegram",
            "transport": "mtproto",
            "event_type": "message_deleted",
        },
    )
    other = add_note("task", {"type": "task", "title": "Call back"})
    legacy_bot = add_note(
        "bot",
        {
            "type": "transport_event",
            "provider": "telegram",
            "transport": "bot",
            "event_type": "message_created",
        },
    )
    db_session.flush()
    stored_ids = {created.id, edited.id, deleted.id, other.id, legacy_bot.id}

    service = NotificationService(db_session, BOOTSTRAP_USER_ID)
    generic_ids = {row.id for row in service.list_notifications(status="unresolved", limit=50)}
    attention_ids = {row.id for row in service.list_inbox_attention(limit=50)}
    assert stored_ids <= generic_ids
    assert created.id not in attention_ids
    assert {edited.id, deleted.id, other.id, legacy_bot.id} <= attention_ids

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    client = AuthTestClient(TestClient(app), auth_headers)
    try:
        listed = client.get("/notifications", params={"status": "unresolved"})
        assert listed.status_code == 200
        listed_ids = {item["id"] for item in listed.json()["notifications"]}
        assert str(created.id) in listed_ids

        inbox = client.get("/inbox")
        assert inbox.status_code == 200
        body = inbox.json()
        unresolved_ids = {item["id"] for item in body["unresolved_notifications"]}
        recent_ids = {item["id"] for item in body["recent_source_objects"]}
        assert str(created.id) not in unresolved_ids
        assert {str(edited.id), str(deleted.id), str(other.id), str(legacy_bot.id)} <= unresolved_ids
        assert str(source.id) in recent_ids
    finally:
        app.dependency_overrides.clear()

    remaining = set(
        db_session.scalars(select(Notification.id).where(Notification.id.in_(stored_ids)))
    )
    assert remaining == stored_ids
    db_session.refresh(created)
    assert created.proposal_["event_type"] == "message_created"
