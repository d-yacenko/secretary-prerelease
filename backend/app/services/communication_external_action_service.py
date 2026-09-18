"""Bounded Mattermost, Telegram, and Teams send_message execution after approval."""

import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.mattermost.credentials import MattermostAccountStore
from app.connectors.mattermost.errors import (
    MattermostConfigurationError,
    MattermostSecurityError,
    MattermostWriteDefiniteError,
    MattermostWriteUncertainError,
)
from app.connectors.mattermost.materialize import MattermostObjectMaterializer
from app.connectors.mattermost.normalize import (
    MattermostChannelContext,
    build_external_id,
    normalize_server_url,
    parse_allowed_base_urls,
    validate_server_url_allowlist,
)
from app.connectors.mattermost.transport import MattermostHttpTransport, MattermostTransport
from app.connectors.teams.account_store import TeamsAccountStore
from app.connectors.teams.constants import (
    ACCEPTED_CHAT_TYPES,
    AUTH_STATUS_RECONNECT_REQUIRED,
)
from app.connectors.teams.constants import (
    MAX_MESSAGE_BODY_CHARS as MAX_TEAMS_MESSAGE_BODY_CHARS,
)
from app.connectors.teams.errors import (
    TeamsConfigurationError,
    TeamsOAuthError,
    TeamsWriteDefiniteError,
    TeamsWriteUncertainError,
)
from app.connectors.teams.html_text import teams_body_to_plain_text
from app.connectors.teams.id_token import (
    canonicalize_microsoft_guid,
    try_canonical_microsoft_guid,
)
from app.connectors.teams.materialize import TeamsObjectMaterializer
from app.connectors.teams.normalize import build_external_id as build_teams_external_id
from app.connectors.teams.normalize import extract_message_reference_ids, sender_from_message
from app.connectors.teams.normalize import provider_id_str as teams_provider_id_str
from app.connectors.teams.oauth_service import TeamsOAuthService
from app.connectors.teams.token_service import TeamsTokenService
from app.connectors.teams.transport import TeamsHttpTransport, TeamsTransport
from app.connectors.telegram.account_store import TelegramAccountStore
from app.connectors.telegram.constants import (
    DIRECTION_INBOUND,
    MAX_TELEGRAM_MESSAGE_BODY_CHARS,
    RECENT_INBOUND_WINDOW_SECONDS,
    TELEGRAM_KIND,
    TELEGRAM_PROVIDER,
)
from app.connectors.telegram.errors import (
    TelegramConfigurationError,
    TelegramWriteDefiniteError,
    TelegramWriteUncertainError,
)
from app.connectors.telegram.materialize import TelegramObjectMaterializer
from app.connectors.telegram.mtproto_account_store import TelegramMtprotoAccountStore
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoProviderReferenceInvalidError,
    TelegramMtprotoWriteDefiniteError,
    TelegramMtprotoWriteUncertainError,
)
from app.connectors.telegram.mtproto_transport import (
    TelegramMtprotoSentMessage,
    TelegramMtprotoTransport,
    TelethonMtprotoTransport,
)
from app.connectors.telegram.normalize import build_external_id as build_telegram_external_id
from app.connectors.telegram.normalize import provider_id_str
from app.connectors.telegram.transport import TelegramHttpTransport, TelegramTransport
from app.connectors.telegram.webhook_service import can_reply_from_rights, telegram_is_configured
from app.core.config import settings
from app.db.models import (
    ExternalActionAttempt,
    MattermostAccount,
    Object,
    TeamsAccount,
    TelegramAccount,
    TelegramMtprotoAccount,
    TelegramMtprotoChatSelection,
)
from app.db.session import SessionLocal
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.domain.task_lifecycle import TASK_STATUS_DELETED
from app.domain.telegram_mtproto_visibility import telegram_mtproto_active_object_predicate
from app.services.provenance import REJECTED_STATE
from app.tools.schemas import (
    MattermostSendRoute,
    SendMessageCanonicalInput,
    SendMessageInput,
    SendMessageOutput,
    TeamsSendRoute,
    TelegramMtprotoSendRoute,
    TelegramSendRoute,
    ToolError,
)

ATTEMPT_STARTED = "started"
ATTEMPT_SUCCEEDED = "succeeded"
ATTEMPT_FAILED_DEFINITE = "failed_definite"
ATTEMPT_UNCERTAIN = "uncertain"

SEND_MESSAGE_TOOL_NAME = "send_message"
PENDING_POST_ID_PREFIX = "secretary:"

_UNCERTAIN_DELIVERY_MESSAGE = "could not confirm message delivery; not retrying send"
_FAILED_DEFINITE_MESSAGE = "message send previously failed; create a new plan"
_KIND_REQUIRED = "chat_message"
_PROVIDER_MATTERMOST = "mattermost"
_PROVIDER_TELEGRAM = "telegram"
_PROVIDER_TEAMS = "teams"


def generate_operation_id() -> str:
    return uuid4().hex


