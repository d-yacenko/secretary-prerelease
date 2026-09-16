from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.connectors.teams.account_store import TeamsAccountStore
from app.connectors.teams.config import teams_is_configured
from app.connectors.teams.errors import (
    TeamsConfigurationError,
    TeamsConnectorError,
    TeamsIdentityConflictError,
    TeamsIdentitySwitchError,
    TeamsOAuthError,
    TeamsReconnectRequiredError,
)
from app.connectors.teams.oauth_service import TeamsOAuthService
from app.connectors.teams.oauth_state import TeamsOAuthStateService
from app.connectors.teams.subscriptions import TeamsSubscriptionService
from app.connectors.teams.token_service import TeamsTokenService
from app.connectors.teams.transport import TeamsHttpTransport
from app.core.config import settings
from app.core.current_user import CurrentUserContext
from app.jobs.constants import JOB_TYPE_SYNC_TEAMS
from app.services.job_queue_service import JobQueueService
from app.services.source_sync_preference_service import SourceSyncPreferenceService
from app.source_sync.constants import SOURCE_TEAMS

router = APIRouter(tags=["teams"])


class TeamsAuthorizationUrlOut(BaseModel):
    authorization_url: str


class TeamsDisconnectOut(BaseModel):
    status: str


def _teams_oauth_service() -> TeamsOAuthService:
    return TeamsOAuthService(
        settings.microsoft_oauth_client_id,
        settings.microsoft_oauth_client_secret,
        settings.microsoft_redirect_uri,
    )


def _account_store(session: Session) -> TeamsAccountStore:
    return TeamsAccountStore(
        session,
        TeamsAccountStore.build_encryption(settings.secretary_credential_key),
    )


def _start_teams_oauth(session: Session, user_id: UUID) -> str:
    if not teams_is_configured():
        raise TeamsConfigurationError("Microsoft Teams is not configured")
    oauth_service = _teams_oauth_service()
    created = TeamsOAuthStateService(session).create_state(user_id)
    session.flush()
    return oauth_service.build_authorization_url(created.state, created.nonce)


def _enable_teams_sync(session: Session, user_id: UUID, account_id: UUID) -> None:
    SourceSyncPreferenceService.build(session).get_effective_preference(
        user_id, SOURCE_TEAMS
    )
    JobQueueService(session).ensure_recurring_source_job(
        JOB_TYPE_SYNC_TEAMS, account_id, user_id
    )
    JobQueueService(session).trigger_recurring_source_job(
        user_id, JOB_TYPE_SYNC_TEAMS, account_id
    )


def _disable_teams_sync(session: Session, user_id: UUID, account_id: UUID) -> None:
    job = JobQueueService(session).find_recurring_source_job(
        user_id, JOB_TYPE_SYNC_TEAMS, account_id
    )
    if job is not None:
        JobQueueService(session).retire_recurring_source_job(job)


def _delete_teams_subscription(session: Session, account) -> None:
    store = _account_store(session)
    service = TeamsSubscriptionService(session, store)
    transport = None
    try:
        token = TeamsTokenService(session, store).acquire_access_token(account)
        transport = TeamsHttpTransport(token)
        service.delete_for_account(account, transport)
    except Exception:
        service.delete_for_account(account)
    finally:
        if transport is not None:
            transport.close()


@router.post("/auth/teams/authorization-url")
def teams_oauth_authorization_url(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TeamsAuthorizationUrlOut:
    try:
        url = _start_teams_oauth(session, current_user.user_id)
    except TeamsConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message)
    return TeamsAuthorizationUrlOut(authorization_url=url)


@router.post("/auth/teams/disconnect", response_model=TeamsDisconnectOut)
def teams_disconnect(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TeamsDisconnectOut:
    if not teams_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft Teams is not configured",
        )
    store = _account_store(session)
    account = store.get_by_user_id(current_user.user_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Microsoft Teams is not connected")
    _disable_teams_sync(session, current_user.user_id, account.id)
    _delete_teams_subscription(session, account)
    store.disconnect(current_user.user_id)
    return TeamsDisconnectOut(status="disconnected")


@router.get("/auth/teams/callback")
def teams_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing oauth parameters")
    try:
        if not teams_is_configured():
            raise TeamsConfigurationError("Microsoft Teams is not configured")
        consumed = TeamsOAuthStateService(session).consume_state(state)
        session.commit()
        oauth_service = _teams_oauth_service()
        login = oauth_service.complete_login(code, nonce_hash=consumed.nonce_hash)
        store = _account_store(session)
        try:
            account = store.upsert_tokens(
                consumed.user_id,
                microsoft_user_id=str(login["microsoft_user_id"]),
                tenant_id=str(login["tenant_id"]),
                upn=login.get("upn"),
                display_name=login.get("display_name"),
                scopes=list(login["scopes"]),
                access_token=str(login["access_token"]),
                refresh_token=str(login["refresh_token"]),
                token_expiry=login.get("token_expiry"),
            )
        except IntegrityError as exc:
            session.rollback()
            raise TeamsIdentityConflictError(
                "Microsoft Teams identity is already connected"
            ) from exc
        session.commit()
        _enable_teams_sync(session, consumed.user_id, account.id)
        session.commit()
    except TeamsConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message)
    except TeamsIdentityConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)
    except TeamsIdentitySwitchError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)
    except TeamsReconnectRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
    except TeamsOAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
    except TeamsConnectorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)

    return {
        "status": "connected",
        "display_name": account.display_name,
        "upn": account.upn,
        "tenant_id": account.tenant_id,
    }
