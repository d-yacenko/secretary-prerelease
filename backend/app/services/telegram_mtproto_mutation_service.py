"""Canonical, approval-gated Telegram MTProto edit/delete/read mutations."""

import asyncio
import inspect
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.constants import MAX_TELEGRAM_MESSAGE_BODY_CHARS
from app.connectors.telegram.mtproto_account_store import TelegramMtprotoAccountStore
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoProviderReferenceInvalidError,
    TelegramMtprotoWriteDefiniteError,
    TelegramMtprotoWriteUncertainError,
)
from app.connectors.telegram.mtproto_transport import (
    TelegramMtprotoTransport,
    TelethonMtprotoTransport,
    validate_provider_peer_reference,
)
from app.core.config import settings
from app.db.models import (
    ExternalActionAttempt,
    Object,
    TelegramMtprotoAccount,
    TelegramMtprotoChatSelection,
)
from app.db.session import SessionLocal
from app.domain.object_visibility import is_object_hidden_from_active_reads, tombstone_object
from app.domain.telegram_mtproto_visibility import telegram_mtproto_active_object_predicate
from app.services.pipeline_enqueue import enqueue_embed_object
from app.tools.schemas import (
    TelegramMtprotoDeleteCanonicalInput,
    TelegramMtprotoDeleteRoute,
    TelegramMtprotoEditCanonicalInput,
    TelegramMtprotoEditInput,
    TelegramMtprotoEditRoute,
    TelegramMtprotoMarkReadCanonicalInput,
    TelegramMtprotoMarkReadRoute,
    TelegramMtprotoMutationOutput,
    ToolError,
)

ATTEMPT_STARTED = "started"
ATTEMPT_SUCCEEDED = "succeeded"
ATTEMPT_FAILED_DEFINITE = "failed_definite"
ATTEMPT_UNCERTAIN = "uncertain"

