"""Telegram MTProto C1A — canonical send/reply and write safety."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.constants import MAX_TELEGRAM_MESSAGE_BODY_CHARS
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoWriteDefiniteError,
    TelegramMtprotoWriteUncertainError,
)
from app.connectors.telegram.mtproto_transport import (
    TelegramMtprotoHistoryEntry,
    TelegramMtprotoSentMessage,
)
from app.db.models import (
    ExternalActionAttempt,
    Job,
    Object,
    TelegramMtprotoAccount,
    TelegramMtprotoChatSelection,
    User,
)
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
from app.services.communication_external_action_service import (
    ATTEMPT_FAILED_DEFINITE,
    ATTEMPT_UNCERTAIN,
    CommunicationExternalActionService,
)
from app.services.telegram_mtproto_history_service import _normalize_entry
from app.tools.schemas import SendMessageInput, TelegramMtprotoSendRoute, ToolError


class _SessionProxy:
    def __init__(self, session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def commit(self) -> None:
        self._session.flush()

    def rollback(self) -> None:
        self._session.flush()

    def __getattr__(self, name):
        return getattr(self._session, name)


class _FakeMtprotoTransport:
    def __init__(self, *, mode: str = "success") -> None:
        self.mode = mode
        self.calls: list[dict[str, object]] = []
        self.next_message_id = 9001

    async def send_message(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        peer_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> TelegramMtprotoSentMessage:
        self.calls.append(
            {
                "session": session,
                "provider_peer_reference": provider_peer_reference,
                "peer_id": peer_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
            }
        )
        if self.mode == "uncertain":
            raise TelegramMtprotoWriteUncertainError("provider outcome is uncertain")
        if self.mode == "definite":
            raise TelegramMtprotoWriteDefiniteError("provider rejected message")
        return TelegramMtprotoSentMessage(
            message_id=self.next_message_id,
            peer_id=peer_id,
            text=text,
            occurred_at=datetime.now(UTC),
            reply_to_message_id=reply_to_message_id,
            sender_peer_id=peer_id,
        )


@pytest.fixture
def credential_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", key)
    monkeypatch.setattr("app.core.config.settings.telegram_mtproto_ai_enabled", False)
    return key


def _service(session, user_id, fake: _FakeMtprotoTransport):
    return CommunicationExternalActionService(
        session,
        user_id,
        telegram_mtproto_transport=fake,
        attempt_session_factory=lambda: _SessionProxy(session),
    )


def _fixture(db_session, credential_key: str, *, scope_active: bool = True):
    user = User(id=uuid4(), display_name="mtproto-c1a")
    db_session.add(user)
    db_session.flush()
    encryption = CredentialEncryption(credential_key)
    account = TelegramMtprotoAccount(
        user_id=user.id,
        telegram_user_id=12345,
        session_encrypted=encryption.encrypt("session-material"),
        username="alice",
        display_name="Alice",
    )
    db_session.add(account)
    db_session.flush()
    peer_id = 777
    selection = TelegramMtprotoChatSelection(
        account_id=account.id,
        peer_id=peer_id,
        peer_kind="private",
        provider_peer_reference_encrypted=encryption.encrypt(
            json.dumps({"entity_type": "user", "id": peer_id, "access_hash": 99})
        ),
        title="Alice",
        username="alice",
        manual_selected=False,
        scope_active=scope_active,
    )
    db_session.add(selection)
    db_session.flush()
    message_id = 41
    obj = Object(
        user_id=user.id,
        kind="chat_message",
        provider="telegram",
        external_id=f"mtproto|{account.id}|{peer_id}|{message_id}",
        origin="source",
        state="observed",
        title="Alice: hello",
        body="hello",
        metadata_={
            "transport": "mtproto",
            "account_id": str(account.id),
            "peer_id": peer_id,
            "peer_kind": "private",
            "message_id": message_id,
            "direction": "inbound",
        },
        occurred_at=datetime.now(UTC),
    )
    db_session.add(obj)
    db_session.flush()
    return user, account, selection, obj


def test_prepare_freezes_mtproto_compose_and_exact_reply_route(db_session, credential_key):
    user, account, selection, obj = _fixture(db_session, credential_key)
    fake = _FakeMtprotoTransport()
    service = _service(db_session, user.id, fake)

    composed = service.prepare_send_message(
        SendMessageInput(body="new", conversation_object_id=obj.id)
    )
    assert isinstance(composed.route, TelegramMtprotoSendRoute)
    assert composed.mode == "compose"
    assert composed.route.account_id == account.id
    assert composed.route.peer_id == selection.peer_id
    assert composed.route.reply_to_message_id is None

    replied = service.prepare_send_message(SendMessageInput(body="reply", reply_to_object_id=obj.id))
    assert replied.mode == "reply"
    assert replied.route.reply_to_message_id == 41
    dumped = json.dumps(replied.model_dump(mode="json"))
    assert "session-material" not in dumped
    assert "access_hash" not in dumped
    assert credential_key not in dumped
    assert fake.calls == []


def test_prepare_mtproto_fails_closed_for_inactive_and_wrong_account(db_session, credential_key):
    user, _, _, obj = _fixture(db_session, credential_key, scope_active=False)
    service = _service(db_session, user.id, _FakeMtprotoTransport())
    with pytest.raises(ToolError, match="active scope"):
        service.prepare_send_message(SendMessageInput(body="hi", conversation_object_id=obj.id))


@pytest.mark.parametrize(
    "reference",
    ["not-json", json.dumps({"entity_type": "channel", "id": 777})],
)
def test_prepare_mtproto_rejects_malformed_or_mismatched_reference(
    db_session, credential_key, reference
):
    user, _, selection, obj = _fixture(db_session, credential_key)
    selection.provider_peer_reference_encrypted = CredentialEncryption(credential_key).encrypt(
        reference
    )
    db_session.flush()
    service = _service(db_session, user.id, _FakeMtprotoTransport())
    with pytest.raises(ToolError, match="reference"):
        service.prepare_send_message(SendMessageInput(body="hi", conversation_object_id=obj.id))

    selection.scope_active = True
    obj.metadata_ = {**obj.metadata_, "account_id": str(uuid4())}
    db_session.flush()
    with pytest.raises(ToolError, match="active scope"):
        service.prepare_send_message(SendMessageInput(body="hi", conversation_object_id=obj.id))


@pytest.mark.parametrize(
    ("field", "value"),
    [("account_id", "not-a-uuid"), ("peer_id", 0), ("message_id", 0)],
)
def test_prepare_mtproto_rejects_malformed_routing_metadata(
    db_session, credential_key, field, value
):
    user, _, _, obj = _fixture(db_session, credential_key)
    obj.metadata_ = {**obj.metadata_, field: value}
    db_session.flush()
    service = _service(db_session, user.id, _FakeMtprotoTransport())
    with pytest.raises(ToolError, match="malformed"):
        service.prepare_send_message(SendMessageInput(body="hi", reply_to_object_id=obj.id))


def test_compose_sends_once_materializes_canonical_object_without_ai_job(
    db_session, credential_key
):
    user, account, selection, obj = _fixture(db_session, credential_key)
    fake = _FakeMtprotoTransport()
    service = _service(db_session, user.id, fake)
    plan = service.prepare_send_message(
        SendMessageInput(body="outbound", conversation_object_id=obj.id)
    )
    result = service.send_message(plan)
    assert result.delivery_status == "sent"
    assert len(fake.calls) == 1
    assert fake.calls[0]["session"] == "session-material"
    assert fake.calls[0]["provider_peer_reference"]
    assert fake.calls[0]["reply_to_message_id"] is None
    created = db_session.scalar(
        select(Object).where(
            Object.user_id == user.id,
            Object.external_id == f"mtproto|{account.id}|{selection.peer_id}|9001",
        )
    )
    assert created is not None
    assert created.metadata_["transport"] == "mtproto"
    assert created.metadata_["direction"] == "outbound"
    assert created.metadata_["reply_to_message_id"] is None
    assert db_session.scalar(
        select(Job.id).where(
            Job.type == JOB_TYPE_EMBED_OBJECT,
            Job.payload["object_id"].as_string() == str(created.id),
        )
    ) is None


def test_execution_revalidates_reference_before_provider_write(db_session, credential_key):
    user, _, selection, obj = _fixture(db_session, credential_key)
    fake = _FakeMtprotoTransport()
    service = _service(db_session, user.id, fake)
    plan = service.prepare_send_message(
        SendMessageInput(body="outbound", conversation_object_id=obj.id)
    )
    selection.provider_peer_reference_encrypted = CredentialEncryption(credential_key).encrypt(
        json.dumps({"entity_type": "user", "id": 778, "access_hash": 99})
    )
    db_session.flush()
    with pytest.raises(ToolError, match="reference|route"):
        service.send_message(plan)
    attempt = db_session.scalar(
        select(ExternalActionAttempt).where(ExternalActionAttempt.operation_id == plan.operation_id)
    )
    assert attempt is not None
    assert attempt.state == "failed_definite"
    assert len(fake.calls) == 0


@pytest.mark.asyncio
async def test_telethon_transport_validates_reference_before_client(monkeypatch):
    from app.connectors.telegram import mtproto_transport

    def fail_if_constructed(*args, **kwargs):
        raise AssertionError("client must not be constructed for invalid reference")

    monkeypatch.setattr(mtproto_transport, "TelegramClient", fail_if_constructed)
    transport = mtproto_transport.TelethonMtprotoTransport(123, "hash")
    with pytest.raises(TelegramMtprotoWriteDefiniteError, match="reference"):
        await transport.send_message(
            "session",
            json.dumps({"entity_type": "user", "id": 778, "access_hash": 99}),
            peer_id=777,
            text="hello",
        )


def test_history_normalization_converges_to_outbound_direction_without_ai_job(
    db_session, credential_key
):
    user, account, selection, obj = _fixture(db_session, credential_key)
    fake = _FakeMtprotoTransport()
    service = _service(db_session, user.id, fake)
    plan = service.prepare_send_message(
        SendMessageInput(body="outbound", conversation_object_id=obj.id)
    )
    result = service.send_message(plan)
    created = db_session.get(Object, result.object_id)
    assert created is not None
    normalized = _normalize_entry(
        account,
        selection,
        TelegramMtprotoHistoryEntry(
            message_id=9001,
            occurred_at=datetime.now(UTC),
            text="outbound",
            sender_peer_id=selection.peer_id,
            reply_to_message_id=None,
            topic_id=None,
            edited_at=None,
            is_service=False,
            outgoing=True,
        ),
        datetime.now(UTC).replace(year=datetime.now(UTC).year - 1),
    )
    assert normalized is not None
    assert normalized["metadata"]["direction"] == "outbound"
    materialized = service._telegram_materializer.upsert_mtproto_message(
        user_id=user.id, normalized=normalized
    )
    assert materialized.obj.id == created.id
    assert materialized.obj.metadata_["direction"] == "outbound"
    assert db_session.scalar(
        select(Job.id).where(Job.type == JOB_TYPE_EMBED_OBJECT)
    ) is None


def test_history_normalization_marks_inbound_entries_inbound(db_session, credential_key):
    _, account, selection, _ = _fixture(db_session, credential_key)
    normalized = _normalize_entry(
        account,
        selection,
        TelegramMtprotoHistoryEntry(
            message_id=9002,
            occurred_at=datetime.now(UTC),
            text="inbound",
            sender_peer_id=-42,
            reply_to_message_id=None,
            topic_id=None,
            edited_at=None,
            is_service=False,
        ),
        datetime.now(UTC).replace(year=datetime.now(UTC).year - 1),
    )
    assert normalized is not None
    assert normalized["metadata"]["direction"] == "inbound"


def test_reply_sends_exact_provider_reply_id_and_success_replay_does_not_resend(
    db_session, credential_key
):
    user, _, _, obj = _fixture(db_session, credential_key)
    fake = _FakeMtprotoTransport()
    service = _service(db_session, user.id, fake)
    plan = service.prepare_send_message(SendMessageInput(body="reply", reply_to_object_id=obj.id))
    first = service.send_message(plan)
    replay = service.send_message(plan)
    assert first.delivery_status == "sent"
    assert replay.delivery_status == "already_sent"
    assert len(fake.calls) == 1
    assert fake.calls[0]["reply_to_message_id"] == 41


def test_uncertain_write_is_recorded_and_never_retried(db_session, credential_key):
    user, _, _, obj = _fixture(db_session, credential_key)
    fake = _FakeMtprotoTransport(mode="uncertain")
    service = _service(db_session, user.id, fake)
    plan = service.prepare_send_message(SendMessageInput(body="hi", conversation_object_id=obj.id))
    with pytest.raises(ToolError, match="could not confirm"):
        service.send_message(plan)
    with pytest.raises(ToolError, match="could not confirm"):
        service.send_message(plan)
    attempt = db_session.scalar(
        select(ExternalActionAttempt).where(ExternalActionAttempt.operation_id == plan.operation_id)
    )
    assert attempt is not None
    assert attempt.state == ATTEMPT_UNCERTAIN
    assert len(fake.calls) == 1


def test_definite_write_is_failed_definite(db_session, credential_key):
    user, _, _, obj = _fixture(db_session, credential_key)
    fake = _FakeMtprotoTransport(mode="definite")
    service = _service(db_session, user.id, fake)
    plan = service.prepare_send_message(SendMessageInput(body="hi", conversation_object_id=obj.id))
    with pytest.raises(ToolError, match="rejected"):
        service.send_message(plan)
    attempt = db_session.scalar(
        select(ExternalActionAttempt).where(ExternalActionAttempt.operation_id == plan.operation_id)
    )
    assert attempt is not None
    assert attempt.state == ATTEMPT_FAILED_DEFINITE


def test_mtproto_body_limit_is_preserved(db_session, credential_key):
    user, _, _, obj = _fixture(db_session, credential_key)
    service = _service(db_session, user.id, _FakeMtprotoTransport())
    with pytest.raises(ToolError, match="maximum length"):
        service.prepare_send_message(
            SendMessageInput(
                body="x" * (MAX_TELEGRAM_MESSAGE_BODY_CHARS + 1),
                conversation_object_id=obj.id,
            )
        )
