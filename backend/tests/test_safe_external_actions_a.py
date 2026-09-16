"""Safe External Actions Pass A — approval-bound Google Calendar create."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select

from app.assistant.action_plan_constants import (
    PENDING_ACTION_PLAN_STATUS_FAILED,
    PENDING_ACTION_PLAN_STATUS_PENDING,
)
from app.assistant.tool_runner import PerTurnToolBudget
from app.connectors.google.calendar_transport import CalendarTransport
from app.connectors.google.constants import (
    CALENDAR_API_BASE,
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_READONLY_SCOPE,
    DRIVE_READONLY_SCOPE,
    GMAIL_READONLY_SCOPE,
    PRIMARY_CALENDAR_ID,
)
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleApiError
from app.connectors.google.oauth_service import GoogleOAuthService
from app.core.client_timezone import set_request_timezone
from app.core.config import settings
from app.db.models import GoogleAccount, Object, PendingActionPlan, User
from app.db.session import SessionLocal
from app.services.action_plan_service import ActionPlanService
from app.services.calendar_external_action_service import (
    CalendarExternalActionService,
    calendar_event_id_from_operation_id,
)
from app.services.domain_tool_service import DomainToolService
from app.services.errors import ValidationError as ServiceValidationError
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import (
    CreateCalendarEventCanonicalInput,
    CreateCalendarEventInput,
    ToolError,
)


class FakeCalendarTransport:
    def __init__(self) -> None:
        self.events: dict[str, dict] = {}
        self.insert_calls: list[dict] = []
        self.get_calls: list[str] = []
        self.lose_insert_response = False
        self.insert_conflict = False
        self.persist_on_insert = True
        self.stored_summary_override: str | None = None
        self.insert_error: GoogleApiError | None = None
        self.lock = threading.Lock()

    def insert_event(self, access_token: str, calendar_id: str, body: dict) -> dict:
        with self.lock:
            self.insert_calls.append(
                {"access_token": access_token, "calendar_id": calendar_id, "body": dict(body)}
            )
            event_id = str(body["id"])
            stored = {
                "id": event_id,
                "summary": body["summary"],
                "start": dict(body["start"]),
                "end": dict(body["end"]),
                "htmlLink": f"https://calendar.google.com/event?eid={event_id}",
            }
            if "description" in body:
                stored["description"] = body["description"]
            if "location" in body:
                stored["location"] = body["location"]
            if self.stored_summary_override is not None:
                stored["summary"] = self.stored_summary_override
            if self.insert_conflict or event_id in self.events:
                if event_id not in self.events:
                    self.events[event_id] = stored
                raise GoogleApiError("already exists", operation="insert_event", status_code=409)
            if self.persist_on_insert:
                self.events[event_id] = stored
            if self.lose_insert_response:
                self.lose_insert_response = False
                raise httpx.TimeoutException("lost insert response")
            if self.insert_error is not None:
                raise self.insert_error
            return dict(stored)

    def get_event(self, access_token: str, calendar_id: str, event_id: str) -> dict:
        with self.lock:
            self.get_calls.append(event_id)
            event = self.events.get(event_id)
            if event is None:
                raise GoogleApiError("not found", operation="get_event", status_code=404)
            return dict(event)


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


def _add_google_account(
    db_session,
    credential_key: str,
    email: str,
    scopes: list[str],
    *,
    user_id,
):
    return _store(db_session, credential_key).upsert_tokens(
        user_id=user_id,
        email=email,
        scopes=scopes,
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=datetime.now(ZoneInfo("UTC")) + timedelta(hours=1),
    )


def _write_scopes() -> list[str]:
    return [
        GMAIL_READONLY_SCOPE,
        CALENDAR_READONLY_SCOPE,
        CALENDAR_EVENTS_SCOPE,
        DRIVE_READONLY_SCOPE,
    ]


def _patch_execution(monkeypatch, fake: FakeCalendarTransport) -> None:
    original_init = DomainToolService.__init__

    def patched(self, *args, **kwargs):
        kwargs.setdefault("calendar_transport", fake)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(DomainToolService, "__init__", patched)
    monkeypatch.setattr(
        CalendarExternalActionService,
        "_valid_access_token",
        lambda self, account_id: "access-token",
    )


def _event_args(**overrides) -> dict:
    payload = {
        "summary": "Созвон с командой",
        "start_at": "2026-09-06T15:00:00",
        "end_at": "2026-09-06T15:30:00",
        "description": "Weekly sync",
        "location": "Office",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def calendar_user(db_session):
    user_id = uuid4()
    db_session.add(User(id=user_id, display_name="calendar-action-user"))
    db_session.flush()
    return user_id

def _other_user(db_session):
    user_id = uuid4()
    db_session.add(User(id=user_id, display_name="other"))
    db_session.flush()
    return user_id


def test_interactive_create_calendar_event_requires_approval_without_transport(
    db_session, google_settings, credential_key, monkeypatch, calendar_user):
    fake = FakeCalendarTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    result = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert fake.insert_calls == []
    assert result.staged_action["arguments"]["account_email"] == "user@example.com"
    assert result.staged_action["arguments"]["calendar_id"] == PRIMARY_CALENDAR_ID
    assert result.staged_action["arguments"]["operation_id"]


def test_approved_action_plan_executes_external_write(
    db_session, google_settings, credential_key, monkeypatch, calendar_user):
    fake = FakeCalendarTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    staged = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    executed = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        staged.staged_action["arguments"],
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert executed.success is True
    assert executed.output["changed"] is True
    assert len(fake.insert_calls) == 1


def test_baseline_create_calendar_event_does_not_bypass_approval(
    db_session, google_settings, credential_key, monkeypatch, calendar_user):
    fake = FakeCalendarTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    result = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.BASELINE,
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert fake.insert_calls == []


def test_mcp_create_calendar_event_requires_approval_without_provider_write(
    db_session, google_settings, credential_key, monkeypatch, calendar_user):
    fake = FakeCalendarTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    result = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.MCP,
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert fake.insert_calls == []


def test_frozen_args_survive_timezone_change_before_approval(
    db_session, google_settings, credential_key, monkeypatch, calendar_user):
    fake = FakeCalendarTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    set_request_timezone("Europe/Moscow")
    try:
        tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
        staged = ToolExecutionGateway().execute(
            tools,
            "create_calendar_event",
            _event_args(),
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        frozen = staged.staged_action["arguments"]
        assert frozen["account_email"] == "user@example.com"
        assert frozen["calendar_id"] == "primary"
        assert frozen["summary"] == "Созвон с командой"
        assert frozen["description"] == "Weekly sync"
        assert frozen["location"] == "Office"
        assert "+03:00" in frozen["start_at"]
        assert "+03:00" in frozen["end_at"]
        assert "operation_id" in frozen
        plan = ActionPlanService(db_session, calendar_user).create_plan([staged.staged_action])
        stored = db_session.get(PendingActionPlan, plan.id)
        stored_args = stored.actions[0]["arguments"]
        assert stored_args["operation_id"] == frozen["operation_id"]
        assert "operation_id" not in plan.actions[0]["arguments"]
        set_request_timezone("America/New_York")
        approved = ActionPlanService(db_session, calendar_user).approve(plan.id)
        assert approved.status == "executed"
        insert_body = fake.insert_calls[0]["body"]
        assert insert_body["start"]["dateTime"].startswith("2026-09-06T15:00:00")
        assert "+03:00" in insert_body["start"]["dateTime"]
    finally:
        from app.core.client_timezone import clear_request_timezone

        clear_request_timezone()


def test_account_resolution_zero_one_two_and_foreign(
    db_session, google_settings, credential_key, calendar_user):
    fake = FakeCalendarTransport()
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    gateway = ToolExecutionGateway()

    none = gateway.execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert none.status == ToolExecutionStatus.TOOL_ERROR
    assert "connected" in (none.error or "").lower()

    _add_google_account(db_session, credential_key, "only@example.com", _write_scopes(), user_id=calendar_user)
    one = gateway.execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert one.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert one.staged_action["arguments"]["account_email"] == "only@example.com"

    _add_google_account(db_session, credential_key, "two@example.com", _write_scopes(), user_id=calendar_user)
    ambiguous = gateway.execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert ambiguous.status == ToolExecutionStatus.TOOL_ERROR
    assert "multiple Google accounts" in (ambiguous.error or "")

    explicit = gateway.execute(
        tools,
        "create_calendar_event",
        _event_args(account_email="two@example.com"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert explicit.staged_action["arguments"]["account_email"] == "two@example.com"

    other = _other_user(db_session)
    _add_google_account(
        db_session,
        credential_key,
        "foreign@example.com",
        _write_scopes(),
        user_id=other,
    )
    foreign = gateway.execute(
        tools,
        "create_calendar_event",
        _event_args(account_email="foreign@example.com"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert foreign.status == ToolExecutionStatus.TOOL_ERROR
    assert fake.insert_calls == []


def test_readonly_account_cannot_stage(db_session, google_settings, credential_key, calendar_user):
    fake = FakeCalendarTransport()
    _add_google_account(
        db_session,
        credential_key,
        "ro@example.com",
        [GMAIL_READONLY_SCOPE, CALENDAR_READONLY_SCOPE, DRIVE_READONLY_SCOPE],
        user_id=calendar_user,
    )
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    result = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert "reconnected" in (result.error or "").lower()
    assert fake.insert_calls == []


def test_write_scope_account_can_stage(db_session, google_settings, credential_key, calendar_user):
    fake = FakeCalendarTransport()
    _add_google_account(db_session, credential_key, "rw@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    result = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED


def test_reject_expire_approve_idempotent(
    db_session, google_settings, credential_key, monkeypatch, calendar_user):
    fake = FakeCalendarTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    gateway = ToolExecutionGateway()
    service = ActionPlanService(db_session, calendar_user)

    before = gateway.execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert fake.insert_calls == []

    rejected_plan = service.create_plan([before.staged_action])
    service.reject(rejected_plan.id)
    assert fake.events == {}

    expired_stage = gateway.execute(
        tools,
        "create_calendar_event",
        _event_args(summary="Expire me"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    expired_plan = service.create_plan([expired_stage.staged_action])
    row = db_session.get(PendingActionPlan, expired_plan.id)
    row.expires_at = datetime.now(ZoneInfo("UTC")) - timedelta(minutes=1)
    service.approve(expired_plan.id)
    assert len(fake.events) == 0

    approved_stage = gateway.execute(
        tools,
        "create_calendar_event",
        _event_args(summary="Approve me"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    approved_plan = service.create_plan([approved_stage.staged_action])
    first = service.approve(approved_plan.id)
    assert first.status == "executed"
    assert len(fake.events) == 1
    second = service.approve(approved_plan.id)
    assert second.status == "executed"
    assert len(fake.events) == 1


def test_concurrent_execution_of_same_frozen_action_creates_one_event(
    db_session, google_settings, credential_key, monkeypatch, calendar_user
):
    fake = FakeCalendarTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    staged = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    args = staged.staged_action["arguments"]
    errors: list[Exception] = []

    def worker() -> None:
        try:
            result = ToolExecutionGateway().execute(
                tools,
                "create_calendar_event",
                args,
                context=ExecutionContext.APPROVED_ACTION_PLAN,
            )
            if not result.success:
                errors.append(RuntimeError(result.error))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(fake.events) == 1


def test_idempotent_provider_results(db_session, google_settings, credential_key, monkeypatch, calendar_user):
    fake = FakeCalendarTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    staged = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    args = staged.staged_action["arguments"]
    first = ToolExecutionGateway().execute(
        tools, "create_calendar_event", args, context=ExecutionContext.APPROVED_ACTION_PLAN
    )
    assert first.output["changed"] is True
    fake.insert_conflict = True
    second = ToolExecutionGateway().execute(
        tools, "create_calendar_event", args, context=ExecutionContext.APPROVED_ACTION_PLAN
    )
    assert second.success is True
    assert second.output["changed"] is False
    assert len(fake.events) == 1

    mismatched_id = calendar_event_id_from_operation_id(args["operation_id"])
    fake.events[mismatched_id]["summary"] = "Unexpected"
    with pytest.raises(ToolError, match="does not match"):
        tools.create_calendar_event(CreateCalendarEventCanonicalInput.model_validate(args))


def test_lost_insert_response_reconciles(
    db_session, google_settings, credential_key, monkeypatch, calendar_user):
    fake = FakeCalendarTransport()
    fake.lose_insert_response = True
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    staged = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    executed = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        staged.staged_action["arguments"],
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert executed.success is True
    assert executed.output["changed"] is False
    assert len(fake.events) == 1
    assert len(fake.insert_calls) == 1


def test_security_bounds(db_session, google_settings, credential_key, calendar_user):
    fake = FakeCalendarTransport()
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    gateway = ToolExecutionGateway()

    extra = gateway.execute(
        tools,
        "create_calendar_event",
        _event_args(attendees=["guest@example.com"]),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert extra.status == ToolExecutionStatus.TOOL_ERROR

    calendar = gateway.execute(
        tools,
        "create_calendar_event",
        _event_args(calendar_id="other-calendar"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert calendar.status == ToolExecutionStatus.TOOL_ERROR

    supplied_id = gateway.execute(
        tools,
        "create_calendar_event",
        _event_args(operation_id="deadbeefdeadbeefdeadbeefdeadbeef"),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert supplied_id.status == ToolExecutionStatus.TOOL_ERROR

    staged = gateway.execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    dumped = str(staged.staged_action)
    assert "access-token" not in dumped
    assert "refresh-token" not in dumped
    plan = ActionPlanService(db_session, calendar_user).create_plan([staged.staged_action])
    persisted = db_session.get(PendingActionPlan, plan.id)
    assert "access-token" not in str(persisted.actions)
    assert "refresh-token" not in str(persisted.actions)
    assert persisted.actions[0]["arguments"]["operation_id"]
    assert "operation_id" not in plan.actions[0]["arguments"]


def test_llm_cannot_smuggle_extra_fields_into_input_model():
    with pytest.raises(PydanticValidationError):
        CreateCalendarEventInput.model_validate(
            _event_args(
                attendees=["a@example.com"],
                start_at="2026-09-06T15:00:00+03:00",
                end_at="2026-09-06T15:30:00+03:00",
            )
        )


def test_token_session_factory_is_not_plan_session(
    db_session, google_settings, credential_key, monkeypatch, calendar_user):
    fake = FakeCalendarTransport()
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    seen: list[object] = []

    class TrackingSession:
        def close(self) -> None:
            return None

    def tracking(self, account_id):
        token_session = self._token_session_factory()
        seen.append(token_session)
        assert token_session is not self._session
        return "access-token"

    monkeypatch.setattr(CalendarExternalActionService, "_valid_access_token", tracking)
    staged_tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    staged = ToolExecutionGateway().execute(
        staged_tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    service = CalendarExternalActionService(
        db_session,
        calendar_user,
        transport=fake,
        token_session_factory=TrackingSession,
    )
    service.create_event(CreateCalendarEventCanonicalInput.model_validate(staged.staged_action["arguments"]))
    assert seen
    assert fake.insert_calls


def test_internal_create_task_still_requires_interactive_approval(db_session, calendar_user):
    tools = DomainToolService(db_session, calendar_user)
    result = ToolExecutionGateway().execute(
        tools,
        "create_task",
        {"title": "Keep approval", "confidence": 0.9},
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED


def test_calendar_transport_insert_and_get_are_mechanical():
    created = {}

    class Client:
        def post(self, url, json=None, headers=None, **kwargs):
            assert "Authorization" in headers
            created["body"] = json
            return httpx.Response(
                200,
                json={
                    "id": json["id"],
                    "summary": json["summary"],
                    "start": json["start"],
                    "end": json["end"],
                },
            )

        def get(self, url, headers=None, **kwargs):
            assert created["body"]["id"] in url
            return httpx.Response(
                200,
                json={
                    "id": created["body"]["id"],
                    "summary": "x",
                    "start": created["body"]["start"],
                    "end": created["body"]["end"],
                },
            )

    transport = CalendarTransport(http_client=Client())
    inserted = transport.insert_event(
        "tok",
        "primary",
        {
            "id": "abcde12345",
            "summary": "S",
            "start": {"dateTime": "2026-09-06T15:00:00+03:00"},
            "end": {"dateTime": "2026-09-06T15:30:00+03:00"},
        },
    )
    assert inserted["id"] == "abcde12345"
    fetched = transport.get_event("tok", "primary", "abcde12345")
    assert fetched["id"] == "abcde12345"
    assert CALENDAR_API_BASE.startswith("https://")


def test_calendar_transport_malformed_2xx_raises_google_api_error() -> None:
    class MalformedClient:
        def post(self, url, json=None, headers=None, **kwargs):
            return httpx.Response(200, json=["not", "an", "object"])

        def get(self, url, headers=None, **kwargs):
            return httpx.Response(200, content=b"null")

    transport = CalendarTransport(http_client=MalformedClient())
    with pytest.raises(GoogleApiError) as insert_exc:
        transport.insert_event("tok", "primary", {"id": "abcde12345", "summary": "S"})
    assert insert_exc.value.retryable is True
    assert insert_exc.value.status_code == 200
    with pytest.raises(GoogleApiError) as get_exc:
        transport.get_event("tok", "primary", "abcde12345")
    assert get_exc.value.retryable is True
    assert get_exc.value.status_code == 200


def _bind_tool_session(monkeypatch, db_session) -> None:
    class BoundSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    monkeypatch.setattr("app.assistant.session.SessionLocal", BoundSession)


def _task_count(db_session, user_id) -> int:
    return db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.user_id == user_id,
            Object.kind == "task",
        )
    )


def test_refreshed_tokens_persist_without_committing_outer_plan_transaction(
    google_settings, credential_key, monkeypatch
):
    user_id = uuid4()
    email = f"token-persist-{user_id.hex}@example.com"
    setup = SessionLocal()
    try:
        setup.add(User(id=user_id, display_name="token-persist-user"))
        setup.commit()
        account = GoogleAccountStore(setup, CredentialEncryption(credential_key)).upsert_tokens(
            user_id=user_id,
            email=email,
            scopes=_write_scopes(),
            access_token="expired-access-token",
            refresh_token="old-refresh-token",
            token_expiry=datetime.now(UTC) - timedelta(hours=1),
        )
        setup.commit()
        account_id = account.id
        old_access_encrypted = account.access_token_encrypted
        old_refresh_encrypted = account.refresh_token_encrypted
    finally:
        setup.close()

    def fake_refresh(self, refresh_token: str) -> dict:
        assert refresh_token == "old-refresh-token"
        return {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }

    monkeypatch.setattr(GoogleOAuthService, "refresh_access_token", fake_refresh)

    plan_session = SessionLocal()
    try:
        plan = PendingActionPlan(
            user_id=user_id,
            status=PENDING_ACTION_PLAN_STATUS_PENDING,
            actions=[{"tool_name": "create_task", "arguments": {"title": "outer-uncommitted"}}],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        plan_session.add(plan)
        plan_session.flush()
        plan_id = plan.id
        token = CalendarExternalActionService(plan_session, user_id)._valid_access_token(
            account_id
        )
        assert token == "new-access-token"
        observer = SessionLocal()
        try:
            assert observer.get(PendingActionPlan, plan_id) is None
            stored = observer.get(GoogleAccount, account_id)
            assert stored is not None
            assert stored.access_token_encrypted != old_access_encrypted
            assert stored.refresh_token_encrypted != old_refresh_encrypted
            snapshot = GoogleAccountStore(
                observer, CredentialEncryption(credential_key)
            ).load_credential_snapshot(account_id, user_id)
            assert snapshot is not None
            assert snapshot.access_token == "new-access-token"
            assert snapshot.refresh_token == "new-refresh-token"
            assert snapshot.token_expiry is not None
            assert snapshot.token_expiry > datetime.now(UTC)
        finally:
            observer.close()
        plan_session.rollback()
    finally:
        plan_session.close()
        cleanup = SessionLocal()
        try:
            account_row = cleanup.get(GoogleAccount, account_id)
            if account_row is not None:
                cleanup.delete(account_row)
            user_row = cleanup.get(User, user_id)
            if user_row is not None:
                cleanup.delete(user_row)
            cleanup.commit()
        finally:
            cleanup.close()


def test_two_create_calendar_event_calls_stage_only_one_external_action(
    db_session, google_settings, credential_key, monkeypatch, calendar_user, fake_embedding_service
):
    fake = FakeCalendarTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    _bind_tool_session(monkeypatch, db_session)
    budget = PerTurnToolBudget()
    first = budget.run(calendar_user, "create_calendar_event", _event_args())
    second = budget.run(calendar_user, "create_calendar_event", _event_args(summary="Second event"))
    assert first.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert second.status == ToolExecutionStatus.TOOL_ERROR
    assert len(budget.staged_actions) == 1
    assert budget.staged_actions[0]["arguments"]["operation_id"]
    plan = ActionPlanService(db_session, calendar_user).create_plan(budget.staged_actions)
    approved = ActionPlanService(db_session, calendar_user).approve(plan.id)
    assert approved.status == "executed"
    assert len(fake.insert_calls) == 1
    assert len(fake.events) == 1


def test_internal_then_calendar_does_not_append_external(
    db_session, google_settings, credential_key, monkeypatch, calendar_user, fake_embedding_service
):
    fake = FakeCalendarTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    _bind_tool_session(monkeypatch, db_session)
    budget = PerTurnToolBudget()
    internal = budget.run(calendar_user, "create_task", {"title": "Already staged", "confidence": 0.9})
    external = budget.run(calendar_user, "create_calendar_event", _event_args())
    assert internal.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert external.status == ToolExecutionStatus.TOOL_ERROR
    assert [action["tool_name"] for action in budget.staged_actions] == ["create_task"]
    assert fake.insert_calls == []


def test_calendar_then_internal_rejects_second_mutation(
    db_session, google_settings, credential_key, monkeypatch, calendar_user, fake_embedding_service
):
    fake = FakeCalendarTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    _bind_tool_session(monkeypatch, db_session)
    budget = PerTurnToolBudget()
    external = budget.run(calendar_user, "create_calendar_event", _event_args())
    internal = budget.run(calendar_user, "create_task", {"title": "Too late", "confidence": 0.9})
    assert external.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert internal.status == ToolExecutionStatus.TOOL_ERROR
    assert [action["tool_name"] for action in budget.staged_actions] == ["create_calendar_event"]


def test_create_plan_rejects_mixed_external_and_internal(
    db_session, google_settings, credential_key, calendar_user
):
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    with pytest.raises(ServiceValidationError, match="only action"):
        ActionPlanService(db_session, calendar_user).create_plan(
            [
                {
                    "tool_name": "create_calendar_event",
                    "permission": "INTERNAL_WRITE",
                    "arguments": _event_args(),
                },
                {
                    "tool_name": "create_task",
                    "arguments": {"title": "Mixed", "confidence": 0.9},
                },
            ]
        )


def test_approve_mixed_legacy_plan_fails_closed_before_provider(
    db_session, google_settings, credential_key, monkeypatch, calendar_user
):
    fake = FakeCalendarTransport()
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    staged = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    plan = PendingActionPlan(
        user_id=calendar_user,
        status=PENDING_ACTION_PLAN_STATUS_PENDING,
        actions=[
            staged.staged_action,
            {
                "tool_name": "create_task",
                "permission": "INTERNAL_WRITE",
                "arguments": {"title": "Will fail if executed", "confidence": 0.9},
            },
        ],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(plan)
    db_session.flush()
    approved = ActionPlanService(db_session, calendar_user).approve(plan.id)
    assert approved.status == PENDING_ACTION_PLAN_STATUS_FAILED
    assert "only action" in (approved.failure or "")
    assert fake.insert_calls == []
    persisted = db_session.get(PendingActionPlan, plan.id)
    assert persisted.status == PENDING_ACTION_PLAN_STATUS_FAILED
    assert persisted.approved_at is None


def test_internal_two_action_plan_still_executes(db_session, calendar_user):
    before = _task_count(db_session, calendar_user)
    plan = ActionPlanService(db_session, calendar_user).create_plan(
        [
            {"tool_name": "create_task", "arguments": {"title": "Internal A", "confidence": 0.9}},
            {"tool_name": "create_task", "arguments": {"title": "Internal B", "confidence": 0.9}},
        ]
    )
    approved = ActionPlanService(db_session, calendar_user).approve(plan.id)
    assert approved.status == "executed"
    assert _task_count(db_session, calendar_user) == before + 2


def test_retryable_503_after_store_reconciles_without_second_create(
    db_session, google_settings, credential_key, monkeypatch, calendar_user
):
    fake = FakeCalendarTransport()
    fake.insert_error = GoogleApiError(
        "backend unavailable",
        operation="insert_event",
        status_code=503,
        retryable=True,
    )
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    staged = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    executed = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        staged.staged_action["arguments"],
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert executed.success is True
    assert executed.output["changed"] is False
    assert len(fake.events) == 1
    assert len(fake.insert_calls) == 1
    assert fake.get_calls == [calendar_event_id_from_operation_id(staged.staged_action["arguments"]["operation_id"])]


def test_retryable_503_without_stored_event_fails_after_one_insert(
    db_session, google_settings, credential_key, monkeypatch, calendar_user
):
    fake = FakeCalendarTransport()
    fake.persist_on_insert = False
    fake.insert_error = GoogleApiError(
        "backend unavailable",
        operation="insert_event",
        status_code=503,
        retryable=True,
    )
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    staged = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    executed = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        staged.staged_action["arguments"],
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert executed.success is False
    assert "failed to create calendar event" in (executed.error or "")
    assert fake.events == {}
    assert len(fake.insert_calls) == 1


def test_malformed_2xx_after_accept_reconciles_same_event(
    db_session, google_settings, credential_key, monkeypatch, calendar_user
):
    fake = FakeCalendarTransport()
    fake.insert_error = GoogleApiError(
        "insert_event returned a malformed response",
        operation="insert_event",
        status_code=200,
        retryable=True,
    )
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    staged = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    executed = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        staged.staged_action["arguments"],
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert executed.success is True
    assert executed.output["changed"] is False
    assert len(fake.events) == 1
    assert len(fake.insert_calls) == 1


def test_deterministic_id_with_different_canonical_fields_fails_closed(
    db_session, google_settings, credential_key, monkeypatch, calendar_user
):
    fake = FakeCalendarTransport()
    fake.stored_summary_override = "Different summary"
    fake.insert_error = GoogleApiError(
        "backend unavailable",
        operation="insert_event",
        status_code=503,
        retryable=True,
    )
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    staged = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    executed = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        staged.staged_action["arguments"],
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert executed.success is False
    assert "does not match frozen fields" in (executed.error or "")
    event_id = calendar_event_id_from_operation_id(staged.staged_action["arguments"]["operation_id"])
    assert fake.events[event_id]["summary"] == "Different summary"
    assert len(fake.insert_calls) == 1


def test_clear_4xx_does_not_reconcile(
    db_session, google_settings, credential_key, monkeypatch, calendar_user
):
    fake = FakeCalendarTransport()
    fake.persist_on_insert = False
    fake.insert_error = GoogleApiError(
        "invalid request",
        operation="insert_event",
        status_code=400,
        retryable=False,
    )
    _patch_execution(monkeypatch, fake)
    _add_google_account(db_session, credential_key, "user@example.com", _write_scopes(), user_id=calendar_user)
    tools = DomainToolService(db_session, calendar_user, calendar_transport=fake)
    staged = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        _event_args(),
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    executed = ToolExecutionGateway().execute(
        tools,
        "create_calendar_event",
        staged.staged_action["arguments"],
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert executed.success is False
    assert "invalid request" in (executed.error or "")
    assert fake.get_calls == []
    assert len(fake.insert_calls) == 1
