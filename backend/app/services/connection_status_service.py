from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.connectors.google.constants import (
    CALENDAR_READONLY_SCOPE,
    DRIVE_READONLY_SCOPE,
    GMAIL_READONLY_SCOPE,
)
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.mattermost.credentials import MattermostAccountStore
from app.connectors.teams.account_store import TeamsAccountStore
from app.connectors.teams.config import teams_is_configured
from app.connectors.teams.constants import AUTH_STATUS_RECONNECT_REQUIRED
from app.connectors.yandex.calendar_credentials import YandexCalendarAccountStore
from app.connectors.yandex.credentials import YandexMailAccountStore
from app.core.config import settings


@dataclass(frozen=True)
class GoogleConnectionStatus:
    connected: bool
    email: str | None = None
    gmail_available: bool = False
    calendar_available: bool = False
    drive_available: bool = False


@dataclass(frozen=True)
class YandexMailConnectionStatus:
    connected: bool
    email: str | None = None


@dataclass(frozen=True)
class YandexCalendarConnectionStatus:
    connected: bool
    email: str | None = None


@dataclass(frozen=True)
class MattermostConnectionStatus:
    account_id: UUID
    server_url: str
    remote_user_id: str
    username: str
    display_name: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class TelegramConnectionStatus:
    configured: bool = False
    identity_linked: bool = False
    business_connected: bool = False
    can_reply: bool = False
    telegram_username: str | None = None
    display_name: str | None = None
    bot_username: str | None = None


@dataclass(frozen=True)
class TeamsConnectionStatus:
    configured: bool = False
    connected: bool = False
    reconnect_required: bool = False
    display_name: str | None = None
    upn: str | None = None
    tenant_id: str | None = None


@dataclass(frozen=True)
class ConnectionStatusSnapshot:
    google: GoogleConnectionStatus
    yandex_mail: YandexMailConnectionStatus
    yandex_calendar: YandexCalendarConnectionStatus
    mattermost: list[MattermostConnectionStatus]
    telegram: TelegramConnectionStatus
    teams: TeamsConnectionStatus


class ConnectionStatusService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def snapshot(self) -> ConnectionStatusSnapshot:
        google = self._google_status()
        yandex_mail = self._yandex_mail_status()
        yandex_calendar = self._yandex_calendar_status()
        mattermost = self._mattermost_accounts()
        telegram = self._telegram_status()
        teams = self._teams_status()
        return ConnectionStatusSnapshot(
            google=google,
            yandex_mail=yandex_mail,
            yandex_calendar=yandex_calendar,
            mattermost=mattermost,
            telegram=telegram,
            teams=teams,
        )

    def _google_status(self) -> GoogleConnectionStatus:
        if not settings.secretary_credential_key:
            return GoogleConnectionStatus(connected=False)
        encryption = CredentialEncryption(settings.secretary_credential_key)
        store = GoogleAccountStore(self._session, encryption)
        accounts = store.list_accounts(self._user_id)
        if not accounts:
            return GoogleConnectionStatus(connected=False)
        account = accounts[0]
        scopes = set(account.scopes or [])
        return GoogleConnectionStatus(
            connected=True,
            email=account.email,
            gmail_available=GMAIL_READONLY_SCOPE in scopes,
            calendar_available=CALENDAR_READONLY_SCOPE in scopes,
            drive_available=DRIVE_READONLY_SCOPE in scopes,
        )

    def _yandex_mail_status(self) -> YandexMailConnectionStatus:
        if not settings.secretary_credential_key:
            return YandexMailConnectionStatus(connected=False)
        encryption = CredentialEncryption(settings.secretary_credential_key)
        store = YandexMailAccountStore(self._session, encryption)
        accounts = store.list_accounts(self._user_id)
        if not accounts:
            return YandexMailConnectionStatus(connected=False)
        return YandexMailConnectionStatus(connected=True, email=accounts[0].email)

    def _yandex_calendar_status(self) -> YandexCalendarConnectionStatus:
        if not settings.secretary_credential_key:
            return YandexCalendarConnectionStatus(connected=False)
        encryption = CredentialEncryption(settings.secretary_credential_key)
        store = YandexCalendarAccountStore(self._session, encryption)
        accounts = store.list_accounts(self._user_id)
        if not accounts:
            return YandexCalendarConnectionStatus(connected=False)
        return YandexCalendarConnectionStatus(connected=True, email=accounts[0].email)

    def _mattermost_accounts(self) -> list[MattermostConnectionStatus]:
        if not settings.secretary_credential_key:
            return []
        encryption = CredentialEncryption(settings.secretary_credential_key)
        store = MattermostAccountStore(self._session, encryption)
        return [
            MattermostConnectionStatus(
                account_id=account.id,
                server_url=account.server_url,
                remote_user_id=account.remote_user_id,
                username=account.username,
                display_name=account.display_name,
                email=account.email,
            )
            for account in store.list_accounts(self._user_id)
        ]

    def _telegram_status(self) -> TelegramConnectionStatus:
        # Bot API is retired; preserve the response shape while keeping the
        # legacy transport inactive and independent of Bot credentials/rows.
        return TelegramConnectionStatus()

    def _teams_status(self) -> TeamsConnectionStatus:
        configured = teams_is_configured()
        if not settings.secretary_credential_key:
            return TeamsConnectionStatus(configured=configured)
        store = TeamsAccountStore(
            self._session,
            TeamsAccountStore.build_encryption(settings.secretary_credential_key),
        )
        account = store.get_by_user_id(self._user_id)
        if account is None:
            return TeamsConnectionStatus(configured=configured)
        return TeamsConnectionStatus(
            configured=configured,
            connected=True,
            reconnect_required=account.auth_status == AUTH_STATUS_RECONNECT_REQUIRED,
            display_name=account.display_name,
            upn=account.upn,
            tenant_id=account.tenant_id,
        )
