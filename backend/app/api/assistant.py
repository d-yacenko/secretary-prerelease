from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.ai_audit.constants import (
    WORKLOAD_SPEECH,
    WORKLOAD_TRANSCRIPTION,
)
from app.ai_audit.context import ai_trace_session
from app.api.assistant_error_responses import (
    build_assistant_error_detail,
    build_openai_daily_budget_error_detail,
)
from app.api.deps import get_current_user, get_db
from app.assistant.action_plan_constants import (
    PENDING_ACTION_PLAN_STATUS_EXPIRED,
    PENDING_ACTION_PLAN_STATUS_FAILED,
)
from app.assistant.speech_constants import (
    SPEECH_PROVIDER_UNAVAILABLE,
    SPEECH_TEXT_EMPTY,
    SPEECH_TEXT_TOO_LONG,
)
from app.assistant.transcription_constants import (
    AUDIO_TOO_LARGE,
    TRANSCRIPTION_AUDIO_INVALID,
    TRANSCRIPTION_AUDIO_INVALID_MESSAGE,
    TRANSCRIPTION_PROVIDER_FAILED,
    TRANSCRIPTION_PROVIDER_FAILED_MESSAGE,
    TRANSCRIPTION_PROVIDER_NOT_CONFIGURED,
    TRANSCRIPTION_PROVIDER_NOT_CONFIGURED_MESSAGE,
    TRANSCRIPTION_UNRECOGNIZED,
    TRANSCRIPTION_UNRECOGNIZED_MESSAGE,
)
from app.core.assistant_openai_config import AssistantOpenAIConfigError
from app.core.current_user import CurrentUserContext
from app.db.session import SessionLocal
from app.llm.assistant_models import AssistantHistoryMessage
from app.llm.openai_assistant_provider import AssistantProviderError
from app.llm.openai_speech_provider import SpeechProviderError
from app.llm.openai_transcription_provider import (
    TranscriptionAudioInvalidError,
    TranscriptionProviderError,
    TranscriptionUnrecognizedError,
)
from app.services.action_plan_service import (
    ActionPlanConflictError,
    ActionPlanService,
    PendingActionPlanView,
)
from app.services.assistant_conversation_service import (
    AssistantConversationService,
    IncompletePersistentTurnError,
)
from app.services.assistant_service import (
    AssistantConfigurationError,
    AssistantProvider,
    AssistantService,
    AssistantValidationError,
    create_assistant_provider_from_effective,
)
from app.services.effective_user_settings_service import (
    EffectiveUserSettings,
    EffectiveUserSettingsService,
)
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.openai_daily_budget import (
    OpenAIDailyBudgetExhaustedError,
    OpenAIDailyBudgetGuard,
)
from app.services.speech_service import (
    SpeechConfigurationError,
    SpeechProvider,
    create_speech_provider_for_api_key,
    prepare_speech_request_text,
    synthesize_prepared_speech_text,
)
from app.services.transcription_service import (
    TranscriptionConfigurationError,
    TranscriptionProvider,
    create_transcription_provider_for_api_key,
    transcribe_audio_upload,
)
from app.services.user_identity_context_service import UserIdentityContextService
from app.services.user_openai_credential_errors import UserOpenAICredentialConfigurationError

router = APIRouter(tags=["assistant"])


class AssistantHistoryMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    content: str


class AssistantMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    history: list[AssistantHistoryMessageIn] = Field(default_factory=list)
    context_object_id: UUID | None = None
    context_notification_id: UUID | None = None
    client_timezone_id: str | None = None
    client_utc_offset_minutes: int | None = None
    conversation_id: UUID | None = None
    client_turn_id: UUID | None = None


class AssistantReferenceOut(BaseModel):
    object_id: UUID
    title: str
    kind: str
    canonical_uri: str | None = None
    provider: str | None = None
    primary_at: datetime | None = None


class AssistantAffectedObjectOut(BaseModel):
    object_id: UUID
    title: str
    kind: str
    state: str
    status: str | None = None


