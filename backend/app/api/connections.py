from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth_schemas import (
    ConnectionsOut,
    GoogleConnectionOut,
    MattermostConnectionOut,
    TeamsConnectionOut,
    TelegramConnectionOut,
    YandexCalendarConnectionOut,
    YandexMailConnectionOut,
)
from app.api.deps import get_current_user, get_db
from app.core.current_user import CurrentUserContext
from app.services.connection_status_service import ConnectionStatusService

router = APIRouter(tags=["connections"])


@router.get("/connections", response_model=ConnectionsOut)
def get_connections(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> ConnectionsOut:
    snapshot = ConnectionStatusService(session, current_user.user_id).snapshot()
    return ConnectionsOut(
        google=GoogleConnectionOut(
            connected=snapshot.google.connected,
            email=snapshot.google.email,
            gmail_available=snapshot.google.gmail_available,
            calendar_available=snapshot.google.calendar_available,
            drive_available=snapshot.google.drive_available,
        ),
        yandex_mail=YandexMailConnectionOut(
            connected=snapshot.yandex_mail.connected,
            email=snapshot.yandex_mail.email,
        ),
        yandex_calendar=YandexCalendarConnectionOut(
            connected=snapshot.yandex_calendar.connected,
            email=snapshot.yandex_calendar.email,
        ),
        mattermost=[
            MattermostConnectionOut(
                account_id=account.account_id,
                server_url=account.server_url,
                remote_user_id=account.remote_user_id,
                username=account.username,
                display_name=account.display_name,
                email=account.email,
            )
            for account in snapshot.mattermost
        ],
        telegram=TelegramConnectionOut(
            configured=snapshot.telegram.configured,
            identity_linked=snapshot.telegram.identity_linked,
            business_connected=snapshot.telegram.business_connected,
            can_reply=snapshot.telegram.can_reply,
            telegram_username=snapshot.telegram.telegram_username,
            display_name=snapshot.telegram.display_name,
            bot_username=snapshot.telegram.bot_username,
        ),
        teams=TeamsConnectionOut(
            configured=snapshot.teams.configured,
            connected=snapshot.teams.connected,
            reconnect_required=snapshot.teams.reconnect_required,
            display_name=snapshot.teams.display_name,
            upn=snapshot.teams.upn,
            tenant_id=snapshot.teams.tenant_id,
        ),
    )
