"""Deterministic Google/Yandex account resolution for universal external actions.

Legacy frozen send_email / create_calendar_event arguments without `provider`
are interpreted as Google only when frozen `account_email` uniquely identifies
an owned Google account for that capability and no owned Yandex account uses
the same email. Any other case fails closed and is never reinterpreted as Yandex.
Newly prepared actions always persist provider explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.connectors.google.constants import (
    CALENDAR_EVENTS_SCOPE,
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
)
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.yandex.calendar_credentials import YandexCalendarAccountStore
from app.connectors.yandex.credentials import YandexMailAccountStore
from app.core.config import settings
from app.db.models import GoogleAccount, YandexCalendarAccount, YandexMailAccount
from app.tools.schemas import ToolError

ExternalProvider = Literal["google", "yandex"]
ExternalCapability = Literal["send_email", "create_calendar_event"]

_NO_ACCOUNT = "no supported account connected"
_MULTI_ACCOUNT = "multiple accounts are connected; specify provider or account"
_MULTI_PROVIDER_EMAIL = "account exists on multiple providers; specify provider"
_LEGACY_AMBIGUOUS = "legacy action is missing provider; specify provider"
_GOOGLE_MISSING = "Google account is not connected"
_YANDEX_MISSING = "Yandex account is not connected"
_MULTI_GOOGLE = "multiple Google accounts are connected; specify account"
_MULTI_YANDEX = "multiple Yandex accounts are connected; specify account"
_RECONNECT_SEND = "Google must be reconnected to grant Gmail send permission"
_RECONNECT_CALENDAR = "Google must be reconnected to grant calendar write permission"


@dataclass(frozen=True)
class ResolvedExternalAccount:
    provider: ExternalProvider
    email: str


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip().lower()
    return stripped or None


def _encryption() -> CredentialEncryption:
    if not settings.secretary_credential_key:
        raise ToolError("credentials are not configured")
    return CredentialEncryption(settings.secretary_credential_key)


def _google_accounts(session: Session, user_id: UUID) -> list[GoogleAccount]:
    return GoogleAccountStore(session, _encryption()).list_accounts(user_id)


def _yandex_mail_accounts(session: Session, user_id: UUID) -> list[YandexMailAccount]:
    return YandexMailAccountStore(session, _encryption()).list_accounts(user_id)


def _yandex_calendar_accounts(session: Session, user_id: UUID) -> list[YandexCalendarAccount]:
    return YandexCalendarAccountStore(session, _encryption()).list_accounts(user_id)


def google_has_send_capability(account: GoogleAccount) -> bool:
    scopes = {str(scope) for scope in (account.scopes or [])}
    return GMAIL_SEND_SCOPE in scopes and GMAIL_READONLY_SCOPE in scopes


def google_has_calendar_write_capability(account: GoogleAccount) -> bool:
    scopes = {str(scope) for scope in (account.scopes or [])}
    return CALENDAR_EVENTS_SCOPE in scopes


def _google_capable(session: Session, user_id: UUID, capability: ExternalCapability) -> list[GoogleAccount]:
    accounts = _google_accounts(session, user_id)
    if capability == "send_email":
        return [account for account in accounts if google_has_send_capability(account)]
    return [account for account in accounts if google_has_calendar_write_capability(account)]


def _yandex_capable(
    session: Session, user_id: UUID, capability: ExternalCapability
) -> list[YandexMailAccount] | list[YandexCalendarAccount]:
    if capability == "send_email":
        return _yandex_mail_accounts(session, user_id)
    return _yandex_calendar_accounts(session, user_id)


def _match_google(accounts: list[GoogleAccount], email: str) -> list[GoogleAccount]:
    return [account for account in accounts if account.email.lower() == email]


def _match_yandex(
    accounts: list[YandexMailAccount] | list[YandexCalendarAccount], email: str
) -> list[YandexMailAccount] | list[YandexCalendarAccount]:
    return [account for account in accounts if account.email.lower() == email]


def _reconnect_message(capability: ExternalCapability) -> str:
    if capability == "send_email":
        return _RECONNECT_SEND
    return _RECONNECT_CALENDAR


def _zero_account_error(
    session: Session,
    user_id: UUID,
    capability: ExternalCapability,
    provider: ExternalProvider | None,
) -> ToolError:
    google_all = _google_accounts(session, user_id)
    if (provider == "google" or provider is None) and google_all and not _google_capable(
        session, user_id, capability
    ):
        return ToolError(_reconnect_message(capability))
    if provider == "google":
        return ToolError(_GOOGLE_MISSING)
    if provider == "yandex":
        return ToolError(_YANDEX_MISSING)
    return ToolError(_NO_ACCOUNT)


def resolve_external_account(
    session: Session,
    user_id: UUID,
    *,
    capability: ExternalCapability,
    provider: ExternalProvider | None,
    account_email: str | None,
) -> ResolvedExternalAccount:
    requested_email = _normalize_email(account_email)
    google_accounts = _google_capable(session, user_id, capability)
    yandex_accounts = _yandex_capable(session, user_id, capability)

    if provider == "google":
        candidates = google_accounts
        if requested_email:
            candidates = _match_google(candidates, requested_email)
        if not candidates:
            raise _zero_account_error(session, user_id, capability, "google")
        if len(candidates) > 1:
            raise ToolError(_MULTI_GOOGLE)
        return ResolvedExternalAccount(provider="google", email=candidates[0].email)

    if provider == "yandex":
        candidates = list(yandex_accounts)
        if requested_email:
            candidates = list(_match_yandex(candidates, requested_email))
        if not candidates:
            raise _zero_account_error(session, user_id, capability, "yandex")
        if len(candidates) > 1:
            raise ToolError(_MULTI_YANDEX)
        return ResolvedExternalAccount(provider="yandex", email=candidates[0].email)

    eligible: list[ResolvedExternalAccount] = [
        ResolvedExternalAccount(provider="google", email=account.email)
        for account in google_accounts
    ]
    eligible.extend(
        ResolvedExternalAccount(provider="yandex", email=account.email)
        for account in yandex_accounts
    )
    if requested_email:
        eligible = [
            item for item in eligible if item.email.lower() == requested_email
        ]
        if not eligible:
            raise _zero_account_error(session, user_id, capability, None)
        providers = {item.provider for item in eligible}
        if len(providers) > 1:
            raise ToolError(_MULTI_PROVIDER_EMAIL)
        if len(eligible) > 1:
            raise ToolError(_MULTI_ACCOUNT)
        return eligible[0]

    if not eligible:
        raise _zero_account_error(session, user_id, capability, None)
    if len(eligible) == 1:
        return eligible[0]
    google_only = all(item.provider == "google" for item in eligible)
    yandex_only = all(item.provider == "yandex" for item in eligible)
    if google_only:
        raise ToolError(_MULTI_GOOGLE)
    if yandex_only:
        raise ToolError(_MULTI_YANDEX)
    raise ToolError(_MULTI_ACCOUNT)


def interpret_legacy_frozen_provider(
    session: Session,
    user_id: UUID,
    *,
    capability: ExternalCapability,
    account_email: str,
) -> ExternalProvider:
    """Google-only compatibility for frozen plans that predate `provider`."""
    requested_email = _normalize_email(account_email)
    if requested_email is None:
        raise ToolError(_LEGACY_AMBIGUOUS)
    google_matches = _match_google(
        _google_capable(session, user_id, capability), requested_email
    )
    yandex_matches = list(
        _match_yandex(_yandex_capable(session, user_id, capability), requested_email)
    )
    if len(google_matches) == 1 and not yandex_matches:
        return "google"
    raise ToolError(_LEGACY_AMBIGUOUS)


def execution_provider(
    session: Session,
    user_id: UUID,
    *,
    capability: ExternalCapability,
    provider: ExternalProvider | None,
    account_email: str,
) -> ExternalProvider:
    if provider in {"google", "yandex"}:
        return provider
    return interpret_legacy_frozen_provider(
        session,
        user_id,
        capability=capability,
        account_email=account_email,
    )
