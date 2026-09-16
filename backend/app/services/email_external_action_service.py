"""Bounded Gmail send_email execution after approval."""

import base64
import json
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import SMTP
from email.policy import default as email_default_policy
from email.utils import parseaddr
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.connectors.google.constants import GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleApiError, GoogleConnectorError, GoogleOAuthError
from app.connectors.google.gmail_transport import GmailTransport, GoogleTokenManager
from app.connectors.google.oauth_service import GoogleOAuthService
from app.connectors.yandex.constants import DEFAULT_SMTP_HOST, DEFAULT_SMTP_PORT
from app.connectors.yandex.credentials import YandexMailAccountStore
from app.connectors.yandex.errors import YandexImapError, YandexSmtpError
from app.connectors.yandex.imap_transport import ImaplibTransport
from app.connectors.yandex.smtp_transport import SmtpSslTransport
from app.core.config import settings
from app.db.models import ExternalActionAttempt, GoogleAccount, YandexMailAccount
from app.db.session import SessionLocal
from app.services.external_account_resolution import (
    execution_provider,
    resolve_external_account,
)
from app.tools.schemas import SendEmailCanonicalInput, SendEmailInput, SendEmailOutput, ToolError

ATTEMPT_STARTED = "started"
ATTEMPT_SUCCEEDED = "succeeded"
ATTEMPT_FAILED_DEFINITE = "failed_definite"
ATTEMPT_UNCERTAIN = "uncertain"

_RECONNECT_SEND_SCOPE_MESSAGE = (
    "Google must be reconnected to grant Gmail send permission"
)
_UNCERTAIN_DELIVERY_MESSAGE = (
    "could not confirm email delivery; not retrying send"
)
_MISMATCH_MESSAGE = "existing sent message does not match frozen fields"
_DUPLICATE_OPERATION_MESSAGE = "multiple sent messages match this operation"
_FAILED_DEFINITE_MESSAGE = "email send previously failed; create a new plan"

SECRETARY_OPERATION_HEADER = "X-Secretary-Operation-ID"
SENT_RECONCILE_LOOKBACK = timedelta(hours=2)
SENT_RECONCILE_LOOKAHEAD = timedelta(hours=2)
SENT_LIST_PAGE_SIZE = 50
MAX_SENT_LIST_PAGES = 5
MAX_SENT_CANDIDATES = 200
SECRETARY_UNCERTAIN_FOLDER = "Secretary-Uncertain"
SENT_COPY_NOT_STARTED = "not_started"
SENT_COPY_STARTED = "started"
SENT_COPY_STORED = "stored"
SENT_COPY_UNCERTAIN = "uncertain"
SENT_COPY_FAILED_DEFINITE = "failed_definite"
METADATA_SENT_COPY_STATE = "sent_copy_state"
METADATA_UNCERTAIN_COPY_STATE = "uncertain_copy_state"


def yandex_sent_evidence_window(started_at: datetime) -> tuple[datetime, datetime]:
    started = started_at.astimezone(UTC)
    return started - SENT_RECONCILE_LOOKBACK, started + SENT_RECONCILE_LOOKAHEAD


def yandex_sent_coarse_imap_bounds(started_at: datetime) -> tuple[datetime, datetime]:
    """Day-level IMAP SINCE/BEFORE prefilter covering the exact ±2h window.

    IMAP SINCE is inclusive of the given date. IMAP BEFORE is exclusive of the
    given date, so the exclusive upper date is the UTC day after the window end.
    """
    window_start, window_end = yandex_sent_evidence_window(started_at)
    since = datetime(window_start.year, window_start.month, window_start.day, tzinfo=UTC)
    end_day = datetime(window_end.year, window_end.month, window_end.day, tzinfo=UTC)
    return since, end_day + timedelta(days=1)


def generate_operation_id() -> str:
    return uuid4().hex


def rfc822_message_id_from_operation_id(operation_id: str) -> str:
    compact = operation_id.replace("-", "").lower()
    if len(compact) < 5 or len(compact) > 1024:
        raise ToolError("invalid operation_id")
    return f"<secretary.{compact}@secretary.invalid>"


