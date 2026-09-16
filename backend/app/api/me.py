
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth_schemas import UserMeOut
from app.api.deps import get_current_user, get_db
from app.assistant.constants import (
    DEFAULT_ASSISTANT_MAX_ROUNDS,
    MAX_ASSISTANT_MAX_ROUNDS,
    MIN_ASSISTANT_MAX_ROUNDS,
)
from app.core.current_user import CurrentUserContext
from app.db.models import User
from app.services.effective_user_settings_service import (
    EffectiveUserSettings,
    EffectiveUserSettingsService,
)
from app.services.errors import NotFoundError, ValidationError
from app.services.job_queue_service import JobQueueService
from app.services.openai_daily_budget import (
    MAX_OPENAI_DAILY_TOKEN_LIMIT,
    MIN_OPENAI_DAILY_TOKEN_LIMIT,
    OpenAIDailyBudgetGuard,
    OpenAIDailyBudgetStatus,
)
from app.services.personal_semantic_context_service import PersonalSemanticContextService
from app.services.user_identity_context_service import UserIdentityProfileService
from app.services.user_openai_credential_errors import UserOpenAICredentialConfigurationError
from app.services.user_openai_credential_store import UserOpenAICredentialStore

router = APIRouter(tags=["auth"])


class UserMePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("display_name cannot be blank")
        return value


class OpenAIDailyBudgetOut(BaseModel):
    daily_token_limit: int | None
    tokens_used_today: int
    exhausted: bool
    reset_at: str


class UserSettingsOut(BaseModel):
    timezone: str
    assistant_model: str
    assistant_reasoning_effort: str
    assistant_verbosity: str
    assistant_max_rounds: int
    assistant_max_rounds_override: int | None
    default_assistant_max_rounds: int
    min_assistant_max_rounds: int
    max_assistant_max_rounds: int
    openai_key_configured: bool
    allowed_assistant_models: list[str]
    proactive_enabled: bool
    proactive_interval_minutes: int
    auto_label_enabled: bool
    temporal_signals_enabled: bool
    openai_daily_token_limit: int | None
    min_openai_daily_token_limit: int
    max_openai_daily_token_limit: int
    openai_daily_budget: OpenAIDailyBudgetOut


class UserSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str | None = None
    assistant_model: str | None = None
    assistant_reasoning_effort: str | None = None
    assistant_verbosity: str | None = None
    assistant_max_rounds: int | None = None
    proactive_enabled: bool | None = None
    proactive_interval_minutes: int | None = None
    auto_label_enabled: bool | None = None
    temporal_signals_enabled: bool | None = None
    openai_daily_token_limit: int | None = None


class OpenAICredentialPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=1)


class OpenAICredentialOut(BaseModel):
    configured: bool


class ParsedIdentityOut(BaseModel):
    full_name: str | None = None
    preferred_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    telegram: list[str] = Field(default_factory=list)
    other_identifiers: list[str] = Field(default_factory=list)


class UserIdentityOut(BaseModel):
    profile_text: str
    full_name: str | None = None
    preferred_name: str | None = None
    parsed: ParsedIdentityOut


class UserIdentityPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_text: str


class SemanticContextOut(BaseModel):
    context_text: str


class SemanticContextPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_text: str


def _serialize_identity(view) -> UserIdentityOut:
    parsed = view.parsed
    return UserIdentityOut(
        profile_text=view.profile_text,
        full_name=view.full_name,
        preferred_name=view.preferred_name,
        parsed=ParsedIdentityOut(
            full_name=parsed.full_name,
            preferred_name=parsed.preferred_name,
            aliases=list(parsed.aliases),
            roles=list(parsed.roles),
            organizations=list(parsed.organizations),
            emails=list(parsed.emails),
            phones=list(parsed.phones),
            telegram=list(parsed.telegram),
            other_identifiers=list(parsed.other_identifiers),
        ),
    )


def _settings_service(session: Session) -> EffectiveUserSettingsService:
    return EffectiveUserSettingsService.build(session)


def _budget_status(session: Session, user_id: UUID) -> OpenAIDailyBudgetStatus:
    """Current fuse status; also the guaranteed-committed once-per-day warning point."""
    guard = OpenAIDailyBudgetGuard.build(session, user_id)
    status_view = guard.status()
    if status_view.exhausted:
        guard.ensure_exhausted_notification()
    return status_view


def _serialize_settings(
    effective: EffectiveUserSettings,
    budget: OpenAIDailyBudgetStatus,
) -> UserSettingsOut:
    return UserSettingsOut(
        timezone=effective.timezone,
        assistant_model=effective.assistant_model,
        assistant_reasoning_effort=effective.assistant_reasoning_effort,
        assistant_verbosity=effective.assistant_verbosity,
        assistant_max_rounds=effective.assistant_max_rounds,
        assistant_max_rounds_override=effective.assistant_max_rounds_override,
        default_assistant_max_rounds=DEFAULT_ASSISTANT_MAX_ROUNDS,
        min_assistant_max_rounds=MIN_ASSISTANT_MAX_ROUNDS,
        max_assistant_max_rounds=MAX_ASSISTANT_MAX_ROUNDS,
        openai_key_configured=effective.openai_key_configured,
        allowed_assistant_models=effective.allowed_assistant_models,
        proactive_enabled=effective.proactive_enabled,
        proactive_interval_minutes=effective.proactive_interval_minutes,
        auto_label_enabled=effective.auto_label_enabled,
        temporal_signals_enabled=effective.temporal_signals_enabled,
        openai_daily_token_limit=effective.openai_daily_token_limit,
        min_openai_daily_token_limit=MIN_OPENAI_DAILY_TOKEN_LIMIT,
        max_openai_daily_token_limit=MAX_OPENAI_DAILY_TOKEN_LIMIT,
        openai_daily_budget=OpenAIDailyBudgetOut(
            daily_token_limit=budget.daily_token_limit,
            tokens_used_today=budget.tokens_used_today,
            exhausted=budget.exhausted,
            reset_at=budget.reset_at.isoformat(),
        ),
    )


