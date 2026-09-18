from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SOURCE_SYNC_INTERVAL_SECONDS = 60
MIN_SOURCE_SYNC_HISTORY_DAYS = 1
MAX_SOURCE_SYNC_HISTORY_DAYS = 90


def normalize_allowed_assistant_models(raw_allowlist: str, deployment_default: str) -> list[str]:
    default_model = deployment_default.strip()
    if not default_model:
        return []

    deduped: list[str] = []
    seen: set[str] = set()
    raw = raw_allowlist.strip()
    if raw:
        for item in raw.split(","):
            model = item.strip()
            if not model or model in seen:
                continue
            seen.add(model)
            deduped.append(model)

    if default_model not in seen:
        deduped.insert(0, default_model)
    return deduped if deduped else [default_model]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "secretary"
    postgres_user: str = "secretary"
    postgres_password: str = "secretary"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    openai_model: str = "gpt-5.6-terra"
    openai_assistant_model: str = "gpt-5.6-luna"
    openai_assistant_reasoning_effort: str = "low"
    openai_assistant_verbosity: str = "low"
    openai_assistant_max_output_tokens: int = 1600
    openai_allowed_assistant_models: str = ""
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"
    secretary_timezone: str = "Europe/Amsterdam"
    mcp_enabled: bool = False
    google_oauth_client_file: str = "/run/secrets/google-oauth-client.json"
    google_redirect_uri: str = "http://localhost:18080/auth/google/callback"
    secretary_credential_key: str = ""
    gmail_sync_default_limit: int = 50
    gmail_sync_max_limit: int = 100
    gmail_sync_days: int = 30
    calendar_sync_days_back: int = 60
    calendar_sync_days_forward: int = 90
    calendar_sync_default_limit: int = 100
    calendar_sync_max_limit: int = 100
    calendar_sync_max_calendars: int = 10
    yandex_mail_sync_days: int = 30
    yandex_mail_sync_default_limit: int = 50
    yandex_mail_sync_max_limit: int = 100
    mattermost_allowed_base_urls: str = ""
    mattermost_sync_days: int = 14
    mattermost_sync_max_channels: int = 50
    mattermost_sync_initial_posts_per_channel: int = 100
    mattermost_sync_max_posts_per_run: int = 500
    mattermost_sync_overlap_seconds: int = 300
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_webhook_secret: str = ""
    telegram_webhook_url: str = ""
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_mtproto_ai_enabled: bool = False
    microsoft_oauth_client_id: str = ""
    microsoft_oauth_client_secret: str = ""
    microsoft_redirect_uri: str = "http://localhost:18080/auth/teams/callback"
    microsoft_teams_notification_url: str = ""
    source_sync_teams_interval_seconds: int = 900
    source_sync_telegram_mtproto_interval_seconds: int = 60
    source_sync_gmail_interval_seconds: int = 120
    source_sync_yandex_mail_interval_seconds: int = 120
    source_sync_google_calendar_interval_seconds: int = 300
    source_sync_yandex_calendar_interval_seconds: int = 300
    source_sync_mattermost_interval_seconds: int = 120
    source_sync_scheduler_interval_seconds: int = 60
    source_sync_failed_rearm_seconds: int = 3600
    source_sync_user_min_interval_seconds: int = 60
    source_sync_user_max_interval_seconds: int = 86400
    source_sync_user_min_history_days: int = 1
    source_sync_user_max_history_days: int = 90
    resource_upload_root: str = "/var/lib/secretary/resources"
    local_files_root: str = "/var/lib/secretary/local-files"

    @field_validator(
        "source_sync_gmail_interval_seconds",
        "source_sync_yandex_mail_interval_seconds",
        "source_sync_google_calendar_interval_seconds",
        "source_sync_yandex_calendar_interval_seconds",
        "source_sync_mattermost_interval_seconds",
        "source_sync_teams_interval_seconds",
        "source_sync_telegram_mtproto_interval_seconds",
    )
    @classmethod
    def _validate_source_sync_interval(cls, value: int) -> int:
        if value < MIN_SOURCE_SYNC_INTERVAL_SECONDS:
            raise ValueError(
                f"source sync interval must be >= {MIN_SOURCE_SYNC_INTERVAL_SECONDS} seconds"
            )
        return value

    @field_validator("source_sync_user_min_interval_seconds")
    @classmethod
    def _validate_user_min_interval(cls, value: int) -> int:
        if value < MIN_SOURCE_SYNC_INTERVAL_SECONDS:
            raise ValueError(
                f"source sync user min interval must be >= "
                f"{MIN_SOURCE_SYNC_INTERVAL_SECONDS} seconds"
            )
        return value

    @field_validator("source_sync_user_max_interval_seconds")
    @classmethod
    def _validate_user_max_interval(cls, value: int, info) -> int:
        min_value = info.data.get(
            "source_sync_user_min_interval_seconds",
            MIN_SOURCE_SYNC_INTERVAL_SECONDS,
        )
        if value < min_value:
            raise ValueError(
                "source sync user max interval must be >= user min interval"
            )
        return value

    @field_validator("source_sync_user_min_history_days")
    @classmethod
    def _validate_user_min_history_days(cls, value: int) -> int:
        if value < MIN_SOURCE_SYNC_HISTORY_DAYS:
            raise ValueError(
                f"source sync user min history days must be >= "
                f"{MIN_SOURCE_SYNC_HISTORY_DAYS}"
            )
        return value

    @field_validator("source_sync_user_max_history_days")
    @classmethod
    def _validate_user_max_history_days(cls, value: int, info) -> int:
        min_value = info.data.get(
            "source_sync_user_min_history_days",
            MIN_SOURCE_SYNC_HISTORY_DAYS,
        )
        if value < min_value:
            raise ValueError(
                "source sync user max history days must be >= user min history days"
            )
        if value > MAX_SOURCE_SYNC_HISTORY_DAYS:
            raise ValueError(
                f"source sync user max history days must be <= "
                f"{MAX_SOURCE_SYNC_HISTORY_DAYS}"
            )
        return value

    @property
    def allowed_assistant_models(self) -> list[str]:
        return normalize_allowed_assistant_models(
            self.openai_allowed_assistant_models,
            self.openai_assistant_model,
        )

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
