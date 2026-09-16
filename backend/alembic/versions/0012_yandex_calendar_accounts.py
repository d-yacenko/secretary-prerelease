"""yandex_calendar_accounts

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "yandex_calendar_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("app_password_encrypted", sa.Text(), nullable=False),
        sa.Column("caldav_host", sa.Text(), nullable=False, server_default="caldav.yandex.ru"),
        sa.Column("sync_state", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
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
        sa.UniqueConstraint("user_id", "email", name="uq_yandex_calendar_accounts_user_id_email"),
    )
    op.create_index(
        "ix_yandex_calendar_accounts_user_id",
        "yandex_calendar_accounts",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_yandex_calendar_accounts_user_id", table_name="yandex_calendar_accounts")
    op.drop_table("yandex_calendar_accounts")
