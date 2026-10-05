"""Isolated MTProto sender-metadata repair stays off reconcile and sync state."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoAuthorizationInvalidError,
    TelegramMtprotoProviderUnavailableError,
    TelegramMtprotoReadRejectedError,
)
from app.db.models import Job, Object, TelegramMtprotoChatSelection
from app.domain.role_import_participants import participant_identities
from app.services import telegram_mtproto_sender_repair_service as repair_module
from app.services.telegram_mtproto_sender_repair_service import (
    SENDER_REPAIR_MAX_LOOKUPS,
    SENDER_REPAIR_MAX_PER_PEER,
    SENDER_REPAIR_SCAN_LIMIT,
    TelegramMtprotoSenderRepairService,
)
from tests.test_telegram_mtproto_a3 import KEY, _account, _descriptor, _selection, _user

NOW = datetime(2026, 10, 5, 4, tzinfo=UTC)
HISTORY_FIELDS = (
    "history_latest_message_id",
    "history_backfill_before_message_id",
    "history_cutoff_at",
    "history_complete",
    "history_last_synced_at",
    "scope_active",
    "manual_selected",
    "title",
    "username",
    "peer_id",
)


class FetchTransport:
    def __init__(self, responder):
        self.calls: list[tuple[int, int]] = []
        self.responder = responder

    async def fetch_message(self, session, reference, *, peer_id, message_id):
        self.calls.append((peer_id, message_id))
        return self.responder(peer_id, message_id)

    def __getattr__(self, name):
        raise AssertionError(name)


def test_service_source_does_not_add_entity_lookup_or_side_effects() -> None:
    source = inspect.getsource(repair_module)
    assert "get_sender" not in source
    assert "get_entity" not in source
    assert "tombstone_object" not in source
    assert ".commit(" not in source


@pytest.mark.asyncio
async def test_only_matching_inbound_rows_are_repaired(db_session) -> None:
    user = _user(db_session)
    other = _user(db_session, "other-user")
    account = _account(db_session, user.id)
    other_account = _account(db_session, other.id)
    selection = _selection(db_session, account)
    inactive = _selection(db_session, account, _descriptor(peer_id=-100222))
    inactive.scope_active = False
    db_session.flush()
    peer_id = selection.peer_id
    kept = {
        "marker": "keep-me",
        "sender_peer_id": 11,
        "nested": {"room": "alpha"},
    }
    valid = _object(
        db_session,
        user,
        account,
        peer_id=peer_id,
        message_id=4,
        object_id=UUID(int=10),
        metadata_extra=kept,
    )
    untouched = [
        _object(
            db_session,
            user,
            account,
            peer_id=peer_id,
            message_id=5,
            object_id=UUID(int=1),
            direction="outbound",
        ),
        _object(
            db_session,
            user,
            account,
            peer_id=peer_id,
            message_id=6,
            object_id=UUID(int=2),
            transport="business",
            metadata_extra={"business_connection_id": "biz"},
        ),
        _object(
            db_session,
            user,
            other_account,
            peer_id=peer_id,
            message_id=7,
            object_id=UUID(int=3),
        ),
        _object(
            db_session,
            other,
            other_account,
            peer_id=peer_id,
            message_id=8,
            object_id=UUID(int=4),
        ),
        _object(
            db_session,
            user,
            account,
            peer_id=peer_id,
            message_id=9,
            object_id=UUID(int=5),
            deleted_at=NOW,
        ),
        _object(
            db_session,
            user,
            account,
            peer_id=peer_id,
            message_id=0,
            object_id=UUID(int=6),
        ),
        _object(
            db_session,
            user,
            account,
            peer_id=inactive.peer_id,
            message_id=11,
            object_id=UUID(int=7),
        ),
        _object(
            db_session,
            user,
            account,
            peer_id=peer_id,
            message_id=12,
            object_id=UUID(int=8),
            sender_kind="user",
        ),
    ]
    before = {obj.id: _snapshot(obj) for obj in untouched}
    history = _history_snapshot(selection)
    jobs_before = _job_count(db_session, user.id)
    transport = FetchTransport(
        lambda peer_id, message_id: {
            "peer_id": peer_id,
            "message_id": message_id,
            "text": "replacement body",
            "sender_kind": "user",
            "sender_display_name": "Ирина Сергеевна",
        }
    )

    summary = await _repair(db_session, transport, user.id, account.id)

    assert transport.calls == [(peer_id, 4)]
    assert summary.updated == 1
    assert summary.provider_calls == 1
    assert summary.invalid_or_mismatch == 2
    stored = db_session.get(Object, valid.id)
    assert stored.metadata_["sender_kind"] == "user"
    assert stored.metadata_["sender_display_name"] == "Ирина Сергеевна"
    assert stored.metadata_["marker"] == "keep-me"
    assert stored.metadata_["nested"] == {"room": "alpha"}
    assert stored.metadata_["sender_peer_id"] == 11
    assert stored.title == "legacy title"
    assert stored.body == "legacy body"
    assert stored.occurred_at == NOW
    assert stored.deleted_at is None
    assert stored.external_id == valid.external_id
    for obj in untouched:
        assert _snapshot(db_session.get(Object, obj.id)) == before[obj.id]
    assert _history_snapshot(db_session.get(TelegramMtprotoChatSelection, selection.id)) == history
    assert _job_count(db_session, user.id) == jobs_before


@pytest.mark.asyncio
async def test_hidden_object_is_not_mutated(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    hidden = _object(
        db_session,
        user,
        account,
        peer_id=selection.peer_id,
        message_id=3,
        object_id=UUID(int=1),
        status="deleted",
        metadata_extra={"sender_display_name": "Скрытый Контакт"},
    )
    before = _snapshot(hidden)
    transport = FetchTransport(lambda peer_id, message_id: None)

    summary = await _repair(db_session, transport, user.id, account.id)

    assert transport.calls == []
    assert summary.hidden_skipped == 1
    assert summary.provider_calls == 0
    assert summary.updated == 0
    assert _snapshot(db_session.get(Object, hidden.id)) == before


@pytest.mark.asyncio
async def test_provider_calls_stop_at_twenty_and_five_per_peer(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    peers = [
        _selection(db_session, account, _descriptor(peer_id=-200000 - index)).peer_id
        for index in range(5)
    ]
    sequence = 0
    for _round in range(5):
        for peer_id in peers:
            sequence += 1
            _object(
                db_session,
                user,
                account,
                peer_id=peer_id,
                message_id=sequence,
                object_id=UUID(int=sequence),
            )
    transport = FetchTransport(
        lambda peer_id, message_id: {
            "peer_id": peer_id,
            "message_id": message_id,
            "sender_kind": "bot",
            "sender_display_name": "Helper",
        }
    )

    summary = await _repair(db_session, transport, user.id, account.id)

    assert SENDER_REPAIR_MAX_LOOKUPS == 20
    assert SENDER_REPAIR_MAX_PER_PEER == 5
    assert summary.provider_calls == 20
    assert summary.candidates_scanned == 20
    assert summary.exhausted is False
    assert len(transport.calls) == 20
    assert max(_count(peer_id, transport.calls) for peer_id in peers) <= 5
    assert summary.next_cursor == UUID(int=20)


@pytest.mark.asyncio
async def test_one_peer_stops_after_five_lookups(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    for message_id in range(1, 9):
        _object(
            db_session,
            user,
            account,
            peer_id=selection.peer_id,
            message_id=message_id,
            object_id=UUID(int=message_id),
        )
    transport = FetchTransport(
        lambda peer_id, message_id: {
            "peer_id": peer_id,
            "message_id": message_id,
            "sender_kind": "chat",
        }
    )

    first = await _repair(db_session, transport, user.id, account.id)
    assert first.provider_calls == 5
    assert first.candidates_scanned == 5
    assert first.next_cursor == UUID(int=5)
    assert first.exhausted is False

    second = await _repair(
        db_session, transport, user.id, account.id, cursor=first.next_cursor
    )
    assert second.provider_calls == 3
    assert [message_id for _peer, message_id in transport.calls] == list(range(1, 9))
    assert second.exhausted is True


@pytest.mark.asyncio
async def test_candidate_scan_reads_at_most_one_hundred(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    _selection(db_session, account)
    for index in range(1, 121):
        _object(
            db_session,
            user,
            account,
            peer_id=-1,
            message_id=0,
            object_id=UUID(int=index),
        )
    transport = FetchTransport(lambda peer_id, message_id: None)

    first = await _repair(db_session, transport, user.id, account.id)
    assert SENDER_REPAIR_SCAN_LIMIT == 100
    assert first.candidates_scanned == 100
    assert first.provider_calls == 0
    assert first.invalid_or_mismatch == 100
    assert first.exhausted is False
    assert first.next_cursor == UUID(int=100)

    second = await _repair(
        db_session, transport, user.id, account.id, cursor=first.next_cursor
    )
    assert second.candidates_scanned == 20
    assert second.exhausted is True
    assert transport.calls == []


@pytest.mark.asyncio
async def test_cursor_advances_past_missing_and_unknown_rows(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    missing = _object(
        db_session,
        user,
        account,
        peer_id=selection.peer_id,
        message_id=1,
        object_id=UUID(int=1),
        metadata_extra={"sender_display_name": "Старое Имя"},
    )
    unknown = _object(
        db_session,
        user,
        account,
        peer_id=selection.peer_id,
        message_id=2,
        object_id=UUID(int=2),
    )
    ready = _object(
        db_session,
        user,
        account,
        peer_id=selection.peer_id,
        message_id=3,
        object_id=UUID(int=3),
        metadata_extra={"sender_display_name": "Старое Имя"},
    )

    def respond(peer_id, message_id):
        if message_id == 1:
            return None
        if message_id == 2:
            return {"peer_id": peer_id, "message_id": message_id, "sender_kind": None}
        return {
            "peer_id": peer_id,
            "message_id": message_id,
            "sender_kind": "user",
            "sender_display_name": "Ирина Сергеевна",
        }

    transport = FetchTransport(respond)
    summary = await _repair(db_session, transport, user.id, account.id)

    assert [message_id for _peer, message_id in transport.calls] == [1, 2, 3]
    assert summary.provider_missing == 1
    assert summary.fetched_without_kind == 1
    assert summary.updated == 1
    assert summary.next_cursor == ready.id
    assert summary.exhausted is True
    assert db_session.get(Object, missing.id).metadata_.get("sender_kind") is None
    assert db_session.get(Object, missing.id).deleted_at is None
    assert db_session.get(Object, unknown.id).metadata_.get("sender_kind") is None
    assert db_session.get(Object, ready.id).metadata_["sender_display_name"] == "Ирина Сергеевна"

    again = await _repair(
        db_session, transport, user.id, account.id, cursor=summary.next_cursor
    )
    assert again.provider_calls == 0
    assert again.exhausted is True
    assert len(transport.calls) == 3


@pytest.mark.asyncio
async def test_mismatch_does_not_mutate(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    obj = _object(
        db_session,
        user,
        account,
        peer_id=selection.peer_id,
        message_id=4,
        object_id=UUID(int=1),
    )
    before = _snapshot(obj)
    transport = FetchTransport(
        lambda peer_id, message_id: {"peer_id": peer_id, "message_id": message_id + 1, "sender_kind": "user"}
    )

    summary = await _repair(db_session, transport, user.id, account.id)

    assert summary.invalid_or_mismatch == 1
    assert summary.updated == 0
    assert _snapshot(db_session.get(Object, obj.id)) == before


@pytest.mark.asyncio
async def test_user_without_display_keeps_existing_display(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    bare = _object(
        db_session,
        user,
        account,
        peer_id=selection.peer_id,
        message_id=1,
        object_id=UUID(int=1),
    )
    legacy = _object(
        db_session,
        user,
        account,
        peer_id=selection.peer_id,
        message_id=2,
        object_id=UUID(int=2),
        metadata_extra={"sender_display_name": "Старое Имя", "marker": "keep"},
    )
    transport = FetchTransport(
        lambda peer_id, message_id: {
            "peer_id": peer_id,
            "message_id": message_id,
            "sender_kind": "user",
            "sender_display_name": None,
        }
    )

    await _repair(db_session, transport, user.id, account.id)

    bare_meta = db_session.get(Object, bare.id).metadata_
    legacy_meta = db_session.get(Object, legacy.id).metadata_
    assert bare_meta["sender_kind"] == "user"
    assert "sender_display_name" not in bare_meta
    assert legacy_meta["sender_kind"] == "user"
    assert legacy_meta["sender_display_name"] == "Старое Имя"
    assert legacy_meta["marker"] == "keep"
    assert participant_identities(db_session.get(Object, bare.id), self_identity_keys=set()) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["bot", "channel", "chat"])
async def test_non_user_kinds_are_stored_and_do_not_qualify(db_session, kind) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    obj = _object(
        db_session,
        user,
        account,
        peer_id=selection.peer_id,
        message_id=4,
        object_id=UUID(int=1),
        metadata_extra={"sender_peer_id": 11, "sender_display_name": "Не Человек"},
    )
    transport = FetchTransport(
        lambda peer_id, message_id: {
            "peer_id": peer_id,
            "message_id": message_id,
            "sender_kind": kind,
            "sender_display_name": "Не Человек",
        }
    )

    await _repair(db_session, transport, user.id, account.id)

    stored = db_session.get(Object, obj.id)
    assert stored.metadata_["sender_kind"] == kind
    assert stored.metadata_["sender_display_name"] == "Не Человек"
    assert participant_identities(stored, self_identity_keys=set()) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        TelegramMtprotoProviderUnavailableError("unavailable"),
        TelegramMtprotoAuthorizationInvalidError("unauthorized"),
        TelegramMtprotoReadRejectedError("rejected"),
    ],
)
async def test_provider_errors_propagate_without_commit(db_session, monkeypatch, error) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    obj = _object(
        db_session,
        user,
        account,
        peer_id=selection.peer_id,
        message_id=4,
        object_id=UUID(int=1),
    )
    before = _snapshot(obj)

    class FailingTransport(FetchTransport):
        async def fetch_message(self, session, reference, *, peer_id, message_id):
            raise error

    def fail_commit():
        raise AssertionError("commit")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(type(error)):
        await _repair(db_session, FailingTransport(lambda *_args: None), user.id, account.id)
    assert _snapshot(db_session.get(Object, obj.id)) == before


def _repair(db_session, transport, user_id, account_id, cursor=None):
    service = TelegramMtprotoSenderRepairService(
        db_session,
        transport_factory=lambda: transport,
        encryption=CredentialEncryption(KEY),
    )
    return service.repair_inbound_sender_metadata(user_id, account_id, cursor=cursor)


def _object(
    db_session,
    user,
    account,
    *,
    peer_id: int,
    message_id: int,
    object_id: UUID,
    direction: str = "inbound",
    transport: str = "mtproto",
    sender_kind: str | None = None,
    deleted_at: datetime | None = None,
    status: str | None = None,
    metadata_extra: dict | None = None,
) -> Object:
    metadata = {
        "transport": transport,
        "account_id": str(account.id),
        "direction": direction,
        "peer_id": peer_id,
        "message_id": message_id,
        "sender_peer_id": 11,
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    if sender_kind is not None:
        metadata["sender_kind"] = sender_kind
    obj = Object(
        id=object_id,
        user_id=user.id,
        kind="chat_message",
        provider="telegram",
        external_id=f"mtproto|{account.id}|{peer_id}|{message_id}|{object_id.int}",
        origin="source",
        state="observed",
        title="legacy title",
        body="legacy body",
        metadata_=metadata,
        occurred_at=NOW,
        deleted_at=deleted_at,
        status=status,
    )
    db_session.add(obj)
    db_session.flush()
    return obj


def _snapshot(obj: Object) -> dict:
    return {
        "title": obj.title,
        "body": obj.body,
        "occurred_at": obj.occurred_at,
        "deleted_at": obj.deleted_at,
        "external_id": obj.external_id,
        "status": obj.status,
        "metadata": dict(obj.metadata_ or {}),
    }


def _history_snapshot(selection) -> dict:
    return {field: getattr(selection, field) for field in HISTORY_FIELDS}


def _job_count(db_session, user_id) -> int:
    return int(
        db_session.scalar(select(func.count()).select_from(Job).where(Job.user_id == user_id))
        or 0
    )


def _count(peer_id: int, calls: list[tuple[int, int]]) -> int:
    return sum(1 for called_peer, _message_id in calls if called_peer == peer_id)