class PendingActionOut(BaseModel):
    tool_name: str
    arguments: dict


class PendingActionPlanOut(BaseModel):
    id: UUID
    status: str
    expires_at: str
    actions: list[PendingActionOut]


class InboxReviewReceiptOut(BaseModel):
    anchor_before_object_id: UUID
    anchor_before_feed_at: datetime
    snapshot_top_object_id: UUID
    snapshot_top_feed_at: datetime
    total_count: int


class AssistantMessageResponse(BaseModel):
    answer: str
    references: list[AssistantReferenceOut]
    affected_objects: list[AssistantAffectedObjectOut]
    pending_action_plan: PendingActionPlanOut | None = None
    inbox_review_receipt: InboxReviewReceiptOut | None = None
    conversation_id: UUID | None = None
    user_message_id: UUID | None = None
    assistant_message_id: UUID | None = None


class ActionPlanResponse(BaseModel):
    id: UUID
    status: str
    expires_at: str
    actions: list[PendingActionOut]
    result: dict | None = None
    failure: str | None = None


class ActionPlanResumeResponse(BaseModel):
    answer: str
    affected_objects: list[AssistantAffectedObjectOut]


class AssistantTranscribeResponse(BaseModel):
    text: str


class AssistantSpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


@dataclass(frozen=True)
class AssistantRuntime:
    provider: AssistantProvider
    effective: EffectiveUserSettings


def build_assistant_runtime(session: Session, user_id: UUID) -> AssistantRuntime:
    settings_service = EffectiveUserSettingsService.build(session)
    effective = settings_service.get_effective_settings(user_id)
    provider = OpenAIDailyBudgetGuard.build(session, user_id).guard_assistant_provider(
        create_assistant_provider_from_effective(effective)
    )
    return AssistantRuntime(provider=provider, effective=effective)


def get_assistant_runtime(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> AssistantRuntime:
    try:
        return build_assistant_runtime(session, current_user.user_id)
    except (
        AssistantConfigurationError,
        AssistantOpenAIConfigError,
        UserOpenAICredentialConfigurationError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=build_assistant_error_detail(exc),
        ) from exc


def get_assistant_provider(
    runtime: AssistantRuntime = Depends(get_assistant_runtime),
) -> AssistantProvider:
    return runtime.provider


def get_assistant_service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
    runtime: AssistantRuntime = Depends(get_assistant_runtime),
) -> AssistantService:
    identity_context_service = UserIdentityContextService.build(session)
    return AssistantService(
        current_user.user_id,
        runtime.provider,
        user_timezone=runtime.effective.timezone,
        identity_context_service=identity_context_service,
    )


