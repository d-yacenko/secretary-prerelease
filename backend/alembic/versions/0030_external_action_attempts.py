"""durable irreversible external action attempts

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_action_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_external_id", sa.Text(), nullable=True),
        sa.Column(
            "result_metadata",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "operation_id",
            name="uq_external_action_attempts_user_id_operation_id",
        ),
    )
    op.create_index(
        "ix_external_action_attempts_user_id",
        "external_action_attempts",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_external_action_attempts_user_id",
        table_name="external_action_attempts",
    )
    op.drop_table("external_action_attempts")
