import uuid
from datetime import datetime

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(nullable=False)
    token_prefix: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_auth_tokens_user_id", "user_id"),
        Index("ix_auth_tokens_token_prefix", "token_prefix"),
        sa.UniqueConstraint("token_hash", name="uq_auth_tokens_token_hash"),
    )


class Object(Base):
    __tablename__ = "objects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(nullable=False)
    body: Mapped[str | None] = mapped_column(nullable=True)
    provider: Mapped[str | None] = mapped_column(nullable=True)
    external_id: Mapped[str | None] = mapped_column(nullable=True)
    canonical_uri: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str | None] = mapped_column(nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    planned_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    origin: Mapped[str] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(nullable=False, server_default="confirmed")
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    embedding_signature: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_objects_user_id", "user_id"),
        Index("ix_objects_kind", "kind"),
        Index("ix_objects_status", "status"),
        Index("ix_objects_state", "state"),
        Index("ix_objects_due_at", "due_at"),
        Index("ix_objects_user_id_deleted_at", "user_id", "deleted_at"),
        Index(
            "uq_objects_user_provider_kind_external_id",
            "user_id",
            "provider",
            "kind",
            "external_id",
            unique=True,
            postgresql_where=text("provider IS NOT NULL AND external_id IS NOT NULL"),
        ),
    )


class Edge(Base):
    __tablename__ = "edges"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("objects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("objects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(nullable=False)
    origin: Mapped[str] = mapped_column(nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    state: Mapped[str] = mapped_column(nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_edges_source_id", "source_id"),
        Index("ix_edges_target_id", "target_id"),
        Index("ix_edges_type", "type"),
    )


class View(Base):
    __tablename__ = "views"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(nullable=False)
    view_type: Mapped[str] = mapped_column(nullable=False)
    root_object_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("objects.id", ondelete="SET NULL"),
        nullable=True,
    )
    settings_: Mapped[dict] = mapped_column(
        "settings",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (Index("ix_views_user_id", "user_id"),)


class ViewItem(Base):
    __tablename__ = "view_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    view_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("views.id", ondelete="CASCADE"),
        nullable=False,
    )
    object_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("objects.id", ondelete="CASCADE"),
        nullable=True,
    )
    visual_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    x: Mapped[float | None] = mapped_column(nullable=True)
    y: Mapped[float | None] = mapped_column(nullable=True)
    width: Mapped[float | None] = mapped_column(nullable=True)
    height: Mapped[float | None] = mapped_column(nullable=True)
    collapsed: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    settings_: Mapped[dict] = mapped_column(
        "settings",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        sa.CheckConstraint(
            "(object_id IS NOT NULL AND visual_id IS NULL) "
            "OR (object_id IS NULL AND visual_id IS NOT NULL)",
            name="ck_view_items_object_xor_visual",
        ),
    )


class Representation(Base):
    __tablename__ = "representations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    object_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("objects.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(nullable=False)
    part_index: Mapped[int | None] = mapped_column(nullable=True)
    text: Mapped[str | None] = mapped_column(nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_representations_object_id", "object_id"),
        Index("ix_representations_kind", "kind"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    status: Mapped[str] = mapped_column(nullable=False)
    attempts: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_jobs_user_id_status_run_after", "user_id", "status", "run_after"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(nullable=False)
    body: Mapped[str | None] = mapped_column(nullable=True)
    priority: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    source_object_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("objects.id", ondelete="SET NULL"),
        nullable=True,
    )
    related_object_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("objects.id", ondelete="SET NULL"),
        nullable=True,
    )
    result_object_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("objects.id", ondelete="SET NULL"),
        nullable=True,
    )
    proposal_: Mapped[dict] = mapped_column(
        "proposal",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_notifications_user_id_status", "user_id", "status"),
        Index("ix_notifications_priority", "priority"),
        Index("ix_notifications_created_at", "created_at"),
    )


class PendingActionPlan(Base):
    __tablename__ = "pending_action_plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(nullable=False)
    actions: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    failure: Mapped[str | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_pending_action_plans_user_id", "user_id"),
        Index("ix_pending_action_plans_status", "status"),
        Index("ix_pending_action_plans_expires_at", "expires_at"),
    )


class GoogleAccount(Base):
    __tablename__ = "google_accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(nullable=False)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False)
    access_token_encrypted: Mapped[str | None] = mapped_column(nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(nullable=True)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gmail_sync_state: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    calendar_sync_state: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_google_accounts_user_id", "user_id"),
        sa.UniqueConstraint("user_id", "email", name="uq_google_accounts_user_id_email"),
    )


class OAuthState(Base):
    __tablename__ = "oauth_states"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    state_hash: Mapped[str] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_oauth_states_state_hash", "state_hash"),
    )


class YandexMailAccount(Base):
    __tablename__ = "yandex_mail_accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(nullable=False)
    app_password_encrypted: Mapped[str] = mapped_column(nullable=False)
    imap_host: Mapped[str] = mapped_column(nullable=False, server_default="imap.yandex.ru")
    imap_port: Mapped[int] = mapped_column(nullable=False, server_default=text("993"))
    sync_state: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_yandex_mail_accounts_user_id", "user_id"),
        sa.UniqueConstraint("user_id", "email", name="uq_yandex_mail_accounts_user_id_email"),
    )


