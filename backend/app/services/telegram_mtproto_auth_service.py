import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleConfigurationError
from app.connectors.telegram.mtproto_account_store import TelegramMtprotoAccountStore
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoChallengeExpiredError,
    TelegramMtprotoChallengeNotFoundError,
    TelegramMtprotoConfigurationError,
    TelegramMtprotoInvalidPhoneError,
)
from app.connectors.telegram.mtproto_transport import (
    TelegramMtprotoAuthorizationResult,
    TelegramMtprotoAuthState,
    TelegramMtprotoTransport,
    TelethonMtprotoTransport,
)
from app.core.config import settings
from app.db.models import TelegramMtprotoAccount, TelegramMtprotoAuthChallenge

CHALLENGE_TTL = timedelta(minutes=10)
_PHONE_RE = re.compile(r"^\+?[1-9]\d{6,14}$")


@dataclass(frozen=True)
class TelegramMtprotoChallenge:
    id: UUID
    expires_at: datetime


@dataclass(frozen=True)
class TelegramMtprotoAccountSummary:
    id: UUID
    telegram_user_id: int
    username: str | None
    display_name: str | None


@dataclass(frozen=True)
class TelegramMtprotoCodeResult:
    status: str
    account: TelegramMtprotoAccountSummary | None = None


class TelegramMtprotoAuthService:
    def __init__(
        self,
        session,
        *,
        transport_factory: Callable[[], TelegramMtprotoTransport] | None = None,
        encryption: CredentialEncryption | None = None,
    ) -> None:
        self._session = session
        self._transport_factory = transport_factory or _build_transport
        self._encryption = encryption

    async def start(self, user_id: UUID, phone: str) -> TelegramMtprotoChallenge:
        store = self._store()
        normalized_phone = normalize_phone(phone)
        auth_state = await self._transport_factory().send_login_code(normalized_phone)
        expires_at = _utcnow() + CHALLENGE_TTL
        challenge = store.replace_challenge(
            user_id=user_id,
            auth_state=_serialize_state(auth_state),
            expires_at=expires_at,
        )
        return TelegramMtprotoChallenge(id=challenge.id, expires_at=expires_at)

    async def submit_code(
        self, user_id: UUID, challenge_id: UUID, code: str
    ) -> TelegramMtprotoCodeResult:
        store = self._store()
        challenge, state = self._load_challenge(store, user_id, challenge_id)
        result = await self._transport_factory().submit_code(state, code.strip())
        if result.password_required:
            store.update_challenge(challenge, _serialize_state(result.state))
            return TelegramMtprotoCodeResult(status="password_required")
        account = self._save_authorized_account(store, user_id, challenge, result)
        return TelegramMtprotoCodeResult(
            status="authorized", account=_account_summary(account)
        )

    async def submit_password(
        self, user_id: UUID, challenge_id: UUID, password: str
    ) -> TelegramMtprotoAccountSummary:
        store = self._store()
        challenge, state = self._load_challenge(store, user_id, challenge_id)
        result = await self._transport_factory().submit_password(state, password)
        account = self._save_authorized_account(store, user_id, challenge, result)
        return _account_summary(account)

    def status(self, user_id: UUID) -> TelegramMtprotoAccountSummary | None:
        return _account_summary(self._store().get_by_user_id(user_id))

    def _store(self) -> TelegramMtprotoAccountStore:
        return TelegramMtprotoAccountStore(self._session, self._encryption_or_raise())

    def _encryption_or_raise(self) -> CredentialEncryption:
        if self._encryption is not None:
            return self._encryption
        if not settings.secretary_credential_key.strip():
            raise TelegramMtprotoConfigurationError("Telegram MTProto is not configured")
        try:
            return CredentialEncryption(settings.secretary_credential_key)
        except GoogleConfigurationError as exc:
            raise TelegramMtprotoConfigurationError("Telegram MTProto is not configured") from exc

    def _load_challenge(
        self,
        store: TelegramMtprotoAccountStore,
        user_id: UUID,
        challenge_id: UUID,
    ) -> tuple[TelegramMtprotoAuthChallenge, TelegramMtprotoAuthState]:
        challenge = store.get_challenge(user_id, challenge_id)
        if challenge is None:
            raise TelegramMtprotoChallengeNotFoundError("Telegram authorization challenge not found")
        if challenge.expires_at <= _utcnow():
            store.delete_challenge(challenge)
            raise TelegramMtprotoChallengeExpiredError("Telegram authorization challenge expired")
        try:
            state = _deserialize_state(
                self._encryption_or_raise().decrypt(challenge.auth_state_encrypted)
            )
        except Exception as exc:
            raise TelegramMtprotoChallengeNotFoundError(
                "Telegram authorization challenge not found"
            ) from exc
        return challenge, state

    def _save_authorized_account(
        self,
        store: TelegramMtprotoAccountStore,
        user_id: UUID,
        challenge: TelegramMtprotoAuthChallenge,
        result: TelegramMtprotoAuthorizationResult,
    ) -> TelegramMtprotoAccount:
        if result.identity is None:
            raise TelegramMtprotoConfigurationError("Telegram authorization result is incomplete")
        account = store.save_account(
            user_id=user_id,
            identity=result.identity,
            session=result.state.session,
        )
        store.delete_challenge(challenge)
        return account


def normalize_phone(phone: str) -> str:
    normalized = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not _PHONE_RE.fullmatch(normalized):
        raise TelegramMtprotoInvalidPhoneError("Telegram phone number is invalid")
    return normalized if normalized.startswith("+") else f"+{normalized}"


def _build_transport() -> TelegramMtprotoTransport:
    if not mtproto_is_configured():
        raise TelegramMtprotoConfigurationError("Telegram MTProto is not configured")
    return TelethonMtprotoTransport(settings.telegram_api_id, settings.telegram_api_hash.strip())


def mtproto_is_configured() -> bool:
    return bool(
        settings.telegram_api_id > 0
        and settings.telegram_api_hash.strip()
        and settings.secretary_credential_key.strip()
    )


def _serialize_state(state: TelegramMtprotoAuthState) -> str:
    return json.dumps(
        {
            "phone": state.phone,
            "phone_code_hash": state.phone_code_hash,
            "session": state.session,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _deserialize_state(raw: str) -> TelegramMtprotoAuthState:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise TypeError("invalid state")
    phone = payload.get("phone")
    phone_code_hash = payload.get("phone_code_hash")
    session = payload.get("session")
    if not all(isinstance(value, str) and value for value in (phone, phone_code_hash, session)):
        raise TypeError("invalid state")
    return TelegramMtprotoAuthState(
        phone=phone,
        phone_code_hash=phone_code_hash,
        session=session,
    )


def _account_summary(account: TelegramMtprotoAccount | None) -> TelegramMtprotoAccountSummary | None:
    if account is None:
        return None
    return TelegramMtprotoAccountSummary(
        id=account.id,
        telegram_user_id=account.telegram_user_id,
        username=account.username,
        display_name=account.display_name,
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)
