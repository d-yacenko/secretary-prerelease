"""russian fts document index

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-29

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_objects_russian_fts_document ON objects USING gin (
            (
                setweight(to_tsvector('russian', coalesce(title, '')), 'A')
                || setweight(to_tsvector('russian', coalesce(body, '')), 'C')
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_objects_russian_fts_document")
