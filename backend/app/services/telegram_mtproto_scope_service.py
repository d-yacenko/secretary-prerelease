"""Telegram folder configuration and read-only dynamic sync scope."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleConfigurationError
from app.connectors.telegram.mtproto_account_store import TelegramMtprotoAccountStore
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoAccountNotConnectedError,
    TelegramMtprotoFolderConfigurationError,
    TelegramMtprotoScopeUnavailableError,
)
from app.connectors.telegram.mtproto_transport import (
    DISCOVERY_DIALOG_LIMIT,
    TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT,
    TelegramMtprotoDialogDescriptor,
    TelegramMtprotoFolderDescriptor,
    TelegramMtprotoTransport,
    TelethonMtprotoTransport,
    dialog_matches_filter,
)
from app.core.config import settings
from app.db.models import TelegramMtprotoSyncFolder


@dataclass(frozen=True)
class TelegramMtprotoFolder:
    folder_id: int
    name: str


@dataclass(frozen=True)
class TelegramMtprotoFoldersResult:
    folders: tuple[TelegramMtprotoFolder, ...]
    truncated: bool


@dataclass(frozen=True)
class TelegramMtprotoConfiguredFolder:
    folder_id: int
    name: str
    ignore_muted: bool


@dataclass(frozen=True)
class TelegramMtprotoScopeResult:
    dialogs: tuple[TelegramMtprotoDialogDescriptor, ...]
    truncated: bool
    skipped_counts: dict[str, int]
    configured_folder_count: int


@dataclass(frozen=True)
class TelegramMtprotoScopeReconcileResult:
    scope: TelegramMtprotoScopeResult
    active: int
    activated: int
    deactivated: int
    unchanged: int


class TelegramMtprotoScopeService:
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

    async def list_available_folders(self, user_id: UUID) -> TelegramMtprotoFoldersResult:
        _, _, session = self._account_context(user_id)
        result = await self._transport_factory().discover_folders(session, DISCOVERY_DIALOG_LIMIT)
        return TelegramMtprotoFoldersResult(
            tuple(_folder_out(folder) for folder in result.folders), result.truncated
        )

    def configured_folders(self, user_id: UUID) -> tuple[TelegramMtprotoConfiguredFolder, ...]:
        account, store, _ = self._account_context(user_id)
        return tuple(
            TelegramMtprotoConfiguredFolder(item.folder_id, item.folder_name, item.ignore_muted)
            for item in store.list_sync_folders(account.id)
        )

    async def replace_folders(
        self, user_id: UUID, names: Sequence[str], *, ignore_muted: bool = True
    ) -> tuple[TelegramMtprotoConfiguredFolder, ...]:
        if not ignore_muted:
            raise TelegramMtprotoFolderConfigurationError("muted dialogs must remain excluded")
        normalized = [name.strip() for name in names]
        if any(not name for name in normalized) or len(set(normalized)) != len(normalized):
            raise TelegramMtprotoFolderConfigurationError("Telegram folder names must be non-blank and unique")
        account, store, session = self._account_context(user_id)
        if not normalized:
            return tuple(_configured_out(item) for item in store.replace_sync_folders(account.id, []))
        discovery = await self._transport_factory().discover_folders(session, DISCOVERY_DIALOG_LIMIT)
        by_name: dict[str, list[TelegramMtprotoFolderDescriptor]] = {}
        for folder in discovery.folders:
            by_name.setdefault(folder.name, []).append(folder)
        resolved: list[tuple[int, str]] = []
        for name in normalized:
            matches = by_name.get(name, [])
            if len(matches) != 1:
                raise TelegramMtprotoFolderConfigurationError("Telegram folder configuration could not be resolved")
            resolved.append((matches[0].folder_id, matches[0].name))
        return tuple(_configured_out(item) for item in store.replace_sync_folders(account.id, resolved))

    async def preview_scope(self, user_id: UUID) -> TelegramMtprotoScopeResult:
        account, store, session = self._account_context(user_id)
        configured = store.list_sync_folders(account.id)
        if not configured:
            return TelegramMtprotoScopeResult((), False, {}, 0)
        discovery = await self._transport_factory().discover_folders(session, DISCOVERY_DIALOG_LIMIT)
        current_by_id = {folder.folder_id: folder for folder in discovery.folders}
        if any(item.folder_id not in current_by_id for item in configured):
            raise TelegramMtprotoScopeUnavailableError("Telegram configured folder is no longer available")
        store.refresh_sync_folder_names(
            account.id, {folder_id: folder.name for folder_id, folder in current_by_id.items()}
        )
        dialogs: dict[int, TelegramMtprotoDialogDescriptor] = {}
        skipped: dict[str, int] = {}
        truncated = discovery.truncated
        universe = await self._transport_factory().fetch_dialog_universe(
            session, TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT
        )
        truncated = truncated or universe.truncated
        for key, value in universe.skipped_counts.items():
            skipped[key] = skipped.get(key, 0) + value
        for dialog in universe.dialogs:
            if not dialog.is_muted and any(
                dialog_matches_filter(current_by_id[item.folder_id].definition, dialog)
                for item in configured
            ):
                dialogs.setdefault(dialog.peer_id, dialog)
        return TelegramMtprotoScopeResult(tuple(dialogs.values()), truncated, skipped, len(configured))

    async def reconcile_scope(self, user_id: UUID) -> TelegramMtprotoScopeReconcileResult:
        result = await self.preview_scope(user_id)
        if result.truncated:
            raise TelegramMtprotoScopeUnavailableError(
                "Telegram sync scope could not be reconciled completely"
            )
        account, store, _ = self._account_context(user_id)
        active, activated, deactivated, unchanged = store.reconcile_scope(
            account.id, list(result.dialogs)
        )
        return TelegramMtprotoScopeReconcileResult(
            scope=result,
            active=active,
            activated=activated,
            deactivated=deactivated,
            unchanged=unchanged,
        )

    def _account_context(self, user_id: UUID):
        store = TelegramMtprotoAccountStore(self._session, self._encryption_or_raise())
        account = store.get_by_user_id(user_id)
        if account is None:
            raise TelegramMtprotoAccountNotConnectedError("Telegram MTProto account is not connected")
        try:
            session = store.decrypt_session(account)
        except GoogleConfigurationError as exc:
            raise TelegramMtprotoFolderConfigurationError("Telegram MTProto is not configured") from exc
        return account, store, session

    def _encryption_or_raise(self) -> CredentialEncryption:
        if self._encryption is not None:
            return self._encryption
        if not settings.secretary_credential_key.strip():
            raise TelegramMtprotoFolderConfigurationError("Telegram MTProto is not configured")
        try:
            return CredentialEncryption(settings.secretary_credential_key)
        except GoogleConfigurationError as exc:
            raise TelegramMtprotoFolderConfigurationError("Telegram MTProto is not configured") from exc


def _folder_out(folder: TelegramMtprotoFolderDescriptor) -> TelegramMtprotoFolder:
    return TelegramMtprotoFolder(folder.folder_id, folder.name)


def _configured_out(folder: TelegramMtprotoSyncFolder) -> TelegramMtprotoConfiguredFolder:
    return TelegramMtprotoConfiguredFolder(folder.folder_id, folder.folder_name, folder.ignore_muted)


def _build_transport() -> TelegramMtprotoTransport:
    if settings.telegram_api_id <= 0 or not settings.telegram_api_hash.strip():
        raise TelegramMtprotoFolderConfigurationError("Telegram MTProto is not configured")
    return TelethonMtprotoTransport(settings.telegram_api_id, settings.telegram_api_hash.strip())