class YandexCalendarAccount(Base):
    __tablename__ = "yandex_calendar_accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(nullable=False)
    app_password_encrypted: Mapped[str] = mapped_column(nullable=False)
    caldav_host: Mapped[str] = mapped_column(nullable=False, server_default="caldav.yandex.ru")
    sync_state: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_yandex_calendar_accounts_user_id", "user_id"),
        sa.UniqueConstraint("user_id", "email", name="uq_yandex_calendar_accounts_user_id_email"),
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    timezone: Mapped[str | None] = mapped_column(nullable=True)
    assistant_model: Mapped[str | None] = mapped_column(nullable=True)
    assistant_reasoning_effort: Mapped[str | None] = mapped_column(nullable=True)
    assistant_verbosity: Mapped[str | None] = mapped_column(nullable=True)
    assistant_max_rounds: Mapped[int | None] = mapped_column(nullable=True)
    openai_daily_token_limit: Mapped[int | None] = mapped_column(nullable=True)
    proactive_enabled: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    proactive_interval_minutes: Mapped[int] = mapped_column(
        nullable=False,
        default=60,
        server_default=text("60"),
    )
    auto_label_enabled: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    temporal_signals_enabled: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserOpenAICredential(Base):
    __tablename__ = "user_openai_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    api_key_encrypted: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserSourcePreference(Base):
    __tablename__ = "user_source_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source: Mapped[str] = mapped_column(primary_key=True)
    enabled: Mapped[bool | None] = mapped_column(nullable=True)
    sync_interval_seconds: Mapped[int | None] = mapped_column(nullable=True)
    history_days: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MattermostAccount(Base):
    __tablename__ = "mattermost_accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    server_url: Mapped[str] = mapped_column(nullable=False)
    remote_user_id: Mapped[str] = mapped_column(nullable=False)
    username: Mapped[str] = mapped_column(nullable=False)
    display_name: Mapped[str | None] = mapped_column(nullable=True)
    email: Mapped[str | None] = mapped_column(nullable=True)
    access_token_encrypted: Mapped[str] = mapped_column(nullable=False)
    sync_state: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_mattermost_accounts_user_id", "user_id"),
        sa.UniqueConstraint(
            "user_id",
            "server_url",
            "remote_user_id",
            name="uq_mattermost_accounts_user_server_remote_user",
        ),
    )


class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    telegram_user_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    user_chat_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    telegram_username: Mapped[str | None] = mapped_column(nullable=True)
    display_name: Mapped[str | None] = mapped_column(nullable=True)
    business_connection_id: Mapped[str | None] = mapped_column(nullable=True)
    business_user_chat_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    business_rights: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    business_connection_enabled: Mapped[bool] = mapped_column(
        nullable=False,
        server_default=text("false"),
    )
    business_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        sa.UniqueConstraint("user_id", name="uq_telegram_accounts_user_id"),
        sa.UniqueConstraint("telegram_user_id", name="uq_telegram_accounts_telegram_user_id"),
        sa.UniqueConstraint(
            "business_connection_id",
            name="uq_telegram_accounts_business_connection_id",
        ),
    )


class TelegramLinkState(Base):
    __tablename__ = "telegram_link_states"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    state_hash: Mapped[str] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        sa.UniqueConstraint("state_hash", name="uq_telegram_link_states_state_hash"),
        Index("ix_telegram_link_states_user_id", "user_id"),
    )


class TelegramMtprotoAccount(Base):
    __tablename__ = "telegram_mtproto_accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    telegram_user_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    session_encrypted: Mapped[str] = mapped_column(nullable=False)
    username: Mapped[str | None] = mapped_column(nullable=True)
    display_name: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        sa.UniqueConstraint("user_id", name="uq_telegram_mtproto_accounts_user_id"),
        sa.UniqueConstraint(
            "telegram_user_id", name="uq_telegram_mtproto_accounts_telegram_user_id"
        ),
    )


class TelegramMtprotoChatSelection(Base):
    __tablename__ = "telegram_mtproto_chat_selections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("telegram_mtproto_accounts.id", ondelete="CASCADE"), nullable=False
    )
    peer_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    peer_kind: Mapped[str] = mapped_column(sa.String(length=32), nullable=False)
    provider_peer_reference_encrypted: Mapped[str] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(nullable=False)
    username: Mapped[str | None] = mapped_column(nullable=True)
    is_forum: Mapped[bool] = mapped_column(nullable=False, server_default=sa.false())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "account_id", "peer_id", name="uq_telegram_mtproto_chat_selections_account_peer"
        ),
        sa.CheckConstraint(
            "peer_kind IN ('group', 'supergroup')",
            name="ck_telegram_mtproto_chat_selections_peer_kind",
        ),
    )