def secretary_operation_header_value(operation_id: str) -> str:
    compact = operation_id.replace("-", "").strip()
    if len(compact) < 5 or len(compact) > 1024:
        raise ToolError("invalid operation_id")
    return compact


def sent_window_query(started_at: datetime) -> str:
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    after_epoch = int((started_at - SENT_RECONCILE_LOOKBACK).timestamp())
    before_epoch = int((started_at + SENT_RECONCILE_LOOKAHEAD).timestamp()) + 1
    return f"in:sent after:{after_epoch} before:{before_epoch}"


def build_email_message(payload: SendEmailCanonicalInput) -> EmailMessage:
    message = EmailMessage()
    message["From"] = payload.account_email
    message["To"] = ", ".join(payload.to)
    message["Subject"] = payload.subject
    message["Message-ID"] = payload.rfc822_message_id
    message[SECRETARY_OPERATION_HEADER] = secretary_operation_header_value(payload.operation_id)
    message.set_content(payload.body, subtype="plain", charset="utf-8")
    return message


def build_rfc822_raw(payload: SendEmailCanonicalInput) -> str:
    raw = build_email_message(payload).as_bytes(policy=SMTP)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize_body(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def _header_from_list(headers: list[dict[str, Any]], name: str) -> str | None:
    for header in headers:
        if str(header.get("name") or "").lower() == name.lower():
            value = header.get("value")
            return str(value) if value is not None else None
    return None


def _parse_addresses(value: str | None) -> list[str]:
    if not value:
        return []
    addresses: list[str] = []
    for part in value.split(","):
        _, addr = parseaddr(part.strip())
        if addr:
            addresses.append(addr)
    return addresses


def _extract_plain_body(payload: dict[str, Any]) -> str | None:
    mime_type = str(payload.get("mimeType") or "")
    body = payload.get("body") or {}
    data = body.get("data")
    if data and mime_type.startswith("text/plain"):
        padded = str(data) + "=" * (-len(str(data)) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
    for part in payload.get("parts") or []:
        if isinstance(part, dict):
            found = _extract_plain_body(part)
            if found is not None:
                return found
    return None


class EmailExternalActionService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        *,
        transport: GmailTransport | None = None,
        token_session_factory=SessionLocal,
        attempt_session_factory=SessionLocal,
        yandex_smtp_transport=None,
        yandex_imap_transport=None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._transport = transport or GmailTransport()
        self._token_session_factory = token_session_factory
        self._attempt_session_factory = attempt_session_factory
        self._yandex_smtp_transport = yandex_smtp_transport
        self._yandex_imap_transport = yandex_imap_transport

    def prepare_send_email(self, payload: SendEmailInput) -> SendEmailCanonicalInput:
        resolved = resolve_external_account(
            self._session,
            self._user_id,
            capability="send_email",
            provider=payload.provider,
            account_email=payload.account_email,
        )
        if resolved.provider == "google":
            account = self._require_google_account(resolved.email)
            self._require_send_scopes(account)
        else:
            self._require_yandex_mail_account(resolved.email)
        operation_id = generate_operation_id()
        return SendEmailCanonicalInput(
            provider=resolved.provider,
            account_email=resolved.email,
            to=list(payload.to),
            subject=payload.subject,
            body=payload.body,
            operation_id=operation_id,
            rfc822_message_id=rfc822_message_id_from_operation_id(operation_id),
        )

    def send_email(self, payload: SendEmailCanonicalInput) -> SendEmailOutput:
        expected_id = rfc822_message_id_from_operation_id(payload.operation_id)
        if payload.rfc822_message_id != expected_id:
            raise ToolError("rfc822_message_id does not match operation_id")
        provider = execution_provider(
            self._session,
            self._user_id,
            capability="send_email",
            provider=payload.provider,
            account_email=payload.account_email,
        )
        if provider == "yandex":
            return self._send_yandex_email(payload)
        return self._send_gmail(payload)

    def _send_gmail(self, payload: SendEmailCanonicalInput) -> SendEmailOutput:
        account = self._require_google_account(payload.account_email)
        self._require_send_scopes(account)
        attempt, claimed = self._claim_started(payload.operation_id)
        if not claimed:
            return self._resume_existing_attempt(account, payload, attempt)

        access_token = self._valid_access_token(account.id)
        raw = build_rfc822_raw(payload)
        try:
            sent = self._transport.send_message(
                access_token=access_token,
                user_id="me",
                raw=raw,
            )
        except GoogleApiError as exc:
            if _is_ambiguous_send_error(exc):
                return self._after_ambiguous_send(account, payload, access_token, attempt)
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_FAILED_DEFINITE,
                error=self._bounded_provider_error(exc),
            )
            raise ToolError(self._bounded_provider_error(exc)) from exc
        except httpx.RequestError:
            return self._after_ambiguous_send(account, payload, access_token, attempt)

        provider_id = str(sent.get("id") or "").strip() or None
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_SUCCEEDED,
            provider_external_id=provider_id,
            delivery_status="sent",
        )
        return self._output(payload, provider_id, delivery_status="sent", changed=True)

    def _resume_existing_attempt(
        self,
        account: GoogleAccount,
        payload: SendEmailCanonicalInput,
        attempt: ExternalActionAttempt,
    ) -> SendEmailOutput:
        if attempt.state == ATTEMPT_SUCCEEDED:
            return self._output(
                payload,
                attempt.provider_external_id,
                delivery_status="already_sent",
                changed=False,
            )
        if attempt.state == ATTEMPT_FAILED_DEFINITE:
            raise ToolError(_FAILED_DEFINITE_MESSAGE)
        access_token = self._valid_access_token(account.id)
        return self._reconcile_sent(account, payload, access_token, attempt)

    def _after_ambiguous_send(
        self,
        account: GoogleAccount,
        payload: SendEmailCanonicalInput,
        access_token: str,
        attempt: ExternalActionAttempt,
    ) -> SendEmailOutput:
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_UNCERTAIN,
            error=_UNCERTAIN_DELIVERY_MESSAGE,
        )
        return self._reconcile_sent(account, payload, access_token, attempt)

    def _reconcile_sent(
        self,
        account: GoogleAccount,
        payload: SendEmailCanonicalInput,
        access_token: str,
        attempt: ExternalActionAttempt,
    ) -> SendEmailOutput:
        started_at = self._attempt_started_at(payload.operation_id) or attempt.started_at or _utcnow()
        query = sent_window_query(started_at)
        try:
            ids, incomplete = self._list_sent_candidate_ids(access_token, query)
        except (GoogleApiError, httpx.RequestError) as exc:
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_UNCERTAIN,
                error=_UNCERTAIN_DELIVERY_MESSAGE,
            )
            raise ToolError(_UNCERTAIN_DELIVERY_MESSAGE) from exc

        if incomplete:
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_UNCERTAIN,
                error=_UNCERTAIN_DELIVERY_MESSAGE,
            )
            raise ToolError(_UNCERTAIN_DELIVERY_MESSAGE)

        tagged: list[dict[str, Any]] = []
        for message_id in ids:
            try:
                message = self._transport.get_message(access_token, "me", message_id)
            except (GoogleApiError, httpx.RequestError) as exc:
                self._persist_attempt_state(
                    payload.operation_id,
                    ATTEMPT_UNCERTAIN,
                    error=_UNCERTAIN_DELIVERY_MESSAGE,
                )
                raise ToolError(_UNCERTAIN_DELIVERY_MESSAGE) from exc
            if not isinstance(message, dict):
                self._persist_attempt_state(
                    payload.operation_id,
                    ATTEMPT_UNCERTAIN,
                    error=_UNCERTAIN_DELIVERY_MESSAGE,
                )
                raise ToolError(_UNCERTAIN_DELIVERY_MESSAGE)
            if self._operation_header_matches(payload, message):
                tagged.append(message)

        if len(tagged) > 1:
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_UNCERTAIN,
                error=_DUPLICATE_OPERATION_MESSAGE,
            )
            raise ToolError(_DUPLICATE_OPERATION_MESSAGE)
        if not tagged:
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_UNCERTAIN,
                error=_UNCERTAIN_DELIVERY_MESSAGE,
            )
            raise ToolError(_UNCERTAIN_DELIVERY_MESSAGE)

        matched = tagged[0]
        if not self._message_content_matches(account, payload, matched):
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_FAILED_DEFINITE,
                error=_MISMATCH_MESSAGE,
            )
            raise ToolError(_MISMATCH_MESSAGE)

        provider_id = str(matched.get("id") or "").strip() or None
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_SUCCEEDED,
            provider_external_id=provider_id,
            delivery_status="already_sent",
        )
        return self._output(
            payload,
            provider_id,
            delivery_status="already_sent",
            changed=False,
        )

    def _list_sent_candidate_ids(
        self,
        access_token: str,
        query: str,
    ) -> tuple[list[str], bool]:
        ids: list[str] = []
        page_token: str | None = None
        pages = 0
        while pages < MAX_SENT_LIST_PAGES and len(ids) < MAX_SENT_CANDIDATES:
            remaining = MAX_SENT_CANDIDATES - len(ids)
            page = self._transport.list_message_ids_page(
                access_token=access_token,
                user_id="me",
                query=query,
                max_results=min(SENT_LIST_PAGE_SIZE, remaining),
                page_token=page_token,
            )
            pages += 1
            ids.extend(page.message_ids[:remaining])
            if not page.next_page_token:
                return ids, False
            if len(ids) >= MAX_SENT_CANDIDATES:
                return ids[:MAX_SENT_CANDIDATES], True
            page_token = page.next_page_token
        return ids[:MAX_SENT_CANDIDATES], True

    def _send_yandex_email(self, payload: SendEmailCanonicalInput) -> SendEmailOutput:
        account = self._require_yandex_mail_account(payload.account_email)
        attempt, claimed = self._claim_started(payload.operation_id)
        imap = self._yandex_imap(account)
        if not claimed:
            return self._resume_yandex_attempt(payload, attempt, imap)
        smtp = self._yandex_smtp(account)
        message = build_email_message(payload)
        message_bytes = message.as_bytes(policy=SMTP)
        try:
            smtp.send_rfc822(
                from_addr=payload.account_email,
                to_addrs=list(payload.to),
                message_bytes=message_bytes,
            )
        except YandexSmtpError as exc:
            if exc.retryable:
                return self._after_ambiguous_yandex_send(payload, imap, message_bytes)
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_FAILED_DEFINITE,
                error=self._bounded_yandex_error(exc),
            )
            raise ToolError(self._bounded_yandex_error(exc)) from exc
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_SUCCEEDED,
            delivery_status="sent",
            extra_metadata={METADATA_SENT_COPY_STATE: SENT_COPY_NOT_STARTED},
        )
        copy_status = self._best_effort_sent_copy(
            payload,
            lambda: self._complete_yandex_sent_copy(payload, imap, message_bytes),
        )
        return self._output(
            payload,
            None,
            delivery_status="sent",
            changed=True,
            sent_copy_status=copy_status,
        )

    def _resume_yandex_attempt(
        self,
        payload: SendEmailCanonicalInput,
        attempt: ExternalActionAttempt,
        imap,
    ) -> SendEmailOutput:
        message_bytes = build_email_message(payload).as_bytes(policy=SMTP)
        if attempt.state == ATTEMPT_FAILED_DEFINITE:
            raise ToolError(_FAILED_DEFINITE_MESSAGE)
        if attempt.state == ATTEMPT_SUCCEEDED:
            return self._resume_succeeded_yandex_copy(payload, attempt, imap, message_bytes)
        if attempt.state == ATTEMPT_STARTED:
            raise ToolError(_UNCERTAIN_DELIVERY_MESSAGE)
        return self._after_ambiguous_yandex_send(payload, imap, message_bytes)

    def _resume_succeeded_yandex_copy(
        self,
        payload: SendEmailCanonicalInput,
        attempt: ExternalActionAttempt,
        imap,
        message_bytes: bytes,
    ) -> SendEmailOutput:
        copy_state = self._copy_state(attempt, METADATA_SENT_COPY_STATE)
        if copy_state == SENT_COPY_STORED:
            return self._output(
                payload,
                attempt.provider_external_id,
                delivery_status="already_sent",
                changed=False,
                sent_copy_status="already_present",
            )

        def _copy() -> str:
            if copy_state == SENT_COPY_NOT_STARTED:
                return self._complete_yandex_sent_copy(payload, imap, message_bytes)
            return self._reconcile_yandex_mailbox_copy(
                payload,
                imap,
                self._sent_folder_or_none(imap),
                METADATA_SENT_COPY_STATE,
                allow_append=False,
            )

        copy_status = self._best_effort_sent_copy(payload, _copy)
        return self._output(
            payload,
            attempt.provider_external_id,
            delivery_status="already_sent",
            changed=False,
            sent_copy_status=copy_status,
        )

    def _best_effort_sent_copy(self, payload: SendEmailCanonicalInput, work) -> str:
        try:
            return work()
        except Exception:  # noqa: BLE001
            try:
                self._set_copy_state(
                    payload.operation_id,
                    METADATA_SENT_COPY_STATE,
                    SENT_COPY_UNCERTAIN,
                )
            except Exception:  # noqa: BLE001, S110
                pass
            return "unconfirmed"

    def _after_ambiguous_yandex_send(
        self,
        payload: SendEmailCanonicalInput,
        imap,
        message_bytes: bytes,
    ) -> SendEmailOutput:
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_UNCERTAIN,
            error=_UNCERTAIN_DELIVERY_MESSAGE,
        )
        self._store_yandex_uncertain_copy(payload, imap, message_bytes)
        raise ToolError(_UNCERTAIN_DELIVERY_MESSAGE)

    def _complete_yandex_sent_copy(
        self,
        payload: SendEmailCanonicalInput,
        imap,
        message_bytes: bytes,
    ) -> str:
        claimed = self._claim_copy_state(payload.operation_id, METADATA_SENT_COPY_STATE)
        if not claimed:
            latest = self._load_attempt(payload.operation_id)
            copy_state = self._copy_state(latest, METADATA_SENT_COPY_STATE) if latest else SENT_COPY_UNCERTAIN
            if copy_state == SENT_COPY_STORED:
                return "already_present"
            return self._reconcile_yandex_mailbox_copy(
                payload,
                imap,
                self._sent_folder_or_none(imap),
                METADATA_SENT_COPY_STATE,
                allow_append=False,
            )
        return self._append_yandex_mailbox_copy(
            payload,
            imap,
            self._sent_folder_or_none(imap),
            message_bytes,
            METADATA_SENT_COPY_STATE,
            create_folder=False,
        )

    def _store_yandex_uncertain_copy(
        self,
        payload: SendEmailCanonicalInput,
        imap,
        message_bytes: bytes,
    ) -> None:
        latest = self._load_attempt(payload.operation_id)
        copy_state = self._copy_state(latest, METADATA_UNCERTAIN_COPY_STATE) if latest else SENT_COPY_NOT_STARTED
        if copy_state == SENT_COPY_STORED:
            return
        try:
            tagged = self._find_exact_mailbox_copies(imap, SECRETARY_UNCERTAIN_FOLDER, payload)
        except YandexImapError:
            tagged = []
        if len(tagged) == 1:
            self._set_copy_state(payload.operation_id, METADATA_UNCERTAIN_COPY_STATE, SENT_COPY_STORED)
            return
        if len(tagged) > 1:
            self._set_copy_state(payload.operation_id, METADATA_UNCERTAIN_COPY_STATE, SENT_COPY_UNCERTAIN)
            return
        if copy_state in {SENT_COPY_STARTED, SENT_COPY_UNCERTAIN, SENT_COPY_FAILED_DEFINITE}:
            self._reconcile_yandex_mailbox_copy(
                payload,
                imap,
                SECRETARY_UNCERTAIN_FOLDER,
                METADATA_UNCERTAIN_COPY_STATE,
                allow_append=False,
            )
            return
        claimed = self._claim_copy_state(payload.operation_id, METADATA_UNCERTAIN_COPY_STATE)
        if not claimed:
            self._reconcile_yandex_mailbox_copy(
                payload,
                imap,
                SECRETARY_UNCERTAIN_FOLDER,
                METADATA_UNCERTAIN_COPY_STATE,
                allow_append=False,
            )
            return
        self._append_yandex_mailbox_copy(
            payload,
            imap,
            SECRETARY_UNCERTAIN_FOLDER,
            message_bytes,
            METADATA_UNCERTAIN_COPY_STATE,
            create_folder=True,
        )

    def _sent_folder_or_none(self, imap) -> str | None:
        try:
            return imap.discover_sent_folder()
        except YandexImapError:
            return None

    def _append_yandex_mailbox_copy(
        self,
        payload: SendEmailCanonicalInput,
        imap,
        folder: str | None,
        message_bytes: bytes,
        metadata_key: str,
        *,
        create_folder: bool,
    ) -> str:
        if folder is None:
            self._set_copy_state(payload.operation_id, metadata_key, SENT_COPY_FAILED_DEFINITE)
            return "unconfirmed"
        try:
            if create_folder:
                imap.ensure_mailbox(folder)
            imap.append_message(folder, message_bytes, flags=["\\Seen"])
        except YandexImapError as exc:
            if exc.retryable:
                return self._reconcile_yandex_mailbox_copy(
                    payload,
                    imap,
                    folder,
                    metadata_key,
                    allow_append=False,
                )
            self._set_copy_state(payload.operation_id, metadata_key, SENT_COPY_FAILED_DEFINITE)
            return "unconfirmed"
        self._set_copy_state(payload.operation_id, metadata_key, SENT_COPY_STORED)
        return "stored"

    def _reconcile_yandex_mailbox_copy(
        self,
        payload: SendEmailCanonicalInput,
        imap,
        folder: str | None,
        metadata_key: str,
        *,
        allow_append: bool,
    ) -> str:
        del allow_append
        if folder is None:
            self._set_copy_state(payload.operation_id, metadata_key, SENT_COPY_UNCERTAIN)
            return "unconfirmed"
        try:
            tagged = self._find_exact_mailbox_copies(imap, folder, payload)
        except YandexImapError:
            self._set_copy_state(payload.operation_id, metadata_key, SENT_COPY_UNCERTAIN)
            return "unconfirmed"
        if len(tagged) > 1:
            self._set_copy_state(payload.operation_id, metadata_key, SENT_COPY_UNCERTAIN)
            return "unconfirmed"
        if len(tagged) == 1:
            self._set_copy_state(payload.operation_id, metadata_key, SENT_COPY_STORED)
            return "stored"
        current = self._copy_state(self._load_attempt(payload.operation_id), metadata_key)
        if current == SENT_COPY_FAILED_DEFINITE:
            return "unconfirmed"
        self._set_copy_state(payload.operation_id, metadata_key, SENT_COPY_UNCERTAIN)
        return "unconfirmed"

    def _find_exact_mailbox_copies(self, imap, folder: str, payload: SendEmailCanonicalInput) -> list[Any]:
        header_value = secretary_operation_header_value(payload.operation_id)
        uids, incomplete = imap.search_uids_header(
            folder,
            SECRETARY_OPERATION_HEADER,
            header_value,
            MAX_SENT_CANDIDATES,
        )
        if incomplete:
            raise YandexImapError("too many mailbox copy candidates", retryable=True)
        tagged: list[Any] = []
        for uid in uids:
            raw = imap.fetch_message(folder, uid)
            parsed = BytesParser(policy=email_default_policy).parsebytes(raw)
            if not self._rfc822_operation_header_matches(payload, parsed):
                continue
            if not self._rfc822_content_matches(payload, parsed):
                continue
            tagged.append(parsed)
        return tagged

    def _rfc822_operation_header_matches(self, payload: SendEmailCanonicalInput, message: Any) -> bool:
        expected = secretary_operation_header_value(payload.operation_id)
        actual = str(message.get(SECRETARY_OPERATION_HEADER) or "").strip()
        return actual == expected

    def _rfc822_content_matches(self, payload: SendEmailCanonicalInput, message: Any) -> bool:
        from_addresses = [
            addr.lower() for addr in _parse_addresses(str(message.get("From") or ""))
        ]
        if payload.account_email.lower() not in from_addresses:
            return False
        to_addresses = {addr.lower() for addr in _parse_addresses(str(message.get("To") or ""))}
        if to_addresses != {addr.lower() for addr in payload.to}:
            return False
        if str(message.get("Subject") or "") != payload.subject:
            return False
        if str(message.get("Message-ID") or "").strip() != payload.rfc822_message_id:
            return False
        if not self._rfc822_operation_header_matches(payload, message):
            return False
        body = message.get_content()
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        if not isinstance(body, str):
            return False
        return _normalize_body(body) == _normalize_body(payload.body)

    def _copy_state(self, attempt: ExternalActionAttempt | None, key: str) -> str:
        if attempt is None:
            return SENT_COPY_NOT_STARTED
        metadata = dict(attempt.result_metadata or {})
        value = str(metadata.get(key) or SENT_COPY_NOT_STARTED)
        return value

    def _load_attempt(self, operation_id: str) -> ExternalActionAttempt | None:
        session = self._attempt_session_factory()
        try:
            attempt = session.scalar(
                select(ExternalActionAttempt).where(
                    ExternalActionAttempt.user_id == self._user_id,
                    ExternalActionAttempt.operation_id == operation_id,
                )
            )
            if attempt is None:
                return None
            session.expunge(attempt)
            return attempt
        finally:
            session.close()

    def _claim_copy_state(self, operation_id: str, key: str) -> bool:
        session = self._attempt_session_factory()
        try:
            result = session.execute(
                text(
                    """
                    UPDATE external_action_attempts
                    SET result_metadata = coalesce(result_metadata, '{}'::jsonb)
                        || CAST(:patch AS jsonb)
                    WHERE user_id = CAST(:user_id AS uuid)
                      AND operation_id = :operation_id
                      AND coalesce(result_metadata->>:key, 'not_started') = 'not_started'
                    """
                ),
                {
                    "patch": json.dumps({key: SENT_COPY_STARTED}),
                    "user_id": str(self._user_id),
                    "operation_id": operation_id,
                    "key": key,
                },
            )
            session.commit()
            return int(result.rowcount or 0) == 1
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _set_copy_state(self, operation_id: str, key: str, value: str) -> None:
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
            metadata = dict(attempt.result_metadata or {})
            metadata[key] = value
            attempt.result_metadata = metadata
            flag_modified(attempt, "result_metadata")
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _yandex_smtp(self, account: YandexMailAccount):
        if self._yandex_smtp_transport is not None:
            return self._yandex_smtp_transport
        password = self._yandex_mail_store().get_app_password(account)
        return SmtpSslTransport(
            host=DEFAULT_SMTP_HOST,
            port=DEFAULT_SMTP_PORT,
            email=account.email,
            password=password,
        )

    def _yandex_imap(self, account: YandexMailAccount):
        if self._yandex_imap_transport is not None:
            return self._yandex_imap_transport
        password = self._yandex_mail_store().get_app_password(account)
        return ImaplibTransport(
            host=account.imap_host,
            port=account.imap_port,
            email=account.email,
            password=password,
        )

    def _bounded_yandex_error(self, exc: YandexSmtpError | YandexImapError) -> str:
        message = (exc.message or "Yandex mail request failed").strip()
        lowered = message.lower()
        if any(token in lowered for token in ("password", "app_password", "app-password", "secret")):
            return "Yandex mail request failed"
        return message[:500]

    def _claim_started(self, operation_id: str) -> tuple[ExternalActionAttempt, bool]:
        session = self._attempt_session_factory()
        try:
            attempt = ExternalActionAttempt(
                user_id=self._user_id,
                operation_id=operation_id,
                tool_name="send_email",
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
                raise ToolError("failed to claim send_email operation")
            return existing, False
        finally:
            session.close()

    def _persist_attempt_state(
        self,
        operation_id: str,
        state: str,
        *,
        provider_external_id: str | None = None,
        delivery_status: str | None = None,
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
            if delivery_status:
                metadata["delivery_status"] = delivery_status
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

    def _attempt_started_at(self, operation_id: str) -> datetime | None:
        session = self._attempt_session_factory()
        try:
            attempt = session.scalar(
                select(ExternalActionAttempt).where(
                    ExternalActionAttempt.user_id == self._user_id,
                    ExternalActionAttempt.operation_id == operation_id,
                )
            )
            if attempt is None or attempt.started_at is None:
                return None
            started = attempt.started_at
            if started.tzinfo is None:
                return started.replace(tzinfo=UTC)
            return started
        finally:
            session.close()

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

    def _require_yandex_mail_account(self, account_email: str) -> YandexMailAccount:
        store = self._yandex_mail_store()
        accounts = store.list_accounts(self._user_id)
        normalized = account_email.strip().lower()
        matches = [account for account in accounts if account.email.lower() == normalized]
        if len(matches) != 1:
            raise ToolError("Yandex account is not connected")
        return matches[0]

    def _require_send_scopes(self, account: GoogleAccount) -> None:
        scopes = {str(scope) for scope in (account.scopes or [])}
        if GMAIL_SEND_SCOPE not in scopes or GMAIL_READONLY_SCOPE not in scopes:
            raise ToolError(_RECONNECT_SEND_SCOPE_MESSAGE)

    def _account_store(self) -> GoogleAccountStore:
        if not settings.secretary_credential_key:
            raise ToolError("google credentials are not configured")
        encryption = CredentialEncryption(settings.secretary_credential_key)
        return GoogleAccountStore(self._session, encryption)

    def _yandex_mail_store(self) -> YandexMailAccountStore:
        if not settings.secretary_credential_key:
            raise ToolError("credentials are not configured")
        return YandexMailAccountStore(
            self._session,
            YandexMailAccountStore.build_encryption(settings.secretary_credential_key),
        )

    def _operation_header_matches(
        self,
        payload: SendEmailCanonicalInput,
        message: dict[str, Any],
    ) -> bool:
        expected = secretary_operation_header_value(payload.operation_id)
        actual = (self._header_value(message, SECRETARY_OPERATION_HEADER) or "").strip()
        return actual == expected

    def _message_content_matches(
        self,
        account: GoogleAccount,
        payload: SendEmailCanonicalInput,
        message: dict[str, Any],
    ) -> bool:
        from_addresses = [
            addr.lower() for addr in _parse_addresses(self._header_value(message, "From") or "")
        ]
        if account.email.lower() not in from_addresses:
            return False
        to_addresses = {
            addr.lower() for addr in _parse_addresses(self._header_value(message, "To") or "")
        }
        expected_to = {addr.lower() for addr in payload.to}
        if to_addresses != expected_to:
            return False
        if (self._header_value(message, "Subject") or "") != payload.subject:
            return False
        payload_body = message.get("payload") if isinstance(message.get("payload"), dict) else message
        if not isinstance(payload_body, dict):
            return False
        plain = _extract_plain_body(payload_body)
        if plain is None:
            return False
        return _normalize_body(plain) == _normalize_body(payload.body)

    def _header_value(self, message: dict[str, Any], name: str) -> str | None:
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else message
        headers = payload.get("headers") if isinstance(payload, dict) else None
        if not isinstance(headers, list):
            return None
        return _header_from_list(headers, name)

    def _output(
        self,
        payload: SendEmailCanonicalInput,
        provider_message_id: str | None,
        *,
        delivery_status: str,
        changed: bool,
        sent_copy_status: str | None = None,
    ) -> SendEmailOutput:
        return SendEmailOutput(
            provider="gmail" if (payload.provider or "google") != "yandex" else "yandex",
            account_email=payload.account_email,
            to=list(payload.to),
            subject=payload.subject,
            provider_message_id=provider_message_id,
            delivery_status=delivery_status,  # type: ignore[arg-type]
            changed=changed,
            sent_copy_status=sent_copy_status,  # type: ignore[arg-type]
        )

    def _bounded_provider_error(self, exc: GoogleApiError) -> str:
        message = (exc.message or "Gmail request failed").strip()
        lowered = message.lower()
        if any(token in lowered for token in ("access_token", "refresh_token", "bearer ", "ya29.")):
            return "Gmail request failed"
        return message[:500]


def _is_ambiguous_send_error(exc: GoogleApiError) -> bool:
    if exc.retryable:
        return True
    return exc.status_code is not None and exc.status_code >= 500
