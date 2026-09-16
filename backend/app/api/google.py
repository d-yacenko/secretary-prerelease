from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.connectors.google.calendar_sync import build_calendar_sync_service
from app.connectors.google.constants import GOOGLE_OAUTH_SCOPES
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.errors import (
    GoogleConfigurationError,
    GoogleConnectorError,
    GoogleOAuthError,
)
from app.connectors.google.gmail_sync import build_gmail_sync_service
from app.connectors.google.gmail_transport import GmailTransport
from app.connectors.google.oauth_service import GoogleOAuthService, parse_token_expiry
from app.connectors.google.oauth_state import OAuthStateService
from app.core.config import settings
from app.core.current_user import CurrentUserContext
from app.services.source_sync_preference_service import SourceSyncPreferenceService
from app.source_sync.constants import SOURCE_GMAIL, SOURCE_GOOGLE_CALENDAR

router = APIRouter(tags=["google"])


class GoogleAuthorizationUrlOut(BaseModel):
    authorization_url: str


def _start_google_oauth(session: Session, user_id: UUID) -> str:
    oauth_service = _google_oauth_service()
    state_service = OAuthStateService(session)
    state = state_service.create_state(user_id)
    session.commit()
    return oauth_service.build_authorization_url(state)


def _google_oauth_service() -> GoogleOAuthService:
    return GoogleOAuthService(
        client_file=settings.google_oauth_client_file,
        redirect_uri=settings.google_redirect_uri,
    )


def _account_store(session: Session) -> GoogleAccountStore:
    encryption = GoogleAccountStore.build_encryption(settings.secretary_credential_key)
    return GoogleAccountStore(session, encryption)


@router.get("/auth/google/start")
def google_oauth_start(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> RedirectResponse:
    try:
        url = _start_google_oauth(session, current_user.user_id)
    except GoogleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message)

    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.post("/auth/google/authorization-url")
def google_oauth_authorization_url(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> GoogleAuthorizationUrlOut:
    try:
        url = _start_google_oauth(session, current_user.user_id)
    except GoogleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message)

    return GoogleAuthorizationUrlOut(authorization_url=url)


@router.get("/auth/google/callback")
def google_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing oauth parameters")

    try:
        state_service = OAuthStateService(session)
        owner_user_id = state_service.consume_state(state)
        session.commit()

        oauth_service = _google_oauth_service()
        token_payload = oauth_service.exchange_code(code)
        access_token = str(token_payload["access_token"])
        refresh_token = token_payload.get("refresh_token")
        token_expiry = parse_token_expiry(token_payload.get("expires_in"))
        granted_scope = token_payload.get("scope")
        scopes = str(granted_scope).split() if granted_scope else list(GOOGLE_OAUTH_SCOPES)

        gmail_transport = GmailTransport()
        email = gmail_transport.fetch_account_email(access_token)

        account_store = _account_store(session)
        account = account_store.upsert_tokens(
            user_id=owner_user_id,
            email=email,
            scopes=scopes,
            access_token=access_token,
            refresh_token=str(refresh_token) if refresh_token else None,
            token_expiry=token_expiry,
        )
        session.commit()
    except GoogleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message)
    except GoogleOAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
    except GoogleConnectorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)

    return {
        "status": "connected",
        "email": account.email,
        "scopes": account.scopes,
    }


@router.post("/connectors/google/gmail/sync")
def gmail_sync(
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="google account not found")

        history_days = SourceSyncPreferenceService.build(session).effective_history_days_for_source(
            current_user.user_id,
            SOURCE_GMAIL,
        )
        sync_service = build_gmail_sync_service(
            session=session,
            credential_key=settings.secretary_credential_key,
            client_file=settings.google_oauth_client_file,
            redirect_uri=settings.google_redirect_uri,
            sync_days=history_days,
            default_limit=settings.gmail_sync_default_limit,
            max_limit=settings.gmail_sync_max_limit,
        )
        result = sync_service.sync_account(
            account.id,
            user_id=current_user.user_id,
            limit=limit,
        )
    except GoogleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message)
    except GoogleConnectorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)

    return result


@router.post("/connectors/google/calendar/sync")
def calendar_sync(
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="google account not found")

        history_days = SourceSyncPreferenceService.build(session).effective_history_days_for_source(
            current_user.user_id,
            SOURCE_GOOGLE_CALENDAR,
        )
        sync_service = build_calendar_sync_service(
            session=session,
            credential_key=settings.secretary_credential_key,
            client_file=settings.google_oauth_client_file,
            redirect_uri=settings.google_redirect_uri,
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
        )
    except GoogleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message)
    except GoogleConnectorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)

    return result
