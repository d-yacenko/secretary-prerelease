"""Inbound MTProto sender identity comes only from the cached Telethon entity."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from telethon import utils
from telethon.sessions import StringSession
from telethon.tl import types

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.materialize import TelegramObjectMaterializer
from app.connectors.telegram.mtproto_transport import (
    TelethonMtprotoTransport,
    _cached_sender_identity,
    _history_entry_from_message,
    _input_peer_from_reference,
)
from app.db.models import Object
from app.domain.role_import_participants import participant_identities
from app.services.telegram_mtproto_history_service import (
    TelegramMtprotoHistoryService,
    _normalize_entry,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_telegram_mtproto_a3 import KEY, _account, _selection, _user

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


def test_cached_user_display_uses_provider_names_only() -> None:
    both = _message(types.User(id=7, first_name="  Ирина ", last_name="\tСергеевна  ", username="ira", phone="7999", bot=False))
    entry = _history_entry_from_message(both)
    assert entry is not None
    assert entry.sender_kind == "user"
    assert entry.sender_display_name == "Ирина Сергеевна"

    first_only = _history_entry_from_message(_message(types.User(id=7, first_name="Ирина", bot=False)))
    last_only = _history_entry_from_message(_message(types.User(id=7, last_name="Сергеевна", bot=False)))
    assert first_only is not None and first_only.sender_display_name == "Ирина"
    assert last_only is not None and last_only.sender_display_name == "Сергеевна"

    username_only = _history_entry_from_message(
        _message(types.User(id=7, username="ira", phone="7999", bot=False))
    )
    assert username_only is not None
    assert username_only.sender_kind == "user"
    assert username_only.sender_display_name is None


def test_non_user_and_missing_senders_do_not_qualify() -> None:
    bot = _history_entry_from_message(
        _message(types.User(id=8, first_name="Helper", bot=True, username="helperbot"))
    )
    channel = _history_entry_from_message(
        _message(types.Channel(id=9, title="  Канал  ", photo=None, date=None, username="news"))
    )
    chat = _history_entry_from_message(
        _message(types.Chat(id=10, title="Чат", photo=None, participants_count=2, date=None, version=1))
    )
    missing = _history_entry_from_message(_message(None))
    assert bot is not None and bot.sender_kind == "bot"
    assert channel is not None and channel.sender_kind == "channel"
    assert chat is not None and chat.sender_kind == "chat"
    assert missing is not None
    assert missing.sender_kind is None and missing.sender_display_name is None
    assert _cached_sender_identity(SimpleNamespace(first_name="Ирина", bot=False)) == (None, None)
    for entry in (bot, channel, chat, missing):
        assert participant_identities(_stored(entry), self_identity_keys=set()) == ()


def test_parser_requires_user_kind_and_keeps_outbound_private() -> None:
    ready = _stored(
        _history_entry_from_message(
            _message(types.User(id=11, first_name="Ирина", last_name="Сергеевна", bot=False), sender_id=11)
        )
    )
    identities = participant_identities(ready, self_identity_keys=set())
    assert [(item.canonical_value, item.display_value) for item in identities] == [
        ("11", "Ирина Сергеевна")
    ]
    legacy = _object(
        {
            "transport": "mtproto",
            "account_id": "account",
            "direction": "inbound",
            "sender_peer_id": 11,
            "sender_display_name": "Ирина Сергеевна",
        }
    )
    assert participant_identities(legacy, self_identity_keys=set()) == ()
    outbound = _object(
        {
            "transport": "mtproto",
            "account_id": "account",
            "direction": "outbound",
            "peer_kind": "private",
            "peer_id": 22,
            "peer_title": "Исходящий Контакт",
        }
    )
    outbound_ids = participant_identities(outbound, self_identity_keys=set())
    assert [(item.canonical_value, item.display_value) for item in outbound_ids] == [
        ("22", "Исходящий Контакт")
    ]


def test_sender_helpers_do_not_request_entities() -> None:
    folded = inspect.getsource(_history_entry_from_message) + inspect.getsource(_cached_sender_identity)
    assert "get_sender" not in folded
    assert "get_entity" not in folded


@pytest.mark.asyncio
async def test_fetch_history_and_fetch_message_use_the_cached_sender(monkeypatch) -> None:
    sender = types.User(id=11, first_name="Ирина", last_name="Сергеевна", username="ira", bot=False)
    message = _message(sender, sender_id=11)
    calls: list[str] = []

    class Client:
        def __init__(self, *args):
            pass

        async def connect(self):
            calls.append("connect")

        async def is_user_authorized(self):
            return True

        async def disconnect(self):
            calls.append("disconnect")

        async def iter_messages(self, *args, **kwargs):
            calls.append("iter_messages")
            yield message

        async def get_messages(self, peer, ids):
            calls.append("get_messages")
            return message

        def __getattr__(self, name):
            raise AssertionError(name)

    monkeypatch.setattr("app.connectors.telegram.mtproto_transport.TelegramClient", Client)
    transport = TelethonMtprotoTransport(1, "hash")
    session = StringSession().save()
    reference = json.dumps({"entity_type": "chat", "id": 123})
    peer_id = utils.get_peer_id(_input_peer_from_reference(reference))
    page = await transport.fetch_history(session, reference, limit=1)
    assert page.entries[0].sender_kind == "user"
    assert page.entries[0].sender_display_name == "Ирина Сергеевна"
    fetched = await transport.fetch_message(session, reference, peer_id=peer_id, message_id=4)
    assert fetched is not None
    assert fetched["sender_kind"] == "user"
    assert fetched["sender_display_name"] == "Ирина Сергеевна"
    assert "get_entity" not in calls
    assert "get_sender" not in calls


def test_reprocessing_the_same_message_adds_sender_identity(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    bare = _normalize_entry(
        account,
        selection,
        _entry(sender_kind=None, sender_display_name=None),
        datetime.min.replace(tzinfo=UTC),
    )
    enriched = _normalize_entry(
        account,
        selection,
        _entry(sender_kind="user", sender_display_name="Ирина Сергеевна"),
        datetime.min.replace(tzinfo=UTC),
    )
    assert bare is not None and enriched is not None
    materializer = TelegramObjectMaterializer(db_session)
    created = materializer.upsert_mtproto_message(user_id=user.id, normalized=bare)
    updated = materializer.upsert_mtproto_message(user_id=user.id, normalized=enriched)
    assert created.obj.id == updated.obj.id
    assert updated.change == "metadata_updated"
    assert updated.obj.metadata_["sender_kind"] == "user"
    assert updated.obj.metadata_["sender_display_name"] == "Ирина Сергеевна"
    identities = participant_identities(updated.obj, self_identity_keys=set())
    assert len(identities) == 1
    assert identities[0].display_value == "Ирина Сергеевна"
    rows = list(
        db_session.scalars(select(Object).where(Object.external_id == enriched["external_id"]))
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_reconcile_reconstruction_keeps_sender_fields(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    selection = _selection(db_session, account)
    bare = _normalize_entry(
        account,
        selection,
        _entry(sender_kind=None, sender_display_name=None),
        datetime.min.replace(tzinfo=UTC),
    )
    assert bare is not None
    TelegramObjectMaterializer(db_session).upsert_mtproto_message(user_id=user.id, normalized=bare)

    class Transport:
        def __init__(self):
            self.calls: list[str] = []

        async def fetch_message(self, session, reference, *, peer_id, message_id):
            self.calls.append("fetch_message")
            return {
                "peer_id": peer_id,
                "message_id": message_id,
                "text": "hello",
                "occurred_at": NOW,
                "edited_at": None,
                "reply_to_message_id": None,
                "sender_peer_id": 11,
                "sender_display_name": "Ирина Сергеевна",
                "sender_kind": "user",
                "outgoing": False,
                "topic_id": None,
                "service": False,
            }

    transport = Transport()
    service = TelegramMtprotoHistoryService(
        db_session,
        transport_factory=lambda: transport,
        encryption=CredentialEncryption(KEY),
    )
    payload: dict = {}
    await service.reconcile_recent_messages(user.id, account.id, payload)
    assert transport.calls == ["fetch_message"]
    stored = db_session.scalar(select(Object).where(Object.external_id == bare["external_id"]))
    assert stored is not None
    assert stored.metadata_["sender_kind"] == "user"
    assert stored.metadata_["sender_display_name"] == "Ирина Сергеевна"


def _message(sender, *, sender_id: int = 11):
    return SimpleNamespace(
        id=4,
        message="hello",
        date=NOW,
        action=None,
        out=False,
        media=None,
        sender=sender,
        sender_id=sender_id,
    )


def _entry(*, sender_kind, sender_display_name):
    from app.connectors.telegram.mtproto_transport import TelegramMtprotoHistoryEntry

    return TelegramMtprotoHistoryEntry(
        message_id=4,
        occurred_at=NOW,
        text="hello",
        sender_peer_id=11,
        reply_to_message_id=None,
        topic_id=None,
        edited_at=None,
        is_service=False,
        sender_display_name=sender_display_name,
        sender_kind=sender_kind,
    )


def _stored(entry) -> Object:
    account = SimpleNamespace(id=uuid4())
    selection = SimpleNamespace(
        peer_id=10, peer_kind="group", title="Group", username=None, is_forum=False
    )
    normalized = _normalize_entry(account, selection, entry, datetime.min.replace(tzinfo=UTC))
    assert normalized is not None
    return _object(normalized["metadata"])


def _object(metadata: dict) -> Object:
    return Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider="telegram",
        title="hello",
        origin="source",
        state="observed",
        occurred_at=NOW,
        metadata_=metadata,
    )
