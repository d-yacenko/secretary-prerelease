"""notification result_object_id

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("result_object_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_notifications_result_object_id_objects",
        "notifications",
        "objects",
        ["result_object_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_notifications_result_object_id_objects",
        "notifications",
        type_="foreignkey",
    )
    op.drop_column("notifications", "result_object_id")
