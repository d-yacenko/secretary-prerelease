"""Persist user-scoped canonical Task world-space centers.

Revision ID: 0052
Revises: 0051
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_layout_states",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("topology_revision", sa.Integer(), nullable=False),
        sa.Column("snapshot_revision", sa.Integer(), nullable=True),
        sa.Column("algorithm_version", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "topology_revision >= 1",
            name="ck_task_layout_states_topology_revision",
        ),
        sa.CheckConstraint(
            "snapshot_revision IS NULL OR "
            "(snapshot_revision >= 1 AND snapshot_revision <= topology_revision)",
            name="ck_task_layout_states_snapshot_revision",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "task_layout_positions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_revision", sa.Integer(), nullable=False),
        sa.Column("world_x", sa.Float(), nullable=False),
        sa.Column("world_y", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "snapshot_revision >= 1",
            name="ck_task_layout_positions_snapshot_revision",
        ),
        sa.CheckConstraint(
            "world_x = world_x AND world_y = world_y "
            "AND world_x > '-infinity'::float8 AND world_x < 'infinity'::float8 "
            "AND world_y > '-infinity'::float8 AND world_y < 'infinity'::float8",
            name="ck_task_layout_positions_finite",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "user_id",
            "task_id",
            "snapshot_revision",
            name="pk_task_layout_positions",
        ),
    )
    op.create_index(
        "ix_task_layout_positions_user_snapshot",
        "task_layout_positions",
        ["user_id", "snapshot_revision"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_task_layout_positions_user_snapshot",
        table_name="task_layout_positions",
    )
    op.drop_table("task_layout_positions")
    op.drop_table("task_layout_states")