@router.get("/me", response_model=UserMeOut)
def get_me(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> UserMeOut:
    user = session.scalar(select(User).where(User.id == current_user.user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token user")
    return UserMeOut.model_validate(user)


@router.patch("/me", response_model=UserMeOut)
def patch_me(
    payload: UserMePatch,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> UserMeOut:
    if not payload.model_fields_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="no fields to update",
        )
    user = session.scalar(select(User).where(User.id == current_user.user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token user")
    if "display_name" in payload.model_fields_set:
        if payload.display_name is None or not payload.display_name.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="display_name cannot be blank",
            )
        user.display_name = payload.display_name.strip()
    session.flush()
    return UserMeOut.model_validate(user)


@router.get("/me/settings", response_model=UserSettingsOut)
def get_my_settings(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> UserSettingsOut:
    service = _settings_service(session)
    effective = service.get_settings_view(current_user.user_id)
    return _serialize_settings(effective, _budget_status(session, current_user.user_id))


@router.patch("/me/settings", response_model=UserSettingsOut)
def patch_my_settings(
    payload: UserSettingsPatch,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> UserSettingsOut:
    if not payload.model_fields_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="no fields to update",
        )
    service = _settings_service(session)
    try:
        effective = service.update_settings(
            current_user.user_id,
            timezone=payload.timezone if "timezone" in payload.model_fields_set else None,
            assistant_model=(
                payload.assistant_model if "assistant_model" in payload.model_fields_set else None
            ),
            assistant_reasoning_effort=(
                payload.assistant_reasoning_effort
                if "assistant_reasoning_effort" in payload.model_fields_set
                else None
            ),
            assistant_verbosity=(
                payload.assistant_verbosity
                if "assistant_verbosity" in payload.model_fields_set
                else None
            ),
            assistant_max_rounds=(
                payload.assistant_max_rounds
                if "assistant_max_rounds" in payload.model_fields_set
                else None
            ),
            assistant_max_rounds_set="assistant_max_rounds" in payload.model_fields_set,
            proactive_enabled=(
                payload.proactive_enabled if "proactive_enabled" in payload.model_fields_set else None
            ),
            proactive_interval_minutes=(
                payload.proactive_interval_minutes
                if "proactive_interval_minutes" in payload.model_fields_set
                else None
            ),
            auto_label_enabled=(
                payload.auto_label_enabled
                if "auto_label_enabled" in payload.model_fields_set
                else None
            ),
            temporal_signals_enabled=(
                payload.temporal_signals_enabled
                if "temporal_signals_enabled" in payload.model_fields_set
                else None
            ),
            openai_daily_token_limit=(
                payload.openai_daily_token_limit
                if "openai_daily_token_limit" in payload.model_fields_set
                else None
            ),
            openai_daily_token_limit_set=(
                "openai_daily_token_limit" in payload.model_fields_set
            ),
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc
    if (
        "proactive_enabled" in payload.model_fields_set
        or "proactive_interval_minutes" in payload.model_fields_set
    ):
        from app.services.proactive_scheduler import ProactiveScheduler

        ProactiveScheduler(session).sync_user(current_user.user_id)

    budget = _budget_status(session, current_user.user_id)
    if "timezone" in payload.model_fields_set or (
        "openai_daily_token_limit" in payload.model_fields_set and not budget.exhausted
    ):
        JobQueueService(session).release_budget_parked_jobs(current_user.user_id)
    return _serialize_settings(effective, budget)


@router.put("/me/credentials/openai", response_model=OpenAICredentialOut)
def put_openai_credential(
    payload: OpenAICredentialPut,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> OpenAICredentialOut:
    store = UserOpenAICredentialStore.build_from_settings(session)
    try:
        store.upsert(current_user.user_id, payload.api_key)
    except UserOpenAICredentialConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return OpenAICredentialOut(configured=True)


@router.delete("/me/credentials/openai", response_model=OpenAICredentialOut)
def delete_openai_credential(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> OpenAICredentialOut:
    store = UserOpenAICredentialStore.build_from_settings(session)
    store.delete(current_user.user_id)
    return OpenAICredentialOut(configured=False)


@router.get("/me/identity", response_model=UserIdentityOut)
def get_my_identity(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> UserIdentityOut:
    service = UserIdentityProfileService.build(session)
    return _serialize_identity(service.get_profile_view(current_user.user_id))


@router.put("/me/identity", response_model=UserIdentityOut)
def put_my_identity(
    payload: UserIdentityPut,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> UserIdentityOut:
    service = UserIdentityProfileService.build(session)
    try:
        view = service.upsert_profile(current_user.user_id, payload.profile_text)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc
    return _serialize_identity(view)


@router.get("/me/semantic-context", response_model=SemanticContextOut)
def get_my_semantic_context(
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> SemanticContextOut:
    service = PersonalSemanticContextService.build(session)
    return SemanticContextOut(context_text=service.get_context_text(current_user.user_id))


@router.put("/me/semantic-context", response_model=SemanticContextOut)
def put_my_semantic_context(
    payload: SemanticContextPut,
    session: Session = Depends(get_db),
    current_user: CurrentUserContext = Depends(get_current_user),
) -> SemanticContextOut:
    service = PersonalSemanticContextService.build(session)
    try:
        text = service.upsert_context(current_user.user_id, payload.context_text)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc
    return SemanticContextOut(context_text=text)
