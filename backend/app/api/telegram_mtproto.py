from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, Response

from app.api.deps import get_current_user, get_db
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoAccountNotConnectedError,
    TelegramMtprotoAuthorizationInvalidError,
    TelegramMtprotoChallengeExpiredError,
    TelegramMtprotoChallengeNotFoundError,
    TelegramMtprotoConfigurationError,
    TelegramMtprotoFolderConfigurationError,
    TelegramMtprotoGroupNotSelectedError,
    TelegramMtprotoGroupUnavailableError,
    TelegramMtprotoIdentityConflictError,
    TelegramMtprotoInvalidCodeError,
    TelegramMtprotoInvalidPasswordError,
    TelegramMtprotoInvalidPhoneError,
    TelegramMtprotoPeerNotInActiveScopeError,
    TelegramMtprotoProviderReferenceInvalidError,
    TelegramMtprotoProviderUnavailableError,
    TelegramMtprotoScopeUnavailableError,
)
from app.core.current_user import CurrentUserContext
from app.services.telegram_mtproto_auth_service import (
    TelegramMtprotoAccountSummary,
    TelegramMtprotoAuthService,
    mtproto_is_configured,
)
from app.services.telegram_mtproto_group_service import (
    TelegramMtprotoGroup,
    TelegramMtprotoGroupService,
)
from app.services.telegram_mtproto_history_service import (
    TelegramMtprotoHistoryService,
    TelegramMtprotoHistorySummary,
)
from app.services.telegram_mtproto_scope_service import (
    TelegramMtprotoConfiguredFolder,
    TelegramMtprotoFoldersResult,
    TelegramMtprotoScopeResult,
    TelegramMtprotoScopeService,
)

INVALID_MTPROTO_REQUEST_DETAIL = "Invalid Telegram MTProto request"


class TelegramMtprotoRoute(APIRoute):
    def get_route_handler(self):
        route_handler = super().get_route_handler()

        async def handle(request) -> Response:
            try:
                return await route_handler(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    content={"detail": INVALID_MTPROTO_REQUEST_DETAIL},
                )

        return handle


router = APIRouter(route_class=TelegramMtprotoRoute, tags=["telegram-mtproto"])


class TelegramMtprotoAuthStartIn(BaseModel):
    phone: str = Field(min_length=1, max_length=32, strict=True)


class TelegramMtprotoAuthStartOut(BaseModel):
    challenge_id: UUID
    expires_at: datetime


class TelegramMtprotoCodeIn(BaseModel):
    challenge_id: UUID
    code: str = Field(min_length=1, max_length=32, strict=True)


class TelegramMtprotoPasswordIn(BaseModel):
    challenge_id: UUID
    password: str = Field(min_length=1, max_length=256, strict=True)


class TelegramMtprotoAccountOut(BaseModel):
    id: UUID
    telegram_user_id: int
    username: str | None
    display_name: str | None


class TelegramMtprotoCodeOut(BaseModel):
    status: Literal["authorized", "password_required"]
    account: TelegramMtprotoAccountOut | None = None


class TelegramMtprotoStatusOut(BaseModel):
    configured: bool
    connected: bool
    account: TelegramMtprotoAccountOut | None = None


class TelegramMtprotoGroupOut(BaseModel):
    peer_id: int
    kind: Literal["group", "supergroup"]
    title: str
    username: str | None
    is_forum: bool
    selected: bool
    available: bool


class TelegramMtprotoGroupsOut(BaseModel):
    groups: list[TelegramMtprotoGroupOut]
    truncated: bool


class TelegramMtprotoFolderOut(BaseModel):
    folder_id: int
    name: str


class TelegramMtprotoFoldersOut(BaseModel):
    folders: list[TelegramMtprotoFolderOut]
    truncated: bool


class TelegramMtprotoConfiguredFolderOut(BaseModel):
    folder_id: int
    name: str
    ignore_muted: bool


class TelegramMtprotoConfiguredFoldersOut(BaseModel):
    folders: list[TelegramMtprotoConfiguredFolderOut]
    ignore_muted: bool = True


class TelegramMtprotoFolderConfigurationIn(BaseModel):
    folder_names: list[str] = Field(default_factory=list, max_length=100)
    ignore_muted: bool = Field(default=True, strict=True)


class TelegramMtprotoScopeDialogOut(BaseModel):
    peer_id: int
    kind: Literal["private", "group", "supergroup"]
    title: str
    username: str | None
    is_muted: bool


