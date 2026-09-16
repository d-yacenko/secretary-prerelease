"""object embedding signature provenance

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-11

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "objects",
        sa.Column("embedding_signature", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("objects", "embedding_signature")
