from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.connectors.google.errors import GoogleConfigurationError
from app.connectors.yandex.caldav_api_errors import format_yandex_caldav_error
from app.connectors.yandex.caldav_host import trusted_caldav_base_url
from app.connectors.yandex.caldav_transport import CalDavHttpTransport
from app.connectors.yandex.calendar_credentials import YandexCalendarAccountStore
from app.connectors.yandex.calendar_sync import build_yandex_calendar_sync_service
from app.connectors.yandex.constants import (
    DEFAULT_CALDAV_HOST,
    DEFAULT_IMAP_HOST,
    DEFAULT_IMAP_PORT,
)
from app.connectors.yandex.credentials import YandexMailAccountStore
from app.connectors.yandex.errors import (
    YandexCalDavError,
    YandexConfigurationError,
    YandexConnectorError,
)
from app.connectors.yandex.mail_sync import build_yandex_mail_sync_service
from app.core.config import settings
from app.core.current_user import CurrentUserContext
from app.services.source_sync_preference_service import SourceSyncPreferenceService
from app.source_sync.constants import SOURCE_YANDEX_CALENDAR, SOURCE_YANDEX_MAIL

router = APIRouter(tags=["yandex"])


class YandexMailConnectRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    app_password: str
    imap_host: str = DEFAULT_IMAP_HOST
    imap_port: int = DEFAULT_IMAP_PORT


class YandexCalendarConnectRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    app_password: str
    caldav_host: str = DEFAULT_CALDAV_HOST


def _mail_account_store(session: Session) -> YandexMailAccountStore:
    encryption = YandexMailAccountStore.build_encryption(settings.secretary_credential_key)
    return YandexMailAccountStore(session, encryption)


def _calendar_account_store(session: Session) -> YandexCalendarAccountStore:
    encryption = YandexCalendarAccountStore.build_encryption(settings.secretary_credential_key)
    return YandexCalendarAccountStore(session, encryption)


def _account_store(session: Session) -> YandexMailAccountStore:
    return _mail_account_store(session)


def _validate_yandex_calendar_credentials(
    email: str,
    app_password: str,
    caldav_host: str,
) -> None:
    transport = CalDavHttpTransport(
        email=email,
        password=app_password,
        base_url=trusted_caldav_base_url(caldav_host),
    )
    transport.probe_principal()


@router.post("/connectors/yandex/mail/connect")
def yandex_mail_connect(
    body: YandexMailConnectRequest,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        account_store = _account_store(session)
        account = account_store.upsert_account(
            user_id=current_user.user_id,
            email=str(body.email),
            app_password=body.app_password,
            imap_host=body.imap_host,
            imap_port=body.imap_port,
        )
        session.commit()
    except (GoogleConfigurationError, YandexConfigurationError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message)

    return {
        "status": "connected",
        "account_id": str(account.id),
        "email": account.email,
        "imap_host": account.imap_host,
        "imap_port": account.imap_port,
    }


@router.post("/connectors/yandex/mail/sync")
def yandex_mail_sync(
    account_id: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=100),
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        account_store = _account_store(session)
        if account_id:
            account = account_store.get_by_id_for_user(UUID(account_id), current_user.user_id)
        else:
            accounts = account_store.list_accounts(current_user.user_id)
            account = accounts[0] if accounts else None
        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="yandex mail account not found")

        history_days = SourceSyncPreferenceService.build(session).effective_history_days_for_source(
            current_user.user_id,
            SOURCE_YANDEX_MAIL,
        )
        sync_service = build_yandex_mail_sync_service(
            session=session,
            credential_key=settings.secretary_credential_key,
            sync_days=history_days,
            default_limit=settings.yandex_mail_sync_default_limit,
            max_limit=settings.yandex_mail_sync_max_limit,
        )
        result = sync_service.sync_account(
            account.id,
            user_id=current_user.user_id,
            limit=limit,
        )
    except (GoogleConfigurationError, YandexConfigurationError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message)
    except YandexConnectorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)

    return result


@router.post("/connectors/yandex/calendar/connect")
def yandex_calendar_connect(
    body: YandexCalendarConnectRequest,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        trusted_caldav_base_url(body.caldav_host)
    except YandexConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)

    try:
        _validate_yandex_calendar_credentials(
            str(body.email),
            body.app_password,
            body.caldav_host,
        )
        account_store = _calendar_account_store(session)
        account = account_store.upsert_account(
            user_id=current_user.user_id,
            email=str(body.email),
            app_password=body.app_password,
            caldav_host=body.caldav_host,
        )
        session.commit()
    except (GoogleConfigurationError, YandexConfigurationError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message)
    except YandexCalDavError as exc:
        detail = format_yandex_caldav_error(exc)
        if exc.retryable:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    return {
        "status": "connected",
        "account_id": str(account.id),
        "email": account.email,
        "caldav_host": account.caldav_host,
    }


@router.post("/connectors/yandex/calendar/sync")
def yandex_calendar_sync(
    account_id: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=100),
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        account_store = _calendar_account_store(session)
        if account_id:
            account = account_store.get_by_id_for_user(UUID(account_id), current_user.user_id)
        else:
            accounts = account_store.list_accounts(current_user.user_id)
            account = accounts[0] if accounts else None
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="yandex calendar account not found",
            )

        history_days = SourceSyncPreferenceService.build(session).effective_history_days_for_source(
            current_user.user_id,
            SOURCE_YANDEX_CALENDAR,
        )
        sync_service = build_yandex_calendar_sync_service(
            session=session,
            credential_key=settings.secretary_credential_key,
            days_back=history_days,
            days_forward=settings.calendar_sync_days_forward,
            default_limit=settings.calendar_sync_default_limit,
            max_limit=settings.calendar_sync_max_limit,
            max_calendars=settings.calendar_sync_max_calendars,
        )
        result = sync_service.sync_account(
            account.id,
            user_id=current_user.user_id,
            limit=limit,
            include_history_pass=False,
        )
    except (GoogleConfigurationError, YandexConfigurationError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message)
    except YandexConnectorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)

    return result
