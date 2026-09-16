from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleConfigurationError
from app.connectors.telegram.mtproto_account_store import TelegramMtprotoAccountStore
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoAccountNotConnectedError,
    TelegramMtprotoConfigurationError,
    TelegramMtprotoGroupUnavailableError,
)
from app.connectors.telegram.mtproto_transport import (
    DISCOVERY_DIALOG_LIMIT,
    TelegramMtprotoGroupDescriptor,
    TelegramMtprotoGroupDiscoveryResult,
    TelegramMtprotoTransport,
    TelethonMtprotoTransport,
)
from app.core.config import settings
from app.db.models import TelegramMtprotoAccount, TelegramMtprotoChatSelection


@dataclass(frozen=True)
class TelegramMtprotoGroup:
    peer_id: int
    kind: str
    title: str
    username: str | None
    is_forum: bool
    selected: bool
    available: bool


@dataclass(frozen=True)
class TelegramMtprotoGroupsResult:
    groups: tuple[TelegramMtprotoGroup, ...]
    truncated: bool


class TelegramMtprotoGroupService:
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

    async def list_groups(self, user_id: UUID) -> TelegramMtprotoGroupsResult:
        store = self._store()
        account = self._account_or_raise(store, user_id)
        discovery = await self._discover(store, account)
        selections = store.list_selections(account.id)
        selected_by_peer = {selection.peer_id: selection for selection in selections}
        groups: list[TelegramMtprotoGroup] = []
        discovered_peer_ids: set[int] = set()
        for descriptor in discovery.groups:
            if descriptor.peer_id in discovered_peer_ids:
                continue
            discovered_peer_ids.add(descriptor.peer_id)
            groups.append(
                _group_from_descriptor(
                    descriptor, selected=descriptor.peer_id in selected_by_peer, available=True
                )
            )
        for selection in selections:
            if selection.peer_id not in discovered_peer_ids:
                groups.append(_group_from_selection(selection))
        return TelegramMtprotoGroupsResult(groups=tuple(groups), truncated=discovery.truncated)

    async def set_selection(
        self, user_id: UUID, peer_id: int, selected: bool
    ) -> TelegramMtprotoGroup | None:
        store = self._store()
        account = self._account_or_raise(store, user_id)
        if not selected:
            store.delete_selection(account.id, peer_id)
            return None

        discovery = await self._discover(store, account)
        descriptor = next(
            (item for item in discovery.groups if item.peer_id == peer_id),
            None,
        )
        if descriptor is None:
            raise TelegramMtprotoGroupUnavailableError("Telegram group is not available")
        store.save_selection(account.id, descriptor)
        return _group_from_descriptor(descriptor, selected=True, available=True)

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

    @staticmethod
    def _account_or_raise(
        store: TelegramMtprotoAccountStore, user_id: UUID
    ) -> TelegramMtprotoAccount:
        account = store.get_by_user_id(user_id)
        if account is None:
            raise TelegramMtprotoAccountNotConnectedError(
                "Telegram MTProto account is not connected"
            )
        return account

    async def _discover(
        self, store: TelegramMtprotoAccountStore, account: TelegramMtprotoAccount
    ) -> TelegramMtprotoGroupDiscoveryResult:
        try:
            session = store.decrypt_session(account)
        except GoogleConfigurationError as exc:
            raise TelegramMtprotoConfigurationError("Telegram MTProto is not configured") from exc
        return await self._transport_factory().discover_groups(session, DISCOVERY_DIALOG_LIMIT)


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


def _group_from_descriptor(
    descriptor: TelegramMtprotoGroupDescriptor, *, selected: bool, available: bool
) -> TelegramMtprotoGroup:
    return TelegramMtprotoGroup(
        peer_id=descriptor.peer_id,
        kind=descriptor.kind,
        title=descriptor.title,
        username=descriptor.username,
        is_forum=descriptor.is_forum,
        selected=selected,
        available=available,
    )


def _group_from_selection(selection: TelegramMtprotoChatSelection) -> TelegramMtprotoGroup:
    return TelegramMtprotoGroup(
        peer_id=selection.peer_id,
        kind=selection.peer_kind,
        title=selection.title,
        username=selection.username,
        is_forum=selection.is_forum,
        selected=True,
        available=False,
    )