class TelegramMtprotoScopePreviewOut(BaseModel):
    dialogs: list[TelegramMtprotoScopeDialogOut]
    truncated: bool
    skipped_counts: dict[str, int]
    configured_folder_count: int


class TelegramMtprotoScopeReconcileOut(BaseModel):
    active: int
    activated: int
    deactivated: int
    unchanged: int
    peers: list[TelegramMtprotoScopeDialogOut]


class TelegramMtprotoGroupSelectionIn(BaseModel):
    selected: bool = Field(strict=True)


class TelegramMtprotoGroupSelectionOut(BaseModel):
    peer_id: int
    selected: bool


class TelegramMtprotoHistorySyncOut(BaseModel):
    peer_id: int
    scanned: int
    materialized: int
    created: int
    updated: int
    unchanged: int
    skipped: int
    jobs_enqueued: int
    history_complete: bool


@router.post("/telegram/mtproto/auth/start", response_model=TelegramMtprotoAuthStartOut)
async def telegram_mtproto_auth_start(
    payload: TelegramMtprotoAuthStartIn,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoAuthStartOut:
    _require_configured()
    try:
        challenge = await TelegramMtprotoAuthService(session).start(
            current_user.user_id, payload.phone
        )
    except TelegramMtprotoConfigurationError as exc:
        raise _configuration_response() from exc
    except TelegramMtprotoInvalidPhoneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    except TelegramMtprotoProviderUnavailableError as exc:
        raise _provider_response(exc) from exc
    return TelegramMtprotoAuthStartOut(
        challenge_id=challenge.id,
        expires_at=challenge.expires_at,
    )


@router.post("/telegram/mtproto/auth/code", response_model=TelegramMtprotoCodeOut)
async def telegram_mtproto_auth_code(
    payload: TelegramMtprotoCodeIn,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoCodeOut:
    _require_configured()
    try:
        result = await TelegramMtprotoAuthService(session).submit_code(
            current_user.user_id, payload.challenge_id, payload.code
        )
    except TelegramMtprotoChallengeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except TelegramMtprotoChallengeExpiredError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=exc.message) from exc
    except TelegramMtprotoInvalidCodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    except TelegramMtprotoIdentityConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoProviderUnavailableError as exc:
        raise _provider_response(exc) from exc
    except TelegramMtprotoConfigurationError as exc:
        raise _configuration_response() from exc
    return TelegramMtprotoCodeOut(
        status=result.status,
        account=_account_out(result.account),
    )


@router.post("/telegram/mtproto/auth/password", response_model=TelegramMtprotoAccountOut)
async def telegram_mtproto_auth_password(
    payload: TelegramMtprotoPasswordIn,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoAccountOut:
    _require_configured()
    try:
        account = await TelegramMtprotoAuthService(session).submit_password(
            current_user.user_id, payload.challenge_id, payload.password
        )
    except TelegramMtprotoChallengeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except TelegramMtprotoChallengeExpiredError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=exc.message) from exc
    except TelegramMtprotoInvalidPasswordError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    except TelegramMtprotoIdentityConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoProviderUnavailableError as exc:
        raise _provider_response(exc) from exc
    except TelegramMtprotoConfigurationError as exc:
        raise _configuration_response() from exc
    return _account_out(account)


@router.get("/telegram/mtproto/status", response_model=TelegramMtprotoStatusOut)
def telegram_mtproto_status(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoStatusOut:
    _require_configured()
    try:
        account = TelegramMtprotoAuthService(session).status(current_user.user_id)
    except TelegramMtprotoConfigurationError as exc:
        raise _configuration_response() from exc
    return TelegramMtprotoStatusOut(
        configured=True,
        connected=account is not None,
        account=_account_out(account),
    )


@router.get("/telegram/mtproto/groups", response_model=TelegramMtprotoGroupsOut)
async def telegram_mtproto_groups(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoGroupsOut:
    _require_configured()
    try:
        result = await TelegramMtprotoGroupService(session).list_groups(current_user.user_id)
    except TelegramMtprotoAccountNotConnectedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoAuthorizationInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoConfigurationError as exc:
        raise _configuration_response() from exc
    except TelegramMtprotoProviderUnavailableError as exc:
        raise _provider_response(exc) from exc
    return TelegramMtprotoGroupsOut(
        groups=[_group_out(group) for group in result.groups], truncated=result.truncated
    )


@router.get("/telegram/mtproto/folders", response_model=TelegramMtprotoFoldersOut)
async def telegram_mtproto_folders(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoFoldersOut:
    _require_configured()
    try:
        result = await TelegramMtprotoScopeService(session).list_available_folders(current_user.user_id)
    except TelegramMtprotoAccountNotConnectedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoAuthorizationInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoFolderConfigurationError as exc:
        raise _configuration_response() from exc
    except TelegramMtprotoProviderUnavailableError as exc:
        raise _provider_response(exc) from exc
    return _folders_out(result)


@router.get("/telegram/mtproto/sync-folders", response_model=TelegramMtprotoConfiguredFoldersOut)
def telegram_mtproto_sync_folders(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoConfiguredFoldersOut:
    _require_configured()
    try:
        folders = TelegramMtprotoScopeService(session).configured_folders(current_user.user_id)
    except TelegramMtprotoAccountNotConnectedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoFolderConfigurationError as exc:
        raise _configuration_response() from exc
    return _configured_folders_out(folders)


@router.put("/telegram/mtproto/sync-folders", response_model=TelegramMtprotoConfiguredFoldersOut)
async def telegram_mtproto_replace_sync_folders(
    payload: TelegramMtprotoFolderConfigurationIn,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoConfiguredFoldersOut:
    _require_configured()
    try:
        folders = await TelegramMtprotoScopeService(session).replace_folders(
            current_user.user_id, payload.folder_names, ignore_muted=payload.ignore_muted
        )
    except TelegramMtprotoAccountNotConnectedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoFolderConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoAuthorizationInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoProviderUnavailableError as exc:
        raise _provider_response(exc) from exc
    return _configured_folders_out(folders)


@router.get("/telegram/mtproto/sync-scope/preview", response_model=TelegramMtprotoScopePreviewOut)
async def telegram_mtproto_scope_preview(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoScopePreviewOut:
    _require_configured()
    try:
        result = await TelegramMtprotoScopeService(session).preview_scope(current_user.user_id)
    except TelegramMtprotoAccountNotConnectedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except (TelegramMtprotoFolderConfigurationError, TelegramMtprotoScopeUnavailableError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoAuthorizationInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoProviderUnavailableError as exc:
        raise _provider_response(exc) from exc
    return _scope_out(result)


@router.post("/telegram/mtproto/sync-scope/reconcile", response_model=TelegramMtprotoScopeReconcileOut)
async def telegram_mtproto_scope_reconcile(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoScopeReconcileOut:
    _require_configured()
    try:
        result = await TelegramMtprotoScopeService(session).reconcile_scope(current_user.user_id)
    except TelegramMtprotoAccountNotConnectedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except (TelegramMtprotoFolderConfigurationError, TelegramMtprotoScopeUnavailableError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoAuthorizationInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoProviderUnavailableError as exc:
        raise _provider_response(exc) from exc
    return TelegramMtprotoScopeReconcileOut(
        active=result.active,
        activated=result.activated,
        deactivated=result.deactivated,
        unchanged=result.unchanged,
        peers=[
            TelegramMtprotoScopeDialogOut(
                peer_id=item.peer_id,
                kind=item.kind,
                title=item.title,
                username=item.username,
                is_muted=item.is_muted,
            )
            for item in result.scope.dialogs
        ],
    )


@router.post(
    "/telegram/mtproto/sync-scope/peers/{peer_id}/sync",
    response_model=TelegramMtprotoHistorySyncOut,
)
async def telegram_mtproto_scope_peer_sync(
    peer_id: int = Path(ge=-(2**63), le=2**63 - 1),
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoHistorySyncOut:
    _require_configured()
    if peer_id == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=INVALID_MTPROTO_REQUEST_DETAIL)
    try:
        result = await TelegramMtprotoHistoryService(session).sync_scope_peer(
            current_user.user_id, peer_id
        )
    except TelegramMtprotoAccountNotConnectedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoPeerNotInActiveScopeError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except TelegramMtprotoAuthorizationInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoGroupUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Telegram peer is no longer available",
        ) from exc
    except TelegramMtprotoProviderReferenceInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Telegram peer is no longer available") from exc
    except TelegramMtprotoConfigurationError as exc:
        raise _configuration_response() from exc
    except TelegramMtprotoProviderUnavailableError as exc:
        raise _provider_response(exc) from exc
    return _history_sync_out(result)


@router.patch(
    "/telegram/mtproto/groups/{peer_id}", response_model=TelegramMtprotoGroupSelectionOut
)
async def telegram_mtproto_group_selection(
    payload: TelegramMtprotoGroupSelectionIn,
    peer_id: int = Path(ge=-(2**63), le=-1),
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoGroupSelectionOut:
    _require_configured()
    try:
        group = await TelegramMtprotoGroupService(session).set_selection(
            current_user.user_id, peer_id, payload.selected
        )
    except TelegramMtprotoAccountNotConnectedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoAuthorizationInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoGroupUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except TelegramMtprotoConfigurationError as exc:
        raise _configuration_response() from exc
    except TelegramMtprotoProviderUnavailableError as exc:
        raise _provider_response(exc) from exc
    return TelegramMtprotoGroupSelectionOut(
        peer_id=peer_id, selected=group is not None
    )


@router.post(
    "/telegram/mtproto/groups/{peer_id}/sync",
    response_model=TelegramMtprotoHistorySyncOut,
)
async def telegram_mtproto_group_sync(
    peer_id: int = Path(ge=-(2**63), le=-1),
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TelegramMtprotoHistorySyncOut:
    _require_configured()
    try:
        result = await TelegramMtprotoHistoryService(session).sync_group(
            current_user.user_id, peer_id
        )
    except TelegramMtprotoAccountNotConnectedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoGroupNotSelectedError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except TelegramMtprotoAuthorizationInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoGroupUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except TelegramMtprotoProviderReferenceInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Telegram selected group is no longer available",
        ) from exc
    except TelegramMtprotoConfigurationError as exc:
        raise _configuration_response() from exc
    except TelegramMtprotoProviderUnavailableError as exc:
        raise _provider_response(exc) from exc
    return _history_sync_out(result)


def _account_out(account: TelegramMtprotoAccountSummary | None) -> TelegramMtprotoAccountOut | None:
    if account is None:
        return None
    return TelegramMtprotoAccountOut(
        id=account.id,
        telegram_user_id=account.telegram_user_id,
        username=account.username,
        display_name=account.display_name,
    )


def _group_out(group: TelegramMtprotoGroup) -> TelegramMtprotoGroupOut:
    return TelegramMtprotoGroupOut(
        peer_id=group.peer_id,
        kind=group.kind,
        title=group.title,
        username=group.username,
        is_forum=group.is_forum,
        selected=group.selected,
        available=group.available,
    )


def _folders_out(result: TelegramMtprotoFoldersResult) -> TelegramMtprotoFoldersOut:
    return TelegramMtprotoFoldersOut(
        folders=[TelegramMtprotoFolderOut(folder_id=item.folder_id, name=item.name) for item in result.folders],
        truncated=result.truncated,
    )


def _configured_folders_out(
    folders: tuple[TelegramMtprotoConfiguredFolder, ...],
) -> TelegramMtprotoConfiguredFoldersOut:
    return TelegramMtprotoConfiguredFoldersOut(
        folders=[
            TelegramMtprotoConfiguredFolderOut(
                folder_id=item.folder_id, name=item.name, ignore_muted=item.ignore_muted
            )
            for item in folders
        ],
        ignore_muted=True,
    )


def _scope_out(result: TelegramMtprotoScopeResult) -> TelegramMtprotoScopePreviewOut:
    return TelegramMtprotoScopePreviewOut(
        dialogs=[
            TelegramMtprotoScopeDialogOut(
                peer_id=item.peer_id,
                kind=item.kind,
                title=item.title,
                username=item.username,
                is_muted=item.is_muted,
            )
            for item in result.dialogs
        ],
        truncated=result.truncated,
        skipped_counts=result.skipped_counts,
        configured_folder_count=result.configured_folder_count,
    )


def _history_sync_out(result: TelegramMtprotoHistorySummary) -> TelegramMtprotoHistorySyncOut:
    return TelegramMtprotoHistorySyncOut(
        peer_id=result.peer_id,
        scanned=result.scanned,
        materialized=result.materialized,
        created=result.created,
        updated=result.updated,
        unchanged=result.unchanged,
        skipped=result.skipped,
        jobs_enqueued=result.jobs_enqueued,
        history_complete=result.history_complete,
    )


def _require_configured() -> None:
    if not mtproto_is_configured():
        raise _configuration_response()


def _configuration_response() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Telegram MTProto is not configured",
    )


def _provider_response(exc: TelegramMtprotoProviderUnavailableError) -> HTTPException:
    headers = {}
    if exc.retry_after_seconds is not None:
        headers["Retry-After"] = str(exc.retry_after_seconds)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Telegram authorization provider is temporarily unavailable",
        headers=headers,
    )
