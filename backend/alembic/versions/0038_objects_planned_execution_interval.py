"""objects planned execution interval

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-12

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "objects",
        sa.Column("planned_start_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "objects",
        sa.Column("planned_end_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_objects_planned_execution_interval",
        "objects",
        "(planned_start_at IS NULL AND planned_end_at IS NULL) "
        "OR (kind = 'task' AND planned_start_at IS NOT NULL "
        "AND planned_end_at IS NOT NULL AND planned_end_at > planned_start_at)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_objects_planned_execution_interval",
        "objects",
        type_="check",
    )
    op.drop_column("objects", "planned_end_at")
    op.drop_column("objects", "planned_start_at")
