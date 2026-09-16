"""local_devices and local_roots

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-29

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "local_devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_key", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "device_key", name="uq_local_devices_user_id_device_key"),
    )
    op.create_index("ix_local_devices_user_id", "local_devices", ["user_id"])

    op.create_table(
        "local_roots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("default_policy", sa.Text(), nullable=False, server_default="metadata_only"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["device_id"], ["local_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "device_id",
            "root_path",
            name="uq_local_roots_user_device_root_path",
        ),
    )
    op.create_index("ix_local_roots_user_id", "local_roots", ["user_id"])
    op.create_index("ix_local_roots_device_id", "local_roots", ["device_id"])


def downgrade() -> None:
    op.drop_index("ix_local_roots_device_id", table_name="local_roots")
    op.drop_index("ix_local_roots_user_id", table_name="local_roots")
    op.drop_table("local_roots")
    op.drop_index("ix_local_devices_user_id", table_name="local_devices")
    op.drop_table("local_devices")
