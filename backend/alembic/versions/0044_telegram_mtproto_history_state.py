"""Durable bounded Telegram MTProto history cursors.

Revision ID: 0044
Revises: 0043
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "telegram_mtproto_chat_selections",
        sa.Column("history_latest_message_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "telegram_mtproto_chat_selections",
        sa.Column("history_backfill_before_message_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "telegram_mtproto_chat_selections",
        sa.Column("history_cutoff_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "telegram_mtproto_chat_selections",
        sa.Column("history_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "telegram_mtproto_chat_selections",
        sa.Column("history_last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegram_mtproto_chat_selections", "history_last_synced_at")
    op.drop_column("telegram_mtproto_chat_selections", "history_complete")
    op.drop_column("telegram_mtproto_chat_selections", "history_cutoff_at")
    op.drop_column("telegram_mtproto_chat_selections", "history_backfill_before_message_id")
    op.drop_column("telegram_mtproto_chat_selections", "history_latest_message_id")
