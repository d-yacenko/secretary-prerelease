"""Safe External Actions Pass B — approval-bound Gmail send_email."""

from __future__ import annotations

import base64
import copy
import re
import threading
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import delete, select

from app.assistant.tool_runner import PerTurnToolBudget
from app.connectors.google.constants import (
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_READONLY_SCOPE,
    DRIVE_READONLY_SCOPE,
    GMAIL_API_BASE,
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
)
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleApiError
from app.connectors.google.gmail_transport import GmailMessagePage, GmailTransport
from app.core.config import settings
from app.db.models import ExternalActionAttempt, PendingActionPlan, User
from app.db.session import SessionLocal
from app.services.action_plan_service import ActionPlanService
from app.services.domain_tool_service import DomainToolService
from app.services.email_external_action_service import (
    ATTEMPT_FAILED_DEFINITE,
    ATTEMPT_STARTED,
    ATTEMPT_UNCERTAIN,
    SECRETARY_OPERATION_HEADER,
    EmailExternalActionService,
    build_rfc822_raw,
    rfc822_message_id_from_operation_id,
    secretary_operation_header_value,
    sent_window_query,
)
from app.services.errors import ValidationError as ServiceValidationError
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import SendEmailCanonicalInput, SendEmailInput


class FakeGmailTransport:
    def __init__(self) -> None:
        self.messages: dict[str, dict] = {}
        self.send_calls: list[dict] = []
        self.list_calls: list[str] = []
        self.lock = threading.Lock()
        self.persist_on_send = True
        self.lose_send_response = False
        self.send_error: GoogleApiError | None = None
        self.malformed_success = False
        self.before_send = None
        self.field_overrides: dict[str, str] | None = None
        self.strip_operation_header = False
        self.also_store_untagged_clone = False
        self.also_store_tagged_clone = False
        self.force_incomplete_listing = False

    def send_message(self, access_token: str, user_id: str, raw: str) -> dict:
        with self.lock:
            if self.before_send is not None:
                self.before_send()
            self.send_calls.append(
                {"access_token": access_token, "user_id": user_id, "raw": raw}
            )
            parsed = _payload_from_raw(raw, f"msg-{len(self.send_calls)}")
            _apply_gmail_provider_rewrite(parsed)
            if self.strip_operation_header:
                parsed["payload"]["headers"] = [
                    header
                    for header in parsed["payload"]["headers"]
                    if str(header.get("name") or "").lower() != SECRETARY_OPERATION_HEADER.lower()
                ]
            if self.field_overrides:
                headers = parsed["payload"]["headers"]
                for name, value in self.field_overrides.items():
                    replaced = False
                    for header in headers:
                        if header["name"].lower() == name.lower():
                            header["value"] = value
                            replaced = True
                    if not replaced:
                        headers.append({"name": name, "value": value})
            if self.persist_on_send:
                self.messages[parsed["id"]] = parsed
                if self.also_store_untagged_clone:
                    clone = copy.deepcopy(parsed)
                    clone["id"] = f"{parsed['id']}-untagged"
                    clone["payload"]["headers"] = [
                        header
                        for header in clone["payload"]["headers"]
                        if str(header.get("name") or "").lower()
                        != SECRETARY_OPERATION_HEADER.lower()
                    ]
                    self.messages[clone["id"]] = clone
                if self.also_store_tagged_clone:
                    clone = copy.deepcopy(parsed)
                    clone["id"] = f"{parsed['id']}-tagged-dup"
                    self.messages[clone["id"]] = clone
            if self.lose_send_response:
                self.lose_send_response = False
                raise httpx.TimeoutException("lost send response")
            if self.send_error is not None:
                raise self.send_error
            if self.malformed_success:
                self.malformed_success = False
                raise GoogleApiError(
                    "send_message returned a malformed response",
                    operation="send_message",
                    status_code=200,
                    retryable=True,
                )
            return {"id": parsed["id"]}

    def list_message_ids_page(
        self,
        access_token: str,
        user_id: str,
        query: str,
        max_results: int,
        page_token: str | None = None,
    ) -> GmailMessagePage:
        with self.lock:
            self.list_calls.append(query)
            if self.force_incomplete_listing:
                start = int(page_token or 0)
                ids = [f"filler-{start + index}" for index in range(max_results)]
                return GmailMessagePage(ids, next_page_token=str(start + max_results))
            ids = [
                message_id
                for message_id, payload in self.messages.items()
                if _matches_sent_window(payload, query)
            ]
            start = int(page_token or 0)
            chunk = ids[start : start + max_results]
            next_token = str(start + len(chunk)) if start + len(chunk) < len(ids) else None
            return GmailMessagePage(chunk, next_token)

    def list_message_ids(self, access_token: str, user_id: str, query: str, max_results: int) -> list[str]:
        return self.list_message_ids_page(
            access_token, user_id, query, max_results
        ).message_ids

    def get_message(self, access_token: str, user_id: str, message_id: str) -> dict:
        with self.lock:
            message = self.messages.get(message_id)
            if message is None:
                raise GoogleApiError(f"failed to fetch gmail message {message_id}")
            return dict(message)