def pending_post_id_from_operation_id(operation_id: str) -> str:
    compact = operation_id.replace("-", "").lower().strip()
    if len(compact) < 5 or len(compact) > 1024:
        raise ToolError("invalid operation_id")
    return f"{PENDING_POST_ID_PREFIX}{compact}"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize_body(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_provider_root_id(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class CommunicationExternalActionService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        *,
        transport: MattermostTransport | None = None,
        telegram_transport: TelegramTransport | None = None,
        telegram_mtproto_transport: TelegramMtprotoTransport | None = None,
        teams_transport: TeamsTransport | None = None,
        teams_oauth_service: TeamsOAuthService | None = None,
        attempt_session_factory=SessionLocal,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._transport = transport
        self._telegram_transport = telegram_transport
        self._telegram_mtproto_transport = telegram_mtproto_transport
        self._teams_transport = teams_transport
        self._teams_oauth_service = teams_oauth_service
        self._attempt_session_factory = attempt_session_factory
        self._materializer = MattermostObjectMaterializer(session)
        self._telegram_materializer = TelegramObjectMaterializer(session)
        self._teams_materializer = TeamsObjectMaterializer(session)

    def prepare_send_message(self, payload: SendMessageInput) -> SendMessageCanonicalInput:
        if payload.conversation_object_id is not None:
            mode = "compose"
            anchor_id = payload.conversation_object_id
        else:
            mode = "reply"
            if payload.reply_to_object_id is None:
                raise ToolError("exactly one of conversation_object_id or reply_to_object_id is required")
            anchor_id = payload.reply_to_object_id

        obj = self._load_anchor(anchor_id)
        if obj.provider == _PROVIDER_TELEGRAM:
            if self._is_mtproto_object(obj):
                return self._prepare_telegram_mtproto(payload, obj, mode)
            return self._prepare_telegram(payload, obj, mode)
        if obj.provider == _PROVIDER_TEAMS:
            return self._prepare_teams(payload, obj, mode)
        if obj.provider != _PROVIDER_MATTERMOST:
            raise ToolError("anchor provider is not mattermost")
        route = self._validated_route(obj)
        root_id = None
        if mode == "reply":
            root_id = route["root_id"]

        operation_id = generate_operation_id()
        return SendMessageCanonicalInput(
            provider="mattermost",
            mode=mode,
            anchor_object_id=obj.id,
            body=payload.body,
            operation_id=operation_id,
            route=MattermostSendRoute(
                account_id=route["account_id"],
                server_url=route["server_url"],
                channel_id=route["channel_id"],
                channel_type=route["channel_type"],
                channel_name=route["channel_name"],
                channel_display_name=route["channel_display_name"],
                source_post_id=route["post_id"],
                root_id=root_id,
                pending_post_id=pending_post_id_from_operation_id(operation_id),
            ),
        )

    def send_message(self, payload: SendMessageCanonicalInput) -> SendMessageOutput:
        if payload.provider == _PROVIDER_TELEGRAM:
            return self._send_telegram(payload)
        if payload.provider == _PROVIDER_TEAMS:
            return self._send_teams(payload)
        expected_pending = pending_post_id_from_operation_id(payload.operation_id)
        if payload.pending_post_id != expected_pending:
            raise ToolError("pending_post_id does not match operation_id")
        if payload.provider != _PROVIDER_MATTERMOST:
            raise ToolError("unsupported send_message provider")
        account = self._require_account(payload.account_id)
        self._assert_frozen_account(account, payload)
        attempt, claimed = self._claim_started(payload.operation_id)
        if not claimed:
            return self._resume_existing_attempt(payload, attempt)
        return self._write_once(payload, account)

    def _load_anchor(self, object_id: UUID) -> Object:
        obj = self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if obj is None:
            raise ToolError("object not found")
        if is_object_hidden_from_active_reads(obj):
            raise ToolError("object is deleted")
        if obj.state == REJECTED_STATE:
            raise ToolError("object is rejected")
        if obj.kind != _KIND_REQUIRED:
            raise ToolError("anchor must be a chat_message")
        return obj

    @staticmethod
    def _is_mtproto_object(obj: Object) -> bool:
        metadata = obj.metadata_ or {}
        return (
            obj.provider == TELEGRAM_PROVIDER
            and obj.kind == TELEGRAM_KIND
            and metadata.get("transport") == "mtproto"
        )

    def _validated_route(self, obj: Object) -> dict[str, Any]:
        meta = dict(obj.metadata_ or {})
        raw_account_id = meta.get("account_id")
        try:
            account_id = UUID(str(raw_account_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ToolError("malformed Mattermost account_id") from exc

        post_id = str(meta.get("post_id") or "").strip()
        channel_id = str(meta.get("channel_id") or "").strip()
        raw_server = str(meta.get("server_url") or "").strip()
        if not post_id or not channel_id or not raw_server:
            raise ToolError("malformed Mattermost routing metadata")

        try:
            normalized_server = normalize_server_url(raw_server)
            allowed = parse_allowed_base_urls(settings.mattermost_allowed_base_urls)
            validate_server_url_allowlist(normalized_server, allowed)
        except MattermostSecurityError as exc:
            raise ToolError(exc.message) from exc

        account = self._require_account(account_id)
        if account.server_url != normalized_server:
            raise ToolError("Mattermost server_url does not match the connected account")

        expected_external_id = build_external_id(normalized_server, post_id)
        if obj.external_id != expected_external_id:
            raise ToolError("Mattermost external_id does not match post routing")

        raw_root = str(meta.get("root_id") or "").strip() or None
        return {
            "account_id": account.id,
            "server_url": account.server_url,
            "channel_id": channel_id,
            "post_id": post_id,
            "root_id": raw_root,
            "channel_type": str(meta.get("channel_type") or "").strip() or None,
            "channel_name": str(meta.get("channel_name") or "").strip() or None,
            "channel_display_name": str(meta.get("channel_display_name") or "").strip() or None,
        }

    def _require_account(self, account_id: UUID) -> MattermostAccount:
        account = self._account_store().get_by_id_for_user(account_id, self._user_id)
        if account is None:
            raise ToolError("Mattermost account is not connected")
        return account

    def _assert_frozen_account(self, account: MattermostAccount, payload: SendMessageCanonicalInput) -> None:
        if account.id != payload.account_id or account.user_id != self._user_id:
            raise ToolError("Mattermost account is not connected")
        try:
            allowed = parse_allowed_base_urls(settings.mattermost_allowed_base_urls)
            validate_server_url_allowlist(account.server_url, allowed)
        except MattermostSecurityError as exc:
            raise ToolError(exc.message) from exc
        if account.server_url != payload.server_url:
            raise ToolError("Mattermost server_url does not match the connected account")

    def _write_once(
        self,
        payload: SendMessageCanonicalInput,
        account: MattermostAccount,
    ) -> SendMessageOutput:
        owns_transport = False
        transport = self._transport
        if transport is None:
            try:
                transport = self._open_http_transport(account)
            except (ToolError, MattermostConfigurationError) as exc:
                return self._definite_failure(payload, exc.message)
            owns_transport = True
        try:
            try:
                created = transport.create_post(
                    channel_id=payload.channel_id,
                    message=payload.body,
                    pending_post_id=payload.pending_post_id,
                    root_id=payload.root_id,
                )
            except MattermostSecurityError as exc:
                return self._definite_failure(payload, exc.message)
            except MattermostWriteDefiniteError as exc:
                return self._definite_failure(payload, exc.message)
            except MattermostWriteUncertainError as exc:
                return self._after_uncertain_write(payload, exc.message)
        finally:
            if owns_transport:
                transport.close()

        mismatch = self._success_mismatch(payload, account, created)
        if mismatch is not None:
            return self._after_uncertain_write(payload, mismatch)

        provider_id = str(created.get("id") or "").strip() or None
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_SUCCEEDED,
            provider_external_id=provider_id,
            delivery_status="sent",
        )
        obj = self._materialize_created(payload, account, created)
        return self._output(
            payload,
            provider_id,
            object_id=obj.id if obj is not None else None,
            delivery_status="sent",
            changed=True,
        )

    def _resume_existing_attempt(
        self,
        payload: SendMessageCanonicalInput,
        attempt: ExternalActionAttempt,
    ) -> SendMessageOutput:
        if attempt.state == ATTEMPT_SUCCEEDED:
            return self._output(
                payload,
                attempt.provider_external_id,
                object_id=self._object_id_from_attempt(payload, attempt),
                delivery_status="already_sent",
                changed=False,
            )
        if attempt.state == ATTEMPT_FAILED_DEFINITE:
            raise ToolError(_FAILED_DEFINITE_MESSAGE)
        if payload.provider in {_PROVIDER_TELEGRAM, _PROVIDER_TEAMS}:
            raise ToolError(_UNCERTAIN_DELIVERY_MESSAGE)
        matched = self._reconcile_local(payload)
        if matched is not None:
            provider_id = str((matched.metadata_ or {}).get("post_id") or "").strip() or None
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_SUCCEEDED,
                provider_external_id=provider_id,
                delivery_status="already_sent",
            )
            return self._output(
                payload,
                provider_id,
                object_id=matched.id,
                delivery_status="already_sent",
                changed=False,
            )
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_UNCERTAIN,
            error=_UNCERTAIN_DELIVERY_MESSAGE,
        )
        raise ToolError(_UNCERTAIN_DELIVERY_MESSAGE)

    def _after_uncertain_write(self, payload: SendMessageCanonicalInput, error: str) -> SendMessageOutput:
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_UNCERTAIN,
            error=error or _UNCERTAIN_DELIVERY_MESSAGE,
        )
        if payload.provider in {_PROVIDER_TELEGRAM, _PROVIDER_TEAMS}:
            raise ToolError(_UNCERTAIN_DELIVERY_MESSAGE)
        matched = self._reconcile_local(payload)
        if matched is not None:
            provider_id = str((matched.metadata_ or {}).get("post_id") or "").strip() or None
            self._persist_attempt_state(
                payload.operation_id,
                ATTEMPT_SUCCEEDED,
                provider_external_id=provider_id,
                delivery_status="already_sent",
            )
            return self._output(
                payload,
                provider_id,
                object_id=matched.id,
                delivery_status="already_sent",
                changed=False,
            )
        raise ToolError(_UNCERTAIN_DELIVERY_MESSAGE)

    def _definite_failure(self, payload: SendMessageCanonicalInput, error: str) -> SendMessageOutput:
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_FAILED_DEFINITE,
            error=error,
        )
        raise ToolError(error or "Mattermost write rejected")

    def _prepare_telegram_mtproto(
        self,
        payload: SendMessageInput,
        obj: Object,
        mode: str,
    ) -> SendMessageCanonicalInput:
        if len(payload.body) > MAX_TELEGRAM_MESSAGE_BODY_CHARS:
            raise ToolError("body exceeds Telegram maximum length")
        route = self._validated_telegram_mtproto_route(obj, mode)
        return SendMessageCanonicalInput(
            provider="telegram",
            mode=mode,
            anchor_object_id=obj.id,
            body=payload.body,
            operation_id=generate_operation_id(),
            route=TelegramMtprotoSendRoute(
                account_id=route["account_id"],
                peer_id=route["peer_id"],
                source_message_id=route["source_message_id"],
                reply_to_message_id=(
                    route["source_message_id"] if mode == "reply" else None
                ),
                peer_title=route["peer_title"],
            ),
        )

    def _validated_telegram_mtproto_route(self, obj: Object, mode: str) -> dict[str, Any]:
        metadata = dict(obj.metadata_ or {})
        try:
            account_id = UUID(str(metadata.get("account_id")))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ToolError("malformed Telegram MTProto account_id") from exc
        peer_id = self._parse_signed_peer_id(metadata.get("peer_id"))
        raw_message_id = metadata.get("message_id")
        source_message_id = None
        if raw_message_id is not None:
            source_message_id = self._parse_positive_message_id(raw_message_id)
        if mode == "reply" and source_message_id is None:
            raise ToolError("malformed Telegram MTProto message_id")
        if self._session.scalar(
            select(Object.id).where(
                Object.id == obj.id,
                Object.user_id == self._user_id,
                telegram_mtproto_active_object_predicate(),
            )
        ) is None:
            raise ToolError("Telegram MTProto peer is not in active scope")

        store = self._mtproto_store()
        account = store.get_by_id_for_user(account_id, self._user_id)
        if account is None:
            raise ToolError("Telegram MTProto account is not connected")
        selection = store.get_selection(account.id, peer_id)
        if selection is None or not selection.scope_active:
            raise ToolError("Telegram MTProto peer is not in active scope")
        try:
            reference = store.decrypt_reference(selection)
        except (TelegramMtprotoProviderReferenceInvalidError, ValueError) as exc:
            raise ToolError("Telegram MTProto peer reference is invalid") from exc
        except Exception as exc:
            raise ToolError("Telegram MTProto peer reference is invalid") from exc
        if not reference:
            raise ToolError("Telegram MTProto peer reference is invalid")
        if source_message_id is not None:
            expected_external_id = f"mtproto|{account.id}|{peer_id}|{source_message_id}"
            if obj.external_id != expected_external_id:
                raise ToolError("Telegram MTProto message routing does not match")
        return {
            "account_id": account.id,
            "peer_id": peer_id,
            "source_message_id": source_message_id,
            "peer_title": selection.title,
        }

    @staticmethod
    def _parse_signed_peer_id(value: object) -> int:
        if isinstance(value, bool):
            raise ToolError("malformed Telegram MTProto peer_id")
        try:
            peer_id = int(str(value))
        except (TypeError, ValueError) as exc:
            raise ToolError("malformed Telegram MTProto peer_id") from exc
        if peer_id == 0 or peer_id < -(2**63) or peer_id > 2**63 - 1:
            raise ToolError("malformed Telegram MTProto peer_id")
        return peer_id

    @staticmethod
    def _parse_positive_message_id(value: object) -> int:
        if isinstance(value, bool):
            raise ToolError("malformed Telegram MTProto message_id")
        try:
            message_id = int(str(value))
        except (TypeError, ValueError) as exc:
            raise ToolError("malformed Telegram MTProto message_id") from exc
        if message_id <= 0:
            raise ToolError("malformed Telegram MTProto message_id")
        return message_id

    def _mtproto_store(self) -> TelegramMtprotoAccountStore:
        if not settings.secretary_credential_key.strip():
            raise ToolError("Telegram MTProto credentials are not configured")
        try:
            encryption = CredentialEncryption(settings.secretary_credential_key)
        except Exception as exc:
            raise ToolError("Telegram MTProto credentials are not configured") from exc
        return TelegramMtprotoAccountStore(self._session, encryption)

    def _prepare_telegram(
        self,
        payload: SendMessageInput,
        obj: Object,
        mode: str,
    ) -> SendMessageCanonicalInput:
        if len(payload.body) > MAX_TELEGRAM_MESSAGE_BODY_CHARS:
            raise ToolError("body exceeds Telegram maximum length")
        route = self._validated_telegram_route(obj)
        self._require_recent_inbound(
            account_id=route["account_id"],
            business_connection_id=route["business_connection_id"],
            chat_id=route["chat_id"],
        )
        reply_to_message_id = route["source_message_id"] if mode == "reply" else None
        return SendMessageCanonicalInput(
            provider="telegram",
            mode=mode,
            anchor_object_id=obj.id,
            body=payload.body,
            operation_id=generate_operation_id(),
            route=TelegramSendRoute(
                account_id=route["account_id"],
                business_connection_id=route["business_connection_id"],
                business_user_id=route["business_user_id"],
                chat_id=route["chat_id"],
                source_message_id=route["source_message_id"],
                reply_to_message_id=reply_to_message_id,
                chat_display_name=route["chat_display_name"],
                chat_username=route["chat_username"],
            ),
        )

    def _validated_telegram_route(self, obj: Object) -> dict[str, Any]:
        meta = dict(obj.metadata_ or {})
        raw_account_id = meta.get("account_id")
        try:
            account_id = UUID(str(raw_account_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ToolError("malformed Telegram account_id") from exc

        business_connection_id = provider_id_str(meta.get("business_connection_id"))
        business_user_id = provider_id_str(meta.get("business_user_id"))
        chat_id = provider_id_str(meta.get("chat_id"))
        source_message_id = provider_id_str(meta.get("message_id"))
        if not business_connection_id or not business_user_id or not chat_id or not source_message_id:
            raise ToolError("malformed Telegram routing metadata")
        if not str(chat_id).lstrip("-").isdigit() or not str(source_message_id).isdigit():
            raise ToolError("malformed Telegram provider IDs")

        account = self._require_telegram_account(account_id)
        if not account.business_connection_enabled:
            raise ToolError("Telegram business connection is not active")
        if provider_id_str(account.business_connection_id) != business_connection_id:
            raise ToolError("Telegram business connection does not match")
        if str(account.telegram_user_id) != business_user_id:
            raise ToolError("Telegram account identity does not match")
        if not can_reply_from_rights(account.business_rights):
            raise ToolError("Telegram reply permission is required")

        expected_external_id = build_telegram_external_id(
            business_connection_id,
            chat_id,
            source_message_id,
        )
        if obj.external_id != expected_external_id:
            raise ToolError("Telegram external_id does not match message routing")

        return {
            "account_id": account.id,
            "business_connection_id": business_connection_id,
            "business_user_id": str(account.telegram_user_id),
            "chat_id": chat_id,
            "source_message_id": source_message_id,
            "chat_display_name": str(meta.get("chat_display_name") or "").strip() or None,
            "chat_username": str(meta.get("chat_username") or "").strip() or None,
        }

    def _require_telegram_account(self, account_id: UUID) -> TelegramAccount:
        account = TelegramAccountStore(self._session).get_by_id_for_user(account_id, self._user_id)
        if account is None:
            raise ToolError("Telegram account is not connected")
        return account

    def _require_recent_inbound(
        self,
        *,
        account_id: UUID,
        business_connection_id: str,
        chat_id: str,
    ) -> None:
        cutoff = _utcnow() - timedelta(seconds=RECENT_INBOUND_WINDOW_SECONDS)
        exists = self._session.scalar(
            select(Object.id).where(
                Object.user_id == self._user_id,
                Object.provider == TELEGRAM_PROVIDER,
                Object.kind == TELEGRAM_KIND,
                Object.deleted_at.is_(None),
                or_(Object.status.is_(None), Object.status != TASK_STATUS_DELETED),
                Object.metadata_["direction"].as_string() == DIRECTION_INBOUND,
                Object.metadata_["account_id"].as_string() == str(account_id),
                Object.metadata_["business_connection_id"].as_string() == business_connection_id,
                Object.metadata_["chat_id"].as_string() == chat_id,
                Object.occurred_at.is_not(None),
                Object.occurred_at >= cutoff,
            ).limit(1)
        )
        if exists is None:
            raise ToolError("Telegram chat is not eligible for outbound send")

    def _assert_frozen_telegram_account(
        self,
        account: TelegramAccount,
        route: TelegramSendRoute,
    ) -> None:
        if account.id != route.account_id or account.user_id != self._user_id:
            raise ToolError("Telegram account is not connected")
        if not account.business_connection_enabled:
            raise ToolError("Telegram business connection is not active")
        if provider_id_str(account.business_connection_id) != route.business_connection_id:
            raise ToolError("Telegram business connection does not match")
        if str(account.telegram_user_id) != route.business_user_id:
            raise ToolError("Telegram account identity does not match")
        if not can_reply_from_rights(account.business_rights):
            raise ToolError("Telegram reply permission is required")

    def _send_telegram(self, payload: SendMessageCanonicalInput) -> SendMessageOutput:
        if payload.provider != _PROVIDER_TELEGRAM:
            raise ToolError("unsupported send_message provider")
        if isinstance(payload.route, TelegramMtprotoSendRoute):
            return self._send_telegram_mtproto(payload)
        attempt, claimed = self._claim_started(payload.operation_id)
        if not claimed:
            return self._resume_existing_attempt(payload, attempt)
        try:
            route = payload.telegram_route
            account = self._require_telegram_account(route.account_id)
            self._assert_frozen_telegram_account(account, route)
            self._require_recent_inbound(
                account_id=route.account_id,
                business_connection_id=route.business_connection_id,
                chat_id=route.chat_id,
            )
        except ToolError as exc:
            return self._definite_failure(payload, exc.message)
        return self._write_telegram_once(payload, account)

    def _send_telegram_mtproto(
        self, payload: SendMessageCanonicalInput
    ) -> SendMessageOutput:
        attempt, claimed = self._claim_started(payload.operation_id)
        if not claimed:
            return self._resume_existing_attempt(payload, attempt)
        route = payload.telegram_mtproto_route
        try:
            store = self._mtproto_store()
            account = store.get_by_id_for_user(route.account_id, self._user_id)
            if account is None:
                return self._definite_failure(payload, "Telegram MTProto account is not connected")
            selection = store.get_selection(account.id, route.peer_id)
            if selection is None or not selection.scope_active:
                return self._definite_failure(payload, "Telegram MTProto peer is not in active scope")
            reference = store.decrypt_reference(selection)
            session = store.decrypt_session(account)
            if not reference or not session:
                return self._definite_failure(payload, "Telegram MTProto route is unavailable")
        except (ToolError, TelegramMtprotoProviderReferenceInvalidError, ValueError) as exc:
            return self._definite_failure(payload, str(exc) or "Telegram MTProto route is unavailable")
        except Exception:  # noqa: BLE001 - durable route errors fail closed
            return self._definite_failure(payload, "Telegram MTProto route is unavailable")

        transport = self._telegram_mtproto_transport
        if transport is None:
            if settings.telegram_api_id <= 0 or not settings.telegram_api_hash.strip():
                return self._definite_failure(payload, "Telegram MTProto is not configured")
            transport = TelethonMtprotoTransport(
                settings.telegram_api_id, settings.telegram_api_hash.strip()
            )
        try:
            sent = transport.send_message(
                session,
                reference,
                peer_id=route.peer_id,
                text=payload.body,
                reply_to_message_id=route.reply_to_message_id,
            )
            if inspect.isawaitable(sent):
                sent = asyncio.run(sent)
        except TelegramMtprotoWriteDefiniteError as exc:
            return self._definite_failure(payload, exc.message)
        except TelegramMtprotoWriteUncertainError as exc:
            return self._after_uncertain_write(payload, exc.message)
        except Exception:  # noqa: BLE001 - provider outcome is ambiguous after send
            return self._after_uncertain_write(payload, _UNCERTAIN_DELIVERY_MESSAGE)

        normalized = self._normalize_mtproto_sent(sent, payload, route)
        if normalized is None:
            return self._after_uncertain_write(payload, _UNCERTAIN_DELIVERY_MESSAGE)
        provider_id = str(normalized["message_id"])
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_SUCCEEDED,
            provider_external_id=provider_id,
            delivery_status="sent",
        )
        obj = self._materialize_mtproto_created(payload, account, selection, normalized)
        return self._output(
            payload,
            provider_id,
            object_id=obj.id if obj is not None else None,
            delivery_status="sent",
            changed=True,
        )

    def _normalize_mtproto_sent(
        self,
        sent: object,
        payload: SendMessageCanonicalInput,
        route: TelegramMtprotoSendRoute,
    ) -> dict[str, Any] | None:
        if isinstance(sent, TelegramMtprotoSentMessage):
            data = {
                "message_id": sent.message_id,
                "peer_id": sent.peer_id,
                "text": sent.text,
                "occurred_at": sent.occurred_at,
                "reply_to_message_id": sent.reply_to_message_id,
                "sender_peer_id": sent.sender_peer_id,
            }
        elif isinstance(sent, dict):
            data = dict(sent)
        else:
            return None
        try:
            message_id = self._parse_positive_message_id(data.get("message_id"))
            peer_id = self._parse_signed_peer_id(data.get("peer_id"))
        except ToolError:
            return None
        if peer_id != route.peer_id or data.get("text") != payload.body:
            return None
        returned_reply = data.get("reply_to_message_id")
        if returned_reply is not None:
            try:
                returned_reply = self._parse_positive_message_id(returned_reply)
            except ToolError:
                return None
        if payload.mode == "compose" and returned_reply is not None:
            return None
        if payload.mode == "reply" and returned_reply != route.reply_to_message_id:
            return None
        data["message_id"] = message_id
        data["peer_id"] = peer_id
        return data

    def _materialize_mtproto_created(
        self,
        payload: SendMessageCanonicalInput,
        account: TelegramMtprotoAccount,
        selection: TelegramMtprotoChatSelection,
        sent: dict[str, Any],
    ) -> Object | None:
        body = str(sent["text"])
        title = f"{selection.title}: {body.splitlines()[0].strip()}"[:240]
        normalized = {
            "provider": TELEGRAM_PROVIDER,
            "kind": TELEGRAM_KIND,
            "origin": "source",
            "state": "observed",
            "external_id": f"mtproto|{account.id}|{selection.peer_id}|{sent['message_id']}",
            "title": title,
            "body": body,
            "occurred_at": sent.get("occurred_at") or _utcnow(),
            "metadata": {
                "transport": "mtproto",
                "account_id": str(account.id),
                "peer_id": selection.peer_id,
                "peer_kind": selection.peer_kind,
                "message_id": sent["message_id"],
                "reply_to_message_id": sent.get("reply_to_message_id"),
                "peer_title": selection.title,
                "direction": "outbound",
                "sender_peer_id": sent.get("sender_peer_id"),
            },
        }
        return self._telegram_materializer.upsert_mtproto_message(
            user_id=self._user_id,
            normalized=normalized,
            skip_hidden=False,
        ).obj

    def _write_telegram_once(
        self,
        payload: SendMessageCanonicalInput,
        account: TelegramAccount,
    ) -> SendMessageOutput:
        route = payload.telegram_route
        owns_transport = False
        transport = self._telegram_transport
        if transport is None:
            try:
                transport = self._open_telegram_http_transport()
            except (ToolError, TelegramConfigurationError) as exc:
                return self._definite_failure(payload, exc.message)
            owns_transport = True
        try:
            try:
                created = transport.send_message(
                    business_connection_id=route.business_connection_id,
                    chat_id=route.chat_id,
                    text=payload.body,
                    reply_to_message_id=route.reply_to_message_id,
                )
            except TelegramWriteDefiniteError as exc:
                return self._definite_failure(payload, exc.message)
            except TelegramWriteUncertainError as exc:
                return self._after_uncertain_write(payload, exc.message)
        finally:
            if owns_transport:
                transport.close()

        mismatch = self._telegram_success_mismatch(payload, created)
        if mismatch is not None:
            return self._after_uncertain_write(payload, mismatch)

        provider_id = provider_id_str(created.get("message_id"))
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_SUCCEEDED,
            provider_external_id=provider_id,
            delivery_status="sent",
        )
        obj = self._materialize_telegram_created(payload, account, created)
        return self._output(
            payload,
            provider_id,
            object_id=obj.id if obj is not None else None,
            delivery_status="sent",
            changed=True,
        )

    def _telegram_success_mismatch(
        self,
        payload: SendMessageCanonicalInput,
        created: dict[str, Any],
    ) -> str | None:
        if not isinstance(created, dict):
            return _UNCERTAIN_DELIVERY_MESSAGE
        route = payload.telegram_route
        message_id = provider_id_str(created.get("message_id"))
        if not message_id:
            return _UNCERTAIN_DELIVERY_MESSAGE
        returned_connection = provider_id_str(created.get("business_connection_id"))
        if returned_connection != route.business_connection_id:
            return _UNCERTAIN_DELIVERY_MESSAGE
        chat = created.get("chat") if isinstance(created.get("chat"), dict) else None
        returned_chat = provider_id_str(chat.get("id") if chat else None)
        if returned_chat != route.chat_id:
            return _UNCERTAIN_DELIVERY_MESSAGE
        returned_text = created.get("text")
        if not isinstance(returned_text, str) or _normalize_body(returned_text) != payload.body:
            return _UNCERTAIN_DELIVERY_MESSAGE
        sender_bot = created.get("sender_business_bot")
        if isinstance(sender_bot, dict):
            returned_username = str(sender_bot.get("username") or "").strip().lstrip("@").lower()
            expected_username = settings.telegram_bot_username.strip().lstrip("@").lower()
            if expected_username and returned_username and returned_username != expected_username:
                return _UNCERTAIN_DELIVERY_MESSAGE
        reply_to = created.get("reply_to_message") if isinstance(created.get("reply_to_message"), dict) else None
        returned_reply = provider_id_str(reply_to.get("message_id") if reply_to else None)
        if payload.mode == "compose" and returned_reply is not None:
            return _UNCERTAIN_DELIVERY_MESSAGE
        if payload.mode == "reply" and returned_reply != route.reply_to_message_id:
            return _UNCERTAIN_DELIVERY_MESSAGE
        return None

    def _materialize_telegram_created(
        self,
        payload: SendMessageCanonicalInput,
        account: TelegramAccount,
        created: dict[str, Any],
    ) -> Object | None:
        route = payload.telegram_route
        message = dict(created)
        message.setdefault("business_connection_id", route.business_connection_id)
        from_user = message.get("from") if isinstance(message.get("from"), dict) else None
        if from_user is None:
            message["from"] = {
                "id": account.telegram_user_id,
                "username": account.telegram_username,
                "first_name": account.display_name or "",
            }
        result = self._telegram_materializer.upsert_business_message(
            user_id=self._user_id,
            account_id=account.id,
            business_connection_id=route.business_connection_id,
            business_user_id=str(account.telegram_user_id),
            message=message,
            skip_hidden=False,
        )
        return result.obj

    def _open_telegram_http_transport(self) -> TelegramHttpTransport:
        if not telegram_is_configured():
            raise ToolError("telegram is not configured")
        return TelegramHttpTransport(settings.telegram_bot_token)

    def _prepare_teams(
        self,
        payload: SendMessageInput,
        obj: Object,
        mode: str,
    ) -> SendMessageCanonicalInput:
        if len(payload.body) > MAX_TEAMS_MESSAGE_BODY_CHARS:
            raise ToolError("body exceeds Teams maximum length")
        route = self._validated_teams_route(obj)
        quoted_message_id = route["source_message_id"] if mode == "reply" else None
        return SendMessageCanonicalInput(
            provider="teams",
            mode=mode,
            anchor_object_id=obj.id,
            body=payload.body,
            operation_id=generate_operation_id(),
            route=TeamsSendRoute(
                account_id=route["account_id"],
                tenant_id=route["tenant_id"],
                teams_user_id=route["teams_user_id"],
                chat_id=route["chat_id"],
                chat_type=route["chat_type"],
                source_message_id=route["source_message_id"],
                quoted_message_id=quoted_message_id,
                chat_display_title=route["chat_display_title"],
            ),
        )

    def _validated_teams_route(self, obj: Object) -> dict[str, Any]:
        meta = dict(obj.metadata_ or {})
        raw_account_id = meta.get("account_id")
        try:
            account_id = UUID(str(raw_account_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ToolError("malformed Teams account_id") from exc

        tenant_id = teams_provider_id_str(meta.get("tenant_id"))
        teams_user_id = teams_provider_id_str(meta.get("teams_user_id"))
        chat_id = teams_provider_id_str(meta.get("chat_id"))
        chat_type = teams_provider_id_str(meta.get("chat_type"))
        source_message_id = teams_provider_id_str(meta.get("message_id"))
        if not tenant_id or not teams_user_id or not chat_id or not chat_type or not source_message_id:
            raise ToolError("malformed Teams routing metadata")
        try:
            tenant_id = canonicalize_microsoft_guid(tenant_id, claim="tenant id")
            teams_user_id = canonicalize_microsoft_guid(teams_user_id, claim="user id")
        except TeamsOAuthError as exc:
            raise ToolError("malformed Teams routing metadata") from exc
        if chat_type not in ACCEPTED_CHAT_TYPES:
            raise ToolError("unsupported Teams chat type")

        account = self._require_teams_account(account_id)
        if account.tenant_id != tenant_id:
            raise ToolError("Teams tenant does not match")
        if account.microsoft_user_id != teams_user_id:
            raise ToolError("Teams account identity does not match")

        expected_external_id = build_teams_external_id(
            tenant_id,
            teams_user_id,
            chat_id,
            source_message_id,
        )
        if obj.external_id != expected_external_id:
            raise ToolError("Teams external_id does not match message routing")

        return {
            "account_id": account.id,
            "tenant_id": tenant_id,
            "teams_user_id": teams_user_id,
            "chat_id": chat_id,
            "chat_type": chat_type,
            "source_message_id": source_message_id,
            "chat_display_title": str(meta.get("chat_display_title") or "").strip() or None,
        }

    def _require_teams_account(self, account_id: UUID) -> TeamsAccount:
        if not settings.secretary_credential_key:
            raise ToolError("credentials are not configured")
        account = TeamsAccountStore(
            self._session,
            TeamsAccountStore.build_encryption(settings.secretary_credential_key),
        ).get_by_id_for_user(account_id, self._user_id)
        if account is None:
            raise ToolError("Teams account is not connected")
        return account

    def _assert_frozen_teams_account(self, account: TeamsAccount, route: TeamsSendRoute) -> None:
        if account.id != route.account_id or account.user_id != self._user_id:
            raise ToolError("Teams account is not connected")
        if account.tenant_id != route.tenant_id:
            raise ToolError("Teams tenant does not match")
        if account.microsoft_user_id != route.teams_user_id:
            raise ToolError("Teams account identity does not match")
        if route.chat_type not in ACCEPTED_CHAT_TYPES:
            raise ToolError("unsupported Teams chat type")

    def _send_teams(self, payload: SendMessageCanonicalInput) -> SendMessageOutput:
        if payload.provider != _PROVIDER_TEAMS:
            raise ToolError("unsupported send_message provider")
        attempt, claimed = self._claim_started(payload.operation_id)
        if not claimed:
            return self._resume_existing_attempt(payload, attempt)
        try:
            route = payload.teams_route
            account = self._require_teams_account(route.account_id)
            self._assert_frozen_teams_account(account, route)
            if account.auth_status == AUTH_STATUS_RECONNECT_REQUIRED:
                raise ToolError("Microsoft Teams reconnect is required")
        except ToolError as exc:
            return self._definite_failure(payload, exc.message)
        return self._write_teams_once(payload, account)

    def _write_teams_once(
        self,
        payload: SendMessageCanonicalInput,
        account: TeamsAccount,
    ) -> SendMessageOutput:
        route = payload.teams_route
        owns_transport = False
        transport = self._teams_transport
        if transport is None:
            try:
                transport = self._open_teams_http_transport(account)
            except (ToolError, TeamsConfigurationError, TeamsOAuthError) as exc:
                return self._definite_failure(payload, exc.message)
            owns_transport = True
        try:
            try:
                if payload.mode == "reply":
                    created = transport.reply_with_quote(
                        chat_id=route.chat_id,
                        quoted_message_id=route.quoted_message_id or route.source_message_id,
                        body=payload.body,
                    )
                else:
                    created = transport.send_message(chat_id=route.chat_id, body=payload.body)
            except TeamsWriteDefiniteError as exc:
                return self._definite_failure(payload, exc.message)
            except TeamsWriteUncertainError as exc:
                return self._after_uncertain_write(payload, exc.message)
        finally:
            if owns_transport:
                transport.close()

        mismatch = self._teams_success_mismatch(payload, created)
        if mismatch is not None:
            return self._after_uncertain_write(payload, mismatch)

        provider_id = teams_provider_id_str(created.get("id"))
        self._persist_attempt_state(
            payload.operation_id,
            ATTEMPT_SUCCEEDED,
            provider_external_id=provider_id,
            delivery_status="sent",
        )
        obj = self._materialize_teams_created(payload, account, created)
        return self._output(
            payload,
            provider_id,
            object_id=obj.id if obj is not None else None,
            delivery_status="sent",
            changed=True,
        )

    def _teams_success_mismatch(
        self,
        payload: SendMessageCanonicalInput,
        created: dict[str, Any],
    ) -> str | None:
        if not isinstance(created, dict):
            return _UNCERTAIN_DELIVERY_MESSAGE
        route = payload.teams_route
        message_id = teams_provider_id_str(created.get("id"))
        if not message_id:
            return _UNCERTAIN_DELIVERY_MESSAGE
        returned_chat = teams_provider_id_str(created.get("chatId"))
        if returned_chat and returned_chat != route.chat_id:
            return _UNCERTAIN_DELIVERY_MESSAGE
        body = created.get("body") if isinstance(created.get("body"), dict) else None
        if body is not None:
            returned_text = teams_body_to_plain_text(
                content_type=teams_provider_id_str(body.get("contentType")),
                content=str(body.get("content") or ""),
            )
            if _normalize_body(returned_text) != payload.body:
                return _UNCERTAIN_DELIVERY_MESSAGE
        sender_id, _sender_name = sender_from_message(created)
        if sender_id and try_canonical_microsoft_guid(sender_id) != route.teams_user_id:
            return _UNCERTAIN_DELIVERY_MESSAGE
        returned_reply = teams_provider_id_str(created.get("replyToId"))
        referenced_ids = extract_message_reference_ids(created)
        if payload.mode == "compose" and (returned_reply is not None or referenced_ids):
            return _UNCERTAIN_DELIVERY_MESSAGE
        if payload.mode == "reply":
            frozen_quoted = teams_provider_id_str(route.quoted_message_id)
            if returned_reply and returned_reply != frozen_quoted:
                return _UNCERTAIN_DELIVERY_MESSAGE
            if any(item != frozen_quoted for item in referenced_ids):
                return _UNCERTAIN_DELIVERY_MESSAGE
        return None

    def _materialize_teams_created(
        self,
        payload: SendMessageCanonicalInput,
        account: TeamsAccount,
        created: dict[str, Any],
    ) -> Object | None:
        route = payload.teams_route
        message = dict(created)
        message.setdefault("chatId", route.chat_id)
        frozen_quoted = route.quoted_message_id if payload.mode == "reply" else None
        result = self._teams_materializer.upsert_message(
            user_id=self._user_id,
            account_id=account.id,
            tenant_id=account.tenant_id,
            microsoft_user_id=account.microsoft_user_id,
            chat_id=route.chat_id,
            chat_type=route.chat_type,
            chat_display_title=route.chat_display_title,
            message=message,
            skip_hidden=False,
            frozen_quoted_message_id=frozen_quoted,
        )
        return result.obj

    def _open_teams_http_transport(self, account: TeamsAccount) -> TeamsHttpTransport:
        if not settings.secretary_credential_key:
            raise ToolError("credentials are not configured")
        store = TeamsAccountStore(
            self._session,
            TeamsAccountStore.build_encryption(settings.secretary_credential_key),
        )
        token = TeamsTokenService(
            self._session,
            store,
            self._teams_oauth_service,
        ).acquire_access_token(account)
        return TeamsHttpTransport(token)

    def _reconcile_local(self, payload: SendMessageCanonicalInput) -> Object | None:
        return self._materializer.find_by_pending_post_id(
            user_id=self._user_id,
            account_id=payload.account_id,
            channel_id=payload.channel_id,
            pending_post_id=payload.pending_post_id,
        )

    def _success_mismatch(
        self,
        payload: SendMessageCanonicalInput,
        account: MattermostAccount,
        created: dict[str, Any],
    ) -> str | None:
        if not isinstance(created, dict):
            return _UNCERTAIN_DELIVERY_MESSAGE
        post_id = str(created.get("id") or "").strip()
        if not post_id:
            return _UNCERTAIN_DELIVERY_MESSAGE
        returned_channel = str(created.get("channel_id") or "").strip()
        if returned_channel != payload.channel_id:
            return _UNCERTAIN_DELIVERY_MESSAGE
        returned_message = created.get("message")
        if not isinstance(returned_message, str) or _normalize_body(returned_message) != payload.body:
            return _UNCERTAIN_DELIVERY_MESSAGE
        returned_user = str(created.get("user_id") or "").strip()
        if returned_user and returned_user != account.remote_user_id:
            return _UNCERTAIN_DELIVERY_MESSAGE
        returned_pending = str(created.get("pending_post_id") or "").strip()
        if returned_pending and returned_pending != payload.pending_post_id:
            return _UNCERTAIN_DELIVERY_MESSAGE
        returned_root = _normalize_provider_root_id(created.get("root_id"))
        if returned_root != payload.root_id:
            return _UNCERTAIN_DELIVERY_MESSAGE
        return None

    def _materialize_created(
        self,
        payload: SendMessageCanonicalInput,
        account: MattermostAccount,
        created: dict[str, Any],
    ) -> Object | None:
        channel = MattermostChannelContext(
            channel_id=payload.channel_id,
            channel_name=payload.channel_name,
            channel_display_name=payload.channel_display_name,
            channel_type=payload.channel_type,
            team_id=None,
            team_name=None,
            team_display_name=None,
        )
        author = {
            "id": account.remote_user_id,
            "username": account.username,
            "display_name": account.display_name,
        }
        result = self._materializer.upsert_post(
            user_id=self._user_id,
            normalized_server_url=payload.server_url,
            account_id=account.id,
            channel=channel,
            post=created,
            author=author,
            skip_hidden=False,
        )
        return result.obj

    def _object_id_from_attempt(
        self,
        payload: SendMessageCanonicalInput,
        attempt: ExternalActionAttempt,
    ) -> UUID | None:
        provider_id = str(attempt.provider_external_id or "").strip()
        if payload.provider == _PROVIDER_TELEGRAM:
            if not provider_id:
                return None
            route = payload.route
            if isinstance(route, TelegramMtprotoSendRoute):
                existing = self._telegram_materializer.find_existing(
                    self._user_id,
                    f"mtproto|{route.account_id}|{route.peer_id}|{provider_id}",
                )
                return existing.id if existing is not None else None
            existing = self._telegram_materializer.find_existing(
                self._user_id,
                build_telegram_external_id(route.business_connection_id, route.chat_id, provider_id),
            )
            return existing.id if existing is not None else None
        if payload.provider == _PROVIDER_TEAMS:
            if not provider_id:
                return None
            route = payload.teams_route
            existing = self._teams_materializer.find_existing(
                self._user_id,
                build_teams_external_id(
                    route.tenant_id,
                    route.teams_user_id,
                    route.chat_id,
                    provider_id,
                ),
            )
            return existing.id if existing is not None else None
        if not provider_id:
            matched = self._reconcile_local(payload)
            return matched.id if matched is not None else None
        existing = self._materializer.find_existing(
            self._user_id,
            build_external_id(payload.server_url, provider_id),
        )
        return existing.id if existing is not None else None

    def _open_http_transport(self, account: MattermostAccount) -> MattermostHttpTransport:
        if not settings.secretary_credential_key:
            raise ToolError("credentials are not configured")
        token = self._account_store().get_access_token(account)
        return MattermostHttpTransport(
            base_url=account.server_url,
            access_token=token,
        )

    def _account_store(self) -> MattermostAccountStore:
        if not settings.secretary_credential_key:
            raise ToolError("credentials are not configured")
        return MattermostAccountStore(
            self._session,
            MattermostAccountStore.build_encryption(settings.secretary_credential_key),
        )

    def _claim_started(self, operation_id: str) -> tuple[ExternalActionAttempt, bool]:
        session = self._attempt_session_factory()
        try:
            nested = session.begin_nested()
            try:
                attempt = ExternalActionAttempt(
                    user_id=self._user_id,
                    operation_id=operation_id,
                    tool_name=SEND_MESSAGE_TOOL_NAME,
                    state=ATTEMPT_STARTED,
                    started_at=_utcnow(),
                )
                session.add(attempt)
                session.flush()
                nested.commit()
            except IntegrityError:
                nested.rollback()
                existing = session.scalar(
                    select(ExternalActionAttempt).where(
                        ExternalActionAttempt.user_id == self._user_id,
                        ExternalActionAttempt.operation_id == operation_id,
                    )
                )
                if existing is None:
                    raise ToolError("failed to claim send_message operation")
                return existing, False
            session.commit()
            session.refresh(attempt)
            return attempt, True
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

    def _output(
        self,
        payload: SendMessageCanonicalInput,
        provider_message_id: str | None,
        *,
        object_id: UUID | None,
        delivery_status: str,
        changed: bool,
    ) -> SendMessageOutput:
        return SendMessageOutput(
            provider=payload.provider,
            mode=payload.mode,
            provider_message_id=provider_message_id,
            object_id=object_id,
            delivery_status=delivery_status,  # type: ignore[arg-type]
            changed=changed,
        )
