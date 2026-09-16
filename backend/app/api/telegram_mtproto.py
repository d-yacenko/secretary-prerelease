from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, Response

from app.api.deps import get_current_user, get_db
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoChallengeExpiredError,
    TelegramMtprotoChallengeNotFoundError,
    TelegramMtprotoConfigurationError,
    TelegramMtprotoIdentityConflictError,
    TelegramMtprotoInvalidCodeError,
    TelegramMtprotoInvalidPasswordError,
    TelegramMtprotoInvalidPhoneError,
    TelegramMtprotoProviderUnavailableError,
)
from app.core.current_user import CurrentUserContext
from app.services.telegram_mtproto_auth_service import (
    TelegramMtprotoAccountSummary,
    TelegramMtprotoAuthService,
    mtproto_is_configured,
)

INVALID_MTPROTO_REQUEST_DETAIL = "Invalid Telegram MTProto request"


class TelegramMtprotoRoute(APIRoute):
    def get_route_handler(self):
        route_handler = super().get_route_handler()

        async def handle(request) -> Response:
            try:
                return await route_handler(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    content={"detail": INVALID_MTPROTO_REQUEST_DETAIL},
                )

        return handle


router = APIRouter(route_class=TelegramMtprotoRoute, tags=["telegram-mtproto"])


class TelegramMtprotoAuthStartIn(BaseModel):
    phone: str = Field(min_length=1, max_length=32, strict=True)


class TelegramMtprotoAuthStartOut(BaseModel):
    challenge_id: UUID
    expires_at: datetime


class TelegramMtprotoCodeIn(BaseModel):
    challenge_id: UUID
    code: str = Field(min_length=1, max_length=32, strict=True)


class TelegramMtprotoPasswordIn(BaseModel):
    challenge_id: UUID
    password: str = Field(min_length=1, max_length=256, strict=True)


class TelegramMtprotoAccountOut(BaseModel):
    id: UUID
    telegram_user_id: int
    username: str | None
    display_name: str | None


class TelegramMtprotoCodeOut(BaseModel):
    status: Literal["authorized", "password_required"]
    account: TelegramMtprotoAccountOut | None = None


class TelegramMtprotoStatusOut(BaseModel):
    configured: bool
    connected: bool
    account: TelegramMtprotoAccountOut | None = None


@router.post("/telegram/mtproto/auth/start", response_model=TelegramMtprotoAuthStartOut)
async def telegram_mtproto_auth_start(
    payload: TelegramMtprotoAuthStartIn,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoAuthStartOut:
    _require_configured()
    try:
        challenge = await TelegramMtprotoAuthService(session).start(
            current_user.user_id, payload.phone
        )
    except TelegramMtprotoConfigurationError as exc:
        raise _configuration_response() from exc
    except TelegramMtprotoInvalidPhoneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    except TelegramMtprotoProviderUnavailableError as exc:
        raise _provider_response(exc) from exc
    return TelegramMtprotoAuthStartOut(
        challenge_id=challenge.id,
        expires_at=challenge.expires_at,
    )


@router.post("/telegram/mtproto/auth/code", response_model=TelegramMtprotoCodeOut)
async def telegram_mtproto_auth_code(
    payload: TelegramMtprotoCodeIn,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoCodeOut:
    _require_configured()
    try:
        result = await TelegramMtprotoAuthService(session).submit_code(
            current_user.user_id, payload.challenge_id, payload.code
        )
    except TelegramMtprotoChallengeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except TelegramMtprotoChallengeExpiredError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=exc.message) from exc
    except TelegramMtprotoInvalidCodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    except TelegramMtprotoIdentityConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoProviderUnavailableError as exc:
        raise _provider_response(exc) from exc
    except TelegramMtprotoConfigurationError as exc:
        raise _configuration_response() from exc
    return TelegramMtprotoCodeOut(
        status=result.status,
        account=_account_out(result.account),
    )


@router.post("/telegram/mtproto/auth/password", response_model=TelegramMtprotoAccountOut)
async def telegram_mtproto_auth_password(
    payload: TelegramMtprotoPasswordIn,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoAccountOut:
    _require_configured()
    try:
        account = await TelegramMtprotoAuthService(session).submit_password(
            current_user.user_id, payload.challenge_id, payload.password
        )
    except TelegramMtprotoChallengeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except TelegramMtprotoChallengeExpiredError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=exc.message) from exc
    except TelegramMtprotoInvalidPasswordError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    except TelegramMtprotoIdentityConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoProviderUnavailableError as exc:
        raise _provider_response(exc) from exc
    except TelegramMtprotoConfigurationError as exc:
        raise _configuration_response() from exc
    return _account_out(account)


@router.get("/telegram/mtproto/status", response_model=TelegramMtprotoStatusOut)
def telegram_mtproto_status(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoStatusOut:
    _require_configured()
    try:
        account = TelegramMtprotoAuthService(session).status(current_user.user_id)
    except TelegramMtprotoConfigurationError as exc:
        raise _configuration_response() from exc
    return TelegramMtprotoStatusOut(
        configured=True,
        connected=account is not None,
        account=_account_out(account),
    )


def _account_out(account: TelegramMtprotoAccountSummary | None) -> TelegramMtprotoAccountOut | None:
    if account is None:
        return None
    return TelegramMtprotoAccountOut(
        id=account.id,
        telegram_user_id=account.telegram_user_id,
        username=account.username,
        display_name=account.display_name,
    )


def _require_configured() -> None:
    if not mtproto_is_configured():
        raise _configuration_response()


def _configuration_response() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Telegram MTProto is not configured",
    )


def _provider_response(exc: TelegramMtprotoProviderUnavailableError) -> HTTPException:
    headers = {}
    if exc.retry_after_seconds is not None:
        headers["Retry-After"] = str(exc.retry_after_seconds)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Telegram authorization provider is temporarily unavailable",
        headers=headers,
    )