class TelegramMtprotoAuthChallenge(Base):
    __tablename__ = "telegram_mtproto_auth_challenges"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    auth_state_encrypted: Mapped[str] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        sa.UniqueConstraint("user_id", name="uq_telegram_mtproto_auth_challenges_user_id"),
        Index("ix_telegram_mtproto_auth_challenges_expires_at", "expires_at"),
    )


class TeamsAccount(Base):
    __tablename__ = "teams_accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    microsoft_user_id: Mapped[str] = mapped_column(nullable=False)
    tenant_id: Mapped[str] = mapped_column(nullable=False)
    upn: Mapped[str | None] = mapped_column(nullable=True)
    display_name: Mapped[str | None] = mapped_column(nullable=True)
    auth_status: Mapped[str] = mapped_column(
        nullable=False,
        server_default=text("'active'"),
    )
    access_token_encrypted: Mapped[str] = mapped_column(nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(nullable=False)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    sync_state: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        sa.UniqueConstraint("user_id", name="uq_teams_accounts_user_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "microsoft_user_id",
            name="uq_teams_accounts_tenant_microsoft_user",
        ),
    )


class TeamsSubscription(Base):
    __tablename__ = "teams_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams_accounts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    subscription_id: Mapped[str] = mapped_column(nullable=False)
    resource: Mapped[str] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    client_state_encrypted: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, server_default=text("'active'"))
    last_renewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        sa.UniqueConstraint("account_id", name="uq_teams_subscriptions_account_id"),
        sa.UniqueConstraint("subscription_id", name="uq_teams_subscriptions_subscription_id"),
        Index("ix_teams_subscriptions_user_id", "user_id"),
    )


class TeamsOAuthState(Base):
    __tablename__ = "teams_oauth_states"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    state_hash: Mapped[str] = mapped_column(nullable=False)
    nonce_hash: Mapped[str] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        sa.UniqueConstraint("state_hash", name="uq_teams_oauth_states_state_hash"),
        Index("ix_teams_oauth_states_user_id", "user_id"),
    )


class LocalDevice(Base):
    __tablename__ = "local_devices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    device_key: Mapped[str] = mapped_column(nullable=False)
    display_name: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_local_devices_user_id", "user_id"),
        sa.UniqueConstraint("user_id", "device_key", name="uq_local_devices_user_id_device_key"),
    )


class LocalRoot(Base):
    __tablename__ = "local_roots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("local_devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    root_path: Mapped[str] = mapped_column(nullable=False)
    default_policy: Mapped[str] = mapped_column(
        nullable=False,
        server_default="metadata_only",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_local_roots_user_id", "user_id"),
        Index("ix_local_roots_device_id", "device_id"),
        sa.UniqueConstraint(
            "user_id",
            "device_id",
            "root_path",
            name="uq_local_roots_user_device_root_path",
        ),
    )


class AITrace(Base):
    __tablename__ = "ai_traces"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    workload: Mapped[str] = mapped_column(nullable=False)
    parent_trace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_traces.id", ondelete="SET NULL"),
        nullable=True,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    object_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    success: Mapped[bool] = mapped_column(
        nullable=False,
        server_default=text("true"),
    )
    error_category: Mapped[str | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_ai_traces_user_started", "user_id", "started_at"),
    )


class AITraceEvent(Base):
    __tablename__ = "ai_trace_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_traces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    payload_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_ai_trace_events_trace_sequence", "trace_id", "sequence"),
        Index("ix_ai_trace_events_user_created", "user_id", "created_at"),
        Index("ix_ai_trace_events_payload_expires", "payload_expires_at"),
    )


class AIAuditCaptureSession(Base):
    __tablename__ = "ai_audit_capture_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    enabled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    payload_retention_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class UserIdentityProfile(Base):
    __tablename__ = "user_identity_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    profile_text: Mapped[str] = mapped_column(nullable=False, server_default="")
    full_name: Mapped[str | None] = mapped_column(nullable=True)
    preferred_name: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserSemanticContext(Base):
    __tablename__ = "user_semantic_contexts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    context_text: Mapped[str] = mapped_column(nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class InboxReviewMarker(Base):
    __tablename__ = "inbox_review_markers"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    anchor_feed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    anchor_object_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ObjectBookmark(Base):
    __tablename__ = "object_bookmarks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("objects.id", ondelete="CASCADE"),
        nullable=False,
    )
    color: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint("user_id", "object_id", name="pk_object_bookmarks"),
        sa.UniqueConstraint("user_id", "object_id", name="uq_object_bookmarks_user_id_object_id"),
        Index("ix_object_bookmarks_user_id", "user_id"),
        Index("ix_object_bookmarks_object_id", "object_id"),
    )


class ExternalActionAttempt(Base):
    __tablename__ = "external_action_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    operation_id: Mapped[str] = mapped_column(nullable=False)
    tool_name: Mapped[str] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_external_id: Mapped[str | None] = mapped_column(nullable=True)
    result_metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "user_id",
            "operation_id",
            name="uq_external_action_attempts_user_id_operation_id",
        ),
        Index("ix_external_action_attempts_user_id", "user_id"),
    )
