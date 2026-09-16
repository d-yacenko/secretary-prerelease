"""object occurred_at and retrieval indexes

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-29

"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_EMAIL_PROVIDERS = ("gmail", "yandex_mail")
_BATCH_SIZE = 500


def _parse_metadata_timestamp(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))  # noqa: FURB162
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _backfill_email_occurred_at(connection: sa.Connection) -> None:
    last_id: object = None
    base_where = """
        WHERE occurred_at IS NULL
          AND kind = 'email'
          AND provider IN ('gmail', 'yandex_mail')
          AND metadata ? 'timestamp'
    """
    while True:
        if last_id is None:
            select_sql = f"""
                SELECT id, metadata->>'timestamp' AS ts
                FROM objects
                {base_where}
                ORDER BY id
                LIMIT :batch_size
            """
            params: dict[str, object] = {"batch_size": _BATCH_SIZE}
        else:
            select_sql = f"""
                SELECT id, metadata->>'timestamp' AS ts
                FROM objects
                {base_where}
                  AND id > :last_id
                ORDER BY id
                LIMIT :batch_size
            """
            params = {"last_id": last_id, "batch_size": _BATCH_SIZE}

        rows = connection.execute(text(select_sql), params).fetchall()
        if not rows:
            break
        for row in rows:
            parsed = _parse_metadata_timestamp(row.ts)
            if parsed is not None:
                connection.execute(
                    text("UPDATE objects SET occurred_at = :occurred_at WHERE id = :id"),
                    {"occurred_at": parsed, "id": row.id},
                )
            last_id = row.id
        if len(rows) < _BATCH_SIZE:
            break


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.add_column(
        "objects",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_objects_user_occurred_at", "objects", ["user_id", "occurred_at"])

    op.execute(
        """
        CREATE INDEX ix_objects_fts_document ON objects USING gin (
            (
                setweight(to_tsvector('simple', coalesce(title, '')), 'A')
                || setweight(to_tsvector('simple', coalesce(body, '')), 'C')
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_objects_title_trgm ON objects USING gin (title gin_trgm_ops)
        """
    )

    connection = op.get_bind()
    _backfill_email_occurred_at(connection)
    op.execute(
        """
        UPDATE objects
        SET occurred_at = start_at
        WHERE occurred_at IS NULL
          AND kind = 'event'
          AND start_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_objects_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_objects_fts_document")
    op.drop_index("ix_objects_user_occurred_at", table_name="objects")
    op.drop_column("objects", "occurred_at")
