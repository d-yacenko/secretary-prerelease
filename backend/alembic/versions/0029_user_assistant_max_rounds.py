"""user assistant max rounds setting

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("assistant_max_rounds", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "assistant_max_rounds")