def get_transcription_provider(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> TranscriptionProvider:
    try:
        api_key = EffectiveUserSettingsService.build(session).resolve_openai_api_key(
            current_user.user_id
        )
        provider = create_transcription_provider_for_api_key(api_key)
        return OpenAIDailyBudgetGuard.build(
            session, current_user.user_id
        ).guard_transcription_provider(provider)
    except (
        TranscriptionConfigurationError,
        UserOpenAICredentialConfigurationError,
    ) as exc:
        raise _transcription_http_error(exc) from exc


def get_validated_speech_text(data: AssistantSpeechRequest) -> str:
    try:
        return prepare_speech_request_text(data.text)
    except ValidationError as exc:
        raise _speech_validation_http_error(exc.message) from exc


def build_budget_guarded_speech_provider(
    session: Session,
    user_id: UUID,
) -> SpeechProvider:
    api_key = EffectiveUserSettingsService.build(session).resolve_openai_api_key(user_id)
    provider = create_speech_provider_for_api_key(api_key)
    return OpenAIDailyBudgetGuard.build(session, user_id).guard_speech_provider(provider)


def get_speech_provider(
    _prepared: str = Depends(get_validated_speech_text),
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> SpeechProvider:
    try:
        return build_budget_guarded_speech_provider(session, current_user.user_id)
    except (
        SpeechConfigurationError,
        UserOpenAICredentialConfigurationError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=SPEECH_PROVIDER_UNAVAILABLE,
        ) from exc


def _speech_validation_http_error(message: str) -> HTTPException:
    if message == SPEECH_TEXT_EMPTY:
        code = "speech_text_empty"
    elif message == SPEECH_TEXT_TOO_LONG:
        code = "speech_text_too_long"
    else:
        code = "speech_text_invalid"
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": code, "message": message},
    )


def _transcription_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TranscriptionAudioInvalidError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": TRANSCRIPTION_AUDIO_INVALID,
                "message": TRANSCRIPTION_AUDIO_INVALID_MESSAGE,
            },
        )
    if isinstance(exc, TranscriptionUnrecognizedError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": TRANSCRIPTION_UNRECOGNIZED,
                "message": TRANSCRIPTION_UNRECOGNIZED_MESSAGE,
            },
        )
    if isinstance(
        exc,
        (TranscriptionConfigurationError, UserOpenAICredentialConfigurationError),
    ):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": TRANSCRIPTION_PROVIDER_NOT_CONFIGURED,
                "message": TRANSCRIPTION_PROVIDER_NOT_CONFIGURED_MESSAGE,
            },
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": TRANSCRIPTION_PROVIDER_FAILED,
            "message": TRANSCRIPTION_PROVIDER_FAILED_MESSAGE,
        },
    )


def _openai_daily_budget_http_error(
    user_id: UUID,
    exc: OpenAIDailyBudgetExhaustedError,
) -> HTTPException:
    """Typed 429 for blocked interactive AI, plus the once-per-day user warning.

    The warning is written on its own committed session because the request
    session is rolled back when this error response is raised.
    """
    notice_session = SessionLocal()
    try:
        OpenAIDailyBudgetGuard(notice_session, user_id).ensure_exhausted_notification()
        notice_session.commit()
    except Exception:  # noqa: BLE001
        notice_session.rollback()
    finally:
        notice_session.close()
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=build_openai_daily_budget_error_detail(exc),
    )


def _serialize_action_plan_response(plan: PendingActionPlanView) -> ActionPlanResponse:
    return ActionPlanResponse(
        id=plan.id,
        status=plan.status,
        expires_at=plan.expires_at.isoformat(),
        actions=[
            PendingActionOut(tool_name=action["tool_name"], arguments=action["arguments"])
            for action in plan.actions
        ],
        result=plan.result,
        failure=plan.failure,
    )


@router.post("/assistant/transcribe", response_model=AssistantTranscribeResponse)
async def assistant_transcribe(
    audio: UploadFile = File(...),
    current_user: CurrentUserContext = Depends(get_current_user),
    provider: TranscriptionProvider = Depends(get_transcription_provider),
) -> AssistantTranscribeResponse:
    try:
        with ai_trace_session(current_user.user_id, WORKLOAD_TRANSCRIPTION):
            text = await transcribe_audio_upload(audio, provider)
    except OpenAIDailyBudgetExhaustedError as exc:
        raise _openai_daily_budget_http_error(current_user.user_id, exc) from exc
    except ValidationError as exc:
        status_code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if exc.message == AUDIO_TOO_LARGE
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=status_code, detail=exc.message) from exc
    except (
        TranscriptionConfigurationError,
        TranscriptionProviderError,
        TranscriptionAudioInvalidError,
        TranscriptionUnrecognizedError,
        UserOpenAICredentialConfigurationError,
    ) as exc:
        raise _transcription_http_error(exc) from exc

    return AssistantTranscribeResponse(text=text)


