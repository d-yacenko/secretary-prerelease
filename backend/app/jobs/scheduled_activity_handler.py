from uuid import UUID

from sqlalchemy.orm import Session

from app.services.graph_service import GraphService
from app.services.scheduled_activity_service import ScheduledActivityService


def handle_run_scheduled_activity(
    session: Session,
    embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    raw = payload.get("activity_id")
    try:
        activity_id = UUID(str(raw))
    except (TypeError, ValueError):
        return
    ScheduledActivityService(
        session,
        user_id,
        GraphService(session, user_id),
    ).fire(activity_id, payload)
