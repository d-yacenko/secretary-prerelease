"""Disposable local rehearsal for People P1 schema readiness.

Points only at POSTGRES_* in the environment. Refuses the default local
database name on port 5432 so it cannot be aimed at an existing dev database
by accident. Does not read production targets.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

if os.environ.get("POSTGRES_PORT") == "5432" and os.environ.get("POSTGRES_DB", "secretary") == "secretary":
    raise SystemExit("refusing the default local database; set a disposable POSTGRES_DB and POSTGRES_PORT")

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session


def _alembic(revision: str, *, downgrade: bool = False) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _old_object_write(engine, object_id: uuid.UUID, user_id: uuid.UUID, kind: str, title: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO objects (
                    id, user_id, kind, title, origin, state, metadata
                ) VALUES (
                    :id, :user_id, :kind, :title, 'user', 'confirmed', '{}'::jsonb
                )
                """
            ),
            {"id": object_id, "user_id": user_id, "kind": kind, "title": title},
        )


def _old_object_columns(engine, object_id: uuid.UUID) -> dict:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT id, user_id, kind, title, body, provider, external_id,
                       canonical_uri, status, start_at, due_at, planned_start_at,
                       planned_end_at, occurred_at, deleted_at, metadata, origin,
                       state, confidence, created_at, updated_at
                FROM objects WHERE id = :id
                """
            ),
            {"id": object_id},
        ).mappings().one()
    return dict(row)


def main() -> None:
    from app.core.config import settings
    from app.db.models import Object
    from app.domain.person_identity import normalize_email
    from app.services.graph_workspace_service import GraphWorkspaceService
    from app.services.person_graph_workspace_service import PersonGraphWorkspaceService
    from app.services.person_identity_service import PersonIdentityService

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    report: dict[str, object] = {"database": settings.postgres_db, "port": settings.postgres_port}

    _alembic("0047")
    report["at_0047"] = _revision(engine)

    user_id = uuid.uuid4()
    person_id = uuid.uuid4()
    task_id = uuid.uuid4()
    mail_id = uuid.uuid4()
    edge_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, display_name) VALUES (:id, :name)"),
            {"id": user_id, "name": "P1 rehearsal"},
        )
    _old_object_write(engine, person_id, user_id, "person", "Ada")
    _old_object_write(engine, task_id, user_id, "task", "Reply")
    _old_object_write(engine, mail_id, user_id, "email", "Hello")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO edges (
                    id, user_id, source_id, target_id, type, origin, state, metadata
                ) VALUES (
                    :id, :user_id, :source_id, :target_id, 'related_to', 'user', 'confirmed', '{}'::jsonb
                )
                """
            ),
            {
                "id": edge_id,
                "user_id": user_id,
                "source_id": person_id,
                "target_id": task_id,
            },
        )
    report["old_read_at_0047"] = _old_object_columns(engine, person_id)["title"]
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT completion_mode FROM objects LIMIT 1"))
        report["completion_mode_at_0047"] = "present"
    except ProgrammingError:
        report["completion_mode_at_0047"] = "absent"
    try:
        with Session(engine) as session:
            session.get(Object, person_id)
        report["current_orm_at_0047"] = "ok"
    except ProgrammingError:
        report["current_orm_at_0047"] = "missing_completion_mode"

    _alembic("0049")
    report["at_0049"] = _revision(engine)
    try:
        with Session(engine) as session:
            session.get(Object, person_id)
        report["current_orm_at_0049"] = "ok"
    except ProgrammingError:
        report["current_orm_at_0049"] = "missing_completion_mode"

    _alembic("0050")
    report["at_0050"] = _revision(engine)
    with Session(engine) as session:
        task = session.get(Object, task_id)
        person = session.get(Object, person_id)
        report["task_completion_mode_after_backfill"] = None if task is None else task.completion_mode
        report["person_completion_mode_after_backfill"] = None if person is None else person.completion_mode
        graph = GraphWorkspaceService(session, user_id).get_workspace(root_id=None)
        report["graph_workspace_nodes"] = len(graph.nodes)
        people = PersonGraphWorkspaceService(session, user_id)
        overview = people.get_workspace(root_id=None)
        report["people_before_identity"] = [
            {"title": item["title"], "identities": len(item["identities"])}
            for item in overview.people
        ]
        PersonIdentityService(session, user_id).attach(person_id, normalize_email("ada@example.com"))
        session.commit()
        overview = people.get_workspace(root_id=None)
        rooted = people.get_workspace(root_id=person_id)
        report["people_after_identity"] = [
            {
                "title": item["title"],
                "providers": [identity["provider"] for identity in item["identities"]],
                "open_task_count": item["open_task_count"],
            }
            for item in overview.people
        ]
        report["rooted_titles"] = [node.title for node in rooted.nodes]
        report["health_select_1"] = session.execute(text("SELECT 1")).scalar_one()

    later_id = uuid.uuid4()
    _old_object_write(engine, later_id, user_id, "task", "Later task")
    with engine.connect() as connection:
        mode = connection.execute(
            text("SELECT completion_mode FROM objects WHERE id = :id"),
            {"id": later_id},
        ).scalar_one()
    report["old_insert_completion_mode_on_0050"] = mode
    report["old_read_on_0050"] = _old_object_columns(engine, later_id)["title"]

    _alembic("0049", downgrade=True)
    report["after_downgrade_0050"] = _revision(engine)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT completion_mode FROM objects LIMIT 1"))
        report["completion_mode_after_downgrade"] = "present"
    except ProgrammingError:
        report["completion_mode_after_downgrade"] = "absent"

    heads = Config(str(BACKEND / "alembic.ini"))
    heads.set_main_option("script_location", str(BACKEND / "alembic"))
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(heads)
    report["alembic_heads"] = script.get_heads()
    for key in sorted(report):
        print(f"{key}={report[key]}")


if __name__ == "__main__":
    main()