def _header(payload: dict, name: str) -> str | None:
    headers = (payload.get("payload") or {}).get("headers") or []
    for header in headers:
        if str(header.get("name") or "").lower() == name.lower():
            return str(header.get("value"))
    return None


def _apply_gmail_provider_rewrite(payload: dict) -> None:
    gmail_id = str(payload["id"])
    rewritten = f"<{gmail_id}@mail.gmail.com>"
    headers = payload.setdefault("payload", {}).setdefault("headers", [])
    replaced = False
    for header in headers:
        if str(header.get("name") or "").lower() == "message-id":
            header["value"] = rewritten
            replaced = True
    if not replaced:
        headers.append({"name": "Message-ID", "value": rewritten})
    payload["internalDate"] = str(int(datetime.now(UTC).timestamp() * 1000))


def _matches_sent_window(payload: dict, query: str) -> bool:
    if "in:sent" not in query:
        return False
    after_match = re.search(r"after:(\d+)", query)
    before_match = re.search(r"before:(\d+)", query)
    stamp_ms = payload.get("internalDate")
    epoch = int(int(stamp_ms) / 1000) if stamp_ms else int(datetime.now(UTC).timestamp())
    if after_match and epoch < int(after_match.group(1)):
        return False
    return not (before_match and epoch >= int(before_match.group(1)))


