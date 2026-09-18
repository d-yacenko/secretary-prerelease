"""Telegram MTProto C1B edit, delete, and mark-read regressions."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.assistant.execution_effects import (
    classify_tool_execution_effect,
    describe_execution_effect,
)
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoWriteDefiniteError,
    TelegramMtprotoWriteUncertainError,
)
from app.db.models import ExternalActionAttempt, Object
from app.services.domain_tool_service import DomainToolService
from app.services.telegram_mtproto_mutation_service import (
    ATTEMPT_FAILED_DEFINITE,
    ATTEMPT_UNCERTAIN,
    TelegramMtprotoMutationService,
)
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.schemas import TelegramMtprotoEditInput, ToolError
from tests.test_telegram_mtproto_c1a import _fixture, _SessionProxy


@pytest.fixture
def credential_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", key)
    monkeypatch.setattr("app.core.config.settings.telegram_mtproto_ai_enabled", False)
    return key


class _MutationTransport:
    def __init__(self, *, mode: str = "success") -> None:
        self.mode = mode
        self.edit_calls: list[dict[str, object]] = []
        self.fetch_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.read_calls: list[dict[str, object]] = []
        self.lookup_peer_id: int | None = None

    async def edit_message(self, session, reference, *, peer_id, message_id, text):
        self.edit_calls.append(
            {"session": session, "reference": reference, "peer_id": peer_id, "message_id": message_id, "text": text}
        )
        self._raise_if_needed()
        return {"peer_id": peer_id, "message_id": message_id, "text": text, "edited_at": datetime.now(UTC)}

    async def delete_message(self, session, reference, *, peer_id, message_id):
        self.delete_calls.append(
            {"session": session, "reference": reference, "peer_id": peer_id, "message_id": message_id}
        )
        self._raise_if_needed()
        return True

    async def fetch_message(self, session, reference, *, peer_id, message_id):
        self.fetch_calls.append(
            {"session": session, "reference": reference, "peer_id": peer_id, "message_id": message_id}
        )
        return {
            "peer_id": self.lookup_peer_id if self.lookup_peer_id is not None else peer_id,
            "message_id": message_id,
        }

    async def mark_read(self, session, reference, *, peer_id, max_message_id):
        self.read_calls.append(
            {"session": session, "reference": reference, "peer_id": peer_id, "max_message_id": max_message_id}
        )
        self._raise_if_needed()
        return True

    def _raise_if_needed(self) -> None:
        if self.mode == "uncertain":
            raise TelegramMtprotoWriteUncertainError("provider outcome is uncertain")
        if self.mode == "definite":
            raise TelegramMtprotoWriteDefiniteError("provider rejected mutation")


def _service(session, user_id, transport):
    return TelegramMtprotoMutationService(
        session,
        user_id,
        transport=transport,
        attempt_session_factory=lambda: _SessionProxy(session),
    )


def _outbound_fixture(db_session, credential_key):
    user, account, selection, obj = _fixture(db_session, credential_key)
    obj.metadata_ = {**obj.metadata_, "direction": "outbound"}
    db_session.flush()
    return user, account, selection, obj


def test_edit_updates_same_object_and_replay_does_not_write(db_session, credential_key):
    user, _, _, obj = _outbound_fixture(db_session, credential_key)
    transport = _MutationTransport()
    service = _service(db_session, user.id, transport)

    plan = service.prepare_edit(TelegramMtprotoEditInput(object_id=obj.id, body="edited"))
    first = service.edit(plan)
    replay = service.edit(plan)

    db_session.refresh(obj)
    assert first.status == "succeeded"
    assert replay.status == "already_succeeded"
    assert len(transport.edit_calls) == 1
    assert obj.id == first.object_id
    assert obj.external_id.endswith("|41")
    assert obj.body == "edited"
    assert obj.metadata_["direction"] == "outbound"


def test_edit_uses_approval_gateway_and_freezes_only_safe_route(db_session, credential_key):
    user, _, _, obj = _outbound_fixture(db_session, credential_key)
    transport = _MutationTransport()
    tools = DomainToolService(
        db_session,
        user.id,
        telegram_mtproto_transport=transport,
        attempt_session_factory=lambda: _SessionProxy(db_session),
    )
    result = ToolExecutionGateway().execute(
        tools,
        "edit_message",
        {"object_id": str(obj.id), "body": "edited"},
        ExecutionContext.BASELINE,
    )

    assert result.approval_required is True
    assert result.status.value == "approval_required"
    frozen = json.dumps(result.staged_action["arguments"], default=str)
    assert "session-material" not in frozen
    assert "access_hash" not in frozen
    assert credential_key not in frozen
    assert transport.edit_calls == []


def test_edit_rejects_inbound_and_inactive_messages_before_plan(db_session, credential_key):
    user, _, selection, obj = _fixture(db_session, credential_key)
    service = _service(db_session, user.id, _MutationTransport())
    with pytest.raises(ToolError, match="inbound"):
        service.prepare_edit(TelegramMtprotoEditInput(object_id=obj.id, body="x"))

    obj.metadata_ = {**obj.metadata_, "direction": "outbound"}
    selection.scope_active = False
    db_session.flush()
    with pytest.raises(ToolError, match="active scope"):
        service.prepare_edit(TelegramMtprotoEditInput(object_id=obj.id, body="x"))


def test_edit_mismatched_reference_fails_definite_before_provider(db_session, credential_key):
    user, _, selection, obj = _outbound_fixture(db_session, credential_key)
    transport = _MutationTransport()
    service = _service(db_session, user.id, transport)
    plan = service.prepare_edit(TelegramMtprotoEditInput(object_id=obj.id, body="edited"))
    selection.provider_peer_reference_encrypted = CredentialEncryption(credential_key).encrypt(
        json.dumps({"entity_type": "user", "id": 778, "access_hash": 99})
    )
    db_session.flush()

    with pytest.raises(ToolError, match="reference"):
        service.edit(plan)
    attempt = db_session.scalar(
        select(ExternalActionAttempt).where(ExternalActionAttempt.operation_id == plan.operation_id)
    )
    assert attempt is not None
    assert attempt.state == ATTEMPT_FAILED_DEFINITE
    assert transport.edit_calls == []


@pytest.mark.parametrize("mode, expected", [("uncertain", ATTEMPT_UNCERTAIN), ("definite", ATTEMPT_FAILED_DEFINITE)])
def test_edit_provider_outcomes_are_not_retried(db_session, credential_key, mode, expected):
    user, _, _, obj = _outbound_fixture(db_session, credential_key)
    transport = _MutationTransport(mode=mode)
    service = _service(db_session, user.id, transport)
    plan = service.prepare_edit(TelegramMtprotoEditInput(object_id=obj.id, body="edited"))
    with pytest.raises(ToolError):
        service.edit(plan)
    with pytest.raises(ToolError):
        service.edit(plan)
    assert len(transport.edit_calls) == 1
    attempt = db_session.scalar(
        select(ExternalActionAttempt).where(ExternalActionAttempt.operation_id == plan.operation_id)
    )
    assert attempt is not None
    assert attempt.state == expected


def test_delete_tombstones_same_object_and_replay_does_not_write(db_session, credential_key):
    user, _, _, obj = _fixture(db_session, credential_key)
    transport = _MutationTransport()
    service = _service(db_session, user.id, transport)
    plan = service.prepare_delete(obj.id)

    first = service.delete(plan)
    replay = service.delete(plan)
    db_session.refresh(obj)

    assert first.status == "succeeded"
    assert replay.status == "already_succeeded"
    assert len(transport.delete_calls) == 1
    assert db_session.get(Object, obj.id) is not None
    assert obj.deleted_at is not None


@pytest.mark.parametrize("peer_kind", ["private", "group", "supergroup"])
def test_delete_exact_peer_preflight_blocks_wrong_peer_without_delete(
    db_session, credential_key, peer_kind
):
    user, _, selection, obj = _fixture(db_session, credential_key)
    selection.peer_kind = peer_kind
    db_session.flush()
    transport = _MutationTransport()
    transport.lookup_peer_id = 778
    service = _service(db_session, user.id, transport)
    plan = service.prepare_delete(obj.id)

    with pytest.raises(ToolError, match="not present"):
        service.delete(plan)
    assert len(transport.fetch_calls) == 1
    assert transport.delete_calls == []
    assert obj.deleted_at is None
    attempt = db_session.scalar(
        select(ExternalActionAttempt).where(ExternalActionAttempt.operation_id == plan.operation_id)
    )
    assert attempt is not None
    assert attempt.state == ATTEMPT_FAILED_DEFINITE


def test_edit_replay_repairs_lost_local_convergence_without_provider_call(db_session, credential_key):
    user, _, _, obj = _outbound_fixture(db_session, credential_key)
    transport = _MutationTransport()
    service = _service(db_session, user.id, transport)
    plan = service.prepare_edit(TelegramMtprotoEditInput(object_id=obj.id, body="edited"))
    service.edit(plan)
    obj.body = "stale"
    obj.metadata_ = {key: value for key, value in obj.metadata_.items() if key != "edited_at"}
    db_session.flush()

    replay = service.edit(plan)
    db_session.refresh(obj)
    assert replay.status == "already_succeeded"
    assert len(transport.edit_calls) == 1
    assert obj.body == "edited"
    assert "edited_at" in obj.metadata_


def test_delete_replay_repairs_lost_tombstone_without_provider_call(db_session, credential_key):
    user, _, _, obj = _fixture(db_session, credential_key)
    transport = _MutationTransport()
    service = _service(db_session, user.id, transport)
    plan = service.prepare_delete(obj.id)
    service.delete(plan)
    obj.deleted_at = None
    db_session.flush()

    replay = service.delete(plan)
    db_session.refresh(obj)
    assert replay.status == "already_succeeded"
    assert len(transport.delete_calls) == 1
    assert obj.deleted_at is not None


@pytest.mark.parametrize("mode, expected", [("uncertain", ATTEMPT_UNCERTAIN), ("definite", ATTEMPT_FAILED_DEFINITE)])
def test_delete_provider_outcomes_are_not_retried(db_session, credential_key, mode, expected):
    user, _, _, obj = _fixture(db_session, credential_key)
    transport = _MutationTransport(mode=mode)
    service = _service(db_session, user.id, transport)
    plan = service.prepare_delete(obj.id)
    with pytest.raises(ToolError):
        service.delete(plan)
    with pytest.raises(ToolError):
        service.delete(plan)
    assert len(transport.delete_calls) == 1
    attempt = db_session.scalar(
        select(ExternalActionAttempt).where(ExternalActionAttempt.operation_id == plan.operation_id)
    )
    assert attempt is not None
    assert attempt.state == expected


def test_mark_read_freezes_exact_message_and_replay_does_not_change_content(db_session, credential_key):
    user, _, _, obj = _fixture(db_session, credential_key)
    original_body = obj.body
    transport = _MutationTransport()
    service = _service(db_session, user.id, transport)
    plan = service.prepare_mark_read(obj.id)

    first = service.mark_read(plan)
    replay = service.mark_read(plan)
    db_session.refresh(obj)

    assert plan.route.max_message_id == 41
    assert first.status == "succeeded"
    assert first.changed is True
    assert replay.status == "already_succeeded"
    assert replay.changed is False
    assert len(transport.read_calls) == 1
    assert transport.read_calls[0]["peer_id"] == 777
    assert transport.read_calls[0]["max_message_id"] == 41
    assert obj.body == original_body


def test_mark_read_requires_active_scope_and_exact_route(db_session, credential_key):
    user, _, selection, obj = _fixture(db_session, credential_key)
    service = _service(db_session, user.id, _MutationTransport())
    selection.scope_active = False
    db_session.flush()
    with pytest.raises(ToolError, match="active scope"):
        service.prepare_mark_read(obj.id)


@pytest.mark.parametrize("tool_name", ["edit_message", "delete_message", "mark_message_read"])
def test_mutation_execution_effects_are_changed_not_created(tool_name):
    assert classify_tool_execution_effect(tool_name, {"changed": True}) == "changed"
    assert classify_tool_execution_effect(tool_name, {"changed": False}) == "no_op"
    assert "changed=true" in describe_execution_effect(tool_name, {"changed": True})
    assert "already completed" in describe_execution_effect(tool_name, {"changed": False})


def test_mutation_transport_methods_do_not_construct_client_for_bad_reference(monkeypatch):
    from app.connectors.telegram import mtproto_transport

    monkeypatch.setattr(mtproto_transport, "TelegramClient", lambda *args: pytest.fail("client constructed"))
    transport = mtproto_transport.TelethonMtprotoTransport(123, "hash")
    bad = json.dumps({"entity_type": "user", "id": 778, "access_hash": 99})
    with pytest.raises(TelegramMtprotoWriteDefiniteError, match="reference"):
        asyncio.run(transport.delete_message("session", bad, peer_id=777, message_id=41))


@pytest.mark.parametrize(
    ("method", "operation"),
    [("edit_message", "edit"), ("delete_message", "delete_message"), ("mark_read", "mark_read")],
)
def test_transport_deterministic_telethon_rejections_are_definite(monkeypatch, method, operation):
    from telethon.errors import MessageIdInvalidError

    from app.connectors.telegram import mtproto_transport

    class Client:
        async def connect(self):
            return None

        async def is_user_authorized(self):
            return True

        async def edit_message(self, *args, **kwargs):
            raise MessageIdInvalidError(None)

        async def delete_messages(self, *args, **kwargs):
            raise MessageIdInvalidError(None)

        async def send_read_acknowledge(self, *args, **kwargs):
            raise MessageIdInvalidError(None)

        async def disconnect(self):
            return None

    monkeypatch.setattr(mtproto_transport, "TelegramClient", lambda *args: Client())
    transport = mtproto_transport.TelethonMtprotoTransport(123, "hash")
    reference = json.dumps({"entity_type": "user", "id": 777, "access_hash": 99})
    kwargs = {"peer_id": 777, "message_id": 41}
    if operation == "edit":
        kwargs["text"] = "edited"
    if operation == "mark_read":
        kwargs = {"peer_id": 777, "max_message_id": 41}
    with pytest.raises(TelegramMtprotoWriteDefiniteError):
        asyncio.run(getattr(transport, method)("", reference, **kwargs))


def test_transport_timeout_is_uncertain(monkeypatch):
    from telethon.errors import TimeoutError

    from app.connectors.telegram import mtproto_transport

    class Client:
        async def connect(self):
            return None

        async def is_user_authorized(self):
            return True

        async def delete_messages(self, *args, **kwargs):
            raise TimeoutError(None)

        async def disconnect(self):
            return None

    monkeypatch.setattr(mtproto_transport, "TelegramClient", lambda *args: Client())
    transport = mtproto_transport.TelethonMtprotoTransport(123, "hash")
    reference = json.dumps({"entity_type": "user", "id": 777, "access_hash": 99})
    with pytest.raises(TelegramMtprotoWriteUncertainError):
        asyncio.run(transport.delete_message("", reference, peer_id=777, message_id=41))
