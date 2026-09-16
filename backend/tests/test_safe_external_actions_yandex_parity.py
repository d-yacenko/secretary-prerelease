"""Yandex parity for universal send_email and create_calendar_event."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from email.policy import SMTP
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import delete

from app.assistant.action_plan_constants import PENDING_ACTION_PLAN_STATUS_EXECUTED
from app.connectors.google.constants import (
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_READONLY_SCOPE,
    DRIVE_READONLY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
)
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.yandex.caldav_transport import CalDavCalendar, FakeCalDavTransport
from app.connectors.yandex.caldav_write import (
    MAX_TARGET_CALENDARS,
    build_vevent_ics,
    caldav_resource_name,
    caldav_uid_from_operation_id,
    event_href_from_operation_id,
    select_unique_vevent_calendar,
)
from app.connectors.yandex.calendar_credentials import YandexCalendarAccountStore
from app.connectors.yandex.credentials import YandexMailAccountStore
from app.connectors.yandex.errors import YandexCalDavError, YandexImapError, YandexSmtpError
from app.connectors.yandex.imap_mailboxes import (
    ImapMailbox,
    parse_imap_list_line,
    sent_folder_from_mailboxes,
)
from app.connectors.yandex.imap_transport import FakeImapTransport, parse_imap_internaldate
from app.connectors.yandex.smtp_transport import FakeSmtpTransport
from app.core.config import settings
from app.db.models import (
    ExternalActionAttempt,
    GoogleAccount,
    PendingActionPlan,
    User,
    YandexCalendarAccount,
)
from app.db.session import SessionLocal
from app.services.action_plan_service import ActionPlanService
from app.services.calendar_external_action_service import (
    ATTEMPT_FAILED_DEFINITE,
    ATTEMPT_STARTED,
    ATTEMPT_SUCCEEDED,
    ATTEMPT_UNCERTAIN,
    CALENDAR_TOOL_NAME,
    CalendarExternalActionService,
)
from app.services.domain_tool_service import DomainToolService
from app.services.email_external_action_service import (
    METADATA_SENT_COPY_STATE,
    SECRETARY_OPERATION_HEADER,
    SECRETARY_UNCERTAIN_FOLDER,
    SENT_COPY_NOT_STARTED,
    SENT_COPY_STARTED,
    SENT_COPY_STORED,
    SENT_COPY_UNCERTAIN,
    EmailExternalActionService,
    build_email_message,
    rfc822_message_id_from_operation_id,
    secretary_operation_header_value,
    yandex_sent_coarse_imap_bounds,
    yandex_sent_evidence_window,
)
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import (
    CreateCalendarEventCanonicalInput,
    SendEmailCanonicalInput,
    SendEmailInput,
    ToolError,
)


class FakeCalendarTransport:
    def __init__(self) -> None:
        self.insert_calls: list[dict] = []
        self.events: dict[str, dict] = {}

    def insert_event(self, access_token: str, calendar_id: str, body: dict) -> dict:
        self.insert_calls.append({"calendar_id": calendar_id, "body": dict(body)})
        event_id = str(body["id"])
        stored = {
            "id": event_id,
            "summary": body["summary"],
            "start": dict(body["start"]),
            "end": dict(body["end"]),
        }
        self.events[event_id] = stored
        return dict(stored)

    def get_event(self, access_token: str, calendar_id: str, event_id: str) -> dict:
        return dict(self.events[event_id])


class FakeGmailTransport:
    def __init__(self) -> None:
        self.send_calls: list[dict] = []

    def send_message(self, access_token: str, user_id: str, raw: str) -> dict:
        self.send_calls.append({"raw": raw})
        return {"id": f"gmail-{len(self.send_calls)}"}


SENT_FOLDER = "Отправленные"
CALENDAR_HREF = "/calendars/user@yandex.ru/events-default/"
ENCODED_CALENDAR_HREF = "/calendars/test.user%40example.test/events-424242/"


def test_caldav_resource_name_is_percent_encoded_uid() -> None:
    operation_id = "c553a47646e34a3c83113233666a2396"
    uid = caldav_uid_from_operation_id(operation_id)
    assert uid == "secretary-c553a47646e34a3c83113233666a2396@secretary"
    assert caldav_resource_name(operation_id) == (
        "secretary-c553a47646e34a3c83113233666a2396%40secretary.ics"
    )
    assert event_href_from_operation_id(CALENDAR_HREF, operation_id) == (
        "/calendars/user@yandex.ru/events-default/"
        "secretary-c553a47646e34a3c83113233666a2396%40secretary.ics"
    )
    encoded = event_href_from_operation_id(ENCODED_CALENDAR_HREF, operation_id)
    assert encoded == (
        "/calendars/test.user%40example.test/events-424242/"
        "secretary-c553a47646e34a3c83113233666a2396%40secretary.ics"
    )
    assert "%2540" not in encoded
    assert encoded.count("%40") == 2


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


@pytest.fixture
def owner(db_session):
    user_id = uuid4()
    db_session.add(User(id=user_id, display_name="parity-user"))
    db_session.flush()
    return user_id


def _send_scopes() -> list[str]:
    return [
        GMAIL_READONLY_SCOPE,
        GMAIL_SEND_SCOPE,
        CALENDAR_READONLY_SCOPE,
        CALENDAR_EVENTS_SCOPE,
        DRIVE_READONLY_SCOPE,
    ]


def _add_google(db_session, credential_key: str, email: str, *, user_id):
    return GoogleAccountStore(db_session, CredentialEncryption(credential_key)).upsert_tokens(
        user_id=user_id,
        email=email,
        scopes=_send_scopes(),
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
    )


def _add_yandex_mail(db_session, credential_key: str, email: str, *, user_id):
    return YandexMailAccountStore(db_session, CredentialEncryption(credential_key)).upsert_account(
        user_id=user_id,
        email=email,
        app_password="yandex-app-password",
        imap_host="imap.yandex.ru",
        imap_port=993,
    )


def _add_yandex_calendar(db_session, credential_key: str, email: str, *, user_id):
    return YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key)).upsert_account(
        user_id=user_id,
        email=email,
        app_password="yandex-caldav-password",
        caldav_host="caldav.yandex.ru",
    )


def _mail_args(**overrides) -> dict:
    payload = {
        "to": ["ivan@example.com"],
        "subject": "Статус задачи",
        "body": "Краткий статус: работа продолжается.",
    }
    payload.update(overrides)
    return payload


def _event_args(**overrides) -> dict:
    payload = {
        "summary": "Созвон",
        "start_at": datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
        "end_at": datetime(2026, 9, 6, 12, 30, tzinfo=UTC),
        "description": "Weekly",
        "location": "Office",
    }
    payload.update(overrides)
    return payload


def _sent_imap() -> FakeImapTransport:
    return FakeImapTransport(
        folder="INBOX",
        messages={},
        mailboxes=[
            ImapMailbox(flags=frozenset({"HASNOCHILDREN"}), name="INBOX"),
            ImapMailbox(flags=frozenset({"HASNOCHILDREN", "SENT"}), name=SENT_FOLDER),
        ],
        folder_messages={"INBOX": {}, SENT_FOLDER: {}},
    )


def _mail_fakes() -> tuple[FakeSmtpTransport, FakeImapTransport]:
    imap = _sent_imap()
    return FakeSmtpTransport(imap=imap, sent_folder=SENT_FOLDER), imap


def _vevent_calendar(
    href: str,
    display_name: str | None = "default",
    sync_token: str | None = "t",
) -> CalDavCalendar:
    return CalDavCalendar(
        href=href,
        display_name=display_name,
        sync_token=sync_token,
        supported_components=frozenset({"VEVENT"}),
    )


def _vtodo_calendar(
    href: str,
    display_name: str | None = "todos",
    sync_token: str | None = "t",
) -> CalDavCalendar:
    return CalDavCalendar(
        href=href,
        display_name=display_name,
        sync_token=sync_token,
        supported_components=frozenset({"VTODO"}),
    )


def _calendar_fake() -> FakeCalDavTransport:
    return FakeCalDavTransport(calendars=[_vevent_calendar(CALENDAR_HREF)])


def _patch_mail(monkeypatch, smtp: FakeSmtpTransport, imap: FakeImapTransport) -> None:
    original_init = DomainToolService.__init__

    def patched(self, *args, **kwargs):
        kwargs.setdefault("yandex_smtp_transport", smtp)
        kwargs.setdefault("yandex_imap_transport", imap)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(DomainToolService, "__init__", patched)


def _patch_calendar(monkeypatch, caldav: FakeCalDavTransport) -> None:
    original_init = DomainToolService.__init__

    def patched(self, *args, **kwargs):
        kwargs.setdefault("yandex_caldav_transport", caldav)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(DomainToolService, "__init__", patched)


def _keepalive(session):
    class _Proxy:
        def __init__(self, inner):
            object.__setattr__(self, "_inner", inner)

        def close(self) -> None:
            return None

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def __setattr__(self, name, value):
            setattr(self._inner, name, value)

    return _Proxy(session)


def _tools_mail(db_session, user_id, smtp, imap, gmail=None):
    return DomainToolService(
        db_session,
        user_id,
        gmail_transport=gmail or FakeGmailTransport(),
        yandex_smtp_transport=smtp,
        yandex_imap_transport=imap,
        attempt_session_factory=lambda: _keepalive(db_session),
    )


def _tools_cal(db_session, user_id, caldav, google=None):
    return DomainToolService(
        db_session,
        user_id,
        calendar_transport=google or FakeCalendarTransport(),
        yandex_caldav_transport=caldav,
    )


def test_imap_sent_folder_uses_special_use_not_english_name() -> None:
    parsed = parse_imap_list_line('(\\HasNoChildren \\Sent) "/" "Отправленные"')
    assert parsed is not None
    assert sent_folder_from_mailboxes([parsed]) == "Отправленные"
    with pytest.raises(Exception, match="Sent folder"):
        sent_folder_from_mailboxes([ImapMailbox(flags=frozenset(), name="Sent")])


def test_provider_resolution_matrix(db_session, google_settings, credential_key, owner):
    gateway = ToolExecutionGateway()
    smtp, imap = _mail_fakes()
    tools = _tools_mail(db_session, owner, smtp, imap)
    none = gateway.execute(tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT)
    assert none.status == ToolExecutionStatus.TOOL_ERROR
    assert "connected" in (none.error or "").lower()

    _add_google(db_session, credential_key, "only-google@example.com", user_id=owner)
    google_only = gateway.execute(tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT)
    assert google_only.staged_action["arguments"]["provider"] == "google"

    db_session.execute(delete(GoogleAccount).where(GoogleAccount.user_id == owner))
    db_session.flush()
    _add_yandex_mail(db_session, credential_key, "only-yandex@yandex.ru", user_id=owner)
    yandex_only = gateway.execute(tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT)
    assert yandex_only.staged_action["arguments"]["provider"] == "yandex"

    _add_google(db_session, credential_key, "google@example.com", user_id=owner)
    both = gateway.execute(tools, "send_email", _mail_args(), context=ExecutionContext.INTERACTIVE_ASSISTANT)
    assert both.status == ToolExecutionStatus.TOOL_ERROR

    assert gateway.execute(
        tools, "send_email", _mail_args(provider="yandex"), context=ExecutionContext.INTERACTIVE_ASSISTANT
    ).staged_action["arguments"]["provider"] == "yandex"
    assert gateway.execute(
        tools, "send_email", _mail_args(provider="google"), context=ExecutionContext.INTERACTIVE_ASSISTANT
    ).staged_action["arguments"]["provider"] == "google"
    assert gateway.execute(
        tools,
        "send_email",
        _mail_args(account_email="only-yandex@yandex.ru"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    ).staged_action["arguments"]["provider"] == "yandex"

    _add_yandex_mail(db_session, credential_key, "google@example.com", user_id=owner)
    clash = gateway.execute(
        tools, "send_email", _mail_args(account_email="google@example.com"), context=ExecutionContext.INTERACTIVE_ASSISTANT
    )
    assert clash.status == ToolExecutionStatus.TOOL_ERROR

    other = uuid4()
    db_session.add(User(id=other, display_name="other"))
    db_session.flush()
    _add_google(db_session, credential_key, "foreign@example.com", user_id=other)
    foreign = gateway.execute(
        tools, "send_email", _mail_args(account_email="foreign@example.com"), context=ExecutionContext.INTERACTIVE_ASSISTANT
    )
    assert foreign.status == ToolExecutionStatus.TOOL_ERROR
    assert smtp.send_calls == []


def test_legacy_google_plan_without_provider(db_session, google_settings, credential_key, owner, monkeypatch):
    gmail = FakeGmailTransport()
    smtp, imap = _mail_fakes()
    monkeypatch.setattr(
        EmailExternalActionService, "_valid_access_token", lambda self, account_id: "access-token"
    )
    _add_google(db_session, credential_key, "user@example.com", user_id=owner)
    operation_id = "deadbeefdeadbeefdeadbeefdeadbeef"
    args = {
        "account_email": "user@example.com",
        "to": ["ivan@example.com"],
        "subject": "Legacy",
        "body": "Legacy body",
        "operation_id": operation_id,
        "rfc822_message_id": rfc822_message_id_from_operation_id(operation_id),
    }
    tools = _tools_mail(db_session, owner, smtp, imap, gmail=gmail)
    result = ToolExecutionGateway().execute(
        tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
    )
    assert result.success is True
    assert len(gmail.send_calls) == 1
    assert smtp.send_calls == []
    _add_yandex_mail(db_session, credential_key, "user@example.com", user_id=owner)
    blocked = ToolExecutionGateway().execute(
        tools, "send_email", args, context=ExecutionContext.APPROVED_ACTION_PLAN
    )
    assert blocked.success is False
    assert len(gmail.send_calls) == 1


def test_yandex_mail_approval_gates(db_session, google_settings, credential_key, owner, monkeypatch):
    smtp, imap = _mail_fakes()
    _patch_mail(monkeypatch, smtp, imap)
    _add_yandex_mail(db_session, credential_key, "user@yandex.ru", user_id=owner)
    tools = _tools_mail(db_session, owner, smtp, imap)
    gateway = ToolExecutionGateway()
    interactive = gateway.execute(
        tools, "send_email", _mail_args(provider="yandex"), context=ExecutionContext.INTERACTIVE_ASSISTANT
    )
    assert interactive.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert interactive.staged_action["arguments"]["provider"] == "yandex"
    assert smtp.send_calls == []
    mcp = gateway.execute(tools, "send_email", _mail_args(provider="yandex"), context=ExecutionContext.MCP)
    assert mcp.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert smtp.send_calls == []
    assert imap.append_calls == []
    assert imap.create_calls == []
    service = ActionPlanService(db_session, owner)
    rejected = gateway.execute(
        tools, "send_email", _mail_args(provider="yandex"), context=ExecutionContext.INTERACTIVE_ASSISTANT
    )
    service.reject(service.create_plan([rejected.staged_action]).id)
    expired = gateway.execute(
        tools,
        "send_email",
        _mail_args(provider="yandex", subject="Expire"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    expired_plan = service.create_plan([expired.staged_action])
    row = db_session.get(PendingActionPlan, expired_plan.id)
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    service.approve(expired_plan.id)
    assert smtp.send_calls == []
    assert imap.append_calls == []
    assert imap.create_calls == []


def test_yandex_mail_approve_sends_once(google_settings, credential_key, monkeypatch):
    smtp, imap = _mail_fakes()
    _patch_mail(monkeypatch, smtp, imap)
    session = SessionLocal()
    user_id = uuid4()
    try:
        session.add(User(id=user_id, display_name="yandex-mail"))
        session.commit()
        _add_yandex_mail(session, credential_key, "user@yandex.ru", user_id=user_id)
        session.commit()
        tools = _tools_mail(session, user_id, smtp, imap)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(provider="yandex"), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        assert "yandex-app-password" not in str(staged.staged_action)
        plan = ActionPlanService(session, user_id).create_plan([staged.staged_action])
        assert "operation_id" not in str(plan.actions)
        first = ActionPlanService(session, user_id).approve(plan.id)
        output = first.result["actions"][0]["output"]
        assert output["changed"] is True
        assert output["provider"] == "yandex"
        assert output["delivery_status"] == "sent"
        assert output["sent_copy_status"] == "stored"
        assert first.result["actions"][0]["effect_description"] == (
            "Письмо отправлено. Копия сохранена в Отправленных."
        )
        assert len(smtp.send_calls) == 1
        assert len(imap.append_calls) == 1
        assert imap.append_calls[0]["folder"] == SENT_FOLDER
        assert imap.append_calls[0]["message_bytes"] == smtp.send_calls[0]["message_bytes"]
        parsed = build_email_message(
            SendEmailCanonicalInput.model_validate(staged.staged_action["arguments"])
        )
        raw = smtp.send_calls[0]["message_bytes"]
        assert SECRETARY_OPERATION_HEADER.encode() in raw
        assert parsed["Message-ID"].encode() in raw
        assert b"yandex-app-password" not in raw
        ActionPlanService(session, user_id).approve(plan.id)
        assert len(smtp.send_calls) == 1
        assert len(imap.append_calls) == 1
        repeated = ToolExecutionGateway().execute(
            tools,
            "send_email",
            staged.staged_action["arguments"],
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert repeated.success is True
        assert repeated.output["changed"] is False
        assert repeated.output["sent_copy_status"] == "already_present"
        assert len(smtp.send_calls) == 1
        assert len(imap.append_calls) == 1
    finally:
        session.execute(delete(ExternalActionAttempt).where(ExternalActionAttempt.user_id == user_id))
        session.execute(delete(PendingActionPlan).where(PendingActionPlan.user_id == user_id))
        session.commit()
        session.close()


def test_yandex_mail_action_plan_survives_post_smtp_copy_error(google_settings, credential_key, monkeypatch):
    smtp, imap = _mail_fakes()
    _patch_mail(monkeypatch, smtp, imap)

    def boom(self, *args, **kwargs):
        raise RuntimeError("sent-copy bookkeeping exploded")

    monkeypatch.setattr(EmailExternalActionService, "_complete_yandex_sent_copy", boom)
    session, user_id = _isolated_mail(credential_key)
    try:
        tools = _tools_mail(session, user_id, smtp, imap)
        staged = ToolExecutionGateway().execute(
            tools, "send_email", _mail_args(provider="yandex"), context=ExecutionContext.INTERACTIVE_ASSISTANT
        )
        plan = ActionPlanService(session, user_id).create_plan([staged.staged_action])
        first = ActionPlanService(session, user_id).approve(plan.id)
        assert first.status == PENDING_ACTION_PLAN_STATUS_EXECUTED
        assert first.failure is None
        output = first.result["actions"][0]["output"]
        assert output["delivery_status"] == "sent"
        assert output["changed"] is True
        assert output["sent_copy_status"] == "unconfirmed"
        assert len(smtp.send_calls) == 1
        repeated = ActionPlanService(session, user_id).approve(plan.id)
        assert repeated.status == PENDING_ACTION_PLAN_STATUS_EXECUTED
        assert len(smtp.send_calls) == 1
    finally:
        _cleanup_isolated(session, user_id)


def test_yandex_mail_action_plan_lock_serializes_approve(google_settings, credential_key, monkeypatch):
    smtp, imap = _mail_fakes()
    _patch_mail(monkeypatch, smtp, imap)
    session, user_id = _isolated_mail(credential_key)
    try:
        staged = ToolExecutionGateway().execute(
            _tools_mail(session, user_id, smtp, imap),
            "send_email",
            _mail_args(provider="yandex"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        plan = ActionPlanService(session, user_id).create_plan([staged.staged_action])
        session.commit()
        errors: list[BaseException] = []

        def worker() -> None:
            worker_session = SessionLocal()
            try:
                ActionPlanService(worker_session, user_id).approve(plan.id)
                worker_session.commit()
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
        assert len(smtp.send_calls) == 1
        assert [call for call in imap.append_calls if call["folder"] == SECRETARY_UNCERTAIN_FOLDER] == []
        session.expire_all()
        stored = ActionPlanService(session, user_id).approve(plan.id)
        assert stored.status == PENDING_ACTION_PLAN_STATUS_EXECUTED
        assert len(smtp.send_calls) == 1
    finally:
        _cleanup_isolated(session, user_id)


def test_yandex_mail_concurrent_smtp_once(google_settings, credential_key, monkeypatch):
    smtp, imap = _mail_fakes()
    _patch_mail(monkeypatch, smtp, imap)
    session = SessionLocal()
    user_id = uuid4()
    try:
        session.add(User(id=user_id, display_name="yandex-conc"))
        session.commit()
        _add_yandex_mail(session, credential_key, "user@yandex.ru", user_id=user_id)
        session.commit()
        args = ToolExecutionGateway().execute(
            _tools_mail(session, user_id, smtp, imap),
            "send_email",
            _mail_args(provider="yandex"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        ).staged_action["arguments"]

        def worker() -> None:
            worker_session = SessionLocal()
            try:
                ToolExecutionGateway().execute(
                    _tools_mail(worker_session, user_id, smtp, imap),
                    "send_email",
                    args,
                    context=ExecutionContext.APPROVED_ACTION_PLAN,
                )
            finally:
                worker_session.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(smtp.send_calls) == 1
        sent_appends = [call for call in imap.append_calls if call["folder"] == SENT_FOLDER]
        assert len(sent_appends) == 1
        assert [call for call in imap.append_calls if call["folder"] == SECRETARY_UNCERTAIN_FOLDER] == []
    finally:
        session.execute(delete(ExternalActionAttempt).where(ExternalActionAttempt.user_id == user_id))
        session.execute(delete(PendingActionPlan).where(PendingActionPlan.user_id == user_id))
        session.commit()
        session.close()


def _isolated_mail(credential_key: str):
    session = SessionLocal()
    user_id = uuid4()
    session.add(User(id=user_id, display_name="yandex-iso"))
    session.commit()
    _add_yandex_mail(session, credential_key, "user@yandex.ru", user_id=user_id)
    session.commit()
    return session, user_id


def _cleanup_isolated(session, user_id) -> None:
    session.execute(delete(ExternalActionAttempt).where(ExternalActionAttempt.user_id == user_id))
    session.execute(delete(PendingActionPlan).where(PendingActionPlan.user_id == user_id))
    session.commit()
    session.close()


def _execute_yandex_send(db_session, owner, smtp, imap, **mail_overrides):
    tools = _tools_mail(db_session, owner, smtp, imap)
    gateway = ToolExecutionGateway()
    staged = gateway.execute(
        tools,
        "send_email",
        _mail_args(provider="yandex", **mail_overrides),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    result = gateway.execute(
        tools, "send_email", staged.staged_action["arguments"], context=ExecutionContext.APPROVED_ACTION_PLAN
    )
    return result, smtp, imap, staged.staged_action["arguments"]


def _attempt_for(db_session, owner, operation_id: str) -> ExternalActionAttempt:
    return db_session.query(ExternalActionAttempt).filter_by(
        user_id=owner, operation_id=operation_id
    ).one()


def _with_provider_valarm(ics: str) -> str:
    alarm = (
        "BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:Yandex reminder\r\n"
        "TRIGGER:-PT15M\r\nEND:VALARM\r\n"
    )
    return ics.replace("END:VEVENT", alarm + "END:VEVENT", 1)


def _isolated_calendar(credential_key: str):
    session = SessionLocal()
    user_id = uuid4()
    session.add(User(id=user_id, display_name="yandex-cal"))
    session.commit()
    _add_yandex_calendar(session, credential_key, "user@yandex.ru", user_id=user_id)
    session.commit()
    return session, user_id


def _cleanup_isolated_calendar(session, user_id) -> None:
    session.execute(delete(ExternalActionAttempt).where(ExternalActionAttempt.user_id == user_id))
    session.execute(delete(PendingActionPlan).where(PendingActionPlan.user_id == user_id))
    session.execute(delete(GoogleAccount).where(GoogleAccount.user_id == user_id))
    session.execute(delete(YandexCalendarAccount).where(YandexCalendarAccount.user_id == user_id))
    session.commit()
    session.close()


def test_yandex_mail_clear_success_appends_sent_once(
    db_session, google_settings, credential_key, owner
):
    _add_yandex_mail(db_session, credential_key, "user@yandex.ru", user_id=owner)
    smtp, imap = _mail_fakes()
    result, smtp, imap, args = _execute_yandex_send(db_session, owner, smtp, imap)
    assert result.success is True
    assert result.output["delivery_status"] == "sent"
    assert result.output["changed"] is True
    assert result.output["sent_copy_status"] == "stored"
    assert len(smtp.send_calls) == 1
    assert len(imap.append_calls) == 1
    assert imap.append_calls[0]["folder"] == SENT_FOLDER
    assert imap.append_calls[0]["flags"] == ["\\Seen"]
    raw = smtp.send_calls[0]["message_bytes"]
    assert raw == imap.append_calls[0]["message_bytes"]
    parsed = build_email_message(SendEmailCanonicalInput.model_validate(args))
    assert parsed["From"] == "user@yandex.ru"
    assert parsed["To"] == "ivan@example.com"
    assert parsed["Subject"] == "Статус задачи"
    assert parsed["Message-ID"] == args["rfc822_message_id"]
    assert parsed[SECRETARY_OPERATION_HEADER] == secretary_operation_header_value(args["operation_id"])
    assert parsed["From"].encode() in raw
    assert parsed["Message-ID"].encode() in raw
    attempt = _attempt_for(db_session, owner, args["operation_id"])
    assert attempt.state == ATTEMPT_SUCCEEDED
    assert attempt.result_metadata[METADATA_SENT_COPY_STATE] == SENT_COPY_STORED


def test_yandex_mail_sent_copy_failure_keeps_smtp_success(google_settings, credential_key):
    session, owner = _isolated_mail(credential_key)
    try:
        smtp, imap = _mail_fakes()
        imap.append_error = YandexImapError("quota exceeded")
        result, smtp, imap, args = _execute_yandex_send(session, owner, smtp, imap)
        assert result.success is True
        assert result.output["delivery_status"] == "sent"
        assert result.output["changed"] is True
        assert result.output["sent_copy_status"] == "unconfirmed"
        assert len(smtp.send_calls) == 1
        assert len(imap.append_calls) == 1
        attempt = _attempt_for(session, owner, args["operation_id"])
        assert attempt.state == ATTEMPT_SUCCEEDED
        resume = ToolExecutionGateway().execute(
            _tools_mail(session, owner, smtp, imap),
            "send_email",
            args,
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert resume.success is True
        assert len(smtp.send_calls) == 1
        assert len(imap.append_calls) == 1
    finally:
        _cleanup_isolated(session, owner)


def test_yandex_mail_append_lost_response_then_found(
    db_session, google_settings, credential_key, owner
):
    _add_yandex_mail(db_session, credential_key, "user@yandex.ru", user_id=owner)
    smtp, imap = _mail_fakes()
    imap.lose_append_response = True
    result, smtp, imap, args = _execute_yandex_send(db_session, owner, smtp, imap)
    assert result.success is True
    assert result.output["sent_copy_status"] == "stored"
    assert len(smtp.send_calls) == 1
    assert len(imap.append_calls) == 1
    attempt = _attempt_for(db_session, owner, args["operation_id"])
    assert attempt.state == ATTEMPT_SUCCEEDED
    assert attempt.result_metadata[METADATA_SENT_COPY_STATE] == SENT_COPY_STORED


def test_yandex_mail_append_ambiguous_without_copy(google_settings, credential_key):
    session, owner = _isolated_mail(credential_key)
    try:
        smtp, imap = _mail_fakes()
        imap.persist_on_append = False
        imap.lose_append_response = True
        result, smtp, imap, args = _execute_yandex_send(session, owner, smtp, imap)
        assert result.success is True
        assert result.output["delivery_status"] == "sent"
        assert result.output["sent_copy_status"] == "unconfirmed"
        assert len(smtp.send_calls) == 1
        assert len(imap.append_calls) == 1
        attempt = _attempt_for(session, owner, args["operation_id"])
        assert attempt.state == ATTEMPT_SUCCEEDED
        assert attempt.result_metadata[METADATA_SENT_COPY_STATE] == SENT_COPY_UNCERTAIN
        resume = ToolExecutionGateway().execute(
            _tools_mail(session, owner, smtp, imap),
            "send_email",
            args,
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert resume.success is True
        assert len(smtp.send_calls) == 1
        assert len(imap.append_calls) == 1
    finally:
        _cleanup_isolated(session, owner)


def test_yandex_mail_crash_windows(google_settings, credential_key):
    session, owner = _isolated_mail(credential_key)
    try:
        smtp, imap = _mail_fakes()
        staged = ToolExecutionGateway().execute(
            _tools_mail(session, owner, smtp, imap),
            "send_email",
            _mail_args(provider="yandex"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        args = staged.staged_action["arguments"]
        session.add(
            ExternalActionAttempt(
                user_id=owner,
                operation_id=args["operation_id"],
                tool_name="send_email",
                state=ATTEMPT_SUCCEEDED,
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                result_metadata={
                    "delivery_status": "sent",
                    METADATA_SENT_COPY_STATE: SENT_COPY_NOT_STARTED,
                },
            )
        )
        session.commit()
        resumed = ToolExecutionGateway().execute(
            _tools_mail(session, owner, smtp, imap),
            "send_email",
            args,
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert resumed.success is True
        assert smtp.send_calls == []
        assert len(imap.append_calls) == 1
        assert imap.append_calls[0]["folder"] == SENT_FOLDER

        smtp2, imap2 = _mail_fakes()
        staged2 = ToolExecutionGateway().execute(
            _tools_mail(session, owner, smtp2, imap2),
            "send_email",
            _mail_args(provider="yandex", subject="Started copy"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        args2 = staged2.staged_action["arguments"]
        session.add(
            ExternalActionAttempt(
                user_id=owner,
                operation_id=args2["operation_id"],
                tool_name="send_email",
                state=ATTEMPT_SUCCEEDED,
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                result_metadata={
                    "delivery_status": "sent",
                    METADATA_SENT_COPY_STATE: SENT_COPY_STARTED,
                },
            )
        )
        session.commit()
        started_resume = ToolExecutionGateway().execute(
            _tools_mail(session, owner, smtp2, imap2),
            "send_email",
            args2,
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert started_resume.success is True
        assert smtp2.send_calls == []
        assert imap2.append_calls == []
        assert started_resume.output["sent_copy_status"] == "unconfirmed"

        smtp3, imap3 = _mail_fakes()
        staged3 = ToolExecutionGateway().execute(
            _tools_mail(session, owner, smtp3, imap3),
            "send_email",
            _mail_args(provider="yandex", subject="Already copied"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        args3 = staged3.staged_action["arguments"]
        imap3.add_message(
            SENT_FOLDER,
            9,
            build_email_message(SendEmailCanonicalInput.model_validate(args3)).as_bytes(policy=SMTP),
        )
        session.add(
            ExternalActionAttempt(
                user_id=owner,
                operation_id=args3["operation_id"],
                tool_name="send_email",
                state=ATTEMPT_SUCCEEDED,
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                result_metadata={
                    "delivery_status": "sent",
                    METADATA_SENT_COPY_STATE: SENT_COPY_STARTED,
                },
            )
        )
        session.commit()
        present = ToolExecutionGateway().execute(
            _tools_mail(session, owner, smtp3, imap3),
            "send_email",
            args3,
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert present.success is True
        assert present.output["sent_copy_status"] in {"stored", "already_present"}
        assert smtp3.send_calls == []
        assert imap3.append_calls == []
    finally:
        _cleanup_isolated(session, owner)


def test_yandex_mail_ambiguous_smtp_uses_uncertain_folder(google_settings, credential_key):
    session, owner = _isolated_mail(credential_key)
    try:
        smtp, imap = _mail_fakes()
        smtp.lose_send_response = True
        result, smtp, imap, args = _execute_yandex_send(session, owner, smtp, imap)
        assert result.success is False
        assert len(smtp.send_calls) == 1
        assert [call["folder"] for call in imap.append_calls] == [SECRETARY_UNCERTAIN_FOLDER]
        assert imap.append_calls[0]["message_bytes"] == smtp.send_calls[0]["message_bytes"]
        attempt = _attempt_for(session, owner, args["operation_id"])
        assert attempt.state == ATTEMPT_UNCERTAIN
        resume = ToolExecutionGateway().execute(
            _tools_mail(session, owner, smtp, imap),
            "send_email",
            args,
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert resume.success is False
        assert len(smtp.send_calls) == 1
        assert len(imap.append_calls) == 1
        session.expire_all()
        assert _attempt_for(session, owner, args["operation_id"]).state == ATTEMPT_UNCERTAIN
    finally:
        _cleanup_isolated(session, owner)


def test_yandex_mail_uncertain_artifact_not_delivery_proof(google_settings, credential_key):
    session, owner = _isolated_mail(credential_key)
    try:
        smtp, imap = _mail_fakes()
        staged = ToolExecutionGateway().execute(
            _tools_mail(session, owner, smtp, imap),
            "send_email",
            _mail_args(provider="yandex"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        args = staged.staged_action["arguments"]
        imap.ensure_mailbox(SECRETARY_UNCERTAIN_FOLDER)
        imap.add_message(
            SECRETARY_UNCERTAIN_FOLDER,
            3,
            build_email_message(SendEmailCanonicalInput.model_validate(args)).as_bytes(policy=SMTP),
        )
        session.add(
            ExternalActionAttempt(
                user_id=owner,
                operation_id=args["operation_id"],
                tool_name="send_email",
                state=ATTEMPT_UNCERTAIN,
                started_at=datetime.now(UTC),
                result_metadata={"error": "could not confirm email delivery; not retrying send"},
            )
        )
        session.commit()
        resumed = ToolExecutionGateway().execute(
            _tools_mail(session, owner, smtp, imap),
            "send_email",
            args,
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert resumed.success is False
        assert smtp.send_calls == []
        assert imap.append_calls == []
        session.expire_all()
        assert _attempt_for(session, owner, args["operation_id"]).state == ATTEMPT_UNCERTAIN
    finally:
        _cleanup_isolated(session, owner)


def test_yandex_mail_uncertain_create_error_does_not_resend(google_settings, credential_key):
    session, owner = _isolated_mail(credential_key)
    try:
        smtp, imap = _mail_fakes()
        smtp.lose_send_response = True
        imap.create_error = YandexImapError("cannot create mailbox")
        result, smtp, imap, args = _execute_yandex_send(session, owner, smtp, imap)
        assert result.success is False
        assert len(smtp.send_calls) == 1
        assert imap.append_calls == []
        assert _attempt_for(session, owner, args["operation_id"]).state == ATTEMPT_UNCERTAIN
    finally:
        _cleanup_isolated(session, owner)


def test_yandex_mail_definite_smtp_failure_no_mailbox_copy(google_settings, credential_key):
    session, owner = _isolated_mail(credential_key)
    try:
        smtp, imap = _mail_fakes()
        smtp.send_error = YandexSmtpError("password=yandex-app-password leaked", retryable=False)
        result, smtp, imap, args = _execute_yandex_send(session, owner, smtp, imap)
        assert result.success is False
        assert "password" not in (result.error or "").lower()
        assert "yandex-app-password" not in (result.error or "")
        assert len(smtp.send_calls) == 1
        assert imap.append_calls == []
        assert imap.create_calls == []
        assert _attempt_for(session, owner, args["operation_id"]).state == ATTEMPT_FAILED_DEFINITE
    finally:
        _cleanup_isolated(session, owner)


def test_yandex_sent_internaldate_window_helpers() -> None:
    started_at = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    window_start, window_end = yandex_sent_evidence_window(started_at)
    assert window_start == datetime(2026, 9, 6, 10, 0, tzinfo=UTC)
    assert window_end == datetime(2026, 9, 6, 14, 0, tzinfo=UTC)
    since, before = yandex_sent_coarse_imap_bounds(started_at)
    assert since == datetime(2026, 9, 6, 0, 0, tzinfo=UTC)
    assert before == datetime(2026, 9, 7, 0, 0, tzinfo=UTC)


def test_cross_provider_mail_dispatch(db_session, google_settings, credential_key, owner, monkeypatch):
    gmail = FakeGmailTransport()
    smtp, imap = _mail_fakes()
    monkeypatch.setattr(
        EmailExternalActionService, "_valid_access_token", lambda self, account_id: "access-token"
    )
    _add_google(db_session, credential_key, "user@example.com", user_id=owner)
    _add_yandex_mail(db_session, credential_key, "user@yandex.ru", user_id=owner)
    tools = DomainToolService(
        db_session,
        owner,
        gmail_transport=gmail,
        yandex_smtp_transport=smtp,
        yandex_imap_transport=imap,
        attempt_session_factory=lambda: _keepalive(db_session),
    )
    gateway = ToolExecutionGateway()
    google_staged = gateway.execute(
        tools, "send_email", _mail_args(provider="google"), context=ExecutionContext.INTERACTIVE_ASSISTANT
    )
    gateway.execute(
        tools,
        "send_email",
        google_staged.staged_action["arguments"],
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert len(gmail.send_calls) == 1
    assert smtp.send_calls == []
    yandex_staged = gateway.execute(
        tools, "send_email", _mail_args(provider="yandex"), context=ExecutionContext.INTERACTIVE_ASSISTANT
    )
    gateway.execute(
        tools,
        "send_email",
        yandex_staged.staged_action["arguments"],
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert len(gmail.send_calls) == 1
    assert len(smtp.send_calls) == 1


def test_yandex_calendar_create_and_gates(google_settings, credential_key, monkeypatch):
    caldav = _calendar_fake()
    google = FakeCalendarTransport()
    _patch_calendar(monkeypatch, caldav)
    db_session, owner = _isolated_calendar(credential_key)
    try:
        tools = _tools_cal(db_session, owner, caldav, google)
        gateway = ToolExecutionGateway()
        interactive = gateway.execute(
            tools,
            "create_calendar_event",
            _event_args(provider="yandex"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        assert interactive.status == ToolExecutionStatus.APPROVAL_REQUIRED
        args = interactive.staged_action["arguments"]
        assert args["provider"] == "yandex"
        assert args["calendar_href"] == CALENDAR_HREF
        assert caldav.put_calls == []
        public = ActionPlanService(db_session, owner).create_plan([interactive.staged_action])
        assert "calendar_href" not in str(public.actions)
        assert "yandex-caldav-password" not in str(public.actions)
        mcp = gateway.execute(
            tools,
            "create_calendar_event",
            _event_args(provider="yandex"),
            context=ExecutionContext.MCP,
        )
        assert mcp.status == ToolExecutionStatus.APPROVAL_REQUIRED
        service = ActionPlanService(db_session, owner)
        rejected = gateway.execute(
            tools,
            "create_calendar_event",
            _event_args(provider="yandex", summary="Reject"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        service.reject(service.create_plan([rejected.staged_action]).id)
        expired = gateway.execute(
            tools,
            "create_calendar_event",
            _event_args(provider="yandex", summary="Expire"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        expired_plan = service.create_plan([expired.staged_action])
        row = db_session.get(PendingActionPlan, expired_plan.id)
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        service.approve(expired_plan.id)
        assert caldav.put_calls == []
        db_session.expire_all()
        assert (
            db_session.query(ExternalActionAttempt)
            .filter_by(user_id=owner, tool_name=CALENDAR_TOOL_NAME)
            .count()
            == 0
        )
        executed = gateway.execute(
            tools, "create_calendar_event", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert executed.success is True
        assert executed.output["provider"] == "yandex_calendar"
        assert len(caldav.put_calls) == 1
        assert google.insert_calls == []
        href = event_href_from_operation_id(CALENDAR_HREF, args["operation_id"])
        uid = caldav_uid_from_operation_id(args["operation_id"])
        assert caldav_resource_name(args["operation_id"]) == uid.replace("@", "%40") + ".ics"
        assert href.endswith("/" + caldav_resource_name(args["operation_id"]))
        assert caldav.put_calls[0]["href"] == href
        assert caldav.put_calls[0]["if_none_match"] == "*"
        db_session.expire_all()
        attempt = _attempt_for(db_session, owner, args["operation_id"])
        assert attempt.state == ATTEMPT_SUCCEEDED
        assert attempt.tool_name == CALENDAR_TOOL_NAME
        assert attempt.provider_external_id == href
        stored = caldav.objects[href]
        repeated = gateway.execute(
            tools, "create_calendar_event", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert repeated.success is True
        assert repeated.output["changed"] is False
        assert caldav.put_hrefs == [href]
        assert [call["if_none_match"] for call in caldav.put_calls] == ["*"]
        assert caldav.objects[href] == stored
        assert list(caldav.objects) == [href]
    finally:
        _cleanup_isolated_calendar(db_session, owner)


def test_yandex_calendar_mismatch_timeout_rejects(google_settings, credential_key, monkeypatch):
    caldav = _calendar_fake()
    db_session, owner = _isolated_calendar(credential_key)
    try:
        _patch_calendar(monkeypatch, caldav)
        tools = _tools_cal(db_session, owner, caldav)
        gateway = ToolExecutionGateway()
        staged = gateway.execute(
            tools,
            "create_calendar_event",
            _event_args(provider="yandex"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        args = staged.staged_action["arguments"]
        href = event_href_from_operation_id(CALENDAR_HREF, args["operation_id"])
        caldav.objects[href] = (
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:other\nSUMMARY:nope\nEND:VEVENT\nEND:VCALENDAR\n"
        )
        mismatch = gateway.execute(
            tools, "create_calendar_event", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert mismatch.success is False
        assert "does not match frozen fields" in (mismatch.error or "")
        assert caldav.put_calls == []
        db_session.expire_all()
        assert _attempt_for(db_session, owner, args["operation_id"]).state == ATTEMPT_FAILED_DEFINITE

        caldav2 = _calendar_fake()
        caldav2.lose_put_response = True
        _patch_calendar(monkeypatch, caldav2)
        tools2 = _tools_cal(db_session, owner, caldav2)
        staged2 = gateway.execute(
            tools2,
            "create_calendar_event",
            _event_args(provider="yandex", summary="Timeout"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        timeout = gateway.execute(
            tools2,
            "create_calendar_event",
            staged2.staged_action["arguments"],
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert timeout.success is True
        href2 = event_href_from_operation_id(
            CALENDAR_HREF, staged2.staged_action["arguments"]["operation_id"]
        )
        assert caldav2.put_hrefs == [href2]
        db_session.expire_all()
        assert (
            _attempt_for(
                db_session, owner, staged2.staged_action["arguments"]["operation_id"]
            ).state
            == ATTEMPT_SUCCEEDED
        )

        caldav3 = _calendar_fake()
        caldav3.put_error = YandexCalDavError(
            "HTTP 503", operation="PUT", status_code=503, retryable=True
        )
        _patch_calendar(monkeypatch, caldav3)
        tools3 = _tools_cal(db_session, owner, caldav3)
        staged3 = gateway.execute(
            tools3,
            "create_calendar_event",
            _event_args(provider="yandex", summary="Retryable"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        retryable = gateway.execute(
            tools3,
            "create_calendar_event",
            staged3.staged_action["arguments"],
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert retryable.success is True
        assert caldav3.put_hrefs == [
            event_href_from_operation_id(
                CALENDAR_HREF, staged3.staged_action["arguments"]["operation_id"]
            )
        ]

        for extra in (
            {"attendees": ["a@b.c"]},
            {"ics": "BEGIN:VCALENDAR"},
            {"calendar_href": "/calendars/other/"},
            {"rrule": "FREQ=DAILY"},
        ):
            rejected = gateway.execute(
                tools,
                "create_calendar_event",
                _event_args(provider="yandex", **extra),
                context=ExecutionContext.INTERACTIVE_ASSISTANT,
            )
            assert rejected.status == ToolExecutionStatus.TOOL_ERROR
    finally:
        _cleanup_isolated_calendar(db_session, owner)


def test_fake_caldav_if_none_match_overwrites_like_yandex() -> None:
    caldav = _calendar_fake()
    href = "/calendars/user@yandex.ru/events-default/secretary-abc%40secretary.ics"
    caldav.objects[href] = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nBEGIN:VALARM\nEND:VALARM\nEND:VEVENT\n"
    status = caldav.put_calendar_object(href, "OVERWRITTEN", if_none_match="*")
    assert status == 201
    assert caldav.objects[href] == "OVERWRITTEN"


def test_yandex_calendar_legacy_exact_and_valarm_resume(google_settings, credential_key, monkeypatch):
    caldav = _calendar_fake()
    db_session, owner = _isolated_calendar(credential_key)
    try:
        _patch_calendar(monkeypatch, caldav)
        tools = _tools_cal(db_session, owner, caldav)
        gateway = ToolExecutionGateway()
        staged = gateway.execute(
            tools,
            "create_calendar_event",
            _event_args(provider="yandex"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        args = staged.staged_action["arguments"]
        payload = CreateCalendarEventCanonicalInput.model_validate(args)
        href = event_href_from_operation_id(CALENDAR_HREF, args["operation_id"])
        with_alarm = _with_provider_valarm(build_vevent_ics(payload))
        caldav.objects[href] = with_alarm
        recovered = gateway.execute(
            tools, "create_calendar_event", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert recovered.success is True
        assert recovered.output["changed"] is False
        assert caldav.put_calls == []
        assert "BEGIN:VALARM" in caldav.objects[href]
        assert caldav.objects[href] == with_alarm
        db_session.expire_all()
        attempt = _attempt_for(db_session, owner, args["operation_id"])
        assert attempt.state == ATTEMPT_SUCCEEDED
        assert attempt.provider_external_id == href
    finally:
        _cleanup_isolated_calendar(db_session, owner)


def test_yandex_calendar_started_and_uncertain_resume(google_settings, credential_key, monkeypatch):
    caldav = _calendar_fake()
    db_session, owner = _isolated_calendar(credential_key)
    try:
        _patch_calendar(monkeypatch, caldav)
        tools = _tools_cal(db_session, owner, caldav)
        gateway = ToolExecutionGateway()
        staged = gateway.execute(
            tools,
            "create_calendar_event",
            _event_args(provider="yandex", summary="Started exact"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        args = staged.staged_action["arguments"]
        href = event_href_from_operation_id(CALENDAR_HREF, args["operation_id"])
        payload = CreateCalendarEventCanonicalInput.model_validate(args)
        db_session.add(
            ExternalActionAttempt(
                user_id=owner,
                operation_id=args["operation_id"],
                tool_name=CALENDAR_TOOL_NAME,
                state=ATTEMPT_STARTED,
                started_at=datetime.now(UTC),
            )
        )
        db_session.commit()
        caldav.objects[href] = build_vevent_ics(payload)
        resumed = gateway.execute(
            tools, "create_calendar_event", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert resumed.success is True
        assert resumed.output["changed"] is False
        assert caldav.put_calls == []
        db_session.expire_all()
        assert _attempt_for(db_session, owner, args["operation_id"]).state == ATTEMPT_SUCCEEDED

        missing = gateway.execute(
            tools,
            "create_calendar_event",
            _event_args(provider="yandex", summary="Started missing"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        missing_args = missing.staged_action["arguments"]
        db_session.add(
            ExternalActionAttempt(
                user_id=owner,
                operation_id=missing_args["operation_id"],
                tool_name=CALENDAR_TOOL_NAME,
                state=ATTEMPT_STARTED,
                started_at=datetime.now(UTC),
            )
        )
        db_session.commit()
        crashed = gateway.execute(
            tools, "create_calendar_event", missing_args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert crashed.success is False
        assert "could not confirm calendar event creation" in (crashed.error or "")
        assert caldav.put_calls == []
        db_session.expire_all()
        assert _attempt_for(db_session, owner, missing_args["operation_id"]).state == ATTEMPT_UNCERTAIN

        uncertain_stage = gateway.execute(
            tools,
            "create_calendar_event",
            _event_args(provider="yandex", summary="Uncertain exact"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        uncertain_args = uncertain_stage.staged_action["arguments"]
        uncertain_href = event_href_from_operation_id(CALENDAR_HREF, uncertain_args["operation_id"])
        db_session.add(
            ExternalActionAttempt(
                user_id=owner,
                operation_id=uncertain_args["operation_id"],
                tool_name=CALENDAR_TOOL_NAME,
                state=ATTEMPT_UNCERTAIN,
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
        )
        db_session.commit()
        caldav.objects[uncertain_href] = build_vevent_ics(
            CreateCalendarEventCanonicalInput.model_validate(uncertain_args)
        )
        reconciled = gateway.execute(
            tools,
            "create_calendar_event",
            uncertain_args,
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert reconciled.success is True
        assert reconciled.output["changed"] is False
        assert caldav.put_calls == []
        db_session.expire_all()
        assert _attempt_for(db_session, owner, uncertain_args["operation_id"]).state == ATTEMPT_SUCCEEDED
    finally:
        _cleanup_isolated_calendar(db_session, owner)


def test_yandex_calendar_ambiguous_put_absent_stays_uncertain(
    google_settings, credential_key, monkeypatch
):
    caldav = _calendar_fake()
    caldav.persist_on_put = False
    caldav.lose_put_response = True
    db_session, owner = _isolated_calendar(credential_key)
    try:
        _patch_calendar(monkeypatch, caldav)
        tools = _tools_cal(db_session, owner, caldav)
        gateway = ToolExecutionGateway()
        staged = gateway.execute(
            tools,
            "create_calendar_event",
            _event_args(provider="yandex"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        args = staged.staged_action["arguments"]
        first = gateway.execute(
            tools, "create_calendar_event", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert first.success is False
        assert "could not confirm calendar event creation; not retrying create" in (
            first.error or ""
        )
        assert len(caldav.put_calls) == 1
        db_session.expire_all()
        assert _attempt_for(db_session, owner, args["operation_id"]).state == ATTEMPT_UNCERTAIN
        second = gateway.execute(
            tools, "create_calendar_event", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert second.success is False
        assert len(caldav.put_calls) == 1
    finally:
        _cleanup_isolated_calendar(db_session, owner)


def test_yandex_calendar_definite_put_failure(google_settings, credential_key, monkeypatch):
    caldav = _calendar_fake()
    caldav.persist_on_put = False
    caldav.put_error = YandexCalDavError(
        "HTTP 403", operation="PUT", status_code=403, retryable=False
    )
    db_session, owner = _isolated_calendar(credential_key)
    try:
        _patch_calendar(monkeypatch, caldav)
        tools = _tools_cal(db_session, owner, caldav)
        gateway = ToolExecutionGateway()
        staged = gateway.execute(
            tools,
            "create_calendar_event",
            _event_args(provider="yandex"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        args = staged.staged_action["arguments"]
        failed = gateway.execute(
            tools, "create_calendar_event", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert failed.success is False
        assert len(caldav.put_calls) == 1
        db_session.expire_all()
        assert _attempt_for(db_session, owner, args["operation_id"]).state == ATTEMPT_FAILED_DEFINITE
        again = gateway.execute(
            tools, "create_calendar_event", args, context=ExecutionContext.APPROVED_ACTION_PLAN
        )
        assert again.success is False
        assert len(caldav.put_calls) == 1
    finally:
        _cleanup_isolated_calendar(db_session, owner)


def test_yandex_calendar_get_unavailable_does_not_put(google_settings, credential_key, monkeypatch):
    caldav = _calendar_fake()
    caldav.get_error = YandexCalDavError(
        "HTTP 503", operation="GET", status_code=503, retryable=True
    )
    db_session, owner = _isolated_calendar(credential_key)
    try:
        _patch_calendar(monkeypatch, caldav)
        tools = _tools_cal(db_session, owner, caldav)
        gateway = ToolExecutionGateway()
        staged = gateway.execute(
            tools,
            "create_calendar_event",
            _event_args(provider="yandex"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        blocked = gateway.execute(
            tools,
            "create_calendar_event",
            staged.staged_action["arguments"],
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert blocked.success is False
        assert caldav.put_calls == []
        db_session.expire_all()
        assert (
            _attempt_for(db_session, owner, staged.staged_action["arguments"]["operation_id"]).state
            == ATTEMPT_UNCERTAIN
        )
    finally:
        _cleanup_isolated_calendar(db_session, owner)


def test_yandex_calendar_concurrent_same_operation_put_once(google_settings, credential_key, monkeypatch):
    caldav = _calendar_fake()
    _patch_calendar(monkeypatch, caldav)
    session, user_id = _isolated_calendar(credential_key)
    try:
        args = ToolExecutionGateway().execute(
            _tools_cal(session, user_id, caldav),
            "create_calendar_event",
            _event_args(provider="yandex"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        ).staged_action["arguments"]
        put_started = threading.Event()
        continue_put = threading.Event()
        caldav.before_put = lambda: (put_started.set(), continue_put.wait(10))
        winner_result: list = []

        def winner() -> None:
            worker_session = SessionLocal()
            try:
                winner_result.append(
                    ToolExecutionGateway().execute(
                        DomainToolService(
                            worker_session, user_id, yandex_caldav_transport=caldav
                        ),
                        "create_calendar_event",
                        args,
                        context=ExecutionContext.APPROVED_ACTION_PLAN,
                    )
                )
            finally:
                worker_session.close()

        thread = threading.Thread(target=winner)
        thread.start()
        assert put_started.wait(5)
        loser_session = SessionLocal()
        try:
            loser = ToolExecutionGateway().execute(
                DomainToolService(loser_session, user_id, yandex_caldav_transport=caldav),
                "create_calendar_event",
                args,
                context=ExecutionContext.APPROVED_ACTION_PLAN,
            )
        finally:
            loser_session.close()
        assert loser.success is False
        assert "could not confirm" in (loser.error or "")
        assert len(caldav.put_calls) == 1
        continue_put.set()
        thread.join(10)
        caldav.before_put = None
        assert winner_result[0].success is True
        assert winner_result[0].output["changed"] is True
        assert len(caldav.put_calls) == 1
        errors: list[BaseException] = []

        def parallel() -> None:
            worker_session = SessionLocal()
            try:
                result = ToolExecutionGateway().execute(
                    DomainToolService(worker_session, user_id, yandex_caldav_transport=caldav),
                    "create_calendar_event",
                    args,
                    context=ExecutionContext.APPROVED_ACTION_PLAN,
                )
                if not result.success:
                    errors.append(RuntimeError(result.error))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                worker_session.close()

        threads = [threading.Thread(target=parallel) for _ in range(2)]
        for item in threads:
            item.start()
        for item in threads:
            item.join()
        assert errors == []
        assert len(caldav.put_calls) == 1
    finally:
        _cleanup_isolated_calendar(session, user_id)


def test_yandex_calendar_outer_rollback_keeps_claim(google_settings, credential_key, monkeypatch):
    caldav = _calendar_fake()
    _patch_calendar(monkeypatch, caldav)
    session, user_id = _isolated_calendar(credential_key)
    try:
        plan_session = SessionLocal()
        try:
            staged = ToolExecutionGateway().execute(
                DomainToolService(plan_session, user_id, yandex_caldav_transport=caldav),
                "create_calendar_event",
                _event_args(provider="yandex"),
                context=ExecutionContext.INTERACTIVE_ASSISTANT,
            )
            args = staged.staged_action["arguments"]
            nested = plan_session.begin_nested()
            try:
                executed = ToolExecutionGateway().execute(
                    DomainToolService(plan_session, user_id, yandex_caldav_transport=caldav),
                    "create_calendar_event",
                    args,
                    context=ExecutionContext.APPROVED_ACTION_PLAN,
                )
                assert executed.success is True
            finally:
                nested.rollback()
            plan_session.rollback()
        finally:
            plan_session.close()
        assert len(caldav.put_calls) == 1
        observer = SessionLocal()
        try:
            attempt = observer.query(ExternalActionAttempt).filter_by(
                user_id=user_id, operation_id=args["operation_id"]
            ).one()
            assert attempt.state == ATTEMPT_SUCCEEDED
        finally:
            observer.close()
        resume_session = SessionLocal()
        try:
            resumed = ToolExecutionGateway().execute(
                DomainToolService(resume_session, user_id, yandex_caldav_transport=caldav),
                "create_calendar_event",
                args,
                context=ExecutionContext.APPROVED_ACTION_PLAN,
            )
        finally:
            resume_session.close()
        assert resumed.success is True
        assert resumed.output["changed"] is False
        assert len(caldav.put_calls) == 1
    finally:
        _cleanup_isolated_calendar(session, user_id)


def test_yandex_calendar_action_plan_lock_serializes_approve(google_settings, credential_key, monkeypatch):
    caldav = _calendar_fake()
    _patch_calendar(monkeypatch, caldav)
    session, user_id = _isolated_calendar(credential_key)
    try:
        staged = ToolExecutionGateway().execute(
            DomainToolService(session, user_id, yandex_caldav_transport=caldav),
            "create_calendar_event",
            _event_args(provider="yandex"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        plan = ActionPlanService(session, user_id).create_plan([staged.staged_action])
        session.commit()
        errors: list[BaseException] = []

        def worker() -> None:
            worker_session = SessionLocal()
            try:
                ActionPlanService(worker_session, user_id).approve(plan.id)
                worker_session.commit()
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
        assert len(caldav.put_calls) == 1
        session.expire_all()
        stored = ActionPlanService(session, user_id).approve(plan.id)
        assert stored.status == PENDING_ACTION_PLAN_STATUS_EXECUTED
        assert len(caldav.put_calls) == 1
    finally:
        _cleanup_isolated_calendar(session, user_id)


def test_yandex_calendar_default_and_cross_provider(
    db_session, google_settings, credential_key, owner, monkeypatch
):
    many = FakeCalDavTransport(
        calendars=[
            CalDavCalendar(href="/calendars/user@yandex.ru/work/", display_name="Work", sync_token=None),
            CalDavCalendar(href="/calendars/user@yandex.ru/home/", display_name="Home", sync_token=None),
        ]
    )
    _patch_calendar(monkeypatch, many)
    _add_yandex_calendar(db_session, credential_key, "user@yandex.ru", user_id=owner)
    blocked = ToolExecutionGateway().execute(
        _tools_cal(db_session, owner, many),
        "create_calendar_event",
        _event_args(provider="yandex"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert blocked.status == ToolExecutionStatus.TOOL_ERROR
    assert many.put_calls == []

    google = FakeCalendarTransport()
    yandex = _calendar_fake()
    monkeypatch.setattr(
        CalendarExternalActionService, "_valid_access_token", lambda self, account_id: "access-token"
    )
    db_session, owner = _isolated_calendar(credential_key)
    try:
        _add_google(db_session, credential_key, "user@example.com", user_id=owner)
        db_session.commit()
        _patch_calendar(monkeypatch, yandex)
        tools = _tools_cal(db_session, owner, yandex, google)
        gateway = ToolExecutionGateway()
        g_staged = gateway.execute(
            tools,
            "create_calendar_event",
            _event_args(provider="google"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        gateway.execute(
            tools,
            "create_calendar_event",
            g_staged.staged_action["arguments"],
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert len(google.insert_calls) == 1
        assert yandex.put_calls == []
        y_staged = gateway.execute(
            tools,
            "create_calendar_event",
            _event_args(provider="yandex"),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        gateway.execute(
            tools,
            "create_calendar_event",
            y_staged.staged_action["arguments"],
            context=ExecutionContext.APPROVED_ACTION_PLAN,
        )
        assert len(google.insert_calls) == 1
        assert len(yandex.put_calls) == 1
    finally:
        _cleanup_isolated_calendar(db_session, owner)


def test_select_unique_vevent_calendar_requires_unique_vevent() -> None:
    events = _vevent_calendar(
        "/calendars/user@yandex.ru/events-18154946/",
        display_name="Мои события",
    )
    todos = _vtodo_calendar(
        "/calendars/user@yandex.ru/todos-7121590/",
        display_name="Не забыть",
    )
    misleading_todo = _vtodo_calendar(
        "/calendars/user@yandex.ru/events-999/",
        display_name="Мои события",
    )
    ugly_vevent = _vevent_calendar("/calendars/user@yandex.ru/shared-xyz/", display_name="zzz")
    missing = CalDavCalendar(
        href="/calendars/user@yandex.ru/events-default/",
        display_name="Мои события",
        sync_token="t",
    )
    second_vevent = _vevent_calendar("/calendars/user@yandex.ru/work/", display_name="Work")
    assert select_unique_vevent_calendar([todos, events]) is events
    assert select_unique_vevent_calendar([misleading_todo, ugly_vevent]) is ugly_vevent
    with pytest.raises(ToolError, match="not available"):
        select_unique_vevent_calendar([])
    with pytest.raises(ToolError, match="cannot identify default"):
        select_unique_vevent_calendar([todos])
    with pytest.raises(ToolError, match="cannot identify default"):
        select_unique_vevent_calendar([events, second_vevent, todos])
    with pytest.raises(ToolError, match="cannot identify default"):
        select_unique_vevent_calendar([missing])
    with pytest.raises(ToolError, match="cannot identify default"):
        select_unique_vevent_calendar([todos, missing])
    ten = [_vtodo_calendar(f"/calendars/user@yandex.ru/todo-{i}/") for i in range(9)]
    ten.insert(4, events)
    assert select_unique_vevent_calendar(ten) is events
    overflow = ten + [_vtodo_calendar("/calendars/user@yandex.ru/todo-extra/")]
    with pytest.raises(ToolError, match="cannot identify default"):
        select_unique_vevent_calendar(overflow)
    overflow_last_vevent = [
        _vtodo_calendar(f"/calendars/user@yandex.ru/todo-{i}/") for i in range(10)
    ] + [events]
    with pytest.raises(ToolError, match="cannot identify default"):
        select_unique_vevent_calendar(overflow_last_vevent)


def test_yandex_calendar_sole_non_default_fails_closed(
    db_session, google_settings, credential_key, owner, monkeypatch
):
    sole = FakeCalDavTransport(
        calendars=[
            CalDavCalendar(href="/calendars/user@yandex.ru/shared/", display_name="Shared", sync_token="t")
        ]
    )
    _patch_calendar(monkeypatch, sole)
    _add_yandex_calendar(db_session, credential_key, "user@yandex.ru", user_id=owner)
    blocked = ToolExecutionGateway().execute(
        _tools_cal(db_session, owner, sole),
        "create_calendar_event",
        _event_args(provider="yandex"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert blocked.status == ToolExecutionStatus.TOOL_ERROR
    assert "default" in (blocked.error or "").lower()
    assert sole.put_calls == []


def test_yandex_calendar_selects_vevent_not_vtodo(
    db_session, google_settings, credential_key, owner, monkeypatch
):
    caldav = FakeCalDavTransport(
        calendars=[
            _vtodo_calendar("/calendars/user@yandex.ru/todos-7121590/", display_name="Не забыть"),
            _vevent_calendar("/calendars/user@yandex.ru/events-18154946/", display_name="Мои события"),
        ]
    )
    _patch_calendar(monkeypatch, caldav)
    _add_yandex_calendar(db_session, credential_key, "user@yandex.ru", user_id=owner)
    staged = ToolExecutionGateway().execute(
        _tools_cal(db_session, owner, caldav),
        "create_calendar_event",
        _event_args(provider="yandex"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert staged.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert staged.staged_action["arguments"]["calendar_href"] == (
        "/calendars/user@yandex.ru/events-18154946/"
    )
    assert caldav.put_calls == []


def test_yandex_calendar_vtodo_or_multiple_vevent_fails_closed(
    db_session, google_settings, credential_key, owner, monkeypatch
):
    only_todo = FakeCalDavTransport(
        calendars=[_vtodo_calendar("/calendars/user@yandex.ru/todos-7121590/")]
    )
    _patch_calendar(monkeypatch, only_todo)
    _add_yandex_calendar(db_session, credential_key, "user@yandex.ru", user_id=owner)
    blocked_todo = ToolExecutionGateway().execute(
        _tools_cal(db_session, owner, only_todo),
        "create_calendar_event",
        _event_args(provider="yandex"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert blocked_todo.status == ToolExecutionStatus.TOOL_ERROR
    assert only_todo.put_calls == []

    two_events = FakeCalDavTransport(
        calendars=[
            _vevent_calendar("/calendars/user@yandex.ru/events-1/"),
            _vevent_calendar("/calendars/user@yandex.ru/events-2/"),
        ]
    )
    _patch_calendar(monkeypatch, two_events)
    blocked_two = ToolExecutionGateway().execute(
        _tools_cal(db_session, owner, two_events),
        "create_calendar_event",
        _event_args(provider="yandex"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert blocked_two.status == ToolExecutionStatus.TOOL_ERROR
    assert two_events.put_calls == []


def _bounded_calendars(*, count: int, vevent_index: int) -> list[CalDavCalendar]:
    calendars: list[CalDavCalendar] = []
    for index in range(count):
        href = f"/calendars/user@yandex.ru/cal-{index}/"
        if index == vevent_index:
            calendars.append(_vevent_calendar(href, display_name=f"cal-{index}"))
        else:
            calendars.append(_vtodo_calendar(href, display_name=f"todo-{index}"))
    return calendars


def test_yandex_calendar_complete_bound_selects_unique_vevent(
    db_session, google_settings, credential_key, owner, monkeypatch
):
    ten = FakeCalDavTransport(calendars=_bounded_calendars(count=10, vevent_index=7))
    _patch_calendar(monkeypatch, ten)
    _add_yandex_calendar(db_session, credential_key, "user@yandex.ru", user_id=owner)
    staged = ToolExecutionGateway().execute(
        _tools_cal(db_session, owner, ten),
        "create_calendar_event",
        _event_args(provider="yandex"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert staged.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert staged.staged_action["arguments"]["calendar_href"] == (
        "/calendars/user@yandex.ru/cal-7/"
    )
    assert ten.put_calls == []
    assert ten.discover_max_results == [MAX_TARGET_CALENDARS + 1]


def test_yandex_calendar_overflow_discovery_fails_closed(
    db_session, google_settings, credential_key, owner, monkeypatch
):
    first_ten_unique = FakeCalDavTransport(
        calendars=_bounded_calendars(count=11, vevent_index=0)
    )
    _patch_calendar(monkeypatch, first_ten_unique)
    _add_yandex_calendar(db_session, credential_key, "user@yandex.ru", user_id=owner)
    blocked_prefix = ToolExecutionGateway().execute(
        _tools_cal(db_session, owner, first_ten_unique),
        "create_calendar_event",
        _event_args(provider="yandex"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert blocked_prefix.status == ToolExecutionStatus.TOOL_ERROR
    assert "not available" not in (blocked_prefix.error or "").lower()
    assert "cannot identify" in (blocked_prefix.error or "").lower()
    assert first_ten_unique.put_calls == []
    assert first_ten_unique.discover_max_results == [MAX_TARGET_CALENDARS + 1]

    eleventh_vevent = FakeCalDavTransport(
        calendars=_bounded_calendars(count=11, vevent_index=10)
    )
    _patch_calendar(monkeypatch, eleventh_vevent)
    blocked_last = ToolExecutionGateway().execute(
        _tools_cal(db_session, owner, eleventh_vevent),
        "create_calendar_event",
        _event_args(provider="yandex"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert blocked_last.status == ToolExecutionStatus.TOOL_ERROR
    assert "not available" not in (blocked_last.error or "").lower()
    assert "cannot identify" in (blocked_last.error or "").lower()
    assert eleventh_vevent.put_calls == []


def test_parse_imap_internaldate_uses_server_timestamp() -> None:
    parsed = parse_imap_internaldate(b'1 (UID 7 INTERNALDATE "06-Sep-2026 10:00:00 +0000")')
    assert parsed == datetime(2026, 9, 6, 10, 0, tzinfo=UTC)



def test_send_email_input_rejects_unknown_provider():
    with pytest.raises(PydanticValidationError):
        SendEmailInput.model_validate({**_mail_args(), "provider": "gmail"})
    with pytest.raises(PydanticValidationError):
        CreateCalendarEventCanonicalInput.model_validate(
            {
                **_event_args(),
                "account_email": "a@b.c",
                "operation_id": "deadbeefdeadbeefdeadbeefdeadbeef",
                "provider": "yandex",
                "attendees": ["x@y.z"],
            }
        )
