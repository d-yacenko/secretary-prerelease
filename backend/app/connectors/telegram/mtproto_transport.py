from dataclasses import dataclass
from typing import Protocol

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoError,
    TelegramMtprotoInvalidCodeError,
    TelegramMtprotoInvalidPasswordError,
    TelegramMtprotoProviderUnavailableError,
)


@dataclass(frozen=True)
class TelegramMtprotoAuthState:
    phone: str
    phone_code_hash: str
    session: str


@dataclass(frozen=True)
class TelegramMtprotoIdentity:
    telegram_user_id: int
    username: str | None
    display_name: str | None


@dataclass(frozen=True)
class TelegramMtprotoAuthorizationResult:
    state: TelegramMtprotoAuthState
    identity: TelegramMtprotoIdentity | None
    password_required: bool = False


class TelegramMtprotoTransport(Protocol):
    async def send_login_code(self, phone: str) -> TelegramMtprotoAuthState:
        ...

    async def submit_code(
        self, state: TelegramMtprotoAuthState, code: str
    ) -> TelegramMtprotoAuthorizationResult:
        ...

    async def submit_password(
        self, state: TelegramMtprotoAuthState, password: str
    ) -> TelegramMtprotoAuthorizationResult:
        ...


class TelethonMtprotoTransport:
    def __init__(self, api_id: int, api_hash: str) -> None:
        self._api_id = api_id
        self._api_hash = api_hash

    async def send_login_code(self, phone: str) -> TelegramMtprotoAuthState:
        client: TelegramClient | None = None
        try:
            client = TelegramClient(StringSession(), self._api_id, self._api_hash)
            await client.connect()
            sent_code = await client.send_code_request(phone)
            return TelegramMtprotoAuthState(
                phone=phone,
                phone_code_hash=sent_code.phone_code_hash,
                session=client.session.save(),
            )
        except FloodWaitError as exc:
            raise _flood_wait_error(exc) from None
        except TelegramMtprotoError:
            raise
        except Exception as exc:
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram authorization provider is temporarily unavailable"
            ) from exc
        finally:
            await _disconnect(client)

    async def submit_code(
        self, state: TelegramMtprotoAuthState, code: str
    ) -> TelegramMtprotoAuthorizationResult:
        client: TelegramClient | None = None
        try:
            client = TelegramClient(
                StringSession(state.session), self._api_id, self._api_hash
            )
            await client.connect()
            try:
                await client.sign_in(
                    phone=state.phone,
                    code=code,
                    phone_code_hash=state.phone_code_hash,
                )
            except SessionPasswordNeededError:
                return TelegramMtprotoAuthorizationResult(
                    state=_state_from_client(client, state),
                    identity=None,
                    password_required=True,
                )
            return TelegramMtprotoAuthorizationResult(
                state=_state_from_client(client, state),
                identity=_identity_from_me(await client.get_me()),
            )
        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            raise TelegramMtprotoInvalidCodeError("Telegram login code is invalid") from None
        except FloodWaitError as exc:
            raise _flood_wait_error(exc) from None
        except TelegramMtprotoError:
            raise
        except Exception as exc:
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram authorization provider is temporarily unavailable"
            ) from exc
        finally:
            await _disconnect(client)

    async def submit_password(
        self, state: TelegramMtprotoAuthState, password: str
    ) -> TelegramMtprotoAuthorizationResult:
        client: TelegramClient | None = None
        try:
            client = TelegramClient(
                StringSession(state.session), self._api_id, self._api_hash
            )
            await client.connect()
            try:
                await client.sign_in(password=password)
            except PasswordHashInvalidError:
                raise TelegramMtprotoInvalidPasswordError(
                    "Telegram 2FA password is invalid"
                ) from None
            return TelegramMtprotoAuthorizationResult(
                state=_state_from_client(client, state),
                identity=_identity_from_me(await client.get_me()),
            )
        except FloodWaitError as exc:
            raise _flood_wait_error(exc) from None
        except TelegramMtprotoError:
            raise
        except Exception as exc:
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram authorization provider is temporarily unavailable"
            ) from exc
        finally:
            await _disconnect(client)


def _state_from_client(
    client: TelegramClient, state: TelegramMtprotoAuthState
) -> TelegramMtprotoAuthState:
    return TelegramMtprotoAuthState(
        phone=state.phone,
        phone_code_hash=state.phone_code_hash,
        session=client.session.save(),
    )


def _identity_from_me(me: object) -> TelegramMtprotoIdentity:
    telegram_user_id = getattr(me, "id", None)
    if not isinstance(telegram_user_id, int) or isinstance(telegram_user_id, bool):
        raise TelegramMtprotoProviderUnavailableError(
            "Telegram authorization provider returned an invalid identity"
        )
    username = getattr(me, "username", None)
    if not isinstance(username, str) or not username.strip():
        username = None
    else:
        username = username.strip()
    first_name = getattr(me, "first_name", None)
    last_name = getattr(me, "last_name", None)
    names = [value.strip() for value in (first_name, last_name) if isinstance(value, str)]
    display_name = " ".join(value for value in names if value) or None
    return TelegramMtprotoIdentity(
        telegram_user_id=telegram_user_id,
        username=username,
        display_name=display_name,
    )


def _flood_wait_error(exc: FloodWaitError) -> TelegramMtprotoProviderUnavailableError:
    seconds = getattr(exc, "seconds", None)
    bounded = max(1, min(int(seconds), 3600)) if isinstance(seconds, int) else None
    return TelegramMtprotoProviderUnavailableError(
        "Telegram authorization provider is temporarily unavailable",
        retry_after_seconds=bounded,
    )


async def _disconnect(client: TelegramClient | None) -> None:
    if client is None:
        return
    try:
        await client.disconnect()
    except Exception:  # noqa: BLE001 - cleanup must not mask the provider outcome
        return
