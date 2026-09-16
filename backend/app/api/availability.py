from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.schemas import (
    AvailabilityBusyIntervalOut,
    AvailabilityFreeIntervalOut,
    AvailabilityOut,
)
from app.core.client_timezone import resolve_client_timezone
from app.core.current_user import CurrentUserContext
from app.services.availability_service import (
    DEFAULT_MIN_DURATION_MINUTES,
    AvailabilityService,
    parse_aware_instant,
)
from app.services.errors import ValidationError

router = APIRouter(tags=["availability"])


@router.get("/availability", response_model=AvailabilityOut)
def get_availability(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
    start_at: str = Query(...),
    end_at: str = Query(...),
    min_duration_minutes: int = Query(default=DEFAULT_MIN_DURATION_MINUTES),
    client_timezone_id: str | None = Query(default=None, alias="client_timezone_id"),
    client_utc_offset_minutes: int | None = Query(default=None),
) -> AvailabilityOut:
    try:
        timezone = resolve_client_timezone(client_timezone_id, client_utc_offset_minutes)
        window_start = parse_aware_instant(start_at, "start_at")
        window_end = parse_aware_instant(end_at, "end_at")
        snapshot = AvailabilityService(session, current_user.user_id).query(
            start_at=window_start,
            end_at=window_end,
            timezone=timezone,
            min_duration_minutes=min_duration_minutes,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc
    return AvailabilityOut(
        timezone=snapshot["timezone"],
        window_start=snapshot["window_start"],
        window_end=snapshot["window_end"],
        min_duration_minutes=snapshot["min_duration_minutes"],
        availability_complete=snapshot["availability_complete"],
        busy_intervals=[
            AvailabilityBusyIntervalOut(
                start_at=item["start_at"],
                end_at=item["end_at"],
                event_ids=item["event_ids"],
            )
            for item in snapshot["busy_intervals"]
        ],
        free_intervals=[
            AvailabilityFreeIntervalOut(
                start_at=item["start_at"],
                end_at=item["end_at"],
                duration_minutes=item["duration_minutes"],
            )
            for item in snapshot["free_intervals"]
        ],
        unknown_end_event_ids=snapshot["unknown_end_event_ids"],
    )