EDIT_TOOL_NAME = "edit_message"
DELETE_TOOL_NAME = "delete_message"
MARK_READ_TOOL_NAME = "mark_message_read"
_UNCERTAIN_MESSAGE = "could not confirm Telegram mutation; not retrying"
_FAILED_MESSAGE = "Telegram mutation previously failed; create a new plan"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TelegramMtprotoMutationService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        *,
        transport: TelegramMtprotoTransport | None = None,
        attempt_session_factory=SessionLocal,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._transport = transport
        self._attempt_session_factory = attempt_session_factory

    def prepare_edit(self, payload: TelegramMtprotoEditInput) -> TelegramMtprotoEditCanonicalInput:
        obj, route = self._prepare_route(payload.object_id, operation="edit")
        if obj.metadata_.get("direction") != "outbound":
            raise ToolError("Telegram MTProto inbound messages cannot be edited")
        if len(payload.body) > MAX_TELEGRAM_MESSAGE_BODY_CHARS:
            raise ToolError("body exceeds Telegram maximum length")
        return TelegramMtprotoEditCanonicalInput(
            operation_id=uuid4().hex,
            object_id=obj.id,
            route=TelegramMtprotoEditRoute(body=payload.body, **route),
        )

    def edit(self, payload: TelegramMtprotoEditCanonicalInput) -> TelegramMtprotoMutationOutput:
        route = payload.route
        attempt, claimed = self._claim(payload.operation_id, EDIT_TOOL_NAME)
        if not claimed:
            return self._resume(payload, attempt, operation="edit")
        try:
            obj, _, selection, reference, session = self._revalidate(payload.object_id, route)
        except ToolError as exc:
            return self._definite(payload.operation_id, str(exc))
        if obj.metadata_.get("direction") != "outbound":
            return self._definite(payload.operation_id, "Telegram MTProto inbound messages cannot be edited")
        if len(route.body) > MAX_TELEGRAM_MESSAGE_BODY_CHARS or not route.body.strip():
            return self._definite(payload.operation_id, "body exceeds Telegram maximum length")
        try:
            result = self._call_transport(
                "edit_message",
                session,
                reference,
                peer_id=route.peer_id,
                message_id=route.message_id,
                text=route.body,
            )
        except TelegramMtprotoWriteDefiniteError as exc:
            return self._definite(payload.operation_id, exc.message)
        except TelegramMtprotoWriteUncertainError as exc:
            return self._uncertain(payload.operation_id, exc.message)
        except ToolError:
            raise
        except Exception:  # noqa: BLE001 - provider outcome is ambiguous after write
            return self._uncertain(payload.operation_id, _UNCERTAIN_MESSAGE)
        if not self._valid_result(result, route.peer_id, route.message_id, route.body):
            return self._uncertain(payload.operation_id, _UNCERTAIN_MESSAGE)
        edited_at = result.get("edited_at") or _utcnow()
        edited_at_value = edited_at.isoformat() if isinstance(edited_at, datetime) else str(edited_at)
        title = f"{selection.title}: {route.body.splitlines()[0].strip()}"[:240]
        convergence = {
            "body": route.body,
            "title": title,
            "edited_at": edited_at_value,
        }
        self._persist(
            payload.operation_id,
            ATTEMPT_SUCCEEDED,
            result_metadata=convergence,
        )
        self._converge_edit(payload, convergence)
        return TelegramMtprotoMutationOutput(
            operation="edit", object_id=obj.id, status="succeeded", changed=True
        )

    def prepare_delete(self, object_id: UUID) -> TelegramMtprotoDeleteCanonicalInput:
        obj, route = self._prepare_route(object_id, operation="delete")
        return TelegramMtprotoDeleteCanonicalInput(
            operation_id=uuid4().hex,
            object_id=obj.id,
            route=TelegramMtprotoDeleteRoute(**route),
        )

    def delete(self, payload: TelegramMtprotoDeleteCanonicalInput) -> TelegramMtprotoMutationOutput:
        route = payload.route
        attempt, claimed = self._claim(payload.operation_id, DELETE_TOOL_NAME)
        if not claimed:
            return self._resume(payload, attempt, operation="delete")
        try:
            obj, _, _, reference, session = self._revalidate(payload.object_id, route)
        except ToolError as exc:
            return self._definite(payload.operation_id, str(exc))
        try:
            verified = self._call_transport(
                "fetch_message",
                session,
                reference,
                peer_id=route.peer_id,
                message_id=route.message_id,
            )
        except TelegramMtprotoWriteDefiniteError as exc:
            return self._definite(payload.operation_id, exc.message)
        except TelegramMtprotoWriteUncertainError:
            return self._definite(
                payload.operation_id,
                "Telegram message lookup failed before delete; create a new plan",
            )
        except ToolError:
            raise
        except Exception:  # noqa: BLE001 - preflight fails closed before destructive write
            return self._definite(
                payload.operation_id,
                "Telegram message lookup failed before delete; create a new plan",
            )
        if not (
            isinstance(verified, dict)
            and verified.get("peer_id") == route.peer_id
            and verified.get("message_id") == route.message_id
        ):
            return self._definite(
                payload.operation_id,
                "Telegram message is not present in the selected peer",
            )
        try:
            result = self._call_transport(
                "delete_message",
                session,
                reference,
                peer_id=route.peer_id,
                message_id=route.message_id,
            )
        except TelegramMtprotoWriteDefiniteError as exc:
            return self._definite(payload.operation_id, exc.message)
        except TelegramMtprotoWriteUncertainError as exc:
            return self._uncertain(payload.operation_id, exc.message)
        except ToolError:
            raise
        except Exception:  # noqa: BLE001 - provider outcome is ambiguous after write
            return self._uncertain(payload.operation_id, _UNCERTAIN_MESSAGE)
        if result is not True:
            return self._definite(payload.operation_id, "Telegram message deletion was rejected")
        self._persist(
            payload.operation_id,
            ATTEMPT_SUCCEEDED,
            result_metadata={"peer_id": route.peer_id, "message_id": route.message_id},
        )
        self._converge_delete(payload)
        return TelegramMtprotoMutationOutput(
            operation="delete", object_id=obj.id, status="succeeded", changed=True
        )

    def prepare_mark_read(self, object_id: UUID) -> TelegramMtprotoMarkReadCanonicalInput:
        obj, route = self._prepare_route(object_id, operation="mark_read")
        mark_route = dict(route)
        mark_route["max_message_id"] = mark_route.pop("message_id")
        return TelegramMtprotoMarkReadCanonicalInput(
            operation_id=uuid4().hex,
            object_id=obj.id,
            route=TelegramMtprotoMarkReadRoute(**mark_route),
        )

    def mark_read(
        self, payload: TelegramMtprotoMarkReadCanonicalInput
    ) -> TelegramMtprotoMutationOutput:
        route = payload.route
        attempt, claimed = self._claim(payload.operation_id, MARK_READ_TOOL_NAME)
        if not claimed:
            return self._resume(payload, attempt, operation="mark_read")
        try:
            obj, _, _, reference, session = self._revalidate(payload.object_id, route)
        except ToolError as exc:
            return self._definite(payload.operation_id, str(exc))
        try:
            result = self._call_transport(
                "mark_read",
                session,
                reference,
                peer_id=route.peer_id,
                max_message_id=route.max_message_id,
            )
        except TelegramMtprotoWriteDefiniteError as exc:
            return self._definite(payload.operation_id, exc.message)
        except TelegramMtprotoWriteUncertainError as exc:
            return self._uncertain(payload.operation_id, exc.message)
        except Exception:  # noqa: BLE001 - provider outcome is ambiguous after write
            return self._uncertain(payload.operation_id, _UNCERTAIN_MESSAGE)
        if result is not True:
            return self._definite(payload.operation_id, "Telegram mark-read was rejected")
        self._persist(payload.operation_id, ATTEMPT_SUCCEEDED)
        return TelegramMtprotoMutationOutput(
            operation="mark_read", object_id=obj.id, status="succeeded", changed=True
        )

    def _prepare_route(self, object_id: UUID, *, operation: str) -> tuple[Object, dict[str, Any]]:
        obj = self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if obj is None:
            raise ToolError("object not found")
        if is_object_hidden_from_active_reads(obj):
            raise ToolError("Telegram MTProto message is deleted")
        metadata = dict(obj.metadata_ or {})
        if not (
            obj.provider == "telegram"
            and obj.kind == "chat_message"
            and metadata.get("transport") == "mtproto"
        ):
            raise ToolError("object is not a canonical Telegram MTProto message")
        try:
            account_id = UUID(str(metadata.get("account_id")))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ToolError("malformed Telegram MTProto account_id") from exc
        peer_id = _parse_peer_id(metadata.get("peer_id"))
        message_id = _parse_message_id(metadata.get("message_id"))
        expected_external_id = f"mtproto|{account_id}|{peer_id}|{message_id}"
        if obj.external_id != expected_external_id:
            raise ToolError("Telegram MTProto message route does not match")
        if self._session.scalar(
            select(Object.id).where(
                Object.id == obj.id,
                Object.user_id == self._user_id,
                telegram_mtproto_active_object_predicate(),
            )
        ) is None:
            raise ToolError("Telegram MTProto peer is not in active scope")
        self._validate_account_selection(account_id, peer_id)
        if operation == "edit" and metadata.get("direction") != "outbound":
            raise ToolError("Telegram MTProto inbound messages cannot be edited")
        return obj, {
            "account_id": account_id,
            "peer_id": peer_id,
            "message_id": message_id,
            "peer_title": self._selection(account_id, peer_id).title,
        }

    def _revalidate(self, object_id: UUID, route) -> tuple[Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection, str, str]:
        obj = self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if obj is None or is_object_hidden_from_active_reads(obj):
            raise ToolError("Telegram MTProto message is unavailable")
        account, selection, reference, session = self._validate_account_selection(
            route.account_id, route.peer_id
        )
        metadata = dict(obj.metadata_ or {})
        frozen_message_id = getattr(route, "message_id", None)
        if frozen_message_id is None:
            frozen_message_id = getattr(route, "max_message_id", None)
        if metadata.get("message_id") != frozen_message_id:
            raise ToolError("Telegram MTProto message route does not match")
        if not self._session.scalar(
            select(Object.id).where(
                Object.id == obj.id,
                Object.user_id == self._user_id,
                telegram_mtproto_active_object_predicate(),
            )
        ):
            raise ToolError("Telegram MTProto peer is not in active scope")
        return obj, account, selection, reference, session

    def _validate_account_selection(
        self, account_id: UUID, peer_id: int
    ) -> tuple[TelegramMtprotoAccount, TelegramMtprotoChatSelection, str, str]:
        if not settings.secretary_credential_key.strip():
            raise ToolError("Telegram MTProto credentials are not configured")
        encryption = CredentialEncryption(settings.secretary_credential_key)
        store = TelegramMtprotoAccountStore(self._session, encryption)
        account = store.get_by_id_for_user(account_id, self._user_id)
        selection = store.get_selection(account_id, peer_id)
        if account is None or selection is None or not selection.scope_active:
            raise ToolError("Telegram MTProto peer is not in active scope")
        try:
            reference = store.decrypt_reference(selection)
            validate_provider_peer_reference(reference, expected_peer_id=peer_id)
            session = store.decrypt_session(account)
        except (TelegramMtprotoProviderReferenceInvalidError, ValueError) as exc:
            raise ToolError("Telegram MTProto peer reference is invalid") from exc
        except Exception as exc:
            raise ToolError("Telegram MTProto route is unavailable") from exc
        return account, selection, reference, session

    def _selection(self, account_id: UUID, peer_id: int) -> TelegramMtprotoChatSelection:
        selection = self._session.scalar(
            select(TelegramMtprotoChatSelection).where(
                TelegramMtprotoChatSelection.account_id == account_id,
                TelegramMtprotoChatSelection.peer_id == peer_id,
            )
        )
        if selection is None:
            raise ToolError("Telegram MTProto peer is not in active scope")
        return selection

    def _call_transport(self, method: str, session: str, reference: str, **kwargs):
        transport = self._transport
        if transport is None:
            if settings.telegram_api_id <= 0 or not settings.telegram_api_hash.strip():
                raise TelegramMtprotoWriteDefiniteError("Telegram MTProto is not configured")
            transport = TelethonMtprotoTransport(settings.telegram_api_id, settings.telegram_api_hash)
        result = getattr(transport, method)(session, reference, **kwargs)
        return asyncio.run(result) if inspect.isawaitable(result) else result

    @staticmethod
    def _valid_result(result: object, peer_id: int, message_id: int, body: str) -> bool:
        return (
            isinstance(result, dict)
            and result.get("peer_id") == peer_id
            and result.get("message_id") == message_id
            and result.get("text") == body
        )

    def _claim(self, operation_id: str, tool_name: str) -> tuple[ExternalActionAttempt, bool]:
        session = self._attempt_session_factory()
        try:
            nested = session.begin_nested()
            try:
                attempt = ExternalActionAttempt(
                    user_id=self._user_id,
                    operation_id=operation_id,
                    tool_name=tool_name,
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
                    raise ToolError("failed to claim Telegram mutation")
                return existing, False
            session.commit()
            session.refresh(attempt)
            return attempt, True
        finally:
            session.close()

    def _persist(
        self,
        operation_id: str,
        state: str,
        error: str | None = None,
        result_metadata: dict[str, Any] | None = None,
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
            attempt.state = state
            if result_metadata is not None:
                attempt.result_metadata = result_metadata
                flag_modified(attempt, "result_metadata")
            elif error:
                attempt.result_metadata = {"error": error[:500]}
                flag_modified(attempt, "result_metadata")
            if state in {ATTEMPT_SUCCEEDED, ATTEMPT_FAILED_DEFINITE, ATTEMPT_UNCERTAIN}:
                attempt.finished_at = _utcnow()
            session.commit()
        finally:
            session.close()

    def _resume(self, payload, attempt: ExternalActionAttempt, *, operation: str):
        if attempt.state == ATTEMPT_SUCCEEDED:
            if operation == "edit":
                self._converge_edit(payload, attempt.result_metadata or {})
            elif operation == "delete":
                self._converge_delete(payload)
            return TelegramMtprotoMutationOutput(
                operation=operation, object_id=payload.object_id, status="already_succeeded", changed=False
            )
        if attempt.state == ATTEMPT_FAILED_DEFINITE:
            raise ToolError(_FAILED_MESSAGE)
        raise ToolError(_UNCERTAIN_MESSAGE)

    def _converge_edit(self, payload: TelegramMtprotoEditCanonicalInput, metadata: dict) -> None:
        obj = self._session.scalar(
            select(Object).where(Object.id == payload.object_id, Object.user_id == self._user_id)
        )
        if obj is None:
            raise ToolError("Telegram edited message is unavailable locally")
        body = metadata.get("body", payload.route.body)
        title = metadata.get("title")
        edited_at = metadata.get("edited_at")
        if not isinstance(body, str) or not body.strip():
            raise ToolError("Telegram edited message convergence metadata is invalid")
        if title is not None and not isinstance(title, str):
            raise ToolError("Telegram edited message convergence metadata is invalid")
        if edited_at is not None and not isinstance(edited_at, str):
            raise ToolError("Telegram edited message convergence metadata is invalid")
        obj.body = body
        if title is not None:
            obj.title = title
        object_metadata = dict(obj.metadata_ or {})
        if edited_at is not None:
            object_metadata["edited_at"] = edited_at
        obj.metadata_ = object_metadata
        flag_modified(obj, "metadata_")
        self._session.flush()
        enqueue_embed_object(self._session, obj.id, self._user_id)

    def _converge_delete(self, payload: TelegramMtprotoDeleteCanonicalInput) -> None:
        obj = self._session.scalar(
            select(Object).where(Object.id == payload.object_id, Object.user_id == self._user_id)
        )
        if obj is None:
            raise ToolError("Telegram deleted message is unavailable locally")
        tombstone_object(obj)
        self._session.flush()

    def _definite(self, operation_id: str, message: str):
        self._persist(operation_id, ATTEMPT_FAILED_DEFINITE, message)
        raise ToolError(message or "Telegram mutation rejected")

    def _uncertain(self, operation_id: str, message: str):
        self._persist(operation_id, ATTEMPT_UNCERTAIN, message)
        raise ToolError(message or _UNCERTAIN_MESSAGE)


def _parse_peer_id(value: object) -> int:
    if isinstance(value, bool):
        raise ToolError("malformed Telegram MTProto peer_id")
    try:
        result = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ToolError("malformed Telegram MTProto peer_id") from exc
    if result == 0 or result < -(2**63) or result > 2**63 - 1:
        raise ToolError("malformed Telegram MTProto peer_id")
    return result


def _parse_message_id(value: object) -> int:
    if isinstance(value, bool):
        raise ToolError("malformed Telegram MTProto message_id")
    try:
        result = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ToolError("malformed Telegram MTProto message_id") from exc
    if result <= 0:
        raise ToolError("malformed Telegram MTProto message_id")
    return result
