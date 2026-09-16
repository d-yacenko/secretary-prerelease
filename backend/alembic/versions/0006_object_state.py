"""object provenance state

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("objects", sa.Column("state", sa.Text(), nullable=True))
    op.execute("UPDATE objects SET state = 'observed' WHERE origin = 'source'")
    op.execute("UPDATE objects SET state = 'confirmed' WHERE state IS NULL")
    op.alter_column(
        "objects",
        "state",
        existing_type=sa.Text(),
        nullable=False,
        server_default="confirmed",
    )
    op.create_index("ix_objects_state", "objects", ["state"])


def downgrade() -> None:
    op.drop_index("ix_objects_state", table_name="objects")
    op.drop_column("objects", "state")