def _payload_from_raw(raw: str, gmail_id: str) -> dict:
    padded = raw + "=" * (-len(raw) % 4)
    parsed = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(padded.encode("ascii"))
    )
    body = parsed.get_content()
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    encoded = base64.urlsafe_b64encode(str(body).encode("utf-8")).decode("ascii").rstrip("=")
    headers = [
        {"name": "From", "value": str(parsed.get("From") or "")},
        {"name": "To", "value": str(parsed.get("To") or "")},
        {"name": "Subject", "value": str(parsed.get("Subject") or "")},
        {"name": "Message-ID", "value": str(parsed.get("Message-ID") or "")},
    ]
    operation_header = parsed.get(SECRETARY_OPERATION_HEADER)
    if operation_header:
        headers.append(
            {"name": SECRETARY_OPERATION_HEADER, "value": str(operation_header)}
        )
    return {
        "id": gmail_id,
        "internalDate": str(int(datetime.now(UTC).timestamp() * 1000)),
        "payload": {
            "mimeType": "text/plain",
            "headers": headers,
            "body": {"data": encoded},
        },
    }


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def google_settings(monkeypatch: pytest.MonkeyPatch, tmp_path, credential_key: str) -> None:
    client_file = tmp_path / "google-oauth-client.json"
    client_file.write_text(
        '{"web": {"client_id": "test-client-id", "client_secret": "test-client-secret"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    monkeypatch.setattr(settings, "google_oauth_client_file", str(client_file))
    monkeypatch.setattr(settings, "google_redirect_uri", "http://localhost/auth/google/callback")


def _store(db_session, credential_key: str) -> GoogleAccountStore:
    return GoogleAccountStore(db_session, CredentialEncryption(credential_key))


def _add_google_account(db_session, credential_key: str, email: str, scopes: list[str], *, user_id):
    return _store(db_session, credential_key).upsert_tokens(
        user_id=user_id,
        email=email,
        scopes=scopes,
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
    )


def _send_scopes() -> list[str]:
    return [
        GMAIL_READONLY_SCOPE,
        GMAIL_SEND_SCOPE,
        CALENDAR_READONLY_SCOPE,
        CALENDAR_EVENTS_SCOPE,
        DRIVE_READONLY_SCOPE,
    ]


def _mail_args(**overrides) -> dict:
    payload = {
        "to": ["ivan@example.com"],
        "subject": "Статус задачи",
        "body": "Краткий статус: работа продолжается.",
    }
    payload.update(overrides)
    return payload


def _patch_execution(monkeypatch, fake: FakeGmailTransport) -> None:
    original_init = DomainToolService.__init__

    def patched(self, *args, **kwargs):
        kwargs.setdefault("gmail_transport", fake)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(DomainToolService, "__init__", patched)
    monkeypatch.setattr(
        EmailExternalActionService,
        "_valid_access_token",
        lambda self, account_id: "access-token",
    )


@pytest.fixture
def mail_user(db_session):
    user_id = uuid4()
    db_session.add(User(id=user_id, display_name="gmail-action-user"))
    db_session.flush()
    return user_id


def _other_user(db_session):
    user_id = uuid4()
    db_session.add(User(id=user_id, display_name="other"))
    db_session.flush()
    return user_id


@pytest.fixture
def committed_mail_user(google_settings, credential_key):
    session = SessionLocal()
    user_id = uuid4()
    try:
        session.add(User(id=user_id, display_name="gmail-committed-user"))
        session.commit()
        _add_google_account(
            session, credential_key, "user@example.com", _send_scopes(), user_id=user_id
        )
        session.commit()
        yield user_id
    finally:
        session.execute(
            delete(ExternalActionAttempt).where(ExternalActionAttempt.user_id == user_id)
        )
        session.execute(delete(PendingActionPlan).where(PendingActionPlan.user_id == user_id))
        session.commit()
        session.close()


def test_interactive_send_email_requires_approval_without_provider_send(
    db_session, google_settings, credential_key, monkeypatch, mail_user
):
    fake = FakeGmailTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _send_scopes(), user_id=mail_user)
    tools = DomainToolService(db_session, mail_user, gmail_transport=fake)
    result = ToolExecutionGateway().execute(
        tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert fake.send_calls == []
    args = result.staged_action["arguments"]
    assert args["account_email"] == "user@example.com"
    assert args["to"] == ["ivan@example.com"]
    assert args["subject"] == "Статус задачи"
    assert args["body"] == "Краткий статус: работа продолжается."
    assert args["operation_id"]
    assert args["rfc822_message_id"] == rfc822_message_id_from_operation_id(args["operation_id"])
    attempts = db_session.scalars(select(ExternalActionAttempt)).all()
    assert attempts == []


def test_reject_and_expire_do_not_send(
    db_session, google_settings, credential_key, monkeypatch, mail_user
):
    fake = FakeGmailTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _send_scopes(), user_id=mail_user)
    tools = DomainToolService(db_session, mail_user, gmail_transport=fake)
    gateway = ToolExecutionGateway()
    service = ActionPlanService(db_session, mail_user)

    rejected = gateway.execute(
        tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
    )
    service.reject(service.create_plan([rejected.staged_action]).id)
    assert fake.send_calls == []

    expired = gateway.execute(
        tools, "send_email", _mail_args(subject="Expire"), context=ExecutionContext.INTERACTIVE_ASSISTANT
    )
    expired_plan = service.create_plan([expired.staged_action])
    row = db_session.get(PendingActionPlan, expired_plan.id)
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    service.approve(expired_plan.id)
    assert fake.send_calls == []


