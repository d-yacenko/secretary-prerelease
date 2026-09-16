from datetime import datetime
from typing import Literal, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.schemas import (
    InboxFeedOut,
    InboxOut,
    InboxReviewMarkerOut,
    InboxSourceObjectOut,
    NotificationOut,
    SourceSyncStatusOut,
)
from app.core.current_user import CurrentUserContext
from app.db.models import Object
from app.notifications.constants import NOTIFICATION_FILTER_UNRESOLVED
from app.services.conversation_stack import groups_to_overlay
from app.services.errors import NotFoundError, ValidationError
from app.services.inbox_conversation_overlay import build_inbox_conversation_groups
from app.services.inbox_review_marker import (
    InboxReviewMarkerService,
    ReviewMarkerRecord,
)
from app.services.notification_service import NotificationService
from app.services.object_primary_date import object_primary_search_datetime
from app.services.recent_source_service import RecentSourceService, inbox_feed_at
from app.services.source_status_service import SourceStatusService

router = APIRouter(tags=["inbox"])


class ReviewMarkerPutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    after_object_id: UUID


class ReviewMarkerCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_before_object_id: UUID
    anchor_before_feed_at: datetime
    snapshot_top_object_id: UUID
    snapshot_top_feed_at: datetime
    total_count: int


class ReviewMarkerCompleteOut(BaseModel):
    status: Literal["advanced", "already_current", "conflict"]
    review_marker: InboxReviewMarkerOut | None = None


def _marker_out(record: ReviewMarkerRecord) -> InboxReviewMarkerOut:
    return InboxReviewMarkerOut(
        anchor_feed_at=record.anchor_feed_at,
        anchor_object_id=record.anchor_object_id,
        updated_at=record.updated_at,
    )


def _raise_marker_domain(exc: Exception) -> NoReturn:
    if isinstance(exc, NotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{exc.resource} not found"
        ) from exc
    if isinstance(exc, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
        ) from exc
    raise exc


def _conversation_groups_out(objects: list[Object], marker, session, user_id):
    from app.api.schemas import InboxConversationGroupOut, InboxConversationStackOut

    groups = build_inbox_conversation_groups(
        objects,
        marker=marker,
        session=session,
        user_id=user_id,
        enqueue_summaries=True,
    )
    overlay = groups_to_overlay(groups)
    parsed: list[InboxConversationGroupOut] = []
    for item in overlay:
        stack_raw = item.get("stack")
        stack = None
        if stack_raw:
            stack = InboxConversationStackOut(
                stack_id=stack_raw["stack_id"],
                fingerprint=stack_raw["fingerprint"],
                object_ids=stack_raw["object_ids"],
                display_object_ids=stack_raw["display_object_ids"],
                provider=stack_raw["provider"],
                conversation_key=stack_raw["conversation_key"],
                conversation_label=stack_raw["conversation_label"],
                participants=stack_raw["participants"],
                message_count=stack_raw["message_count"],
                start_at=stack_raw["start_at"],
                end_at=stack_raw["end_at"],
                summary=stack_raw.get("summary"),
                fallback_summary=stack_raw["fallback_summary"],
                summary_status=stack_raw["summary_status"],
                marker_side=stack_raw.get("marker_side"),
            )
        parsed.append(
            InboxConversationGroupOut(
                type=item["type"],
                object_id=item.get("object_id"),
                stack=stack,
            )
        )
    return parsed


def _source_out(obj: Object) -> InboxSourceObjectOut:
    return InboxSourceObjectOut(
        id=obj.id,
        title=obj.title,
        kind=obj.kind,
        provider=obj.provider,
        origin=obj.origin,
        state=obj.state,
        status=obj.status,
        primary_at=object_primary_search_datetime(obj),
        feed_at=inbox_feed_at(obj),
        excerpt=RecentSourceService.excerpt(obj.body),
    )


@router.get("/inbox", response_model=InboxOut)
def get_inbox(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
    recent_limit: int = Query(default=30, ge=1, le=50),
) -> InboxOut:
    user_id = current_user.user_id
    notifications = NotificationService(session, user_id).list_notifications(
        status=NOTIFICATION_FILTER_UNRESOLVED,
        limit=50,
    )
    page = RecentSourceService(session, user_id).list_page(limit=recent_limit)
    status_rows = SourceStatusService(session, user_id).list_status()
    marker = InboxReviewMarkerService(session, user_id).get_marker()
    return InboxOut(
        unresolved_notifications=[
            NotificationOut.from_model(notification) for notification in notifications
        ],
        recent_source_objects=[_source_out(obj) for obj in page.items],
        source_sync_status=[
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
            for row in status_rows
        ],
        recent_next_cursor=page.next_cursor,
        recent_has_more=page.has_more,
        review_marker=_marker_out(marker) if marker is not None else None,
        conversation_groups=_conversation_groups_out(
            page.items, marker, session, user_id
        ),
    )


@router.get("/inbox/feed", response_model=InboxFeedOut)
def get_inbox_feed(
    cursor: str = Query(..., min_length=1),
    limit: int = Query(default=30, ge=1, le=50),
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> InboxFeedOut:
    try:
        page = RecentSourceService(session, current_user.user_id).list_page(
            limit=limit,
            cursor=cursor,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc
    marker = InboxReviewMarkerService(session, current_user.user_id).get_marker()
    return InboxFeedOut(
        items=[_source_out(obj) for obj in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        conversation_groups=_conversation_groups_out(
            page.items, marker, session, current_user.user_id
        ),
    )


@router.put("/inbox/review-marker", response_model=InboxReviewMarkerOut)
def put_inbox_review_marker(
    payload: ReviewMarkerPutRequest,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> InboxReviewMarkerOut:
    try:
        record = InboxReviewMarkerService(session, current_user.user_id).set_marker(
            payload.after_object_id
        )
    except (NotFoundError, ValidationError) as exc:
        _raise_marker_domain(exc)
    return _marker_out(record)


@router.post("/inbox/review-marker/complete", response_model=ReviewMarkerCompleteOut)
def complete_inbox_review_marker(
    payload: ReviewMarkerCompleteRequest,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> ReviewMarkerCompleteOut:
    result = InboxReviewMarkerService(session, current_user.user_id).complete_review(
        expected_anchor_object_id=payload.anchor_before_object_id,
        expected_anchor_feed_at=payload.anchor_before_feed_at,
        snapshot_top_object_id=payload.snapshot_top_object_id,
        snapshot_top_feed_at=payload.snapshot_top_feed_at,
    )
    return ReviewMarkerCompleteOut(
        status=result.status,  # type: ignore[arg-type]
        review_marker=_marker_out(result.marker) if result.marker is not None else None,
    )


@router.delete("/inbox/review-marker")
def delete_inbox_review_marker(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> dict[str, bool]:
    changed = InboxReviewMarkerService(session, current_user.user_id).clear_marker()
    return {"cleared": changed}