@router.post("/assistant/speech")
async def assistant_speech(
    prepared: str = Depends(get_validated_speech_text),
    current_user: CurrentUserContext = Depends(get_current_user),
    provider: SpeechProvider = Depends(get_speech_provider),
) -> Response:
    try:
        with ai_trace_session(current_user.user_id, WORKLOAD_SPEECH):
            result = await synthesize_prepared_speech_text(prepared, provider)
    except OpenAIDailyBudgetExhaustedError as exc:
        raise _openai_daily_budget_http_error(current_user.user_id, exc) from exc
    except (SpeechConfigurationError, SpeechProviderError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=SPEECH_PROVIDER_UNAVAILABLE,
        ) from exc

    return Response(content=result.audio_bytes, media_type=result.content_type)


class AssistantConversationOut(BaseModel):
    id: UUID
    title: str | None = None
    is_current: bool
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None


class AssistantConversationListOut(BaseModel):
    conversations: list[AssistantConversationOut]


class AssistantStoredMessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime
    client_turn_id: UUID | None = None
    references: list[AssistantReferenceOut]
    affected_objects: list[AssistantAffectedObjectOut]
    pending_action_plan: PendingActionPlanOut | None = None
    inbox_review_receipt: InboxReviewReceiptOut | None = None


class AssistantStoredMessageListOut(BaseModel):
    messages: list[AssistantStoredMessageOut]
    has_more: bool


