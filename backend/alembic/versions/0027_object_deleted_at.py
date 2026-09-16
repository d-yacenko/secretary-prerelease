"""object deleted_at tombstone

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "objects",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_objects_user_id_deleted_at", "objects", ["user_id", "deleted_at"])
    op.execute(
        """
        UPDATE objects
        SET deleted_at = COALESCE(updated_at, NOW() AT TIME ZONE 'UTC')
        WHERE kind = 'task'
          AND status = 'deleted'
          AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_objects_user_id_deleted_at", table_name="objects")
    op.drop_column("objects", "deleted_at")
