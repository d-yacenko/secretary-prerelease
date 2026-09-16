
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.schemas import NotificationOut, ObjectOut, TodayOut
from app.core.client_timezone import resolve_client_timezone
from app.core.current_user import CurrentUserContext
from app.services.errors import ValidationError
from app.services.today_service import TodayService

router = APIRouter(tags=["today"])


@router.get("/today", response_model=TodayOut)
def get_today(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
    client_timezone_id: str | None = Query(default=None, alias="client_timezone_id"),
    client_utc_offset_minutes: int | None = Query(default=None),
) -> TodayOut:
    try:
        timezone = resolve_client_timezone(client_timezone_id, client_utc_offset_minutes)
    except ValidationError as exc:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    snapshot = TodayService(session, current_user.user_id).snapshot(timezone=timezone)
    return TodayOut(
        date=snapshot["date"],
        timezone=snapshot["timezone"],
        day_start=snapshot["day_start"],
        tasks=[ObjectOut.from_model(obj) for obj in snapshot["tasks"]],
        calendar_events=[ObjectOut.from_model(obj) for obj in snapshot["calendar_events"]],
        notifications=[
            NotificationOut.from_model(notification)
            for notification in snapshot["notifications"]
        ],
    )
