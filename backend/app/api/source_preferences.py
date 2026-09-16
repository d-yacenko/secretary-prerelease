from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.current_user import CurrentUserContext
from app.services.source_sync_preference_service import (
    EffectiveSourceSyncPreference,
    SourceSyncPreferenceService,
)
from app.services.source_sync_scheduler import SourceSyncScheduler
from app.source_sync.constants import SUPPORTED_SOURCE_KEYS

router = APIRouter(tags=["source-preferences"])


class EffectiveSourcePreferenceOut(BaseModel):
    source: str
    enabled: bool
    sync_interval_seconds: int
    default_sync_interval_seconds: int
    min_sync_interval_seconds: int
    max_sync_interval_seconds: int
    history_days: int
    default_history_days: int
    min_history_days: int
    max_history_days: int


class SourcePreferenceListOut(BaseModel):
    preferences: list[EffectiveSourcePreferenceOut]


class SourcePreferencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    sync_interval_seconds: int | None = None
    history_days: int | None = None


def _serialize_preference(
    preference: EffectiveSourceSyncPreference,
) -> EffectiveSourcePreferenceOut:
    return EffectiveSourcePreferenceOut(
        source=preference.source,
        enabled=preference.enabled,
        sync_interval_seconds=preference.sync_interval_seconds,
        default_sync_interval_seconds=preference.default_sync_interval_seconds,
        min_sync_interval_seconds=preference.min_sync_interval_seconds,
        max_sync_interval_seconds=preference.max_sync_interval_seconds,
        history_days=preference.history_days,
        default_history_days=preference.default_history_days,
        min_history_days=preference.min_history_days,
        max_history_days=preference.max_history_days,
    )


@router.get("/me/source-preferences", response_model=SourcePreferenceListOut)
def list_my_source_preferences(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> SourcePreferenceListOut:
    service = SourceSyncPreferenceService.build(session)
    preferences = service.list_effective_preferences(current_user.user_id)
    return SourcePreferenceListOut(
        preferences=[_serialize_preference(item) for item in preferences]
    )


@router.patch(
    "/me/source-preferences/{source}",
    response_model=EffectiveSourcePreferenceOut,
)
def patch_my_source_preference(
    source: str,
    body: SourcePreferencePatch,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> EffectiveSourcePreferenceOut:
    if source not in SUPPORTED_SOURCE_KEYS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="unsupported source",
        )
    if not body.model_fields_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="no fields to update",
        )
    service = SourceSyncPreferenceService.build(session)
    enabled_specified = "enabled" in body.model_fields_set
    sync_interval_specified = "sync_interval_seconds" in body.model_fields_set
    history_days_specified = "history_days" in body.model_fields_set
    try:
        preference = service.update_preference(
            current_user.user_id,
            source,
            enabled=body.enabled if enabled_specified else None,
            sync_interval_seconds=(
                body.sync_interval_seconds if sync_interval_specified else None
            ),
            history_days=body.history_days if history_days_specified else None,
            enabled_specified=enabled_specified,
            sync_interval_specified=sync_interval_specified,
            history_days_specified=history_days_specified,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if enabled_specified:
        SourceSyncScheduler(session).reconcile_user_source(
            current_user.user_id,
            source,
        )
    return _serialize_preference(preference)
