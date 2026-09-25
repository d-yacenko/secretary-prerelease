import json
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, Protocol

from telethon import TelegramClient, utils
from telethon.errors import (
    AuthKeyError,
    AuthKeyUnregisteredError,
    BadRequestError,
    ChannelInvalidError,
    ChannelPrivateError,
    ChatIdInvalidError,
    FloodWaitError,
    ForbiddenError,
    MessageIdInvalidError,
    NotFoundError,
    PasswordHashInvalidError,
    PeerIdInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    ServerError,
    SessionPasswordNeededError,
    SessionRevokedError,
    TimedOutError,
    UnauthorizedError,
    UserDeactivatedBanError,
    UserDeactivatedError,
)
from telethon.errors.common import AuthKeyNotFound
from telethon.sessions import StringSession
from telethon.tl import types
from telethon.tl.functions.messages import GetDialogFiltersRequest

from app.connectors.telegram.constants import MAX_TELEGRAM_MESSAGE_BODY_CHARS
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoAuthorizationInvalidError,
    TelegramMtprotoError,
    TelegramMtprotoGroupUnavailableError,
    TelegramMtprotoInvalidCodeError,
    TelegramMtprotoInvalidPasswordError,
    TelegramMtprotoProviderReferenceInvalidError,
    TelegramMtprotoProviderUnavailableError,
    TelegramMtprotoReadRejectedError,
    TelegramMtprotoWriteDefiniteError,
    TelegramMtprotoWriteUncertainError,
)

DISCOVERY_DIALOG_LIMIT = 500
TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT = 2000
TELEGRAM_MTPROTO_HISTORY_PAGE_SIZE = 100


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


@dataclass(frozen=True)
class TelegramMtprotoGroupDescriptor:
    peer_id: int
    kind: str
    title: str
    username: str | None
    is_forum: bool
    provider_peer_reference: str


@dataclass(frozen=True)
class TelegramMtprotoGroupDiscoveryResult:
    groups: tuple[TelegramMtprotoGroupDescriptor, ...]
    truncated: bool


@dataclass(frozen=True)
class TelegramMtprotoFolderDescriptor:
    folder_id: int
    name: str
    definition: object | None = None


@dataclass(frozen=True)
class TelegramMtprotoFolderDiscoveryResult:
    folders: tuple[TelegramMtprotoFolderDescriptor, ...]
    truncated: bool


@dataclass(frozen=True)
class TelegramMtprotoDialogDescriptor:
    peer_id: int
    kind: str
    title: str
    username: str | None
    is_muted: bool
    provider_peer_reference: str
    is_contact: bool = False
    is_bot: bool = False
    is_broadcast: bool = False
    is_archived: bool = False
    unread_count: int = 0
    unread_mark: bool = False
    is_forum: bool = False


@dataclass(frozen=True)
class TelegramMtprotoFolderDialogsResult:
    dialogs: tuple[TelegramMtprotoDialogDescriptor, ...]
    truncated: bool
    skipped_counts: dict[str, int]


@dataclass(frozen=True)
class TelegramMtprotoMediaHint:
    media_kind: str
    provider_media_id: str
    filename: str | None = None
    mime_type: str | None = None
    size: int | None = None
    duration_seconds: int | None = None


@dataclass(frozen=True)
class TelegramMtprotoHistoryEntry:
    message_id: int
    occurred_at: datetime | None
    text: str | None
    sender_peer_id: int | None
    reply_to_message_id: int | None
    topic_id: int | None
    edited_at: datetime | None
    is_service: bool
    outgoing: bool = False
    media: tuple[TelegramMtprotoMediaHint, ...] = ()


@dataclass(frozen=True)
class TelegramMtprotoSentMessage:
    message_id: int
    peer_id: int
    text: str
    occurred_at: datetime | None
    reply_to_message_id: int | None
    sender_peer_id: int | None