def test_mcp_send_email_requires_approval_without_provider_send(
    db_session, google_settings, credential_key, monkeypatch, mail_user
):
    fake = FakeGmailTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _send_scopes(), user_id=mail_user)
    tools = DomainToolService(db_session, mail_user, gmail_transport=fake)
    result = ToolExecutionGateway().execute(
        tools, "send_email", _mail_args(), context=ExecutionContext.MCP
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert fake.send_calls == []


def test_approve_sends_frozen_message_once(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        plan = ActionPlanService(session, committed_mail_user).create_plan([staged.staged_action])
        first = ActionPlanService(session, committed_mail_user).approve(plan.id)
        assert first.status == "executed"
        assert first.result["actions"][0]["output"]["changed"] is True
        assert first.result["actions"][0]["output"]["provider"] == "gmail"
        assert len(fake.send_calls) == 1
        parsed = _payload_from_raw(fake.send_calls[0]["raw"], "check")
        assert _header(parsed, "From") == "user@example.com"
        assert "ivan@example.com" in (_header(parsed, "To") or "")
        assert _header(parsed, "Subject") == "Статус задачи"
        body_data = parsed["payload"]["body"]["data"]
        decoded_body = base64.urlsafe_b64decode(
            body_data + "=" * (-len(body_data) % 4)
        ).decode("utf-8")
        assert "Краткий статус" in decoded_body
        assert _header(parsed, SECRETARY_OPERATION_HEADER) == staged.staged_action["arguments"][
            "operation_id"
        ]
        stored_sent = next(iter(fake.messages.values()))
        assert (_header(stored_sent, "Message-ID") or "").endswith("@mail.gmail.com>")
        assert _header(stored_sent, "Message-ID") != staged.staged_action["arguments"][
            "rfc822_message_id"
        ]
        assert _header(stored_sent, SECRETARY_OPERATION_HEADER) == staged.staged_action[
            "arguments"
        ]["operation_id"]
        second = ActionPlanService(session, committed_mail_user).approve(plan.id)
        assert second.status == "executed"
        assert len(fake.send_calls) == 1
        public = str(plan.actions)
        assert "operation_id" not in public
        assert "rfc822_message_id" not in public
        stored = session.get(PendingActionPlan, plan.id)
        assert stored.actions[0]["arguments"]["operation_id"]
        assert stored.actions[0]["arguments"]["rfc822_message_id"]
        assert "access-token" not in str(stored.actions)
        assert "refresh-token" not in str(first.result)
    finally:
        session.close()


def test_account_resolution_zero_one_two_and_foreign(
    db_session, google_settings, credential_key, mail_user
):
    fake = FakeGmailTransport()
    tools = DomainToolService(db_session, mail_user, gmail_transport=fake)
    gateway = ToolExecutionGateway()

    none = gateway.execute(
        tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
    )
    assert none.status == ToolExecutionStatus.TOOL_ERROR
    assert "connected" in (none.error or "").lower()

    _add_google_account(db_session, credential_key, "only@example.com", _send_scopes(), user_id=mail_user)
    one = gateway.execute(
        tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
    )
    assert one.staged_action["arguments"]["account_email"] == "only@example.com"

    _add_google_account(db_session, credential_key, "two@example.com", _send_scopes(), user_id=mail_user)
    ambiguous = gateway.execute(
        tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
    )
    assert "multiple Google accounts" in (ambiguous.error or "")

    explicit = gateway.execute(
        tools,
        "send_email",
        _mail_args(account_email="two@example.com"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert explicit.staged_action["arguments"]["account_email"] == "two@example.com"

    other = _other_user(db_session)
    _add_google_account(
        db_session, credential_key, "foreign@example.com", _send_scopes(), user_id=other
    )
    foreign = gateway.execute(
        tools,
        "send_email",
        _mail_args(account_email="foreign@example.com"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert foreign.status == ToolExecutionStatus.TOOL_ERROR
    assert fake.send_calls == []


def test_missing_send_scope_cannot_stage(db_session, google_settings, credential_key, mail_user):
    fake = FakeGmailTransport()
    _add_google_account(
        db_session,
        credential_key,
        "ro@example.com",
        [GMAIL_READONLY_SCOPE, CALENDAR_READONLY_SCOPE, DRIVE_READONLY_SCOPE],
        user_id=mail_user,
    )
    tools = DomainToolService(db_session, mail_user, gmail_transport=fake)
    result = ToolExecutionGateway().execute(
        tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
    )
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert "reconnected" in (result.error or "").lower()
    assert fake.send_calls == []


def test_security_input_bounds(db_session, google_settings, credential_key, mail_user):
    fake = FakeGmailTransport()
    _add_google_account(db_session, credential_key, "user@example.com", _send_scopes(), user_id=mail_user)
    tools = DomainToolService(db_session, mail_user, gmail_transport=fake)
    gateway = ToolExecutionGateway()

    for extra in (
        {"from": "attacker@example.com"},
        {"cc": ["cc@example.com"]},
        {"bcc": ["bcc@example.com"]},
        {"attachments": ["file"]},
        {"headers": {"X-Evil": "1"}},
        {"raw": "raw-mime"},
        {"operation_id": "deadbeefdeadbeefdeadbeefdeadbeef"},
        {"rfc822_message_id": "<x@y>"},
        {"message_id": "<x@y>"},
        {"html": "<b>x</b>"},
        {SECRETARY_OPERATION_HEADER: "evil-id"},
        {"x_secretary_operation_id": "evil-id"},
    ):
        result = gateway.execute(
            tools,
            "send_email",
            {**_mail_args(), **extra},
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        assert result.status == ToolExecutionStatus.TOOL_ERROR

    crlf_to = gateway.execute(
        tools,
        "send_email",
        _mail_args(to=["ivan@example.com\r\nBcc: hidden@example.com"]),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert crlf_to.status == ToolExecutionStatus.TOOL_ERROR

    crlf_subject = gateway.execute(
        tools,
        "send_email",
        _mail_args(subject="Hello\r\nBcc: hidden@example.com"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert crlf_subject.status == ToolExecutionStatus.TOOL_ERROR
    assert fake.send_calls == []


def test_llm_cannot_smuggle_extra_fields_into_input_model():
    with pytest.raises(PydanticValidationError):
        SendEmailInput.model_validate({**_mail_args(), "from": "attacker@example.com"})
    with pytest.raises(PydanticValidationError):
        SendEmailInput.model_validate({**_mail_args(), "cc": ["a@b.c"]})
    with pytest.raises(PydanticValidationError):
        SendEmailInput.model_validate({**_mail_args(), "operation_id": "abcde12345"})
    with pytest.raises(PydanticValidationError):
        SendEmailInput.model_validate({**_mail_args(), "rfc822_message_id": "<x@y>"})
    with pytest.raises(PydanticValidationError):
        SendEmailInput.model_validate(
            {**_mail_args(), SECRETARY_OPERATION_HEADER: "deadbeefdeadbeefdeadbeefdeadbeef"}
        )


def test_attempt_started_is_visible_before_provider_send(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    seen: list[str] = []

    def before_send() -> None:
        observer = SessionLocal()
        try:
            attempt = observer.scalar(
                select(ExternalActionAttempt).where(
                    ExternalActionAttempt.user_id == committed_mail_user
                )
            )
            assert attempt is not None
            assert attempt.state == ATTEMPT_STARTED
            seen.append(attempt.state)
        finally:
            observer.close()

    fake.before_send = before_send
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        executed = ToolExecutionGateway().execute(
            tools,
            "send_email",
            staged.staged_action["arguments"],
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert executed.success is True
        assert seen == [ATTEMPT_STARTED]
        assert len(fake.send_calls) == 1
    finally:
        session.close()


def test_outer_plan_rollback_cannot_erase_attempt_guard(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    fake.send_error = GoogleApiError(
        "invalid recipient", operation="send_message", status_code=400, retryable=False
    )
    _patch_execution(monkeypatch, fake)
    plan_session = SessionLocal()
    try:
        tools = DomainToolService(plan_session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        nested = plan_session.begin_nested()
        try:
            ToolExecutionGateway().execute(
                tools,
                "send_email",
                staged.staged_action["arguments"],
                context=ExecutionContext.APPROVED_ACTION_PLAN,
            )
        finally:
            nested.rollback()
        plan_session.rollback()
        operation_id = staged.staged_action["arguments"]["operation_id"]
        observer = SessionLocal()
        try:
            attempt = observer.scalar(
                select(ExternalActionAttempt).where(
                    ExternalActionAttempt.user_id == committed_mail_user,
                    ExternalActionAttempt.operation_id == operation_id,
                )
            )
            assert attempt is not None
            assert attempt.state == ATTEMPT_FAILED_DEFINITE
        finally:
            observer.close()
        assert len(fake.send_calls) == 1
    finally:
        plan_session.close()


def test_concurrent_same_operation_id_sends_once(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        args = staged.staged_action["arguments"]
        errors: list[Exception] = []

        def worker() -> None:
            worker_session = SessionLocal()
            try:
                worker_tools = DomainToolService(
                    worker_session, committed_mail_user, gmail_transport=fake
                )
                result = ToolExecutionGateway().execute(
                    worker_tools,
                    "send_email",
                    args,
                    context=ExecutionContext.APPROVED_ACTION_PLAN,
                )
                if not result.success and "could not confirm" not in (result.error or ""):
                    errors.append(RuntimeError(result.error))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                worker_session.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert len(fake.send_calls) == 1
    finally:
        session.close()


def test_started_attempt_from_crash_reconciles_existing_sent_without_resend(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        args = staged.staged_action["arguments"]
        stored = _payload_from_raw(
            build_rfc822_raw(SendEmailCanonicalInput.model_validate(args)),
            "gmail-crash",
        )
        _apply_gmail_provider_rewrite(stored)
        fake.messages[stored["id"]] = stored
        assert (_header(stored, "Message-ID") or "").endswith("@mail.gmail.com>")
        assert _header(stored, "Message-ID") != args["rfc822_message_id"]
        assert _header(stored, SECRETARY_OPERATION_HEADER) == args["operation_id"]
        claim = SessionLocal()
        try:
            claim.add(
                ExternalActionAttempt(
                    user_id=committed_mail_user,
                    operation_id=args["operation_id"],
                    tool_name="send_email",
                    state=ATTEMPT_STARTED,
                    started_at=datetime.now(UTC),
                )
            )
            claim.commit()
        finally:
            claim.close()
        executed = ToolExecutionGateway().execute(
            tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert executed.success is True
        assert executed.output["changed"] is False
        assert executed.output["delivery_status"] == "already_sent"
        assert fake.send_calls == []
    finally:
        session.close()


def test_started_attempt_from_crash_without_sent_stays_uncertain(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        args = staged.staged_action["arguments"]
        claim = SessionLocal()
        try:
            claim.add(
                ExternalActionAttempt(
                    user_id=committed_mail_user,
                    operation_id=args["operation_id"],
                    tool_name="send_email",
                    state=ATTEMPT_STARTED,
                    started_at=datetime.now(UTC),
                )
            )
            claim.commit()
        finally:
            claim.close()
        executed = ToolExecutionGateway().execute(
            tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert executed.success is False
        assert "could not confirm" in (executed.error or "")
        assert fake.send_calls == []
    finally:
        session.close()


def test_failed_definite_does_not_resend(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    fake.send_error = GoogleApiError(
        "invalid recipient", operation="send_message", status_code=400, retryable=False
    )
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        args = staged.staged_action["arguments"]
        first = ToolExecutionGateway().execute(
            tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert first.success is False
        fake.send_error = None
        second = ToolExecutionGateway().execute(
            tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert second.success is False
        assert len(fake.send_calls) == 1
    finally:
        session.close()


def test_timeout_after_accept_reconciles_changed_false(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    fake.lose_send_response = True
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        executed = ToolExecutionGateway().execute(
            tools,
            "send_email",
            staged.staged_action["arguments"],
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert executed.success is True
        assert executed.output["changed"] is False
        assert executed.output["delivery_status"] == "already_sent"
        assert len(fake.send_calls) == 1
        stored_sent = next(iter(fake.messages.values()))
        assert (_header(stored_sent, "Message-ID") or "").endswith("@mail.gmail.com>")
        assert _header(stored_sent, "Message-ID") != staged.staged_action["arguments"][
            "rfc822_message_id"
        ]
        assert _header(stored_sent, SECRETARY_OPERATION_HEADER) == staged.staged_action[
            "arguments"
        ]["operation_id"]
        assert fake.list_calls
        assert "rfc822msgid:" not in fake.list_calls[0]
        assert fake.list_calls[0].startswith("in:sent after:")
        assert "before:" in fake.list_calls[0]
    finally:
        session.close()


def test_retryable_503_after_accept_reconciles(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    fake.send_error = GoogleApiError(
        "backendError", operation="send_message", status_code=503, retryable=True
    )
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        executed = ToolExecutionGateway().execute(
            tools,
            "send_email",
            staged.staged_action["arguments"],
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert executed.success is True
        assert executed.output["changed"] is False
        assert len(fake.send_calls) == 1
    finally:
        session.close()


def test_malformed_2xx_after_accept_reconciles(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    fake.malformed_success = True
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        executed = ToolExecutionGateway().execute(
            tools,
            "send_email",
            staged.staged_action["arguments"],
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert executed.success is True
        assert executed.output["changed"] is False
        assert len(fake.send_calls) == 1
    finally:
        session.close()


def test_ambiguous_without_sent_match_stays_uncertain_no_resend(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    fake.persist_on_send = False
    fake.lose_send_response = True
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        args = staged.staged_action["arguments"]
        first = ToolExecutionGateway().execute(
            tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert first.success is False
        assert "could not confirm" in (first.error or "")
        second = ToolExecutionGateway().execute(
            tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert second.success is False
        assert len(fake.send_calls) == 1
        observer = SessionLocal()
        try:
            attempt = observer.scalar(
                select(ExternalActionAttempt).where(
                    ExternalActionAttempt.operation_id == args["operation_id"]
                )
            )
            assert attempt.state == ATTEMPT_UNCERTAIN
        finally:
            observer.close()
    finally:
        session.close()


def test_operation_header_mismatch_fails_closed(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    fake.lose_send_response = True
    fake.field_overrides = {"Subject": "other subject"}
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        args = staged.staged_action["arguments"]
        first = ToolExecutionGateway().execute(
            tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert first.success is False
        assert "does not match" in (first.error or "")
        second = ToolExecutionGateway().execute(
            tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert second.success is False
        assert len(fake.send_calls) == 1
    finally:
        session.close()


def test_matching_content_without_operation_header_is_not_this_operation(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    fake.lose_send_response = True
    fake.strip_operation_header = True
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        args = staged.staged_action["arguments"]
        first = ToolExecutionGateway().execute(
            tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert first.success is False
        assert "could not confirm" in (first.error or "")
        second = ToolExecutionGateway().execute(
            tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert second.success is False
        assert len(fake.send_calls) == 1
    finally:
        session.close()


def test_identical_untagged_neighbor_is_ignored(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    fake.lose_send_response = True
    fake.also_store_untagged_clone = True
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        executed = ToolExecutionGateway().execute(
            tools,
            "send_email",
            staged.staged_action["arguments"],
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert executed.success is True
        assert executed.output["changed"] is False
        assert executed.output["provider_message_id"] == "msg-1"
        assert "msg-1-untagged" in fake.messages
        assert len(fake.send_calls) == 1
    finally:
        session.close()


def test_duplicate_operation_header_is_uncertain_without_resend(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    fake.lose_send_response = True
    fake.also_store_tagged_clone = True
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        args = staged.staged_action["arguments"]
        first = ToolExecutionGateway().execute(
            tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert first.success is False
        assert "multiple sent messages" in (first.error or "")
        second = ToolExecutionGateway().execute(
            tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert second.success is False
        assert len(fake.send_calls) == 1
    finally:
        session.close()


def test_incomplete_sent_search_is_uncertain_without_resend(
    google_settings, credential_key, monkeypatch, committed_mail_user
):
    fake = FakeGmailTransport()
    fake.lose_send_response = True
    fake.force_incomplete_listing = True
    _patch_execution(monkeypatch, fake)
    session = SessionLocal()
    try:
        tools = DomainToolService(session, committed_mail_user, gmail_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        args = staged.staged_action["arguments"]
        first = ToolExecutionGateway().execute(
            tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert first.success is False
        assert "could not confirm" in (first.error or "")
        second = ToolExecutionGateway().execute(
            tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert second.success is False
        assert len(fake.send_calls) == 1
    finally:
        session.close()


def _bind_tool_session(monkeypatch, db_session) -> None:
    class BoundSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    monkeypatch.setattr("app.assistant.session.SessionLocal", BoundSession)


def test_reads_then_send_email_stages_only_communicate(
    db_session, google_settings, credential_key, monkeypatch, mail_user, fake_embedding_service
):
    fake = FakeGmailTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _send_scopes(), user_id=mail_user)
    _bind_tool_session(monkeypatch, db_session)
    budget = PerTurnToolBudget()
    read = budget.run(mail_user, "get_today", {})
    mail = budget.run(mail_user, "send_email", _mail_args())
    assert read.success is True
    assert mail.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert [action["tool_name"] for action in budget.staged_actions] == ["send_email"]
    preview = str(budget.staged_actions[0]["arguments"])
    assert "Краткий статус" in preview
    assert fake.send_calls == []


def test_send_email_cannot_mix_with_internal_or_calendar(
    db_session, google_settings, credential_key, monkeypatch, mail_user, fake_embedding_service
):
    fake = FakeGmailTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _send_scopes(), user_id=mail_user)
    _bind_tool_session(monkeypatch, db_session)
    budget = PerTurnToolBudget()
    mail = budget.run(mail_user, "send_email", _mail_args())
    task = budget.run(mail_user, "create_task", {"title": "Too late", "confidence": 0.9})
    assert mail.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert task.status == ToolExecutionStatus.TOOL_ERROR
    with pytest.raises(ServiceValidationError, match="only action"):
        ActionPlanService(db_session, mail_user).create_plan(
            [
                {"tool_name": "send_email", "arguments": _mail_args()},
                {"tool_name": "create_task", "arguments": {"title": "Mixed", "confidence": 0.9}},
            ]
        )


def test_gmail_transport_send_is_mechanical():
    captured = {}

    class Client:
        def post(self, url, json=None, headers=None, **kwargs):
            captured["url"] = url
            captured["json"] = json
            assert "Authorization" in headers
            return httpx.Response(200, json={"id": "gmail-1"})

        def get(self, url, params=None, headers=None, **kwargs):
            return httpx.Response(200, json={"messages": [{"id": "gmail-1"}]})

    transport = GmailTransport(http_client=Client())
    sent = transport.send_message("tok", "me", "Zm9v")
    assert sent["id"] == "gmail-1"
    assert captured["url"].startswith(GMAIL_API_BASE)
    assert "/messages/send" in captured["url"]
    assert captured["json"] == {"raw": "Zm9v"}


def test_gmail_transport_malformed_2xx_raises() -> None:
    class MalformedClient:
        def post(self, url, json=None, headers=None, **kwargs):
            return httpx.Response(200, json=["not", "an", "object"])

    transport = GmailTransport(http_client=MalformedClient())
    with pytest.raises(GoogleApiError) as exc:
        transport.send_message("tok", "me", "Zm9v")
    assert exc.value.retryable is True
    assert exc.value.status_code == 200


def test_deterministic_message_id_algorithm():
    operation_id = "deadbeefdeadbeefdeadbeefdeadbeef"
    assert rfc822_message_id_from_operation_id(operation_id) == (
        "<secretary.deadbeefdeadbeefdeadbeefdeadbeef@secretary.invalid>"
    )
    assert secretary_operation_header_value(operation_id) == operation_id
    started = datetime(2026, 9, 6, 6, 30, tzinfo=UTC)
    query = sent_window_query(started_at=started)
    assert query.startswith("in:sent after:")
    assert "before:" in query
    assert "rfc822msgid:" not in query
    payload = SendEmailCanonicalInput.model_validate(
        {
            **_mail_args(),
            "account_email": "user@example.com",
            "operation_id": operation_id,
            "rfc822_message_id": rfc822_message_id_from_operation_id(operation_id),
        }
    )
    parsed = _payload_from_raw(build_rfc822_raw(payload), "mime")
    assert _header(parsed, SECRETARY_OPERATION_HEADER) == operation_id
    assert _header(parsed, "Message-ID") == rfc822_message_id_from_operation_id(operation_id)


def test_tokens_and_raw_mime_absent_from_public_plan(
    db_session, google_settings, credential_key, mail_user
):
    fake = FakeGmailTransport()
    _add_google_account(db_session, credential_key, "user@example.com", _send_scopes(), user_id=mail_user)
    tools = DomainToolService(db_session, mail_user, gmail_transport=fake)
    staged = ToolExecutionGateway().execute(
        tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT
    )
    dumped = str(staged.staged_action)
    assert "access-token" not in dumped
    assert "refresh-token" not in dumped
    plan = ActionPlanService(db_session, mail_user).create_plan([staged.staged_action])
    assert "rfc822_message_id" not in str(plan.actions)
    assert "operation_id" not in str(plan.actions)
    assert SECRETARY_OPERATION_HEADER not in str(plan.actions)
    assert "MIME-Version" not in str(plan.actions)
    assert "raw" not in plan.actions[0]["arguments"]


def test_canonical_input_rejects_llm_supplied_identity_fields():
    payload = SendEmailCanonicalInput.model_validate(
        {
            **_mail_args(),
            "account_email": "user@example.com",
            "operation_id": "deadbeefdeadbeefdeadbeefdeadbeef",
            "rfc822_message_id": rfc822_message_id_from_operation_id(
                "deadbeefdeadbeefdeadbeefdeadbeef"
            ),
        }
    )
    assert payload.rfc822_message_id.startswith("<secretary.")
    with pytest.raises(PydanticValidationError):
        SendEmailCanonicalInput.model_validate(
            {
                **payload.model_dump(),
                "from": "attacker@example.com",
            }
        )
