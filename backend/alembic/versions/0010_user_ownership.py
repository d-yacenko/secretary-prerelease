"""users table and user_id ownership columns

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BOOTSTRAP_USER_ID = "00000000-0000-4000-8000-000000000001"
BOOTSTRAP_DISPLAY_NAME = "Owner"
BOOTSTRAP_USER_ID_STR = BOOTSTRAP_USER_ID


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            f"INSERT INTO users (id, display_name) VALUES ('{BOOTSTRAP_USER_ID_STR}'::uuid, :name)"
        ).bindparams(name=BOOTSTRAP_DISPLAY_NAME)
    )

    op.add_column("objects", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column("edges", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column("views", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column("jobs", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column("notifications", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column("google_accounts", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column("oauth_states", sa.Column("user_id", sa.Uuid(), nullable=True))

    op.execute(sa.text(f"UPDATE objects SET user_id = '{BOOTSTRAP_USER_ID_STR}'"))
    op.execute(sa.text(f"UPDATE edges SET user_id = '{BOOTSTRAP_USER_ID_STR}'"))
    op.execute(sa.text(f"UPDATE views SET user_id = '{BOOTSTRAP_USER_ID_STR}'"))
    op.execute(sa.text(f"UPDATE jobs SET user_id = '{BOOTSTRAP_USER_ID_STR}'"))
    op.execute(sa.text(f"UPDATE notifications SET user_id = '{BOOTSTRAP_USER_ID_STR}'"))
    op.execute(sa.text(f"UPDATE google_accounts SET user_id = '{BOOTSTRAP_USER_ID_STR}'"))
    op.execute(sa.text(f"UPDATE oauth_states SET user_id = '{BOOTSTRAP_USER_ID_STR}'"))

    op.drop_index("uq_objects_provider_kind_external_id", table_name="objects")
    op.drop_constraint("google_accounts_email_key", "google_accounts", type_="unique")

    op.alter_column("objects", "user_id", nullable=False)
    op.alter_column("edges", "user_id", nullable=False)
    op.alter_column("views", "user_id", nullable=False)
    op.alter_column("jobs", "user_id", nullable=False)
    op.alter_column("notifications", "user_id", nullable=False)
    op.alter_column("google_accounts", "user_id", nullable=False)
    op.alter_column("oauth_states", "user_id", nullable=False)

    op.create_foreign_key(
        "fk_objects_user_id_users",
        "objects",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_edges_user_id_users",
        "edges",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_views_user_id_users",
        "views",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_jobs_user_id_users",
        "jobs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_notifications_user_id_users",
        "notifications",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_google_accounts_user_id_users",
        "google_accounts",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_oauth_states_user_id_users",
        "oauth_states",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_index("ix_objects_user_id", "objects", ["user_id"])
    op.create_index("ix_jobs_user_id_status_run_after", "jobs", ["user_id", "status", "run_after"])
    op.create_index("ix_notifications_user_id_status", "notifications", ["user_id", "status"])
    op.create_index("ix_views_user_id", "views", ["user_id"])
    op.create_index("ix_google_accounts_user_id", "google_accounts", ["user_id"])

    op.create_index(
        "uq_objects_user_provider_kind_external_id",
        "objects",
        ["user_id", "provider", "kind", "external_id"],
        unique=True,
        postgresql_where=sa.text(
            "provider IS NOT NULL AND external_id IS NOT NULL"
        ),
    )
    op.create_unique_constraint(
        "uq_google_accounts_user_id_email",
        "google_accounts",
        ["user_id", "email"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_google_accounts_user_id_email", "google_accounts", type_="unique")
    op.drop_index("uq_objects_user_provider_kind_external_id", table_name="objects")
    op.drop_index("ix_google_accounts_user_id", table_name="google_accounts")
    op.drop_index("ix_views_user_id", table_name="views")
    op.drop_index("ix_notifications_user_id_status", table_name="notifications")
    op.drop_index("ix_jobs_user_id_status_run_after", table_name="jobs")
    op.drop_index("ix_objects_user_id", table_name="objects")

    op.drop_constraint("fk_oauth_states_user_id_users", "oauth_states", type_="foreignkey")
    op.drop_constraint("fk_google_accounts_user_id_users", "google_accounts", type_="foreignkey")
    op.drop_constraint("fk_notifications_user_id_users", "notifications", type_="foreignkey")
    op.drop_constraint("fk_jobs_user_id_users", "jobs", type_="foreignkey")
    op.drop_constraint("fk_views_user_id_users", "views", type_="foreignkey")
    op.drop_constraint("fk_edges_user_id_users", "edges", type_="foreignkey")
    op.drop_constraint("fk_objects_user_id_users", "objects", type_="foreignkey")

    op.create_unique_constraint("google_accounts_email_key", "google_accounts", ["email"])
    op.create_index(
        "uq_objects_provider_kind_external_id",
        "objects",
        ["provider", "kind", "external_id"],
        unique=True,
        postgresql_where=sa.text("provider IS NOT NULL AND external_id IS NOT NULL"),
    )

    op.drop_column("oauth_states", "user_id")
    op.drop_column("google_accounts", "user_id")
    op.drop_column("notifications", "user_id")
    op.drop_column("jobs", "user_id")
    op.drop_column("views", "user_id")
    op.drop_column("edges", "user_id")
    op.drop_column("objects", "user_id")
    op.drop_table("users")