@dataclass(frozen=True)
class TelegramMtprotoHistoryPage:
    entries: tuple[TelegramMtprotoHistoryEntry, ...]
    has_more: bool


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

    async def discover_groups(
        self, session: str, limit: int
    ) -> TelegramMtprotoGroupDiscoveryResult:
        ...

    async def discover_folders(
        self, session: str, limit: int
    ) -> TelegramMtprotoFolderDiscoveryResult:
        ...

    async def fetch_dialog_universe(
        self, session: str, limit: int
    ) -> TelegramMtprotoFolderDialogsResult:
        ...

    async def fetch_history(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        limit: int,
        min_message_id: int | None = None,
        max_message_id: int | None = None,
        reverse: bool = False,
    ) -> TelegramMtprotoHistoryPage:
        ...

    async def send_message(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        peer_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> TelegramMtprotoSentMessage:
        ...

    async def edit_message(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        peer_id: int,
        message_id: int,
        text: str,
    ) -> dict[str, Any]:
        ...

    async def fetch_message(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        peer_id: int,
        message_id: int,
    ) -> dict[str, Any] | None:
        ...

    async def download_voice_audio(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        peer_id: int,
        message_id: int,
        provider_media_id: str,
        media_kind: str,
        max_bytes: int,
    ) -> bytes:
        ...

    async def delete_message(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        peer_id: int,
        message_id: int,
    ) -> bool:
        ...

    async def mark_read(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        peer_id: int,
        max_message_id: int,
    ) -> bool:
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

    async def discover_groups(
        self, session: str, limit: int
    ) -> TelegramMtprotoGroupDiscoveryResult:
        client: TelegramClient | None = None
        scan_limit = max(1, min(limit, DISCOVERY_DIALOG_LIMIT))
        try:
            client = TelegramClient(StringSession(session), self._api_id, self._api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                raise TelegramMtprotoAuthorizationInvalidError(
                    "Telegram MTProto authorization is no longer valid"
                )
            groups: list[TelegramMtprotoGroupDescriptor] = []
            seen = 0
            async for dialog in client.iter_dialogs(limit=scan_limit):
                if seen >= scan_limit:
                    break
                seen += 1
                descriptor = _group_from_dialog(dialog)
                if descriptor is not None:
                    groups.append(descriptor)
            return TelegramMtprotoGroupDiscoveryResult(
                groups=tuple(groups),
                truncated=seen >= scan_limit,
            )
        except (
            AuthKeyError,
            AuthKeyNotFound,
            AuthKeyUnregisteredError,
            SessionRevokedError,
            UnauthorizedError,
            UserDeactivatedBanError,
            UserDeactivatedError,
        ):
            raise TelegramMtprotoAuthorizationInvalidError(
                "Telegram MTProto authorization is no longer valid"
            ) from None
        except FloodWaitError as exc:
            raise _flood_wait_error(exc) from None
        except TelegramMtprotoError:
            raise
        except (ValueError, TypeError):
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram provider is temporarily unavailable"
            ) from None
        except Exception as exc:
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram provider is temporarily unavailable"
            ) from exc
        finally:
            await _disconnect(client)

    async def discover_folders(
        self, session: str, limit: int
    ) -> TelegramMtprotoFolderDiscoveryResult:
        client: TelegramClient | None = None
        scan_limit = max(1, min(limit, DISCOVERY_DIALOG_LIMIT))
        try:
            client = TelegramClient(StringSession(session), self._api_id, self._api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                raise TelegramMtprotoAuthorizationInvalidError(
                    "Telegram MTProto authorization is no longer valid"
                )
            response = await client(GetDialogFiltersRequest())
            filters = _custom_filter_definitions(response)
            folders: list[TelegramMtprotoFolderDescriptor] = []
            for item in filters:
                folder_id = getattr(item, "id", None)
                name = _folder_name(item)
                if isinstance(folder_id, int) and not isinstance(folder_id, bool) and folder_id > 0 and name:
                    folders.append(TelegramMtprotoFolderDescriptor(folder_id, name, item))
                    if len(folders) >= scan_limit:
                        break
            return TelegramMtprotoFolderDiscoveryResult(tuple(folders), len(folders) >= scan_limit)
        except (
            AuthKeyError,
            AuthKeyNotFound,
            AuthKeyUnregisteredError,
            SessionRevokedError,
            UnauthorizedError,
            UserDeactivatedBanError,
            UserDeactivatedError,
        ):
            raise TelegramMtprotoAuthorizationInvalidError(
                "Telegram MTProto authorization is no longer valid"
            ) from None
        except FloodWaitError as exc:
            raise _flood_wait_error(exc) from None
        except TelegramMtprotoError:
            raise
        except Exception as exc:
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram folder provider is temporarily unavailable"
            ) from exc
        finally:
            await _disconnect(client)

    async def fetch_dialog_universe(
        self, session: str, limit: int
    ) -> TelegramMtprotoFolderDialogsResult:
        client: TelegramClient | None = None
        scan_limit = max(1, min(limit, TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT))
        try:
            client = TelegramClient(StringSession(session), self._api_id, self._api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                raise TelegramMtprotoAuthorizationInvalidError(
                    "Telegram MTProto authorization is no longer valid"
                )
            dialogs: list[TelegramMtprotoDialogDescriptor] = []
            skipped: dict[str, int] = {}
            seen = 0
            truncated = False
            async for dialog in client.iter_dialogs(limit=scan_limit + 1):
                if seen >= scan_limit:
                    truncated = True
                    break
                seen += 1
                descriptor, reason = _dialog_from_dialog(dialog)
                if descriptor is None:
                    skipped[reason or "unsupported"] = skipped.get(reason or "unsupported", 0) + 1
                else:
                    dialogs.append(descriptor)
            return TelegramMtprotoFolderDialogsResult(tuple(dialogs), truncated, skipped)
        except (
            AuthKeyError,
            AuthKeyNotFound,
            AuthKeyUnregisteredError,
            SessionRevokedError,
            UnauthorizedError,
            UserDeactivatedBanError,
            UserDeactivatedError,
        ):
            raise TelegramMtprotoAuthorizationInvalidError(
                "Telegram MTProto authorization is no longer valid"
            ) from None
        except FloodWaitError as exc:
            raise _flood_wait_error(exc) from None
        except TelegramMtprotoError:
            raise
        except Exception as exc:
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram folder provider is temporarily unavailable"
            ) from exc
        finally:
            await _disconnect(client)

    async def fetch_history(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        limit: int,
        min_message_id: int | None = None,
        max_message_id: int | None = None,
        reverse: bool = False,
    ) -> TelegramMtprotoHistoryPage:
        client: TelegramClient | None = None
        page_limit = max(1, min(limit, TELEGRAM_MTPROTO_HISTORY_PAGE_SIZE))
        try:
            input_peer = _input_peer_from_reference(provider_peer_reference)
            client = TelegramClient(StringSession(session), self._api_id, self._api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                raise TelegramMtprotoAuthorizationInvalidError(
                    "Telegram MTProto authorization is no longer valid"
                )
            entries: list[TelegramMtprotoHistoryEntry] = []
            async for message in client.iter_messages(
                input_peer,
                limit=page_limit,
                min_id=0 if min_message_id is None else min_message_id,
                max_id=0 if max_message_id is None else max_message_id,
                reverse=reverse,
            ):
                entry = _history_entry_from_message(message)
                if entry is None:
                    raise TelegramMtprotoProviderUnavailableError(
                        "Telegram history provider returned an invalid entry"
                    )
                entries.append(entry)
            return TelegramMtprotoHistoryPage(
                entries=tuple(entries), has_more=len(entries) >= page_limit
            )
        except (
            AuthKeyError,
            AuthKeyNotFound,
            AuthKeyUnregisteredError,
            SessionRevokedError,
            UnauthorizedError,
            UserDeactivatedBanError,
            UserDeactivatedError,
        ):
            raise TelegramMtprotoAuthorizationInvalidError(
                "Telegram MTProto authorization is no longer valid"
            ) from None
        except (ChannelInvalidError, ChannelPrivateError, ChatIdInvalidError, PeerIdInvalidError):
            raise TelegramMtprotoGroupUnavailableError(
                "Telegram selected group is no longer available"
            ) from None
        except FloodWaitError as exc:
            raise _flood_wait_error(exc) from None
        except TelegramMtprotoError:
            raise
        except (ValueError, TypeError):
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram history provider is temporarily unavailable"
            ) from None
        except Exception as exc:
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram history provider is temporarily unavailable"
            ) from exc
        finally:
            await _disconnect(client)

    async def send_message(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        peer_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> TelegramMtprotoSentMessage:
        client: TelegramClient | None = None
        try:
            input_peer = validate_provider_peer_reference(
                provider_peer_reference, expected_peer_id=peer_id
            )
            client = TelegramClient(StringSession(session), self._api_id, self._api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                raise TelegramMtprotoWriteDefiniteError(
                    "Telegram MTProto authorization is no longer valid"
                )
            message = await client.send_message(
                input_peer,
                message=text,
                reply_to=reply_to_message_id,
            )
            returned_peer = _peer_id_from_message_peer(getattr(message, "peer_id", None))
            if returned_peer != peer_id:
                raise TelegramMtprotoWriteUncertainError(
                    "Telegram provider returned an unexpected peer"
                )
            message_id = getattr(message, "id", None)
            if not isinstance(message_id, int) or message_id <= 0:
                raise TelegramMtprotoWriteUncertainError(
                    "Telegram provider returned an invalid message"
                )
            returned_text = getattr(message, "message", None)
            if not isinstance(returned_text, str) or returned_text != text:
                raise TelegramMtprotoWriteUncertainError(
                    "Telegram provider returned an unexpected message"
                )
            return TelegramMtprotoSentMessage(
                message_id=message_id,
                peer_id=returned_peer,
                text=returned_text,
                occurred_at=_history_datetime(getattr(message, "date", None)),
                reply_to_message_id=_positive_int(
                    getattr(getattr(message, "reply_to", None), "reply_to_msg_id", None)
                ),
                sender_peer_id=_peer_id_from_message(message),
            )
        except TelegramMtprotoWriteDefiniteError:
            raise
        except TelegramMtprotoWriteUncertainError:
            raise
        except (
            AuthKeyError,
            AuthKeyNotFound,
            AuthKeyUnregisteredError,
            SessionRevokedError,
            UnauthorizedError,
            UserDeactivatedBanError,
            UserDeactivatedError,
        ):
            raise TelegramMtprotoWriteDefiniteError(
                "Telegram MTProto authorization is no longer valid"
            ) from None
        except FloodWaitError:
            raise TelegramMtprotoWriteUncertainError(
                "Telegram send outcome is uncertain; not retrying"
            ) from None
        except TelegramMtprotoProviderReferenceInvalidError:
            raise TelegramMtprotoWriteDefiniteError(
                "Telegram selected group reference is invalid"
            ) from None
        except (ChannelInvalidError, ChannelPrivateError, ChatIdInvalidError, PeerIdInvalidError):
            raise TelegramMtprotoWriteDefiniteError(
                "Telegram peer is unavailable"
            ) from None
        except Exception:  # noqa: BLE001 - provider outcome is ambiguous after send
            raise TelegramMtprotoWriteUncertainError(
                "Telegram send outcome is uncertain; not retrying"
            ) from None
        finally:
            await _disconnect(client)

    async def edit_message(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        peer_id: int,
        message_id: int,
        text: str,
    ) -> dict[str, Any]:
        client: TelegramClient | None = None
        try:
            input_peer = validate_provider_peer_reference(
                provider_peer_reference, expected_peer_id=peer_id
            )
            client = TelegramClient(StringSession(session), self._api_id, self._api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                raise TelegramMtprotoWriteDefiniteError(
                    "Telegram MTProto authorization is no longer valid"
                )
            message = await client.edit_message(input_peer, message_id, text=text)
            returned_peer = _peer_id_from_message_peer(getattr(message, "peer_id", None))
            returned_id = getattr(message, "id", None)
            returned_text = getattr(message, "message", None)
            if returned_peer != peer_id or returned_id != message_id or returned_text != text:
                raise TelegramMtprotoWriteUncertainError(
                    "Telegram provider returned an unexpected edited message"
                )
            return {
                "peer_id": returned_peer,
                "message_id": returned_id,
                "text": returned_text,
                "edited_at": _history_datetime(getattr(message, "edit_date", None))
                or _history_datetime(getattr(message, "date", None)),
            }
        except TelegramMtprotoWriteDefiniteError:
            raise
        except TelegramMtprotoWriteUncertainError:
            raise
        except TelegramMtprotoProviderReferenceInvalidError:
            raise TelegramMtprotoWriteDefiniteError(
                "Telegram selected group reference is invalid"
            ) from None
        except (
            AuthKeyError,
            AuthKeyNotFound,
            AuthKeyUnregisteredError,
            SessionRevokedError,
            UnauthorizedError,
            UserDeactivatedBanError,
            UserDeactivatedError,
        ):
            raise TelegramMtprotoWriteDefiniteError(
                "Telegram MTProto authorization is no longer valid"
            ) from None
        except FloodWaitError:
            raise TelegramMtprotoWriteUncertainError(
                "Telegram edit outcome is uncertain; not retrying"
            ) from None
        except (ChannelInvalidError, ChannelPrivateError, ChatIdInvalidError, PeerIdInvalidError):
            raise TelegramMtprotoWriteDefiniteError("Telegram message edit was rejected") from None
        except (MessageIdInvalidError, BadRequestError, ForbiddenError, NotFoundError):
            raise TelegramMtprotoWriteDefiniteError("Telegram message edit was rejected") from None
        except (ServerError, TimedOutError):
            raise TelegramMtprotoWriteUncertainError(
                "Telegram edit outcome is uncertain; not retrying"
            ) from None
        except Exception:  # noqa: BLE001 - provider outcome is ambiguous after write
            raise TelegramMtprotoWriteUncertainError(
                "Telegram edit outcome is uncertain; not retrying"
            ) from None
        finally:
            await _disconnect(client)

    async def fetch_message(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        peer_id: int,
        message_id: int,
    ) -> dict[str, Any] | None:
        client: TelegramClient | None = None
        try:
            input_peer = validate_provider_peer_reference(
                provider_peer_reference, expected_peer_id=peer_id
            )
            client = TelegramClient(StringSession(session), self._api_id, self._api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                raise TelegramMtprotoAuthorizationInvalidError(
                    "Telegram MTProto authorization is no longer valid"
                )
            message = await client.get_messages(input_peer, ids=message_id)
            if isinstance(message, list):
                message = message[0] if message else None
            if message is None:
                return None
            entry = _history_entry_from_message(message)
            if entry is None:
                return {
                    "peer_id": _peer_id_from_message_peer(getattr(message, "peer_id", None)),
                    "message_id": getattr(message, "id", None),
                    "text": None,
                    "service": getattr(message, "action", None) is not None,
                }
            return {
                "peer_id": _peer_id_from_message_peer(getattr(message, "peer_id", None)),
                "message_id": entry.message_id,
                "text": entry.text,
                "occurred_at": entry.occurred_at,
                "edited_at": entry.edited_at,
                "reply_to_message_id": entry.reply_to_message_id,
                "sender_peer_id": entry.sender_peer_id,
                "outgoing": entry.outgoing,
                "topic_id": entry.topic_id,
                "service": entry.is_service,
            }
        except (TelegramMtprotoAuthorizationInvalidError, TelegramMtprotoProviderReferenceInvalidError):
            raise
        except (
            AuthKeyError,
            AuthKeyNotFound,
            AuthKeyUnregisteredError,
            SessionRevokedError,
            UnauthorizedError,
            UserDeactivatedBanError,
            UserDeactivatedError,
        ):
            raise TelegramMtprotoAuthorizationInvalidError(
                "Telegram MTProto authorization is no longer valid"
            ) from None
        except (ChannelInvalidError, ChannelPrivateError, ChatIdInvalidError, PeerIdInvalidError,
                BadRequestError, ForbiddenError, NotFoundError):
            raise TelegramMtprotoReadRejectedError("Telegram message lookup was rejected") from None
        except FloodWaitError as exc:
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram provider is temporarily unavailable", exc.seconds
            ) from None
        except (ServerError, TimedOutError):
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram provider is temporarily unavailable"
            ) from None
        except Exception:  # noqa: BLE001 - read failure is provider transient
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram provider is temporarily unavailable"
            ) from None
        finally:
            await _disconnect(client)

    async def download_voice_audio(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        peer_id: int,
        message_id: int,
        provider_media_id: str,
        media_kind: str,
        max_bytes: int,
    ) -> bytes:
        client: TelegramClient | None = None
        try:
            input_peer = validate_provider_peer_reference(
                provider_peer_reference, expected_peer_id=peer_id
            )
            client = TelegramClient(StringSession(session), self._api_id, self._api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                raise TelegramMtprotoAuthorizationInvalidError(
                    "Telegram MTProto authorization is no longer valid"
                )
            message = await client.get_messages(input_peer, ids=message_id)
            if isinstance(message, list):
                message = message[0] if message else None
            hint = _verified_voice_audio(message, peer_id, message_id, provider_media_id, media_kind)
            if hint is None or (hint.size is not None and hint.size > max_bytes):
                raise TelegramMtprotoReadRejectedError("Telegram media does not match descriptor")
            buffer = BytesIO()
            await client.download_media(message, file=buffer)
            audio = buffer.getvalue()
            if not audio or len(audio) > max_bytes:
                raise TelegramMtprotoReadRejectedError("Telegram media exceeds size limit")
            return audio
        except (TelegramMtprotoAuthorizationInvalidError, TelegramMtprotoProviderReferenceInvalidError):
            raise
        except TelegramMtprotoReadRejectedError:
            raise
        except (
            AuthKeyError,
            AuthKeyNotFound,
            AuthKeyUnregisteredError,
            SessionRevokedError,
            UnauthorizedError,
            UserDeactivatedBanError,
            UserDeactivatedError,
        ):
            raise TelegramMtprotoAuthorizationInvalidError(
                "Telegram MTProto authorization is no longer valid"
            ) from None
        except (
            ChannelInvalidError,
            ChannelPrivateError,
            ChatIdInvalidError,
            PeerIdInvalidError,
            BadRequestError,
            ForbiddenError,
            NotFoundError,
        ):
            raise TelegramMtprotoReadRejectedError("Telegram media lookup was rejected") from None
        except FloodWaitError as exc:
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram provider is temporarily unavailable", exc.seconds
            ) from None
        except (ServerError, TimedOutError):
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram provider is temporarily unavailable"
            ) from None
        except Exception:  # noqa: BLE001 - read failure is provider transient
            raise TelegramMtprotoProviderUnavailableError(
                "Telegram provider is temporarily unavailable"
            ) from None
        finally:
            await _disconnect(client)

    async def delete_message(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        peer_id: int,
        message_id: int,
    ) -> bool:
        client: TelegramClient | None = None
        try:
            input_peer = validate_provider_peer_reference(
                provider_peer_reference, expected_peer_id=peer_id
            )
            client = TelegramClient(StringSession(session), self._api_id, self._api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                raise TelegramMtprotoWriteDefiniteError(
                    "Telegram MTProto authorization is no longer valid"
                )
            await client.delete_messages(input_peer, [message_id])
            return True
        except TelegramMtprotoWriteDefiniteError:
            raise
        except TelegramMtprotoProviderReferenceInvalidError:
            raise TelegramMtprotoWriteDefiniteError(
                "Telegram selected group reference is invalid"
            ) from None
        except (
            AuthKeyError,
            AuthKeyNotFound,
            AuthKeyUnregisteredError,
            SessionRevokedError,
            UnauthorizedError,
            UserDeactivatedBanError,
            UserDeactivatedError,
        ):
            raise TelegramMtprotoWriteDefiniteError(
                "Telegram MTProto authorization is no longer valid"
            ) from None
        except FloodWaitError:
            raise TelegramMtprotoWriteUncertainError(
                "Telegram delete outcome is uncertain; not retrying"
            ) from None
        except (ChannelInvalidError, ChannelPrivateError, ChatIdInvalidError, PeerIdInvalidError):
            raise TelegramMtprotoWriteDefiniteError("Telegram message deletion was rejected") from None
        except (BadRequestError, ForbiddenError, NotFoundError):
            raise TelegramMtprotoWriteDefiniteError("Telegram message deletion was rejected") from None
        except (ServerError, TimedOutError):
            raise TelegramMtprotoWriteUncertainError(
                "Telegram delete outcome is uncertain; not retrying"
            ) from None
        except Exception:  # noqa: BLE001 - provider outcome is ambiguous after write
            raise TelegramMtprotoWriteUncertainError(
                "Telegram delete outcome is uncertain; not retrying"
            ) from None
        finally:
            await _disconnect(client)

    async def mark_read(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        peer_id: int,
        max_message_id: int,
    ) -> bool:
        client: TelegramClient | None = None
        try:
            input_peer = validate_provider_peer_reference(
                provider_peer_reference, expected_peer_id=peer_id
            )
            client = TelegramClient(StringSession(session), self._api_id, self._api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                raise TelegramMtprotoWriteDefiniteError(
                    "Telegram MTProto authorization is no longer valid"
                )
            await client.send_read_acknowledge(input_peer, max_id=max_message_id)
            return True
        except TelegramMtprotoWriteDefiniteError:
            raise
        except TelegramMtprotoProviderReferenceInvalidError:
            raise TelegramMtprotoWriteDefiniteError(
                "Telegram selected group reference is invalid"
            ) from None
        except (AuthKeyError, AuthKeyNotFound, AuthKeyUnregisteredError, SessionRevokedError, UnauthorizedError):
            raise TelegramMtprotoWriteDefiniteError(
                "Telegram MTProto authorization is no longer valid"
            ) from None
        except FloodWaitError:
            raise TelegramMtprotoWriteUncertainError(
                "Telegram mark-read outcome is uncertain; not retrying"
            ) from None
        except (ChannelInvalidError, ChannelPrivateError, ChatIdInvalidError, PeerIdInvalidError):
            raise TelegramMtprotoWriteDefiniteError("Telegram mark-read was rejected") from None
        except (BadRequestError, ForbiddenError, NotFoundError):
            raise TelegramMtprotoWriteDefiniteError("Telegram mark-read was rejected") from None
        except (ServerError, TimedOutError):
            raise TelegramMtprotoWriteUncertainError(
                "Telegram mark-read outcome is uncertain; not retrying"
            ) from None
        except Exception:  # noqa: BLE001 - provider outcome is ambiguous after write
            raise TelegramMtprotoWriteUncertainError(
                "Telegram mark-read outcome is uncertain; not retrying"
            ) from None
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


def _group_from_dialog(dialog: object) -> TelegramMtprotoGroupDescriptor | None:
    entity = getattr(dialog, "entity", None)
    if isinstance(entity, types.Chat):
        kind = "group"
        is_forum = False
        entity_type = "chat"
    elif isinstance(entity, types.Channel) and entity.megagroup and not entity.broadcast:
        kind = "supergroup"
        is_forum = bool(entity.forum)
        entity_type = "channel"
    else:
        return None
    if any(
        bool(getattr(entity, field, False))
        for field in ("left", "kicked", "deactivated")
    ):
        return None
    title = getattr(entity, "title", None)
    if not isinstance(title, str) or not title.strip():
        return None
    username = getattr(entity, "username", None)
    if not isinstance(username, str) or not username.strip():
        username = None
    else:
        username = username.strip()
    entity_id = getattr(entity, "id", None)
    if not isinstance(entity_id, int) or isinstance(entity_id, bool):
        return None
    peer_id = utils.get_peer_id(entity)
    reference: dict[str, int | str] = {"entity_type": entity_type, "id": entity_id}
    if entity_type == "channel":
        access_hash = getattr(entity, "access_hash", None)
        if not isinstance(access_hash, int) or isinstance(access_hash, bool):
            return None
        reference["access_hash"] = access_hash
    return TelegramMtprotoGroupDescriptor(
        peer_id=peer_id,
        kind=kind,
        title=title.strip(),
        username=username,
        is_forum=is_forum,
        provider_peer_reference=json.dumps(reference, separators=(",", ":")),
    )


def _folder_name(item: object) -> str | None:
    title = getattr(item, "title", None)
    if isinstance(title, str):
        value = title.strip()
    else:
        value = str(getattr(title, "text", "") or "").strip()
    return value or None


def _custom_filter_definitions(response: object) -> tuple[object, ...]:
    filters = getattr(response, "filters", response)
    if not isinstance(filters, (list, tuple)):
        filters = tuple(filters or ())
    return tuple(
        item
        for item in filters
        if isinstance(item, (types.DialogFilter, types.DialogFilterChatlist))
    )


def _dialog_from_dialog(
    dialog: object,
) -> tuple[TelegramMtprotoDialogDescriptor | None, str | None]:
    entity = getattr(dialog, "entity", None)
    is_bot = isinstance(entity, types.User) and bool(getattr(entity, "bot", False))
    is_broadcast = isinstance(entity, types.Channel) and bool(getattr(entity, "broadcast", False))
    if isinstance(entity, types.User):
        if is_bot:
            return None, "bot"
        kind = "private"
        entity_type = "user"
    elif isinstance(entity, types.Chat):
        kind = "group"
        entity_type = "chat"
    elif isinstance(entity, types.Channel) and entity.megagroup and not entity.broadcast:
        kind = "supergroup"
        entity_type = "channel"
    elif is_broadcast:
        return None, "broadcast"
    else:
        return None, "unsupported"
    entity_id = getattr(entity, "id", None)
    if not isinstance(entity_id, int) or isinstance(entity_id, bool):
        return None, "unsupported"
    title = _dialog_title(dialog, entity)
    if not title:
        return None, "unsupported"
    reference: dict[str, int | str] = {"entity_type": entity_type, "id": entity_id}
    if entity_type in {"user", "channel"}:
        access_hash = getattr(entity, "access_hash", None)
        if not isinstance(access_hash, int) or isinstance(access_hash, bool):
            return None, "unsupported"
        reference["access_hash"] = access_hash
    try:
        peer_id = utils.get_peer_id(entity)
    except (TypeError, ValueError):
        return None, "unsupported"
    username = getattr(entity, "username", None)
    if not isinstance(username, str) or not username.strip():
        username = None
    return TelegramMtprotoDialogDescriptor(
        peer_id=peer_id,
        kind=kind,
        title=title,
        username=username.strip() if username else None,
        is_muted=_is_currently_muted(dialog),
        provider_peer_reference=json.dumps(reference, separators=(",", ":")),
        is_contact=bool(getattr(entity, "contact", False)) if isinstance(entity, types.User) else False,
        is_bot=is_bot,
        is_broadcast=is_broadcast,
        is_archived=_is_archived(dialog),
        unread_count=_nonnegative_int(getattr(dialog, "unread_count", 0)),
        unread_mark=bool(getattr(getattr(dialog, "dialog", None), "unread_mark", False)),
        is_forum=bool(getattr(entity, "forum", False)) if kind == "supergroup" else False,
    ), None


def _dialog_title(dialog: object, entity: object) -> str | None:
    title = getattr(dialog, "name", None) or getattr(entity, "title", None)
    if not title and isinstance(entity, types.User):
        names = [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]
        title = " ".join(value.strip() for value in names if isinstance(value, str) and value.strip())
    return title.strip() if isinstance(title, str) and title.strip() else None


def _is_currently_muted(dialog: object, *, now: datetime | None = None) -> bool:
    notify_settings = getattr(getattr(dialog, "dialog", None), "notify_settings", None)
    mute_until = getattr(notify_settings, "mute_until", None)
    return isinstance(mute_until, int) and not isinstance(mute_until, bool) and mute_until > int(
        (now or datetime.now(UTC)).timestamp()
    )


def _is_archived(dialog: object) -> bool:
    return getattr(getattr(dialog, "dialog", None), "folder_id", None) == 1


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _peer_id_from_filter_peer(peer: object) -> int | None:
    try:
        value = utils.get_peer_id(peer)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _filter_peer_ids(filter_definition: object, attribute: str) -> set[int]:
    return {
        peer_id
        for peer in (getattr(filter_definition, attribute, None) or ())
        if (peer_id := _peer_id_from_filter_peer(peer)) is not None
    }


def dialog_matches_filter(
    filter_definition: object, dialog: TelegramMtprotoDialogDescriptor
) -> bool:
    """Evaluate Telegram custom-filter fields against one live dialog descriptor."""
    if dialog.peer_id in _filter_peer_ids(filter_definition, "exclude_peers"):
        return False
    explicit = _filter_peer_ids(filter_definition, "include_peers") | _filter_peer_ids(
        filter_definition, "pinned_peers"
    )
    if dialog.peer_id in explicit:
        return True
    if isinstance(filter_definition, types.DialogFilterChatlist):
        return False
    categories = (
        bool(getattr(filter_definition, "contacts", False)) and dialog.kind == "private" and dialog.is_contact,
        bool(getattr(filter_definition, "non_contacts", False)) and dialog.kind == "private" and not dialog.is_contact and not dialog.is_bot,
        bool(getattr(filter_definition, "groups", False)) and dialog.kind in {"group", "supergroup"},
        bool(getattr(filter_definition, "broadcasts", False)) and dialog.is_broadcast,
        bool(getattr(filter_definition, "bots", False)) and dialog.is_bot,
    )
    if not any(categories):
        return False
    if bool(getattr(filter_definition, "exclude_muted", False)) and dialog.is_muted:
        return False
    if bool(getattr(filter_definition, "exclude_read", False)) and dialog.unread_count == 0 and not dialog.unread_mark:
        return False
    return not (bool(getattr(filter_definition, "exclude_archived", False)) and dialog.is_archived)


def _input_peer_from_reference(provider_peer_reference: str) -> object:
    try:
        payload = json.loads(provider_peer_reference)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise TelegramMtprotoProviderReferenceInvalidError(
            "Telegram selected group reference is invalid"
        ) from None
    if not isinstance(payload, dict):
        raise TelegramMtprotoProviderReferenceInvalidError(
            "Telegram selected group reference is invalid"
        )
    entity_type = payload.get("entity_type")
    entity_id = payload.get("id")
    if not isinstance(entity_id, int) or isinstance(entity_id, bool) or entity_id <= 0:
        raise TelegramMtprotoProviderReferenceInvalidError(
            "Telegram selected group reference is invalid"
        )
    if entity_type == "chat" and set(payload) == {"entity_type", "id"}:
        return types.InputPeerChat(chat_id=entity_id)
    access_hash = payload.get("access_hash")
    if (
        entity_type == "user"
        and set(payload) == {"entity_type", "id", "access_hash"}
        and isinstance(access_hash, int)
        and not isinstance(access_hash, bool)
    ):
        return types.InputPeerUser(user_id=entity_id, access_hash=access_hash)
    if (
        entity_type == "channel"
        and set(payload) == {"entity_type", "id", "access_hash"}
        and isinstance(access_hash, int)
        and not isinstance(access_hash, bool)
    ):
        return types.InputPeerChannel(channel_id=entity_id, access_hash=access_hash)
    raise TelegramMtprotoProviderReferenceInvalidError(
        "Telegram selected group reference is invalid"
    )


def validate_provider_peer_reference(
    provider_peer_reference: str, *, expected_peer_id: int
) -> object:
    """Parse a durable reference and require its canonical Telethon peer id."""
    input_peer = _input_peer_from_reference(provider_peer_reference)
    try:
        canonical_peer_id = utils.get_peer_id(input_peer)
    except (TypeError, ValueError):
        raise TelegramMtprotoProviderReferenceInvalidError(
            "Telegram selected group reference is invalid"
        ) from None
    if canonical_peer_id != expected_peer_id:
        raise TelegramMtprotoProviderReferenceInvalidError(
            "Telegram selected group reference does not match peer"
        )
    return input_peer


def _history_entry_from_message(message: object) -> TelegramMtprotoHistoryEntry | None:
    message_id = getattr(message, "id", None)
    if not isinstance(message_id, int) or isinstance(message_id, bool) or message_id <= 0:
        return None
    raw_text = getattr(message, "message", None)
    text = _bound_history_text(raw_text) if isinstance(raw_text, str) and raw_text.strip() else None
    occurred_at = _history_datetime(getattr(message, "date", None))
    edited_at = _history_datetime(getattr(message, "edit_date", None))
    sender_peer_id = _peer_id_from_message(message)
    reply_header = getattr(message, "reply_to", None)
    reply_to_message_id = _positive_int(getattr(message, "reply_to_msg_id", None))
    if reply_to_message_id is None:
        reply_to_message_id = _positive_int(getattr(reply_header, "reply_to_msg_id", None))
    topic_id = _positive_int(getattr(message, "reply_to_top_id", None))
    if topic_id is None:
        topic_id = _positive_int(getattr(reply_header, "reply_to_top_id", None))
    if topic_id is None and bool(getattr(reply_header, "forum_topic", False)):
        topic_id = reply_to_message_id
    return TelegramMtprotoHistoryEntry(
        message_id=message_id,
        occurred_at=occurred_at,
        text=text,
        sender_peer_id=sender_peer_id,
        reply_to_message_id=reply_to_message_id,
        topic_id=topic_id,
        edited_at=edited_at,
        is_service=getattr(message, "action", None) is not None,
        outgoing=bool(getattr(message, "out", False)),
        media=_media_hints(message),
    )


def select_voice_audio_hint(
    hints: tuple[TelegramMtprotoMediaHint, ...],
    *,
    provider_media_id: str,
    media_kind: str,
) -> TelegramMtprotoMediaHint | None:
    if media_kind not in {"voice", "audio"}:
        return None
    for hint in hints:
        if hint.media_kind == media_kind and hint.provider_media_id == provider_media_id:
            return hint
    return None


def _verified_voice_audio(
    message: object | None,
    peer_id: int,
    message_id: int,
    provider_media_id: str,
    media_kind: str,
) -> TelegramMtprotoMediaHint | None:
    if message is None:
        return None
    returned_peer = _peer_id_from_message_peer(getattr(message, "peer_id", None))
    returned_id = getattr(message, "id", None)
    if returned_peer != peer_id or returned_id != message_id:
        return None
    return select_voice_audio_hint(
        _media_hints(message),
        provider_media_id=provider_media_id,
        media_kind=media_kind,
    )


def _media_hints(message: object) -> tuple[TelegramMtprotoMediaHint, ...]:
    media = getattr(message, "media", None)
    if isinstance(media, types.MessageMediaPhoto):
        photo_id = getattr(getattr(media, "photo", None), "id", None)
        if not isinstance(photo_id, int) or isinstance(photo_id, bool) or photo_id <= 0:
            return ()
        return (
            TelegramMtprotoMediaHint(
                media_kind="photo",
                provider_media_id=str(photo_id),
                mime_type="image/jpeg",
            ),
        )
    if not isinstance(media, types.MessageMediaDocument):
        return ()
    document = getattr(media, "document", None)
    document_id = getattr(document, "id", None)
    if not isinstance(document_id, int) or isinstance(document_id, bool) or document_id <= 0:
        return ()
    kind = "document"
    duration: int | None = None
    filename: str | None = None
    sticker = False
    for attr in getattr(document, "attributes", None) or []:
        if isinstance(attr, types.DocumentAttributeAudio):
            kind = "voice" if bool(getattr(attr, "voice", False)) else "audio"
            duration = _bounded_duration(getattr(attr, "duration", None))
        elif isinstance(attr, types.DocumentAttributeVideo) and kind == "document":
            kind = "video"
            duration = _bounded_duration(getattr(attr, "duration", None))
        elif isinstance(attr, types.DocumentAttributeFilename):
            raw_name = getattr(attr, "file_name", None)
            if isinstance(raw_name, str) and raw_name.strip():
                filename = raw_name.strip()[:200]
        elif isinstance(attr, types.DocumentAttributeSticker):
            sticker = True
    if sticker and kind == "document":
        return ()
    mime = getattr(document, "mime_type", None)
    mime_type = mime.strip()[:200] if isinstance(mime, str) and mime.strip() else None
    size = getattr(document, "size", None)
    bounded_size = size if isinstance(size, int) and not isinstance(size, bool) and 0 <= size <= 2_000_000_000 else None
    return (
        TelegramMtprotoMediaHint(
            media_kind=kind,
            provider_media_id=str(document_id),
            filename=filename,
            mime_type=mime_type,
            size=bounded_size,
            duration_seconds=duration,
        ),
    )


def _bounded_duration(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > 86_400:
        return None
    return value


def _peer_id_from_message(message: object) -> int | None:
    sender_id = _positive_or_negative_int(getattr(message, "sender_id", None))
    if sender_id is not None:
        return sender_id
    sender_peer = getattr(message, "from_id", None)
    if sender_peer is None:
        return None
    try:
        peer_id = utils.get_peer_id(sender_peer)
    except (TypeError, ValueError):
        return None
    return _positive_or_negative_int(peer_id)


def _peer_id_from_message_peer(peer: object) -> int | None:
    if peer is None:
        return None
    try:
        return _positive_or_negative_int(utils.get_peer_id(peer))
    except (TypeError, ValueError):
        return None


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _positive_or_negative_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value != 0:
        return value
    return None


def _history_datetime(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _bound_history_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized[:MAX_TELEGRAM_MESSAGE_BODY_CHARS]


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
