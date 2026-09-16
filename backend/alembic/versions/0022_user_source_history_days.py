"""user_source_history_days

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_source_preferences",
        sa.Column("history_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_source_preferences", "history_days")
