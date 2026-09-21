from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

router = APIRouter(tags=["telegram"])


class TelegramLinkOut(BaseModel):
    telegram_url: str
    expires_at: datetime


@router.post("/telegram/link", response_model=TelegramLinkOut)
def create_telegram_link(
) -> TelegramLinkOut:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Telegram Bot API linking is retired; use Telegram MTProto",
    )


@router.post("/integrations/telegram/webhook", status_code=status.HTTP_410_GONE)
async def telegram_webhook() -> dict[str, str]:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Telegram Bot API webhook is retired",
    )
