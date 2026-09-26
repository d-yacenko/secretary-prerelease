"""Add task completion mode.

Revision ID: 0050
Revises: 0049
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("objects", sa.Column("completion_mode", sa.Text(), nullable=True))
    op.execute(
        "UPDATE objects SET completion_mode = 'finite' "
        "WHERE kind = 'task' AND completion_mode IS NULL"
    )
    op.create_check_constraint(
        "ck_objects_completion_mode",
        "objects",
        "completion_mode IS NULL OR completion_mode IN ('finite', 'ongoing')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_objects_completion_mode", "objects", type_="check")
    op.drop_column("objects", "completion_mode")