def _conversation_service(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> AssistantConversationService:
    return AssistantConversationService(session, current_user.user_id)


def _conversation_out(view) -> AssistantConversationOut:
    return AssistantConversationOut(
        id=view.id,
        title=view.title,
        is_current=view.is_current,
        created_at=view.created_at,
        updated_at=view.updated_at,
        last_message_at=view.last_message_at,
    )


@router.get("/assistant/conversations", response_model=AssistantConversationListOut)
def list_assistant_conversations(
    service: AssistantConversationService = Depends(_conversation_service),
) -> AssistantConversationListOut:
    return AssistantConversationListOut(
        conversations=[_conversation_out(item) for item in service.list_conversations()]
    )


@router.get("/assistant/conversations/current", response_model=AssistantConversationOut)
def get_current_assistant_conversation(
    service: AssistantConversationService = Depends(_conversation_service),
) -> AssistantConversationOut:
    try:
        return _conversation_out(service.get_current())
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc


@router.post(
    "/assistant/conversations",
    response_model=AssistantConversationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_assistant_conversation(
    service: AssistantConversationService = Depends(_conversation_service),
) -> AssistantConversationOut:
    try:
        return _conversation_out(service.create_current())
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc


@router.post(
    "/assistant/conversations/{conversation_id}/select",
    response_model=AssistantConversationOut,
)
def select_assistant_conversation(
    conversation_id: UUID,
    service: AssistantConversationService = Depends(_conversation_service),
) -> AssistantConversationOut:
    try:
        return _conversation_out(service.select(conversation_id))
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc


@router.get(
    "/assistant/conversations/{conversation_id}/messages",
    response_model=AssistantStoredMessageListOut,
)
def list_assistant_conversation_messages(
    conversation_id: UUID,
    limit: int = 50,
    before_id: UUID | None = None,
    service: AssistantConversationService = Depends(_conversation_service),
) -> AssistantStoredMessageListOut:
    try:
        rows, has_more = service.list_messages(
            conversation_id,
            limit=limit,
            before_id=before_id,
        )
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc
    messages = []
    for row in rows:
        rendered = service.message_result(row)
        messages.append(
            AssistantStoredMessageOut(
                id=row.id,
                role=row.role,
                content=row.content,
                created_at=row.created_at,
                client_turn_id=row.client_turn_id,
                references=[
                    AssistantReferenceOut(
                        object_id=ref.object_id,
                        title=ref.title,
                        kind=ref.kind,
                        canonical_uri=ref.canonical_uri,
                        provider=ref.provider,
                        primary_at=ref.primary_at,
                    )
                    for ref in rendered.references
                ],
                affected_objects=[
                    AssistantAffectedObjectOut(
                        object_id=item.object_id,
                        title=item.title,
                        kind=item.kind,
                        state=item.state,
                        status=item.status,
                    )
                    for item in rendered.affected_objects
                ],
                pending_action_plan=_pending_plan_out(rendered.pending_action_plan),
                inbox_review_receipt=_receipt_out(rendered.inbox_review_receipt),
            )
        )
    return AssistantStoredMessageListOut(messages=messages, has_more=has_more)


@router.post(
    "/assistant/message",
    response_model=AssistantMessageResponse,
    response_model_exclude_none=True,
)
def assistant_message(
    data: AssistantMessageRequest,
    service: AssistantService = Depends(get_assistant_service),
    conversations: AssistantConversationService = Depends(_conversation_service),
) -> AssistantMessageResponse:
    persistent = data.conversation_id is not None or data.client_turn_id is not None
    if persistent and (data.conversation_id is None or data.client_turn_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="conversation_id and client_turn_id are required together",
        )
    stored_ids: tuple[UUID, UUID, UUID] | None = None
    if persistent:
        assert data.conversation_id is not None
        assert data.client_turn_id is not None
        try:
            stored = conversations.stored_turn(data.conversation_id, data.client_turn_id)
        except IncompletePersistentTurnError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=exc.message,
            ) from exc
        except NotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{exc.resource} not found",
            ) from exc
        if stored is not None:
            return _message_response(
                stored.result,
                conversation_id=stored.conversation_id,
                user_message_id=stored.user_message_id,
                assistant_message_id=stored.assistant_message_id,
            )
        history = conversations.bounded_history(data.conversation_id)
    else:
        history = [
            AssistantHistoryMessage(role=item.role, content=item.content)
            for item in data.history
        ]
    try:
        result = service.send_message(
            message=data.message,
            history=history,
            context_object_id=data.context_object_id,
            context_notification_id=data.context_notification_id,
            client_timezone_id=data.client_timezone_id,
            client_utc_offset_minutes=data.client_utc_offset_minutes,
        )
    except OpenAIDailyBudgetExhaustedError as exc:
        raise _openai_daily_budget_http_error(
            service.user_id,
            exc,
        ) from exc
    except AssistantValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc
    except (AssistantConfigurationError, AssistantProviderError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=build_assistant_error_detail(exc),
        ) from exc

    if persistent:
        assert data.conversation_id is not None
        assert data.client_turn_id is not None
        try:
            saved = conversations.persist_completed_turn(
                conversation_id=data.conversation_id,
                client_turn_id=data.client_turn_id,
                user_text=data.message.strip(),
                result=result,
            )
        except NotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{exc.resource} not found",
            ) from exc
        stored_ids = (
            saved.conversation_id,
            saved.user_message_id,
            saved.assistant_message_id,
        )
    return _message_response(
        result,
        conversation_id=None if stored_ids is None else stored_ids[0],
        user_message_id=None if stored_ids is None else stored_ids[1],
        assistant_message_id=None if stored_ids is None else stored_ids[2],
    )


