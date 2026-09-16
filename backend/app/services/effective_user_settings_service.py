from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.assistant.constants import (
    DEFAULT_ASSISTANT_MAX_ROUNDS,
    MAX_ASSISTANT_MAX_ROUNDS,
    MIN_ASSISTANT_MAX_ROUNDS,
)
from app.core.assistant_openai_config import (
    ALLOWED_ASSISTANT_REASONING_EFFORTS,
    ALLOWED_ASSISTANT_VERBOSITY,
    AssistantOpenAIConfigError,
    validate_assistant_model,
    validate_assistant_reasoning_effort,
    validate_assistant_verbosity,
    validated_assistant_openai_settings,
)
from app.core.config import settings
from app.db.models import UserSettings
from app.proactive.constants import (
    PROACTIVE_ENABLED_DEFAULT,
    PROACTIVE_INTERVAL_MINUTES_DEFAULT,
    PROACTIVE_INTERVAL_MINUTES_MAX,
    PROACTIVE_INTERVAL_MINUTES_MIN,
)
from app.services.auto_label_constants import AUTO_LABEL_ENABLED_DEFAULT
from app.services.errors import ValidationError
from app.services.openai_daily_budget import (
    MIN_OPENAI_DAILY_TOKEN_LIMIT,
    validate_openai_daily_token_limit,
)
from app.services.temporal_signals_constants import TEMPORAL_SIGNALS_ENABLED_DEFAULT
from app.services.user_openai_credential_store import UserOpenAICredentialStore


def utcnow() -> datetime:
    return datetime.now(UTC)


def resolve_user_timezone(session: Session, user_id: UUID) -> str:
    """Effective IANA timezone for local-day semantics, without touching credentials."""
    row = session.get(UserSettings, user_id)
    return _resolve_timezone_from_row(row)


def _resolve_timezone_from_row(row: UserSettings | None) -> str:
    if row is not None and row.timezone:
        return row.timezone.strip()
    server_tz = settings.secretary_timezone.strip()
    return server_tz if server_tz else "Europe/Amsterdam"


@dataclass(frozen=True)
class EffectiveUserSettings:
    timezone: str
    assistant_model: str
    assistant_reasoning_effort: str
    assistant_verbosity: str
    assistant_max_rounds: int
    assistant_max_rounds_override: int | None
    openai_key_configured: bool
    allowed_assistant_models: list[str]
    openai_api_key: str | None = field(default=None, repr=False)
    proactive_enabled: bool = PROACTIVE_ENABLED_DEFAULT
    proactive_interval_minutes: int = PROACTIVE_INTERVAL_MINUTES_DEFAULT
    auto_label_enabled: bool = AUTO_LABEL_ENABLED_DEFAULT
    temporal_signals_enabled: bool = TEMPORAL_SIGNALS_ENABLED_DEFAULT
    openai_daily_token_limit: int | None = None


