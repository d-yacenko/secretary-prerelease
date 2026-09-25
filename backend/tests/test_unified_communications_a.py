"""Unified Communications A — Mattermost send_message core."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from app.assistant.tool_runner import PerTurnToolBudget
from app.connectors.mattermost.constants import MAX_MESSAGE_BODY_CHARS
from app.connectors.mattermost.credentials import MattermostAccountStore
from app.connectors.mattermost.errors import (
    MattermostSecurityError,
    MattermostTransportError,
    MattermostUnauthorizedError,
    MattermostWriteDefiniteError,
    MattermostWriteUncertainError,
)
from app.connectors.mattermost.normalize import (
    MattermostChannelContext,
    build_external_id,
    normalize_mattermost_post,
)
from app.connectors.mattermost.sync import build_mattermost_sync_service
from app.connectors.mattermost.transport import FakeMattermostTransport, MattermostHttpTransport
from app.db.models import ExternalActionAttempt, Job, MattermostAccount, Object, User
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
from app.services.communication_external_action_service import (
    ATTEMPT_FAILED_DEFINITE,
    ATTEMPT_SUCCEEDED,
    ATTEMPT_UNCERTAIN,
    CommunicationExternalActionService,
    pending_post_id_from_operation_id,
)
from app.services.domain_tool_service import DomainToolService
from app.services.provenance import REJECTED_STATE
from app.tools.assistant_contracts import ASSISTANT_FUNCTION_SCHEMAS
from app.tools.policy import ToolPermission
from app.tools.registry import TOOL_REGISTRY
from app.tools.results import ToolExecutionResult, ToolExecutionStatus
from app.tools.schemas import SendMessageCanonicalInput, SendMessageInput, ToolError

ALLOWED_URL = "https://mm.example.com"
PAT = "mattermost-personal-access-token"
CHANNEL_ID = "ch-1"
POST_ID = "post-1"


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def mattermost_settings(monkeypatch: pytest.MonkeyPatch, credential_key: str) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    monkeypatch.setattr("app.core.config.settings.mattermost_allowed_base_urls", ALLOWED_URL)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _connect_account(session, credential_key: str, user_id) -> MattermostAccount:
    store = MattermostAccountStore(
        session,
        MattermostAccountStore.build_encryption(credential_key),
    )
    account = store.upsert_account(
        user_id=user_id,
        normalized_server_url=ALLOWED_URL,
        remote_user_id="user-1",
        username="alice",
        access_token=PAT,
        display_name="Alice",
        email="alice@example.com",
    )
    session.flush()
    return account


def _anchor_object(
    session,
    user_id,
    account: MattermostAccount,
    *,
    post_id: str = POST_ID,
    channel_id: str = CHANNEL_ID,
    root_id: str | None = None,
    kind: str = "chat_message",
    provider: str = "mattermost",
    extra_meta: dict | None = None,
    deleted: bool = False,
    rejected: bool = False,
    server_url: str = ALLOWED_URL,
    external_id: str | None = None,
) -> Object:
    meta = {
        "server_url": server_url,
        "account_id": str(account.id),
        "post_id": post_id,
        "channel_id": channel_id,
        "channel_name": "sidorov",
        "channel_display_name": "Sidorov",
        "channel_type": "D",
        "root_id": root_id,
        "author_user_id": "sidorov",
        "author_username": "sidorov",
        "author_display_name": "Sidorov",
        "create_at": 1_700_000_000_000,
        "update_at": 1_700_000_000_000,
        "post_type": None,
        "file_ids": [],
    }
    if extra_meta:
        meta.update(extra_meta)
    obj = Object(
        user_id=user_id,
        kind=kind,
        provider=provider,
        external_id=external_id or build_external_id(server_url, post_id),
        origin="source",
        state=REJECTED_STATE if rejected else "observed",
        title="Sidorov: hello",
        body="hello",
        metadata_=meta,
        occurred_at=_utcnow(),
        deleted_at=_utcnow() if deleted else None,
    )
    session.add(obj)
    session.flush()
    return obj


def _service(session, user_id, fake: FakeMattermostTransport | None = None) -> CommunicationExternalActionService:
    return CommunicationExternalActionService(
        session,
        user_id,
        transport=fake,
        attempt_session_factory=lambda: _SessionProxy(session),
    )


# --------------------------------------------------------------------------- schema / registry


def test_send_message_is_registered_communicate_and_exposed() -> None:
    spec = TOOL_REGISTRY["send_message"]
    assert spec.permission == ToolPermission.COMMUNICATE
    assert spec.assistant_exposed is True
    assert spec.mcp_exposed is True
    assert spec.prepare_method == "prepare_send_message"
    assert spec.service_method == "send_message"
    assert spec.execution_input_model is SendMessageCanonicalInput
    assert spec.input_model is SendMessageInput


def test_send_message_input_rejects_empty_and_oversized_body() -> None:
    object_id = str(uuid4())
    with pytest.raises(PydanticValidationError):
        SendMessageInput.model_validate({"body": "   ", "conversation_object_id": object_id})
    with pytest.raises(PydanticValidationError):
        SendMessageInput.model_validate({"body": "", "reply_to_object_id": object_id})
    with pytest.raises(PydanticValidationError):
        SendMessageInput.model_validate(
            {"body": "x" * (MAX_MESSAGE_BODY_CHARS + 1), "conversation_object_id": object_id}
        )


def test_send_message_input_requires_exactly_one_anchor() -> None:
    with pytest.raises(PydanticValidationError):
        SendMessageInput.model_validate({"body": "hello"})
    with pytest.raises(PydanticValidationError):
        SendMessageInput.model_validate(
            {
                "body": "hello",
                "conversation_object_id": str(uuid4()),
                "reply_to_object_id": str(uuid4()),
            }
        )


def test_send_message_input_accepts_conversation_or_reply_anchor() -> None:
    conversation_id = uuid4()
    reply_id = uuid4()
    composed = SendMessageInput.model_validate(
        {"body": "встреча переносится", "conversation_object_id": str(conversation_id)}
    )
    assert composed.conversation_object_id == conversation_id
    assert composed.reply_to_object_id is None
    replied = SendMessageInput.model_validate(
        {"body": "буду завтра в 10", "reply_to_object_id": str(reply_id)}
    )
    assert replied.reply_to_object_id == reply_id
    assert replied.conversation_object_id is None


def test_send_message_normalizes_crlf_without_rewriting_content() -> None:
    object_id = uuid4()
    payload = SendMessageInput.model_validate(
        {"body": "line1\r\nline2\rline3", "conversation_object_id": str(object_id)}
    )
    assert payload.body == "line1\nline2\nline3"


def test_assistant_schema_does_not_expose_provider_routing_ids() -> None:
    schema = ASSISTANT_FUNCTION_SCHEMAS["send_message"]
    properties = schema["parameters"]["properties"]
    assert set(properties) == {
        "body",
        "conversation_object_id",
        "reply_to_object_id",
        "person_id",
    }
    for forbidden in ("channel_id", "server_url", "account_id", "post_id", "root_id"):
        assert forbidden not in properties
    description = schema["description"].lower()
    assert "approval" in description
    assert "send" in description
    assert "draft" in description or "drafting" in description
    assert "mattermost" in description
    assert "telegram" in description
    assert "teams" in description
    for forbidden in (
        "chat_id",
        "business_connection_id",
        "tenant",
        "microsoft user",
    ):
        assert forbidden in description


# --------------------------------------------------------------------------- prepare / fail closed


def test_prepare_compose_freezes_route_without_root(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account)
    fake = FakeMattermostTransport()
    service = _service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="буду через 20 минут", conversation_object_id=anchor.id)
    )
    assert frozen.mode == "compose"
    assert frozen.provider == "mattermost"
    assert frozen.account_id == account.id
    assert frozen.server_url == ALLOWED_URL
    assert frozen.channel_id == CHANNEL_ID
    assert frozen.source_post_id == POST_ID
    assert frozen.root_id is None
    assert frozen.anchor_object_id == anchor.id
    assert frozen.pending_post_id == pending_post_id_from_operation_id(frozen.operation_id)
    assert fake.calls == []
    assert fake.create_post_calls == []


def test_prepare_top_level_reply_omits_root_id(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account, root_id=None)
    frozen = _service(db_session, user.id, FakeMattermostTransport()).prepare_send_message(
        SendMessageInput(body="буду завтра в 10", reply_to_object_id=anchor.id)
    )
    assert frozen.mode == "reply"
    assert frozen.root_id is None
    assert frozen.source_post_id == POST_ID


def test_prepare_thread_reply_preserves_existing_root(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account, root_id="root-99")
    frozen = _service(db_session, user.id, FakeMattermostTransport()).prepare_send_message(
        SendMessageInput(body="согласен", reply_to_object_id=anchor.id)
    )
    assert frozen.mode == "reply"
    assert frozen.root_id == "root-99"
    assert frozen.source_post_id == POST_ID


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"provider": "gmail"}, "provider"),
        ({"kind": "email"}, "chat_message"),
        ({"deleted": True}, "deleted"),
        ({"rejected": True}, "rejected"),
    ],
)
def test_prepare_rejects_invalid_anchor(
    db_session, credential_key: str, mattermost_settings, kwargs, match
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account, **kwargs)
    fake = FakeMattermostTransport()
    with pytest.raises(ToolError, match=match):
        _service(db_session, user.id, fake).prepare_send_message(
            SendMessageInput(body="hi", conversation_object_id=anchor.id)
        )
    assert fake.create_post_calls == []


def test_prepare_rejects_missing_object(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    _connect_account(db_session, credential_key, user.id)
    with pytest.raises(ToolError, match="not found"):
        _service(db_session, user.id).prepare_send_message(
            SendMessageInput(body="hi", conversation_object_id=uuid4())
        )


def test_prepare_rejects_malformed_account_id(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account, extra_meta={"account_id": "not-a-uuid"})
    with pytest.raises(ToolError, match="account_id"):
        _service(db_session, user.id).prepare_send_message(
            SendMessageInput(body="hi", conversation_object_id=anchor.id)
        )


def test_prepare_rejects_account_not_owned(
    db_session, credential_key: str, mattermost_settings
) -> None:
    owner = User(id=uuid4(), display_name="owner")
    other = User(id=uuid4(), display_name="other")
    db_session.add_all([owner, other])
    db_session.flush()
    account = _connect_account(db_session, credential_key, other.id)
    anchor = _anchor_object(db_session, owner.id, account)
    with pytest.raises(ToolError, match="not connected"):
        _service(db_session, owner.id).prepare_send_message(
            SendMessageInput(body="hi", conversation_object_id=anchor.id)
        )


def test_prepare_rejects_server_mismatch(
    db_session, credential_key: str, mattermost_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.core.config.settings.mattermost_allowed_base_urls",
        f"{ALLOWED_URL},https://other.example.com",
    )
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(
        db_session,
        user.id,
        account,
        server_url="https://other.example.com",
        extra_meta={"server_url": "https://other.example.com"},
    )
    with pytest.raises(ToolError, match="server_url"):
        _service(db_session, user.id).prepare_send_message(
            SendMessageInput(body="hi", conversation_object_id=anchor.id)
        )


def test_prepare_rejects_external_id_mismatch(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(
        db_session,
        user.id,
        account,
        external_id=build_external_id(ALLOWED_URL, "other-post"),
    )
    with pytest.raises(ToolError, match="external_id"):
        _service(db_session, user.id).prepare_send_message(
            SendMessageInput(body="hi", conversation_object_id=anchor.id)
        )


def test_prepare_rejects_missing_channel_id(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account, extra_meta={"channel_id": ""})
    with pytest.raises(ToolError, match="routing"):
        _service(db_session, user.id).prepare_send_message(
            SendMessageInput(body="hi", conversation_object_id=anchor.id)
        )


def test_prepare_ignores_metadata_token_and_makes_zero_writes(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(
        db_session,
        user.id,
        account,
        extra_meta={"access_token": "stolen-token", "Authorization": "Bearer stolen"},
    )
    fake = FakeMattermostTransport()
    frozen = _service(db_session, user.id, fake).prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=anchor.id)
    )
    dumped = frozen.model_dump(mode="json")
    assert "stolen-token" not in json.dumps(dumped)
    assert PAT not in json.dumps(dumped)
    assert fake.create_post_calls == []


# --------------------------------------------------------------------------- Mattermost write transport


def _http_transport(handler) -> MattermostHttpTransport:
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return MattermostHttpTransport(ALLOWED_URL, PAT, http_client=client)


def test_http_create_post_compose_payload_and_authorization() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "id": "new-1",
                "channel_id": CHANNEL_ID,
                "message": "hello",
                "user_id": "user-1",
                "pending_post_id": "secretary:abcde",
            },
        )

    transport = _http_transport(handler)
    created = transport.create_post(CHANNEL_ID, "hello", "secretary:abcde")
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v4/posts"
    assert captured["authorization"] == f"Bearer {PAT}"
    assert captured["body"] == {
        "channel_id": CHANNEL_ID,
        "message": "hello",
        "pending_post_id": "secretary:abcde",
    }
    assert created["id"] == "new-1"


def test_http_create_post_thread_includes_root_id() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "id": "new-2",
                "channel_id": CHANNEL_ID,
                "message": "hello",
                "root_id": "root-99",
                "user_id": "user-1",
            },
        )

    created = _http_transport(handler).create_post(
        CHANNEL_ID, "hello", "secretary:abcde", root_id="root-99"
    )
    assert captured["body"]["root_id"] == "root-99"
    assert set(captured["body"]) == {"channel_id", "message", "pending_post_id", "root_id"}
    assert created["id"] == "new-2"


def test_http_create_post_top_level_reply_omits_root_id() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={"id": "new-3", "channel_id": CHANNEL_ID, "message": "hello", "user_id": "user-1"},
        )

    _http_transport(handler).create_post(CHANNEL_ID, "hello", "secretary:abcde", root_id=None)
    assert "root_id" not in captured["body"]


def test_http_create_post_redirect_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

    with pytest.raises(MattermostSecurityError, match="redirect"):
        _http_transport(handler).create_post(CHANNEL_ID, "hello", "secretary:abcde")


@pytest.mark.parametrize("status", [401, 403, 400, 404, 422])
def test_http_create_post_4xx_is_definite(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "nope"})

    with pytest.raises(MattermostWriteDefiniteError):
        _http_transport(handler).create_post(CHANNEL_ID, "hello", "secretary:abcde")


def test_http_create_post_5xx_is_uncertain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "busy"})

    with pytest.raises(MattermostWriteUncertainError):
        _http_transport(handler).create_post(CHANNEL_ID, "hello", "secretary:abcde")


def test_http_create_post_network_is_uncertain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(MattermostWriteUncertainError):
        _http_transport(handler).create_post(CHANNEL_ID, "hello", "secretary:abcde")


def test_http_create_post_malformed_success_is_uncertain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, text="not-json")

    with pytest.raises(MattermostWriteUncertainError):
        _http_transport(handler).create_post(CHANNEL_ID, "hello", "secretary:abcde")


def test_read_transport_4xx_behavior_unchanged() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/users/me"):
            return httpx.Response(401, json={"message": "nope"})
        return httpx.Response(500, json={"message": "busy"})

    transport = _http_transport(handler)
    with pytest.raises(MattermostUnauthorizedError):
        transport.get_me()

    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "busy"})

    with pytest.raises(MattermostTransportError):
        _http_transport(server_error).list_my_channels()


# --------------------------------------------------------------------------- execute / idempotency


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


def _execute_service(db_session, user_id, fake: FakeMattermostTransport) -> CommunicationExternalActionService:
    return CommunicationExternalActionService(
        db_session,
        user_id,
        transport=fake,
        attempt_session_factory=lambda: _SessionProxy(db_session),
    )


def _load_attempt(db_session, user_id, operation_id: str) -> ExternalActionAttempt:
    attempt = db_session.scalar(
        select(ExternalActionAttempt).where(
            ExternalActionAttempt.user_id == user_id,
            ExternalActionAttempt.operation_id == operation_id,
        )
    )
    assert attempt is not None
    return attempt


def test_successful_execution_posts_once_and_succeeds(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account)
    fake = FakeMattermostTransport()
    service = _execute_service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="буду через 20 минут", conversation_object_id=anchor.id)
    )
    result = service.send_message(frozen)
    assert result.delivery_status == "sent"
    assert result.changed is True
    assert result.provider == "mattermost"
    assert result.mode == "compose"
    assert result.provider_message_id == "created-1"
    assert result.object_id is not None
    assert len(fake.create_post_calls) == 1
    assert fake.create_post_calls[0] == {
        "channel_id": CHANNEL_ID,
        "message": "буду через 20 минут",
        "pending_post_id": frozen.pending_post_id,
    }
    attempt = _load_attempt(db_session, user.id, frozen.operation_id)
    assert attempt.state == ATTEMPT_SUCCEEDED
    assert attempt.tool_name == "send_message"
    assert attempt.provider_external_id == "created-1"
    assert PAT not in json.dumps(attempt.result_metadata)


def test_same_canonical_execution_is_already_sent_without_second_post(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account)
    fake = FakeMattermostTransport()
    service = _execute_service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="повтор", conversation_object_id=anchor.id)
    )
    first = service.send_message(frozen)
    second = service.send_message(frozen)
    assert first.delivery_status == "sent"
    assert second.delivery_status == "already_sent"
    assert second.changed is False
    assert len(fake.create_post_calls) == 1


def test_definite_failure_does_not_resend(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account)
    fake = FakeMattermostTransport(
        create_post_error=MattermostWriteDefiniteError("mattermost write rejected")
    )
    service = _execute_service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=anchor.id)
    )
    with pytest.raises(ToolError, match="rejected"):
        service.send_message(frozen)
    assert _load_attempt(db_session, user.id, frozen.operation_id).state == ATTEMPT_FAILED_DEFINITE
    with pytest.raises(ToolError, match="previously failed"):
        service.send_message(frozen)
    assert len(fake.create_post_calls) == 1


def test_network_ambiguity_marks_uncertain_and_does_not_retry(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account)
    fake = FakeMattermostTransport(
        create_post_error=MattermostWriteUncertainError("mattermost write request failed")
    )
    service = _execute_service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=anchor.id)
    )
    with pytest.raises(ToolError, match="could not confirm"):
        service.send_message(frozen)
    assert _load_attempt(db_session, user.id, frozen.operation_id).state == ATTEMPT_UNCERTAIN
    with pytest.raises(ToolError, match="could not confirm"):
        service.send_message(frozen)
    assert len(fake.create_post_calls) == 1


def test_uncertain_reconciles_from_local_pending_post_id_without_repost(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account)
    fake = FakeMattermostTransport(
        create_post_error=MattermostWriteUncertainError("timeout")
    )
    service = _execute_service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=anchor.id)
    )
    with pytest.raises(ToolError):
        service.send_message(frozen)
    created = Object(
        user_id=user.id,
        kind="chat_message",
        provider="mattermost",
        external_id=build_external_id(ALLOWED_URL, "synced-9"),
        origin="source",
        state="observed",
        title="Alice: hi",
        body="hi",
        metadata_={
            "server_url": ALLOWED_URL,
            "account_id": str(account.id),
            "post_id": "synced-9",
            "channel_id": CHANNEL_ID,
            "pending_post_id": frozen.pending_post_id,
        },
        occurred_at=_utcnow(),
    )
    db_session.add(created)
    db_session.flush()
    result = service.send_message(frozen)
    assert result.delivery_status == "already_sent"
    assert result.object_id == created.id
    assert len(fake.create_post_calls) == 1
    assert _load_attempt(db_session, user.id, frozen.operation_id).state == ATTEMPT_SUCCEEDED


def test_different_operation_ids_are_independent(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account)
    fake = FakeMattermostTransport()
    service = _execute_service(db_session, user.id, fake)
    first = service.prepare_send_message(
        SendMessageInput(body="one", conversation_object_id=anchor.id)
    )
    second = service.prepare_send_message(
        SendMessageInput(body="two", conversation_object_id=anchor.id)
    )
    service.send_message(first)
    service.send_message(second)
    assert len(fake.create_post_calls) == 2
    assert first.operation_id != second.operation_id


def test_mismatched_success_response_is_uncertain_not_success(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account)
    fake = FakeMattermostTransport(
        create_post_response={
            "id": "new-1",
            "channel_id": "other-channel",
            "message": "hello",
            "user_id": "user-1",
        }
    )
    service = _execute_service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="hello", conversation_object_id=anchor.id)
    )
    with pytest.raises(ToolError, match="could not confirm"):
        service.send_message(frozen)
    assert _load_attempt(db_session, user.id, frozen.operation_id).state == ATTEMPT_UNCERTAIN


def test_execution_uses_connected_account_token_not_metadata(
    db_session, credential_key: str, mattermost_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(
        db_session,
        user.id,
        account,
        extra_meta={"access_token": "stolen-from-metadata"},
    )
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.headers["authorization"])
        body = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "id": "new-token",
                "channel_id": CHANNEL_ID,
                "message": "hello",
                "user_id": "user-1",
                "pending_post_id": body["pending_post_id"],
                "create_at": 1_700_000_000_000,
                "update_at": 1_700_000_000_000,
            },
        )

    def factory(base_url, access_token, http_client=None):
        captured.append(access_token)
        client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
        return MattermostHttpTransport(base_url, access_token, http_client=client)

    monkeypatch.setattr(
        "app.services.communication_external_action_service.MattermostHttpTransport",
        factory,
    )
    service = CommunicationExternalActionService(
        db_session,
        user.id,
        attempt_session_factory=lambda: _SessionProxy(db_session),
    )
    frozen = service.prepare_send_message(
        SendMessageInput(body="hello", conversation_object_id=anchor.id)
    )
    result = service.send_message(frozen)
    assert result.delivery_status == "sent"
    assert PAT in captured
    assert "stolen-from-metadata" not in captured
    assert f"Bearer {PAT}" in captured


# --------------------------------------------------------------------------- materialization


def test_successful_post_materializes_canonical_object(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account)
    fake = FakeMattermostTransport()
    service = _execute_service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="новый пост", conversation_object_id=anchor.id)
    )
    result = service.send_message(frozen)
    obj = db_session.get(Object, result.object_id)
    assert obj is not None
    assert obj.provider == "mattermost"
    assert obj.kind == "chat_message"
    assert obj.external_id == build_external_id(ALLOWED_URL, "created-1")
    assert obj.body == "новый пост"
    assert obj.metadata_["post_id"] == "created-1"
    assert obj.metadata_["channel_id"] == CHANNEL_ID
    assert obj.metadata_["pending_post_id"] == frozen.pending_post_id
    assert obj.metadata_["account_id"] == str(account.id)
    assert PAT not in str(obj.metadata_)
    embed_jobs = [
        job
        for job in db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)).all()
        if (job.payload or {}).get("object_id") == str(obj.id)
    ]
    assert len(embed_jobs) == 1


def test_materialize_reuses_existing_object_on_passive_sync_race(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account)
    fake = FakeMattermostTransport(
        create_post_response={
            "id": "race-1",
            "channel_id": CHANNEL_ID,
            "user_id": "user-1",
            "message": "гонки",
            "pending_post_id": "will-be-overwritten-by-service-check",
            "create_at": 1_700_000_000_000,
            "update_at": 1_700_000_000_000,
            "type": "",
            "file_ids": [],
        }
    )
    service = _execute_service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="гонки", conversation_object_id=anchor.id)
    )
    fake.create_post_response["pending_post_id"] = frozen.pending_post_id
    existing = Object(
        user_id=user.id,
        kind="chat_message",
        provider="mattermost",
        external_id=build_external_id(ALLOWED_URL, "race-1"),
        origin="source",
        state="observed",
        title="Alice: гонки",
        body="гонки",
        metadata_={
            "server_url": ALLOWED_URL,
            "account_id": str(account.id),
            "post_id": "race-1",
            "channel_id": CHANNEL_ID,
            "channel_name": "sidorov",
            "channel_display_name": "Sidorov",
            "channel_type": "D",
            "root_id": None,
            "author_user_id": "user-1",
            "author_username": "alice",
            "author_display_name": "Alice",
            "create_at": 1_700_000_000_000,
            "update_at": 1_700_000_000_000,
            "post_type": None,
            "file_ids": [],
            "pending_post_id": frozen.pending_post_id,
        },
        occurred_at=datetime.fromtimestamp(1_700_000_000_000 / 1000, tz=UTC),
    )
    db_session.add(existing)
    db_session.flush()
    existing_id = existing.id
    result = service.send_message(frozen)
    assert result.delivery_status == "sent"
    objects = db_session.scalars(
        select(Object).where(
            Object.user_id == user.id,
            Object.provider == "mattermost",
            Object.kind == "chat_message",
            Object.external_id == build_external_id(ALLOWED_URL, "race-1"),
        )
    ).all()
    assert len(objects) == 1
    assert objects[0].id == existing_id
    assert result.object_id == existing_id


def test_subsequent_passive_sync_does_not_duplicate_or_reembed(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account)
    fake = FakeMattermostTransport()
    service = _execute_service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="синхронизация", conversation_object_id=anchor.id)
    )
    result = service.send_message(frozen)
    obj_id = result.object_id
    assert obj_id is not None
    before = [
        job
        for job in db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)).all()
        if (job.payload or {}).get("object_id") == str(obj_id)
    ]
    assert len(before) == 1
    now = _utcnow()
    created_post = fake.posts_by_channel[CHANNEL_ID][-1]
    sync_transport = FakeMattermostTransport(
        me=fake.me,
        channels=[
            {
                "id": CHANNEL_ID,
                "name": "sidorov",
                "display_name": "Sidorov",
                "type": "D",
                "team_id": None,
                "last_post_at": int(now.timestamp() * 1000),
            }
        ],
        posts_by_channel={CHANNEL_ID: [created_post]},
        users_by_id={
            "user-1": {"id": "user-1", "username": "alice", "display_name": "Alice"},
        },
    )
    sync = build_mattermost_sync_service(
        session=db_session,
        credential_key=credential_key,
        sync_days=14,
        max_channels=50,
        initial_posts_per_channel=100,
        max_posts_per_run=500,
        overlap_seconds=300,
        transport_factory=lambda snapshot: sync_transport,
        now_factory=lambda: now,
    )
    sync.sync_account(account.id, user.id)
    objects = db_session.scalars(
        select(Object).where(
            Object.user_id == user.id,
            Object.provider == "mattermost",
            Object.kind == "chat_message",
            Object.external_id == build_external_id(ALLOWED_URL, "created-1"),
        )
    ).all()
    assert len(objects) == 1
    assert objects[0].id == obj_id
    after = [
        job
        for job in db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)).all()
        if (job.payload or {}).get("object_id") == str(obj_id)
    ]
    assert len(after) == 1


def test_normalize_preserves_provider_pending_post_id_only_when_present() -> None:
    channel = MattermostChannelContext(
        channel_id="ch",
        channel_name="general",
        channel_display_name="General",
        channel_type="O",
        team_id=None,
        team_name=None,
        team_display_name=None,
    )
    account_id = uuid4()
    without_pending = normalize_mattermost_post(
        post={
            "id": "p1",
            "message": "hello",
            "create_at": 1,
            "update_at": 1,
            "user_id": "u1",
            "file_ids": [],
        },
        normalized_server_url=ALLOWED_URL,
        account_id=account_id,
        channel=channel,
        author=None,
    )
    assert without_pending is not None
    assert "pending_post_id" not in without_pending["metadata"]
    with_pending = normalize_mattermost_post(
        post={
            "id": "p2",
            "message": "hello",
            "create_at": 1,
            "update_at": 1,
            "user_id": "u1",
            "pending_post_id": "secretary:abcde",
            "file_ids": [],
        },
        normalized_server_url=ALLOWED_URL,
        account_id=account_id,
        channel=channel,
        author=None,
    )
    assert with_pending is not None
    assert with_pending["metadata"]["pending_post_id"] == "secretary:abcde"


def test_domain_tool_service_prepare_send_message_bridge(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account)
    fake = FakeMattermostTransport()
    tools = DomainToolService(
        db_session,
        user.id,
        mattermost_transport=fake,
        attempt_session_factory=lambda: _SessionProxy(db_session),
    )
    frozen = tools.prepare_send_message(
        SendMessageInput(body="через bridge", conversation_object_id=anchor.id)
    )
    assert frozen.mode == "compose"
    assert fake.create_post_calls == []
    output = tools.send_message(frozen)
    assert output.delivery_status == "sent"


def test_thread_reply_payload_uses_frozen_root(
    db_session, credential_key: str, mattermost_settings
) -> None:
    user = User(id=uuid4(), display_name="uc-a")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account, root_id="root-99")
    fake = FakeMattermostTransport()
    service = _execute_service(db_session, user.id, fake)
    frozen = service.prepare_send_message(
        SendMessageInput(body="в тред", reply_to_object_id=anchor.id)
    )
    service.send_message(frozen)
    assert fake.create_post_calls[0]["root_id"] == "root-99"


def test_send_email_still_registered_separately() -> None:
    assert TOOL_REGISTRY["send_email"].name == "send_email"
    assert TOOL_REGISTRY["send_email"].permission == ToolPermission.COMMUNICATE
    assert "telegram" not in TOOL_REGISTRY
    assert "send_teams_message" not in TOOL_REGISTRY
    with pytest.raises(KeyError):
        TOOL_REGISTRY["send_telegram"]


# --------------------------------------------------------------------------- A-R1: assistant seen-object anchor allowlist


def _patch_session_spy(monkeypatch: pytest.MonkeyPatch, *, approval: bool = True):
    calls: list[tuple[object, str, dict]] = []

    def _run(user_id, tool_name, arguments):
        calls.append((user_id, tool_name, dict(arguments)))
        if not approval:
            raise AssertionError("run_assistant_tool must not be called")
        return ToolExecutionResult(
            success=False,
            tool_name=tool_name,
            status=ToolExecutionStatus.APPROVAL_REQUIRED,
            approval_required=True,
            staged_action={"tool_name": tool_name, "arguments": dict(arguments)},
        )

    monkeypatch.setattr("app.assistant.session.run_assistant_tool", _run)
    return calls


def test_unseen_conversation_anchor_is_tool_error_without_session(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_session_spy(monkeypatch, approval=False)
    budget = PerTurnToolBudget()
    result = budget.run(
        uuid4(),
        "send_message",
        {"body": "буду завтра в 10", "conversation_object_id": str(uuid4())},
    )
    assert result.success is False
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert "not exposed" in (result.error or "")
    assert calls == []


def test_unseen_reply_anchor_is_tool_error_without_session(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_session_spy(monkeypatch, approval=False)
    budget = PerTurnToolBudget()
    result = budget.run(
        uuid4(),
        "send_message",
        {"body": "буду завтра в 10", "reply_to_object_id": str(uuid4())},
    )
    assert result.success is False
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert "not exposed" in (result.error or "")
    assert calls == []


def test_malformed_conversation_anchor_is_tool_error_without_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_session_spy(monkeypatch, approval=False)
    budget = PerTurnToolBudget()
    result = budget.run(
        uuid4(),
        "send_message",
        {"body": "hi", "conversation_object_id": "not-a-uuid"},
    )
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert "invalid" in (result.error or "")
    assert calls == []


def test_malformed_reply_anchor_is_tool_error_without_session(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_session_spy(monkeypatch, approval=False)
    budget = PerTurnToolBudget()
    result = budget.run(
        uuid4(),
        "send_message",
        {"body": "hi", "reply_to_object_id": "also-not-a-uuid"},
    )
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert "invalid" in (result.error or "")
    assert calls == []


def test_malformed_both_or_zero_anchors_rejected_without_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_session_spy(monkeypatch, approval=False)
    budget = PerTurnToolBudget()
    zero = budget.run(uuid4(), "send_message", {"body": "hi"})
    both = budget.run(
        uuid4(),
        "send_message",
        {
            "body": "hi",
            "conversation_object_id": str(uuid4()),
            "reply_to_object_id": str(uuid4()),
        },
    )
    assert zero.status == ToolExecutionStatus.TOOL_ERROR
    assert both.status == ToolExecutionStatus.TOOL_ERROR
    assert "exactly one" in (zero.error or "")
    assert "exactly one" in (both.error or "")
    assert calls == []


def test_seen_conversation_anchor_proceeds_to_approval_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_session_spy(monkeypatch)
    anchor = uuid4()
    budget = PerTurnToolBudget()
    budget.seed_seen_object_ids([anchor])
    result = budget.run(
        uuid4(),
        "send_message",
        {"body": "встреча переносится", "conversation_object_id": str(anchor)},
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert result.staged_action is not None
    assert len(calls) == 1
    assert calls[0][1] == "send_message"
    assert budget.staged_actions


def test_seen_reply_anchor_proceeds_to_approval_staging(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_session_spy(monkeypatch)
    anchor = uuid4()
    budget = PerTurnToolBudget()
    budget.seed_seen_object_ids([anchor])
    result = budget.run(
        uuid4(),
        "send_message",
        {"body": "буду завтра в 10", "reply_to_object_id": str(anchor)},
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert len(calls) == 1
    assert calls[0][2]["reply_to_object_id"] == str(anchor)


def test_initial_seen_object_ids_seed_trusted_ui_context(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_session_spy(monkeypatch)
    anchor = uuid4()
    budget = PerTurnToolBudget(initial_seen_object_ids=[anchor])
    result = budget.run(
        uuid4(),
        "send_message",
        {"body": "из UI контекста", "conversation_object_id": str(anchor)},
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert len(calls) == 1


# --------------------------------------------------------------------------- A-R1: exact provider root_id equality


_OMIT_ROOT = object()


def _success_provider_post(
    frozen: SendMessageCanonicalInput,
    *,
    root_id: object = _OMIT_ROOT,
) -> dict:
    payload = {
        "id": "created-root",
        "channel_id": CHANNEL_ID,
        "message": frozen.body,
        "user_id": "user-1",
        "pending_post_id": frozen.pending_post_id,
    }
    if root_id is not _OMIT_ROOT:
        payload["root_id"] = root_id
    return payload


def _send_with_provider_root(
    db_session,
    credential_key: str,
    *,
    mode: str,
    source_root: str | None,
    response_root: object,
):
    user = User(id=uuid4(), display_name="uc-a-r1")
    db_session.add(user)
    db_session.flush()
    account = _connect_account(db_session, credential_key, user.id)
    anchor = _anchor_object(db_session, user.id, account, root_id=source_root)
    fake = FakeMattermostTransport()
    service = _execute_service(db_session, user.id, fake)
    if mode == "compose":
        frozen = service.prepare_send_message(
            SendMessageInput(body="hello root", conversation_object_id=anchor.id)
        )
    else:
        frozen = service.prepare_send_message(
            SendMessageInput(body="hello root", reply_to_object_id=anchor.id)
        )
    fake.create_post_response = _success_provider_post(frozen, root_id=response_root)
    return service, fake, frozen, user


def test_compose_empty_root_response_is_success(
    db_session, credential_key: str, mattermost_settings
) -> None:
    service, fake, frozen, user = _send_with_provider_root(
        db_session, credential_key, mode="compose", source_root=None, response_root=""
    )
    result = service.send_message(frozen)
    assert result.delivery_status == "sent"
    assert frozen.root_id is None
    assert _load_attempt(db_session, user.id, frozen.operation_id).state == ATTEMPT_SUCCEEDED
    assert len(fake.create_post_calls) == 1


def test_compose_omitted_root_response_is_success(
    db_session, credential_key: str, mattermost_settings
) -> None:
    service, fake, frozen, user = _send_with_provider_root(
        db_session, credential_key, mode="compose", source_root=None, response_root=_OMIT_ROOT
    )
    result = service.send_message(frozen)
    assert result.delivery_status == "sent"
    assert _load_attempt(db_session, user.id, frozen.operation_id).state == ATTEMPT_SUCCEEDED
    assert len(fake.create_post_calls) == 1


def test_compose_unexpected_root_is_uncertain_and_does_not_retry(
    db_session, credential_key: str, mattermost_settings
) -> None:
    service, fake, frozen, user = _send_with_provider_root(
        db_session,
        credential_key,
        mode="compose",
        source_root=None,
        response_root="unexpected",
    )
    with pytest.raises(ToolError, match="could not confirm"):
        service.send_message(frozen)
    assert _load_attempt(db_session, user.id, frozen.operation_id).state == ATTEMPT_UNCERTAIN
    with pytest.raises(ToolError, match="could not confirm"):
        service.send_message(frozen)
    assert len(fake.create_post_calls) == 1


def test_top_level_reply_unexpected_root_is_uncertain_and_does_not_retry(
    db_session, credential_key: str, mattermost_settings
) -> None:
    service, fake, frozen, user = _send_with_provider_root(
        db_session,
        credential_key,
        mode="reply",
        source_root=None,
        response_root="unexpected",
    )
    assert frozen.mode == "reply"
    assert frozen.root_id is None
    with pytest.raises(ToolError, match="could not confirm"):
        service.send_message(frozen)
    assert _load_attempt(db_session, user.id, frozen.operation_id).state == ATTEMPT_UNCERTAIN
    with pytest.raises(ToolError, match="could not confirm"):
        service.send_message(frozen)
    assert len(fake.create_post_calls) == 1


def test_threaded_reply_exact_root_is_success(
    db_session, credential_key: str, mattermost_settings
) -> None:
    service, fake, frozen, user = _send_with_provider_root(
        db_session,
        credential_key,
        mode="reply",
        source_root="root-99",
        response_root="root-99",
    )
    result = service.send_message(frozen)
    assert frozen.root_id == "root-99"
    assert result.delivery_status == "sent"
    assert _load_attempt(db_session, user.id, frozen.operation_id).state == ATTEMPT_SUCCEEDED
    assert len(fake.create_post_calls) == 1


def test_threaded_reply_empty_root_is_uncertain_and_does_not_retry(
    db_session, credential_key: str, mattermost_settings
) -> None:
    service, fake, frozen, user = _send_with_provider_root(
        db_session,
        credential_key,
        mode="reply",
        source_root="root-99",
        response_root="",
    )
    with pytest.raises(ToolError, match="could not confirm"):
        service.send_message(frozen)
    assert _load_attempt(db_session, user.id, frozen.operation_id).state == ATTEMPT_UNCERTAIN
    with pytest.raises(ToolError, match="could not confirm"):
        service.send_message(frozen)
    assert len(fake.create_post_calls) == 1


def test_threaded_reply_different_root_is_uncertain_and_does_not_retry(
    db_session, credential_key: str, mattermost_settings
) -> None:
    service, fake, frozen, user = _send_with_provider_root(
        db_session,
        credential_key,
        mode="reply",
        source_root="root-99",
        response_root="root-other",
    )
    with pytest.raises(ToolError, match="could not confirm"):
        service.send_message(frozen)
    assert _load_attempt(db_session, user.id, frozen.operation_id).state == ATTEMPT_UNCERTAIN
    with pytest.raises(ToolError, match="could not confirm"):
        service.send_message(frozen)
    assert len(fake.create_post_calls) == 1
