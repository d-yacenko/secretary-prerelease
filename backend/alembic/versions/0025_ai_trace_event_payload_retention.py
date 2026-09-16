"""ai_trace_event_payload_retention

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_trace_events",
        sa.Column("payload_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_ai_trace_events_payload_expires",
        "ai_trace_events",
        ["payload_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_trace_events_payload_expires", table_name="ai_trace_events")
    op.drop_column("ai_trace_events", "payload_expires_at")
