from typing import Any

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy.orm import Session

from app.connectors.teams.notifications import enqueue_graph_notifications
from app.db.session import SessionLocal

router = APIRouter(tags=["teams"])


@router.api_route("/webhooks/teams", methods=["GET", "POST"], response_model=None)
async def teams_graph_webhook(
    request: Request,
    validation_token: str | None = Query(default=None, alias="validationToken"),
) -> Response | dict[str, Any]:
    if validation_token is not None:
        return Response(content=validation_token, media_type="text/plain", status_code=200)
    if request.method == "GET":
        return Response(status_code=202)
    try:
        payload = await request.json()
    except Exception:
        return {"queued": 0}
    session: Session = SessionLocal()
    try:
        queued = enqueue_graph_notifications(session, payload)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return {"queued": queued}