class EffectiveUserSettingsService:
    def __init__(
        self,
        session: Session,
        credential_store: UserOpenAICredentialStore,
    ) -> None:
        self._session = session
        self._credential_store = credential_store

    def get_effective_settings(self, user_id: UUID) -> EffectiveUserSettings:
        deployment = validated_assistant_openai_settings(settings)
        row = self._session.get(UserSettings, user_id)
        allowed_models = list(settings.allowed_assistant_models)
        timezone = self._resolve_timezone(row)
        assistant_model = self._resolve_assistant_model(row, deployment.model, allowed_models)
        assistant_reasoning_effort = self._resolve_reasoning_effort(
            row, deployment.reasoning_effort
        )
        assistant_verbosity = self._resolve_verbosity(row, deployment.verbosity)
        assistant_max_rounds = self._resolve_assistant_max_rounds(row)
        openai_key_configured = self._credential_store.is_configured(user_id)
        resolved_key = self._resolve_openai_api_key(user_id, openai_key_configured)
        return EffectiveUserSettings(
            timezone=timezone,
            assistant_model=assistant_model,
            assistant_reasoning_effort=assistant_reasoning_effort,
            assistant_verbosity=assistant_verbosity,
            assistant_max_rounds=assistant_max_rounds,
            assistant_max_rounds_override=self._stored_assistant_max_rounds_override(row),
            openai_key_configured=openai_key_configured,
            allowed_assistant_models=allowed_models,
            openai_api_key=resolved_key,
            proactive_enabled=self._resolve_proactive_enabled(row),
            proactive_interval_minutes=self._resolve_proactive_interval_minutes(row),
            auto_label_enabled=self._resolve_auto_label_enabled(row),
            temporal_signals_enabled=self._resolve_temporal_signals_enabled(row),
            openai_daily_token_limit=self._resolve_openai_daily_token_limit(row),
        )

    def get_settings_view(self, user_id: UUID) -> EffectiveUserSettings:
        """Safe settings for GET /me/settings — never decrypts stored credentials."""
        deployment = validated_assistant_openai_settings(settings)
        row = self._session.get(UserSettings, user_id)
        allowed_models = list(settings.allowed_assistant_models)
        openai_key_configured = self._credential_store.is_configured(user_id)
        return EffectiveUserSettings(
            timezone=self._resolve_timezone(row),
            assistant_model=self._resolve_assistant_model(row, deployment.model, allowed_models),
            assistant_reasoning_effort=self._resolve_reasoning_effort(
                row, deployment.reasoning_effort
            ),
            assistant_verbosity=self._resolve_verbosity(row, deployment.verbosity),
            assistant_max_rounds=self._resolve_assistant_max_rounds(row),
            assistant_max_rounds_override=self._stored_assistant_max_rounds_override(row),
            openai_key_configured=openai_key_configured,
            allowed_assistant_models=allowed_models,
            openai_api_key=None,
            proactive_enabled=self._resolve_proactive_enabled(row),
            proactive_interval_minutes=self._resolve_proactive_interval_minutes(row),
            auto_label_enabled=self._resolve_auto_label_enabled(row),
            temporal_signals_enabled=self._resolve_temporal_signals_enabled(row),
            openai_daily_token_limit=self._resolve_openai_daily_token_limit(row),
        )

    def get_or_create_settings_row(self, user_id: UUID) -> UserSettings:
        row = self._session.get(UserSettings, user_id)
        if row is None:
            row = UserSettings(user_id=user_id)
            self._session.add(row)
            self._session.flush()
        return row

    def update_settings(
        self,
        user_id: UUID,
        timezone: str | None = None,
        assistant_model: str | None = None,
        assistant_reasoning_effort: str | None = None,
        assistant_verbosity: str | None = None,
        assistant_max_rounds: int | None = None,
        assistant_max_rounds_set: bool = False,
        proactive_enabled: bool | None = None,
        proactive_interval_minutes: int | None = None,
        auto_label_enabled: bool | None = None,
        temporal_signals_enabled: bool | None = None,
        openai_daily_token_limit: int | None = None,
        openai_daily_token_limit_set: bool = False,
    ) -> EffectiveUserSettings:
        row = self.get_or_create_settings_row(user_id)
        allowed_models = settings.allowed_assistant_models
        if timezone is not None:
            self._validate_timezone(timezone)
            row.timezone = timezone.strip()
        if assistant_model is not None:
            try:
                row.assistant_model = validate_assistant_model(
                    assistant_model, allowed_models
                )
            except AssistantOpenAIConfigError as exc:
                raise ValidationError(str(exc)) from exc
        if assistant_reasoning_effort is not None:
            try:
                row.assistant_reasoning_effort = validate_assistant_reasoning_effort(
                    assistant_reasoning_effort
                )
            except AssistantOpenAIConfigError as exc:
                raise ValidationError(str(exc)) from exc
        if assistant_verbosity is not None:
            try:
                row.assistant_verbosity = validate_assistant_verbosity(assistant_verbosity)
            except AssistantOpenAIConfigError as exc:
                raise ValidationError(str(exc)) from exc
        if assistant_max_rounds_set:
            if assistant_max_rounds is None:
                row.assistant_max_rounds = None
            else:
                row.assistant_max_rounds = self._validate_assistant_max_rounds(
                    assistant_max_rounds
                )
        if proactive_enabled is not None:
            row.proactive_enabled = bool(proactive_enabled)
        if proactive_interval_minutes is not None:
            row.proactive_interval_minutes = self._validate_proactive_interval_minutes(
                proactive_interval_minutes
            )
        if auto_label_enabled is not None:
            row.auto_label_enabled = bool(auto_label_enabled)
        if temporal_signals_enabled is not None:
            row.temporal_signals_enabled = bool(temporal_signals_enabled)
        if openai_daily_token_limit_set:
            if openai_daily_token_limit is None:
                row.openai_daily_token_limit = None
            else:
                row.openai_daily_token_limit = validate_openai_daily_token_limit(
                    openai_daily_token_limit
                )
        row.updated_at = utcnow()
        self._session.flush()
        return self.get_settings_view(user_id)

    def resolve_openai_api_key(self, user_id: UUID) -> str | None:
        """Resolve decrypted OpenAI API key without creating a settings row."""
        return self._resolve_openai_api_key(
            user_id,
            self._credential_store.is_configured(user_id),
        )

    def _resolve_openai_api_key(
        self,
        user_id: UUID,
        openai_key_configured: bool,
    ) -> str | None:
        if openai_key_configured:
            return self._credential_store.get_api_key(user_id)
        deployment_key = settings.openai_api_key.strip() or None
        return deployment_key

    def _resolve_assistant_model(
        self,
        row: UserSettings | None,
        deployment_model: str,
        allowed_models: list[str],
    ) -> str:
        if row is not None and row.assistant_model:
            stored = row.assistant_model.strip()
            if stored in allowed_models:
                return stored
        return deployment_model

    def _resolve_reasoning_effort(
        self,
        row: UserSettings | None,
        deployment_effort: str,
    ) -> str:
        if row is not None and row.assistant_reasoning_effort:
            stored = row.assistant_reasoning_effort.strip().lower()
            if stored in ALLOWED_ASSISTANT_REASONING_EFFORTS:
                return stored
        return deployment_effort

    def _resolve_verbosity(
        self,
        row: UserSettings | None,
        deployment_verbosity: str,
    ) -> str:
        if row is not None and row.assistant_verbosity:
            stored = row.assistant_verbosity.strip().lower()
            if stored in ALLOWED_ASSISTANT_VERBOSITY:
                return stored
        return deployment_verbosity

    def _resolve_assistant_max_rounds(self, row: UserSettings | None) -> int:
        override = self._stored_assistant_max_rounds_override(row)
        if override is not None:
            return override
        return DEFAULT_ASSISTANT_MAX_ROUNDS

    def _stored_assistant_max_rounds_override(self, row: UserSettings | None) -> int | None:
        if row is None or row.assistant_max_rounds is None:
            return None
        stored = row.assistant_max_rounds
        if MIN_ASSISTANT_MAX_ROUNDS <= stored <= MAX_ASSISTANT_MAX_ROUNDS:
            return stored
        return None

    def _validate_assistant_max_rounds(self, value: int) -> int:
        if value < MIN_ASSISTANT_MAX_ROUNDS or value > MAX_ASSISTANT_MAX_ROUNDS:
            raise ValidationError(
                f"assistant_max_rounds must be between "
                f"{MIN_ASSISTANT_MAX_ROUNDS} and {MAX_ASSISTANT_MAX_ROUNDS}"
            )
        return value

    def _resolve_timezone(self, row: UserSettings | None) -> str:
        return _resolve_timezone_from_row(row)

    def _resolve_proactive_enabled(self, row: UserSettings | None) -> bool:
        if row is None:
            return PROACTIVE_ENABLED_DEFAULT
        return bool(row.proactive_enabled)

    def _resolve_proactive_interval_minutes(self, row: UserSettings | None) -> int:
        if row is None:
            return PROACTIVE_INTERVAL_MINUTES_DEFAULT
        stored = row.proactive_interval_minutes
        if PROACTIVE_INTERVAL_MINUTES_MIN <= stored <= PROACTIVE_INTERVAL_MINUTES_MAX:
            return stored
        return PROACTIVE_INTERVAL_MINUTES_DEFAULT

    def _validate_proactive_interval_minutes(self, value: int) -> int:
        if value < PROACTIVE_INTERVAL_MINUTES_MIN or value > PROACTIVE_INTERVAL_MINUTES_MAX:
            raise ValidationError(
                "proactive_interval_minutes must be between "
                f"{PROACTIVE_INTERVAL_MINUTES_MIN} and {PROACTIVE_INTERVAL_MINUTES_MAX}"
            )
        return value

    def _resolve_auto_label_enabled(self, row: UserSettings | None) -> bool:
        if row is None:
            return AUTO_LABEL_ENABLED_DEFAULT
        return bool(row.auto_label_enabled)

    def _resolve_temporal_signals_enabled(self, row: UserSettings | None) -> bool:
        if row is None:
            return TEMPORAL_SIGNALS_ENABLED_DEFAULT
        return bool(row.temporal_signals_enabled)

    def _resolve_openai_daily_token_limit(self, row: UserSettings | None) -> int | None:
        if row is None or row.openai_daily_token_limit is None:
            return None
        stored = int(row.openai_daily_token_limit)
        if stored < MIN_OPENAI_DAILY_TOKEN_LIMIT:
            return None
        return stored

    def _validate_timezone(self, timezone: str) -> str:
        text = timezone.strip()
        if not text:
            raise ValidationError("timezone cannot be blank")
        try:
            ZoneInfo(text)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValidationError(f"invalid timezone: {timezone}") from exc
        return text

    @staticmethod
    def build(session: Session) -> EffectiveUserSettingsService:
        credential_store = UserOpenAICredentialStore.build_from_settings(session)
        return EffectiveUserSettingsService(session, credential_store)
