"""representation fts indexes

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-03

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_representations_fts_simple ON representations USING gin (
            to_tsvector('simple', coalesce(text, ''))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_representations_fts_russian ON representations USING gin (
            to_tsvector('russian', coalesce(text, ''))
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_representations_fts_russian")
    op.execute("DROP INDEX IF EXISTS ix_representations_fts_simple")
