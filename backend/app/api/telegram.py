from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.connectors.telegram.link_state import TelegramLinkStateStore
from app.connectors.telegram.webhook_service import (
    TelegramWebhookService,
    bot_username,
    telegram_is_configured,
    webhook_secret_matches,
)
from app.core.current_user import CurrentUserContext

router = APIRouter(tags=["telegram"])


class TelegramLinkOut(BaseModel):
    telegram_url: str
    expires_at: datetime


@router.post("/telegram/link", response_model=TelegramLinkOut)
def create_telegram_link(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramLinkOut:
    if not telegram_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="telegram is not configured",
        )
    raw_state, row = TelegramLinkStateStore(session).create_for_user(current_user.user_id)
    username = bot_username()
    return TelegramLinkOut(
        telegram_url=f"https://t.me/{username}?start={raw_state}",
        expires_at=row.expires_at,
    )


@router.post("/integrations/telegram/webhook", status_code=status.HTTP_200_OK)
async def telegram_webhook(
    request: Request,
    session: Session = Depends(get_db),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, str]:
    if not webhook_secret_matches(x_telegram_bot_api_secret_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored"}
    if not isinstance(payload, dict):
        return {"status": "ignored"}
    TelegramWebhookService(session).handle_update(payload)
    return {"status": "ok"}
