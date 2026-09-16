"""Encrypted Telegram MTProto account authorization foundation.

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_mtproto_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("session_encrypted", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_telegram_mtproto_accounts_user_id"),
        sa.UniqueConstraint(
            "telegram_user_id", name="uq_telegram_mtproto_accounts_telegram_user_id"
        ),
    )
    op.create_table(
        "telegram_mtproto_auth_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("auth_state_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_telegram_mtproto_auth_challenges_user_id"),
    )
    op.create_index(
        "ix_telegram_mtproto_auth_challenges_expires_at",
        "telegram_mtproto_auth_challenges",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telegram_mtproto_auth_challenges_expires_at",
        table_name="telegram_mtproto_auth_challenges",
    )
    op.drop_table("telegram_mtproto_auth_challenges")
    op.drop_table("telegram_mtproto_accounts")
