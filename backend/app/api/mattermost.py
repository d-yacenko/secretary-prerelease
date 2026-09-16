from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.connectors.mattermost.credentials import MattermostAccountStore
from app.connectors.mattermost.errors import (
    MattermostConfigurationError,
    MattermostConnectorError,
    MattermostSecurityError,
    MattermostUnauthorizedError,
)
from app.connectors.mattermost.normalize import (
    parse_allowed_base_urls,
    validate_server_url_allowlist,
)
from app.connectors.mattermost.transport import MattermostHttpTransport
from app.core.config import settings
from app.core.current_user import CurrentUserContext
from app.jobs.constants import JOB_TYPE_SYNC_MATTERMOST
from app.services.job_queue_service import JobQueueService

router = APIRouter(tags=["mattermost"])


class MattermostConnectRequest(BaseModel):
    server_url: str = Field(min_length=8, max_length=2048)
    access_token: str = Field(min_length=1, max_length=4096)


def _account_store(session: Session) -> MattermostAccountStore:
    encryption = MattermostAccountStore.build_encryption(settings.secretary_credential_key)
    return MattermostAccountStore(session, encryption)


def _allowed_base_urls() -> frozenset[str]:
    return parse_allowed_base_urls(settings.mattermost_allowed_base_urls)


@router.post("/connectors/mattermost/connect")
def mattermost_connect(
    body: MattermostConnectRequest,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> dict[str, Any]:
    transport: MattermostHttpTransport | None = None
    try:
        normalized_server_url = validate_server_url_allowlist(
            body.server_url,
            _allowed_base_urls(),
        )
        transport = MattermostHttpTransport(
            base_url=normalized_server_url,
            access_token=body.access_token,
        )
        me = transport.get_me()
        remote_user_id = str(me.get("id") or "").strip()
        username = str(me.get("username") or "").strip()
        if not remote_user_id or not username:
            raise MattermostConnectorError("mattermost user profile incomplete")

        display_name = str(me.get("display_name") or "").strip() or None
        email = str(me.get("email") or "").strip() or None

        account_store = _account_store(session)
        account = account_store.upsert_account(
            user_id=current_user.user_id,
            normalized_server_url=normalized_server_url,
            remote_user_id=remote_user_id,
            username=username,
            access_token=body.access_token,
            display_name=display_name,
            email=email,
        )
        queue = JobQueueService(session)
        queue.ensure_recurring_source_job(
            JOB_TYPE_SYNC_MATTERMOST,
            account.id,
            current_user.user_id,
        )
        queue.trigger_recurring_source_job(
            current_user.user_id,
            JOB_TYPE_SYNC_MATTERMOST,
            account.id,
        )
        session.commit()
    except MattermostConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message)
    except MattermostSecurityError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
    except MattermostUnauthorizedError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message)
    except MattermostConnectorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
    finally:
        if transport is not None:
            transport.close()

    return {
        "status": "connected",
        "account_id": str(account.id),
        "server_url": account.server_url,
        "remote_user_id": account.remote_user_id,
        "username": account.username,
        "display_name": account.display_name,
        "email": account.email,
    }
