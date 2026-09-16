"""Explicit Telegram MTProto group selections.

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_mtproto_chat_selections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("peer_id", sa.BigInteger(), nullable=False),
        sa.Column("peer_kind", sa.String(length=32), nullable=False),
        sa.Column("provider_peer_reference_encrypted", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("is_forum", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["telegram_mtproto_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "peer_id", name="uq_telegram_mtproto_chat_selections_account_peer"
        ),
        sa.CheckConstraint(
            "peer_kind IN ('group', 'supergroup')",
            name="ck_telegram_mtproto_chat_selections_peer_kind",
        ),
    )


def downgrade() -> None:
    op.drop_table("telegram_mtproto_chat_selections")
