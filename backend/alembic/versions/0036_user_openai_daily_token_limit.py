"""per-user daily OpenAI token hard cap

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-12

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("openai_daily_token_limit", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "openai_daily_token_limit")
