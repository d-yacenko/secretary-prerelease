from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.schemas import WeekDayOut, WeekEventOut, WeekOut, WeekScheduledWorkOut, WeekTemporalHintOut
from app.core.client_timezone import resolve_client_timezone
from app.core.current_user import CurrentUserContext
from app.services.errors import ValidationError
from app.services.week_service import WeekService

router = APIRouter(tags=["week"])


@router.get("/week", response_model=WeekOut)
def get_week(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
    week_start: str | None = Query(default=None),
    client_timezone_id: str | None = Query(default=None, alias="client_timezone_id"),
    client_utc_offset_minutes: int | None = Query(default=None),
) -> WeekOut:
    try:
        timezone = resolve_client_timezone(client_timezone_id, client_utc_offset_minutes)
        snapshot = WeekService(session, current_user.user_id).snapshot(
            week_start=week_start,
            timezone=timezone,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc
    return WeekOut(
        week_start=snapshot["week_start"],
        week_end=snapshot["week_end"],
        timezone=snapshot["timezone"],
        window_start=snapshot["window_start"],
        window_end=snapshot["window_end"],
        today_date=snapshot["today_date"],
        is_current_week=snapshot["is_current_week"],
        days=[
            WeekDayOut(
                date=day["date"],
                is_today=day["is_today"],
                events=[WeekEventOut.from_event(obj) for obj in day["events"]],
                scheduled_work=[
                    WeekScheduledWorkOut.from_task(obj) for obj in day["scheduled_work"]
                ],
                temporal_hints=[
                    WeekTemporalHintOut.from_hint(obj) for obj in day["temporal_hints"]
                ],
            )
            for day in snapshot["days"]
        ],
    )
