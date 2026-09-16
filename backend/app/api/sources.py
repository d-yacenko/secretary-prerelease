from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.schemas import (
    SourceStatusListOut,
    SourceSyncStatusOut,
    SourceSyncTriggerOut,
)
from app.core.current_user import CurrentUserContext
from app.services.source_status_service import SourceStatusService
from app.services.source_sync_scheduler import SourceSyncScheduler

router = APIRouter(tags=["sources"])


@router.get("/sources/status", response_model=SourceStatusListOut)
def list_source_status(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> SourceStatusListOut:
    rows = SourceStatusService(session, current_user.user_id).list_status()
    return SourceStatusListOut(
        sources=[
            SourceSyncStatusOut(
                source=row.source,
                provider=row.provider,
                account_id=row.account_id,
                account_label=row.account_label,
                enabled=row.enabled,
                status=row.status,
                last_success_at=row.last_success_at,
                last_attempt_at=row.last_attempt_at,
                next_sync_at=row.next_sync_at,
                last_error=row.last_error,
                error_kind=row.error_kind,
                retryable=row.retryable,
            )
            for row in rows
        ]
    )


@router.post("/sources/sync", response_model=SourceSyncTriggerOut)
def trigger_source_sync(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> SourceSyncTriggerOut:
    triggered = SourceSyncScheduler(session).trigger_all_for_user(current_user.user_id)
    session.commit()
    return SourceSyncTriggerOut(triggered=triggered, count=len(triggered))