@router.post(
    "/assistant/action-plans/{plan_id}/approve",
    response_model=ActionPlanResponse,
)
def approve_action_plan(
    plan_id: UUID,
    response: Response,
    current_user: CurrentUserContext = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ActionPlanResponse:
    service = ActionPlanService(session, current_user.user_id)
    try:
        plan = service.approve(plan_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc
    except ActionPlanConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc

    body = _serialize_action_plan_response(plan)
    if plan.status in (
        PENDING_ACTION_PLAN_STATUS_FAILED,
        PENDING_ACTION_PLAN_STATUS_EXPIRED,
    ):
        response.status_code = status.HTTP_409_CONFLICT
    return body


@router.post(
    "/assistant/action-plans/{plan_id}/reject",
    response_model=ActionPlanResponse,
)
def reject_action_plan(
    plan_id: UUID,
    response: Response,
    current_user: CurrentUserContext = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ActionPlanResponse:
    service = ActionPlanService(session, current_user.user_id)
    try:
        plan = service.reject(plan_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc
    except ActionPlanConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc

    body = _serialize_action_plan_response(plan)
    if plan.status == PENDING_ACTION_PLAN_STATUS_EXPIRED:
        response.status_code = status.HTTP_409_CONFLICT
    return body


@router.post(
    "/assistant/action-plans/{plan_id}/resume",
    response_model=ActionPlanResumeResponse,
)
def resume_action_plan(
    plan_id: UUID,
    current_user: CurrentUserContext = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ActionPlanResumeResponse:
    plan_service = ActionPlanService(session, current_user.user_id)
    conversations = AssistantConversationService(session, current_user.user_id)
    stored_resume = conversations.stored_resume(plan_id)
    if stored_resume is not None:
        return ActionPlanResumeResponse(
            answer=stored_resume.answer,
            affected_objects=[
                AssistantAffectedObjectOut(
                    object_id=item.object_id,
                    title=item.title,
                    kind=item.kind,
                    state=item.state,
                    status=item.status,
                )
                for item in stored_resume.affected_objects
            ],
        )
    try:
        plan = plan_service.get_for_resume(plan_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{exc.resource} not found",
        ) from exc
    except ActionPlanConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc

    try:
        runtime = build_assistant_runtime(session, current_user.user_id)
    except (
        AssistantConfigurationError,
        AssistantOpenAIConfigError,
        UserOpenAICredentialConfigurationError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=build_assistant_error_detail(exc),
        ) from exc

    assistant = AssistantService(
        current_user.user_id,
        runtime.provider,
        user_timezone=runtime.effective.timezone,
    )
    try:
        result = assistant.finalize_executed_plan(plan)
    except OpenAIDailyBudgetExhaustedError as exc:
        raise _openai_daily_budget_http_error(current_user.user_id, exc) from exc
    except AssistantProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=build_assistant_error_detail(exc),
        ) from exc

    persisted = conversations.persist_resume(plan_id, result)
    return ActionPlanResumeResponse(
        answer=persisted.answer,
        affected_objects=[
            AssistantAffectedObjectOut(
                object_id=item.object_id,
                title=item.title,
                kind=item.kind,
                state=item.state,
                status=item.status,
            )
            for item in persisted.affected_objects
        ],
    )


def _pending_plan_out(plan) -> PendingActionPlanOut | None:
    if plan is None:
        return None
    return PendingActionPlanOut(
        id=plan.id,
        status=plan.status,
        expires_at=plan.expires_at.isoformat(),
        actions=[
            PendingActionOut(tool_name=action.tool_name, arguments=action.arguments)
            for action in plan.actions
        ],
    )


def _receipt_out(receipt) -> InboxReviewReceiptOut | None:
    if receipt is None:
        return None
    return InboxReviewReceiptOut(
        anchor_before_object_id=receipt.anchor_before_object_id,
        anchor_before_feed_at=receipt.anchor_before_feed_at,
        snapshot_top_object_id=receipt.snapshot_top_object_id,
        snapshot_top_feed_at=receipt.snapshot_top_feed_at,
        total_count=receipt.total_count,
    )


def _message_response(
    result,
    *,
    conversation_id: UUID | None = None,
    user_message_id: UUID | None = None,
    assistant_message_id: UUID | None = None,
) -> AssistantMessageResponse:
    return AssistantMessageResponse(
        answer=result.answer,
        references=[
            AssistantReferenceOut(
                object_id=ref.object_id,
                title=ref.title,
                kind=ref.kind,
                canonical_uri=ref.canonical_uri,
                provider=ref.provider,
                primary_at=ref.primary_at,
            )
            for ref in result.references
        ],
        affected_objects=[
            AssistantAffectedObjectOut(
                object_id=item.object_id,
                title=item.title,
                kind=item.kind,
                state=item.state,
                status=item.status,
            )
            for item in result.affected_objects
        ],
        pending_action_plan=_pending_plan_out(result.pending_action_plan),
        inbox_review_receipt=_receipt_out(result.inbox_review_receipt),
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
    )
