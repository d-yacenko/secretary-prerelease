from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.connectors.google.constants import EXPLICIT_LINK_MAX_URL_CHARS, GOOGLE_DRIVE_PROVIDER
from app.connectors.google.errors import GoogleConfigurationError, GoogleConnectorError
from app.connectors.yandex.constants import YANDEX_DISK_PROVIDER
from app.connectors.yandex.errors import YandexDiskApiError
from app.core.config import settings
from app.core.current_user import CurrentUserContext
from app.resources.constants import PROVIDER_WEB
from app.services.explicit_link_intake_errors import (
    AccountSelectionRequiredError,
    ExplicitLinkIntakeError,
)
from app.services.explicit_link_intake_service import (
    build_google_explicit_link_intake_service,
    build_yandex_explicit_link_intake_service,
)
from app.services.explicit_link_provider import detect_intake_provider
from app.services.web_explicit_link_intake_service import WebExplicitLinkIntakeService

router = APIRouter(tags=["intake"])


class IntakeLinkRequest(BaseModel):
    url: str = Field(min_length=1, max_length=EXPLICIT_LINK_MAX_URL_CHARS)
    account_id: UUID | None = None


class IntakeLinkResponse(BaseModel):
    object_id: UUID
    provider: str
    kind: str
    status: str
    content_status: str
    content_jobs_enqueued: int


@router.post("/intake/link", response_model=IntakeLinkResponse)
def intake_link(
    data: IntakeLinkRequest,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> IntakeLinkResponse:
    try:
        provider = detect_intake_provider(data.url)
    except ExplicitLinkIntakeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc

    if provider == YANDEX_DISK_PROVIDER:
        service = build_yandex_explicit_link_intake_service(
            session=session,
            user_id=current_user.user_id,
        )
    elif provider == GOOGLE_DRIVE_PROVIDER:
        if not settings.secretary_credential_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="credential encryption is not configured",
            )
        try:
            service = build_google_explicit_link_intake_service(
                session=session,
                user_id=current_user.user_id,
                credential_key=settings.secretary_credential_key,
                client_file=settings.google_oauth_client_file,
                redirect_uri=settings.google_redirect_uri,
            )
        except GoogleConfigurationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=exc.message,
            ) from exc
    elif provider == PROVIDER_WEB:
        service = WebExplicitLinkIntakeService(session=session, user_id=current_user.user_id)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported link url")

    try:
        result = service.intake_link(url=data.url, account_id=data.account_id)
        session.commit()
        return IntakeLinkResponse(
            object_id=result.object_id,
            provider=result.provider,
            kind=result.kind,
            status=result.status,
            content_status=result.content_status,
            content_jobs_enqueued=result.content_jobs_enqueued,
        )
    except AccountSelectionRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    except ExplicitLinkIntakeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    except GoogleConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc
    except GoogleConnectorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    except YandexDiskApiError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    finally:
        service.close()
