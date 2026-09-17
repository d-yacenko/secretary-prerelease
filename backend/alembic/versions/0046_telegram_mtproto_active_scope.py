"""Add independent manual and dynamic Telegram peer state.

Revision ID: 0046
Revises: 0045
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "telegram_mtproto_chat_selections",
        sa.Column("manual_selected", sa.Boolean(), nullable=True, server_default=sa.true()),
    )
    op.add_column(
        "telegram_mtproto_chat_selections",
        sa.Column("scope_active", sa.Boolean(), nullable=True, server_default=sa.false()),
    )
    op.execute(
        "UPDATE telegram_mtproto_chat_selections SET manual_selected = TRUE, scope_active = FALSE"
    )
    op.alter_column("telegram_mtproto_chat_selections", "manual_selected", nullable=False)
    op.alter_column("telegram_mtproto_chat_selections", "scope_active", nullable=False)
    op.drop_constraint(
        "ck_telegram_mtproto_chat_selections_peer_kind",
        "telegram_mtproto_chat_selections",
        type_="check",
    )
    op.create_check_constraint(
        "ck_telegram_mtproto_chat_selections_peer_kind",
        "telegram_mtproto_chat_selections",
        "peer_kind IN ('private', 'group', 'supergroup')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_telegram_mtproto_chat_selections_peer_kind",
        "telegram_mtproto_chat_selections",
        type_="check",
    )
    op.create_check_constraint(
        "ck_telegram_mtproto_chat_selections_peer_kind",
        "telegram_mtproto_chat_selections",
        "peer_kind IN ('group', 'supergroup')",
    )
    op.drop_column("telegram_mtproto_chat_selections", "scope_active")
    op.drop_column("telegram_mtproto_chat_selections", "manual_selected")
