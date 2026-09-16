from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.ai_audit import router as ai_audit_router
from app.api.assistant import router as assistant_router
from app.api.availability import router as availability_router
from app.api.capture import router as capture_router
from app.api.connections import router as connections_router
from app.api.google import router as google_router
from app.api.inbox import router as inbox_router
from app.api.intake import router as intake_router
from app.api.labels import router as labels_router
from app.api.local import router as local_router
from app.api.mattermost import router as mattermost_router
from app.api.me import router as me_router
from app.api.object_bookmarks import router as object_bookmarks_router
from app.api.routes.graph import router as graph_router
from app.api.routes.graph_workspace import router as graph_workspace_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.relations import router as relations_router
from app.api.routes.resources import router as resources_router
from app.api.routes.tasks import router as tasks_router
from app.api.source_preferences import router as source_preferences_router
from app.api.sources import router as sources_router
from app.api.teams import router as teams_router
from app.api.teams_webhook import router as teams_webhook_router
from app.api.telegram import router as telegram_router
from app.api.telegram_mtproto import router as telegram_mtproto_router
from app.api.today import router as today_router
from app.api.week import router as week_router
from app.api.yandex import router as yandex_router
from app.core.config import settings
from app.db.engine import engine
from app.users.current_user_provider import reset_request_bearer_token, set_request_bearer_token

_mcp_server = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _mcp_server is not None:
        async with _mcp_server.session_manager.run():
            yield
    else:
        yield


app = FastAPI(title="Personal Secretary", lifespan=lifespan)


@app.middleware("http")
async def bearer_context_middleware(request: Request, call_next):
    authorization = request.headers.get("Authorization")
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip() or None
    reset = set_request_bearer_token(token)
    try:
        return await call_next(request)
    finally:
        reset_request_bearer_token(reset)


@app.exception_handler(StarletteHTTPException)
async def register_multipart_size_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    if (
        exc.status_code == 400
        and request.url.path.endswith("/resources/register")
        and "Part exceeded maximum size" in str(exc.detail)
    ):
        return JSONResponse(
            status_code=413,
            content={"detail": "register payload exceeds size limit"},
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(me_router)
app.include_router(ai_audit_router)
app.include_router(source_preferences_router)
app.include_router(connections_router)
app.include_router(capture_router)
app.include_router(assistant_router)
app.include_router(graph_router)
app.include_router(labels_router)
app.include_router(object_bookmarks_router)
app.include_router(graph_workspace_router)
app.include_router(tasks_router)
app.include_router(relations_router)
app.include_router(resources_router)
app.include_router(local_router)
app.include_router(notifications_router)
app.include_router(google_router)
app.include_router(inbox_router)
app.include_router(intake_router)
app.include_router(sources_router)
app.include_router(yandex_router)
app.include_router(mattermost_router)
app.include_router(telegram_router)
app.include_router(telegram_mtproto_router)
app.include_router(teams_router)
app.include_router(teams_webhook_router)
app.include_router(today_router)
app.include_router(week_router)
app.include_router(availability_router)


if settings.mcp_enabled:
    from app.mcp.server import create_mcp_server

    _mcp_server = create_mcp_server()
    app.mount(
        "/mcp",
        _mcp_server.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            json_response=True,
        ),
    )


@app.get("/health")
def health() -> dict[str, str]:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
