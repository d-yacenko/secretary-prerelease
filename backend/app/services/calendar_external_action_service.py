"""Bounded Google Calendar create-event execution after approval."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.connectors.google.calendar_transport import CalendarTransport
from app.connectors.google.constants import (
    CALENDAR_EVENTS_SCOPE,
    PRIMARY_CALENDAR_ID,
)
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleApiError, GoogleConnectorError, GoogleOAuthError
from app.connectors.google.gmail_transport import GoogleTokenManager
from app.connectors.google.oauth_service import GoogleOAuthService
from app.connectors.yandex.caldav_host import trusted_caldav_base_url
from app.connectors.yandex.caldav_transport import CalDavHttpTransport
from app.connectors.yandex.caldav_write import (
    build_vevent_ics,
    event_href_from_operation_id,
    event_matches_frozen_payload,
    resolve_unique_vevent_calendar,
)
from app.connectors.yandex.calendar_credentials import YandexCalendarAccountStore
from app.connectors.yandex.errors import YandexCalDavError
from app.core.config import settings
from app.db.models import ExternalActionAttempt, GoogleAccount, YandexCalendarAccount
from app.db.session import SessionLocal
from app.services.external_account_resolution import (
    execution_provider,
    resolve_external_account,
)
from app.tools.datetime_utils import normalize_tool_datetime
from app.tools.schemas import (
    CreateCalendarEventCanonicalInput,
    CreateCalendarEventInput,
    CreateCalendarEventOutput,
    ToolError,
)

_RECONNECT_WRITE_SCOPE_MESSAGE = (
    "Google must be reconnected to grant calendar write permission"
)
ATTEMPT_STARTED = "started"
ATTEMPT_SUCCEEDED = "succeeded"
ATTEMPT_FAILED_DEFINITE = "failed_definite"
ATTEMPT_UNCERTAIN = "uncertain"
CALENDAR_TOOL_NAME = "create_calendar_event"
_UNCERTAIN_CREATE_MESSAGE = (
    "could not confirm calendar event creation; not retrying create"
)
_MISMATCH_MESSAGE = "existing calendar event does not match frozen fields"
_MISSING_EVENT_MESSAGE = "calendar event is missing; not retrying create"
_FAILED_DEFINITE_MESSAGE = "calendar event creation previously failed; create a new plan"


def calendar_event_id_from_operation_id(operation_id: str) -> str:
    compact = operation_id.replace("-", "").lower()
    if len(compact) < 5 or len(compact) > 1024:
        raise ToolError("invalid operation_id")
    return compact


def generate_operation_id() -> str:
    return uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _format_rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        raise ToolError("calendar event times must be timezone-aware")
    return value.isoformat().replace("+00:00", "Z")


def _parse_provider_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # noqa: FURB162
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed


class CalendarExternalActionService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        *,
        transport: CalendarTransport | None = None,
        token_session_factory=SessionLocal,
        attempt_session_factory=SessionLocal,
        yandex_caldav_transport=None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._transport = transport or CalendarTransport()
        self._token_session_factory = token_session_factory
        self._attempt_session_factory = attempt_session_factory
        self._yandex_caldav_transport = yandex_caldav_transport

    def prepare_create_event(
        self,
        payload: CreateCalendarEventInput,
        timezone_name: str,
    ) -> CreateCalendarEventCanonicalInput:
        start_at = normalize_tool_datetime(payload.start_at, timezone_name)
        end_at = normalize_tool_datetime(payload.end_at, timezone_name)
        if start_at is None or end_at is None:
            raise ToolError("start_at and end_at are required")
        if end_at <= start_at:
            raise ToolError("end_at must be after start_at")
        resolved = resolve_external_account(
            self._session,
            self._user_id,
            capability="create_calendar_event",
            provider=payload.provider,
            account_email=payload.account_email,
        )
        calendar_href = None
        calendar_label = None
        if resolved.provider == "google":
            account = self._require_google_account(resolved.email)
            self._require_write_scope(account)
        else:
            yandex_account = self._require_yandex_calendar_account(resolved.email)
            calendar = resolve_unique_vevent_calendar(
                self._yandex_caldav_for_account(yandex_account)
            )
            calendar_href = calendar.href
            calendar_label = calendar.display_name or "default"
        return CreateCalendarEventCanonicalInput(
            provider=resolved.provider,
            summary=payload.summary.strip(),
            start_at=start_at,
            end_at=end_at,
            description=payload.description,
            location=payload.location,
            account_email=resolved.email,
            calendar_id=PRIMARY_CALENDAR_ID,
            operation_id=generate_operation_id(),
            calendar_href=calendar_href,
            calendar_label=calendar_label,
        )

    def create_event(self, payload: CreateCalendarEventCanonicalInput) -> CreateCalendarEventOutput:
        if payload.calendar_id != PRIMARY_CALENDAR_ID:
            raise ToolError("calendar_id must be primary")
        provider = execution_provider(
            self._session,
            self._user_id,
            capability="create_calendar_event",
            provider=payload.provider,
            account_email=payload.account_email,
        )
        if provider == "yandex":
            return self._create_yandex_event(payload)
        return self._create_google_event(payload)

    def _create_google_event(
        self, payload: CreateCalendarEventCanonicalInput
    ) -> CreateCalendarEventOutput:
        account = self._require_google_account(payload.account_email)
        self._require_write_scope(account)
        event_id = calendar_event_id_from_operation_id(payload.operation_id)
        access_token = self._valid_access_token(account.id)
        body = self._provider_body(payload, event_id)
        try:
            created = self._transport.insert_event(
                access_token=access_token,
                calendar_id=PRIMARY_CALENDAR_ID,
                body=body,
            )
            self._assert_event_matches(payload, created, event_id)
            return self._output(payload, created, event_id, changed=True)
        except GoogleApiError as exc:
            if exc.status_code == 409:
                existing = self._require_matching_existing(access_token, payload, event_id)
                return self._output(payload, existing, event_id, changed=False)
            if _is_ambiguous_insert_error(exc):
                return self._reconcile_after_uncertain_insert(access_token, payload, event_id)
            raise ToolError(self._bounded_provider_error(exc)) from exc
        except httpx.RequestError:
            return self._reconcile_after_uncertain_insert(access_token, payload, event_id)

    def _create_yandex_event(
        self, payload: CreateCalendarEventCanonicalInput
    ) -> CreateCalendarEventOutput:
        if not payload.calendar_href:
            raise ToolError("Yandex calendar target is missing")
        self._assert_safe_calendar_href(payload.calendar_href)
        account = self._require_yandex_calendar_account(payload.account_email)
        transport = self._yandex_caldav_for_account(account)
        href = event_href_from_operation_id(payload.calendar_href, payload.operation_id)
        event_id = calendar_event_id_from_operation_id(payload.operation_id)
        attempt, claimed = self._claim_started(payload.operation_id)
        if not claimed:
            return self._resume_yandex_attempt(transport, payload, href, event_id, attempt)
        inspection = self._inspect_canonical(transport, payload, href)
        if inspection == "match":
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_SUCCEEDED,
                provider_external_id=href,
            )
            return self._yandex_output(payload, event_id, changed=False)
        if inspection == "mismatch":
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_FAILED_DEFINITE,
                error=_MISMATCH_MESSAGE,
            )
            raise ToolError(_MISMATCH_MESSAGE)
        if inspection == "unverifiable":
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_UNCERTAIN,
                error=_UNCERTAIN_CREATE_MESSAGE,
            )
            raise ToolError(_UNCERTAIN_CREATE_MESSAGE)
        ics = build_vevent_ics(payload)
        try:
            status = transport.put_calendar_object(href, ics, if_none_match="*")
        except YandexCalDavError as exc:
            if _is_ambiguous_caldav_error(exc):
                return self._after_ambiguous_put(transport, payload, href, event_id)
            message = self._bounded_caldav_error(exc)
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_FAILED_DEFINITE,
                error=message,
            )
            raise ToolError(message) from exc
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_SUCCEEDED,
            provider_external_id=href,
            extra_metadata={"provider_status": status},
        )
        return self._yandex_output(payload, event_id, changed=True)

    def _resume_yandex_attempt(
        self,
        transport,
        payload: CreateCalendarEventCanonicalInput,
        href: str,
        event_id: str,
        attempt: ExternalActionAttempt,
    ) -> CreateCalendarEventOutput:
        if attempt.state == ATTEMPT_FAILED_DEFINITE:
            raise ToolError(_FAILED_DEFINITE_MESSAGE)
        inspection = self._inspect_canonical(transport, payload, href)
        if attempt.state == ATTEMPT_SUCCEEDED:
            if inspection == "match":
                return self._yandex_output(payload, event_id, changed=False)
            if inspection == "absent":
                raise ToolError(_MISSING_EVENT_MESSAGE)
            if inspection == "mismatch":
                raise ToolError(_MISMATCH_MESSAGE)
            raise ToolError(_UNCERTAIN_CREATE_MESSAGE)
        if inspection == "match":
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_SUCCEEDED,
                provider_external_id=href,
            )
            return self._yandex_output(payload, event_id, changed=False)
        if inspection == "mismatch":
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_FAILED_DEFINITE,
                error=_MISMATCH_MESSAGE,
            )
            raise ToolError(_MISMATCH_MESSAGE)
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_UNCERTAIN,
            error=_UNCERTAIN_CREATE_MESSAGE,
        )
        raise ToolError(_UNCERTAIN_CREATE_MESSAGE)

    def _after_ambiguous_put(
        self,
        transport,
        payload: CreateCalendarEventCanonicalInput,
        href: str,
        event_id: str,
    ) -> CreateCalendarEventOutput:
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_UNCERTAIN,
            error=_UNCERTAIN_CREATE_MESSAGE,
        )
        inspection = self._inspect_canonical(transport, payload, href)
        if inspection == "match":
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_SUCCEEDED,
                provider_external_id=href,
            )
            return self._yandex_output(payload, event_id, changed=True)
        if inspection == "mismatch":
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_FAILED_DEFINITE,
                error=_MISMATCH_MESSAGE,
            )
            raise ToolError(_MISMATCH_MESSAGE)
        raise ToolError(_UNCERTAIN_CREATE_MESSAGE)

    def _inspect_canonical(
        self,
        transport,
        payload: CreateCalendarEventCanonicalInput,
        href: str,
    ) -> str:
        try:
            existing = self._get_yandex_event(transport, href)
        except ToolError:
            return "unverifiable"
        if existing is None:
            return "absent"
        if event_matches_frozen_payload(
            payload, existing, payload.calendar_href or "", href
        ):
            return "match"
        return "mismatch"

    def _get_yandex_event(self, transport, href: str) -> str | None:
        try:
            return transport.get_calendar_object(href)
        except YandexCalDavError as exc:
            if exc.status_code == 404:
                return None
            raise ToolError(self._bounded_caldav_error(exc)) from exc

    def _claim_started(self, operation_id: str) -> tuple[ExternalActionAttempt, bool]:
        session = self._attempt_session_factory()
        try:
            attempt = ExternalActionAttempt(
                user_id=self._user_id,
                operation_id=operation_id,
                tool_name=CALENDAR_TOOL_NAME,
                state=ATTEMPT_STARTED,
                started_at=_utcnow(),
            )
            session.add(attempt)
            session.commit()
            session.refresh(attempt)
            return attempt, True
        except IntegrityError:
            session.rollback()
            existing = session.scalar(
                select(ExternalActionAttempt).where(
                    ExternalActionAttempt.user_id == self._user_id,
                    ExternalActionAttempt.operation_id == operation_id,
                )
            )
            if existing is None:
                raise ToolError("failed to claim create_calendar_event operation")
            return existing, False
        finally:
            session.close()

    def _persist_attempt_state(
        self,
        operation_id: str,
        state: str,
        *,
        provider_external_id: str | None = None,
        error: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        session = self._attempt_session_factory()
        try:
            attempt = session.scalar(
                select(ExternalActionAttempt).where(
                    ExternalActionAttempt.user_id == self._user_id,
                    ExternalActionAttempt.operation_id == operation_id,
                )
            )
            if attempt is None:
                return
            if attempt.state == ATTEMPT_FAILED_DEFINITE and state != ATTEMPT_FAILED_DEFINITE:
                return
            metadata = dict(attempt.result_metadata or {})
            if error:
                metadata["error"] = error[:500]
            if extra_metadata:
                metadata.update(extra_metadata)
            if attempt.state == ATTEMPT_SUCCEEDED and state != ATTEMPT_SUCCEEDED:
                attempt.result_metadata = metadata
                flag_modified(attempt, "result_metadata")
                session.commit()
                return
            attempt.state = state
            attempt.result_metadata = metadata
            flag_modified(attempt, "result_metadata")
            if provider_external_id:
                attempt.provider_external_id = provider_external_id[:200]
            if state != ATTEMPT_STARTED:
                attempt.finished_at = _utcnow()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _assert_safe_calendar_href(self, href: str) -> None:
        if not href.startswith("/") or ".." in href or "\n" in href or "\r" in href:
            raise ToolError("invalid calendar target")

    def _yandex_output(
        self,
        payload: CreateCalendarEventCanonicalInput,
        event_id: str,
        *,
        changed: bool,
    ) -> CreateCalendarEventOutput:
        return self._output(
            payload,
            {
                "id": event_id,
                "summary": payload.summary,
                "start": {"dateTime": _format_rfc3339(payload.start_at)},
                "end": {"dateTime": _format_rfc3339(payload.end_at)},
            },
            event_id,
            changed=changed,
        )

    def _bounded_caldav_error(self, exc: YandexCalDavError) -> str:
        message = (exc.message or "Yandex Calendar request failed").strip()
        lowered = message.lower()
        if any(token in lowered for token in ("password", "app_password", "app-password", "authorization")):
            return "Yandex Calendar request failed"
        return message[:500]

    def _reconcile_after_uncertain_insert(
        self,
        access_token: str,
        payload: CreateCalendarEventCanonicalInput,
        event_id: str,
    ) -> CreateCalendarEventOutput:
        try:
            existing = self._get_event(access_token, event_id)
        except ToolError as exc:
            raise ToolError(
                "could not confirm calendar event creation; not retrying with a new event id"
            ) from exc
        if existing is None:
            raise ToolError("failed to create calendar event")
        self._assert_event_matches(payload, existing, event_id)
        return self._output(payload, existing, event_id, changed=False)

    def _require_matching_existing(
        self,
        access_token: str,
        payload: CreateCalendarEventCanonicalInput,
        event_id: str,
    ) -> dict[str, Any]:
        existing = self._get_event(access_token, event_id)
        if existing is None:
            raise ToolError("failed to create calendar event")
        self._assert_event_matches(payload, existing, event_id)
        return existing

    def _get_event(self, access_token: str, event_id: str) -> dict[str, Any] | None:
        try:
            return self._transport.get_event(
                access_token=access_token,
                calendar_id=PRIMARY_CALENDAR_ID,
                event_id=event_id,
            )
        except GoogleApiError as exc:
            if exc.status_code == 404:
                return None
            raise ToolError(self._bounded_provider_error(exc)) from exc
        except httpx.RequestError as exc:
            raise ToolError(
                "could not confirm calendar event creation; not retrying with a new event id"
            ) from exc

    def _valid_access_token(self, account_id: UUID) -> str:
        if not settings.secretary_credential_key:
            raise ToolError("google credentials are not configured")
        token_session = self._token_session_factory()
        try:
            store = GoogleAccountStore(
                token_session,
                GoogleAccountStore.build_encryption(settings.secretary_credential_key),
            )
            oauth_service = GoogleOAuthService(
                client_file=settings.google_oauth_client_file,
                redirect_uri=settings.google_redirect_uri,
            )
            token_manager = GoogleTokenManager(token_session, store, oauth_service)
            token = token_manager.get_valid_access_token(account_id, self._user_id)
            token_session.commit()
            return token
        except (GoogleConnectorError, GoogleOAuthError) as exc:
            token_session.rollback()
            raise ToolError(exc.message) from exc
        except Exception:
            token_session.rollback()
            raise
        finally:
            token_session.close()

    def _resolve_account(self, account_email: str | None) -> GoogleAccount:
        if not account_email:
            raise ToolError("Google account is not connected")
        return self._require_google_account(account_email)

    def _require_google_account(self, account_email: str) -> GoogleAccount:
        store = self._account_store()
        accounts = store.list_accounts(self._user_id)
        normalized = account_email.strip().lower()
        matches = [account for account in accounts if account.email.lower() == normalized]
        if len(matches) != 1:
            raise ToolError("Google account is not connected")
        return matches[0]

    def _require_yandex_calendar_account(self, account_email: str) -> YandexCalendarAccount:
        store = self._yandex_calendar_store()
        accounts = store.list_accounts(self._user_id)
        normalized = account_email.strip().lower()
        matches = [account for account in accounts if account.email.lower() == normalized]
        if len(matches) != 1:
            raise ToolError("Yandex account is not connected")
        return matches[0]

    def _require_write_scope(self, account: GoogleAccount) -> None:
        scopes = {str(scope) for scope in (account.scopes or [])}
        if CALENDAR_EVENTS_SCOPE not in scopes:
            raise ToolError(_RECONNECT_WRITE_SCOPE_MESSAGE)

    def _account_store(self) -> GoogleAccountStore:
        if not settings.secretary_credential_key:
            raise ToolError("google credentials are not configured")
        encryption = CredentialEncryption(settings.secretary_credential_key)
        return GoogleAccountStore(self._session, encryption)

    def _yandex_calendar_store(self) -> YandexCalendarAccountStore:
        if not settings.secretary_credential_key:
            raise ToolError("credentials are not configured")
        return YandexCalendarAccountStore(
            self._session,
            YandexCalendarAccountStore.build_encryption(settings.secretary_credential_key),
        )

    def _yandex_caldav_for_account(self, account: YandexCalendarAccount):
        if self._yandex_caldav_transport is not None:
            return self._yandex_caldav_transport
        password = self._yandex_calendar_store().get_app_password(account)
        return CalDavHttpTransport(
            email=account.email,
            password=password,
            base_url=trusted_caldav_base_url(account.caldav_host),
        )

    def _provider_body(
        self,
        payload: CreateCalendarEventCanonicalInput,
        event_id: str,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "id": event_id,
            "summary": payload.summary,
            "start": {"dateTime": _format_rfc3339(payload.start_at)},
            "end": {"dateTime": _format_rfc3339(payload.end_at)},
        }
        if payload.description:
            body["description"] = payload.description
        if payload.location:
            body["location"] = payload.location
        return body

    def _assert_event_matches(
        self,
        payload: CreateCalendarEventCanonicalInput,
        event: dict[str, Any],
        event_id: str,
    ) -> None:
        if str(event.get("id") or "") != event_id:
            raise ToolError("calendar event identity mismatch")
        if str(event.get("summary") or "") != payload.summary:
            raise ToolError("existing calendar event does not match frozen fields")
        start = _parse_provider_datetime((event.get("start") or {}).get("dateTime"))
        end = _parse_provider_datetime((event.get("end") or {}).get("dateTime"))
        if start is None or end is None:
            raise ToolError("existing calendar event does not match frozen fields")
        if start.astimezone(ZoneInfo("UTC")) != payload.start_at.astimezone(ZoneInfo("UTC")):
            raise ToolError("existing calendar event does not match frozen fields")
        if end.astimezone(ZoneInfo("UTC")) != payload.end_at.astimezone(ZoneInfo("UTC")):
            raise ToolError("existing calendar event does not match frozen fields")
        provider_description = event.get("description")
        if (payload.description or None) != (provider_description or None):
            raise ToolError("existing calendar event does not match frozen fields")
        provider_location = event.get("location")
        if (payload.location or None) != (provider_location or None):
            raise ToolError("existing calendar event does not match frozen fields")

    def _output(
        self,
        payload: CreateCalendarEventCanonicalInput,
        event: dict[str, Any],
        event_id: str,
        *,
        changed: bool,
    ) -> CreateCalendarEventOutput:
        html_link = event.get("htmlLink")
        canonical_uri = str(html_link) if isinstance(html_link, str) and html_link.strip() else None
        start = _parse_provider_datetime((event.get("start") or {}).get("dateTime")) or payload.start_at
        end = _parse_provider_datetime((event.get("end") or {}).get("dateTime")) or payload.end_at
        return CreateCalendarEventOutput(
            provider=(
                "yandex_calendar"
                if (payload.provider or "google") == "yandex"
                else "google_calendar"
            ),
            account_email=payload.account_email,
            calendar_id=PRIMARY_CALENDAR_ID,
            event_id=event_id,
            summary=payload.summary,
            start_at=start,
            end_at=end,
            canonical_uri=canonical_uri,
            changed=changed,
        )

    def _bounded_provider_error(self, exc: GoogleApiError) -> str:
        message = (exc.message or "Google Calendar request failed").strip()
        lowered = message.lower()
        if any(token in lowered for token in ("access_token", "refresh_token", "bearer ", "ya29.")):
            return "Google Calendar request failed"
        return message[:500]


def _is_ambiguous_insert_error(exc: GoogleApiError) -> bool:
    if exc.retryable:
        return True
    return exc.status_code is not None and exc.status_code >= 500


def _is_ambiguous_caldav_error(exc: YandexCalDavError) -> bool:
    if exc.retryable:
        return True
    return exc.status_code is not None and exc.status_code >= 500
