"""pending_action_plans table

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pending_action_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("actions", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("failure", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pending_action_plans_user_id",
        "pending_action_plans",
        ["user_id"],
    )
    op.create_index(
        "ix_pending_action_plans_status",
        "pending_action_plans",
        ["status"],
    )
    op.create_index(
        "ix_pending_action_plans_expires_at",
        "pending_action_plans",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pending_action_plans_expires_at", table_name="pending_action_plans")
    op.drop_index("ix_pending_action_plans_status", table_name="pending_action_plans")
    op.drop_index("ix_pending_action_plans_user_id", table_name="pending_action_plans")
    op.drop_table("pending_action_plans")
