"""Task completion mode: finite by default, ongoing is a task property."""

import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.api.schemas import ObjectCreate, ObjectOut, ObjectUpdate
from app.db.engine import engine
from app.domain.task_completion import (
    TASK_COMPLETION_FINITE,
    TASK_COMPLETION_ONGOING,
    effective_task_completion_mode,
)
from app.services.errors import ValidationError
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE
from app.services.task_mutation_service import TaskMutationService
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import BOOTSTRAP_USER_ID as _BOOTSTRAP

ROOT = Path(__file__).parents[1]


def test_effective_mode_does_not_read_due_date() -> None:
    assert effective_task_completion_mode("task", None) == TASK_COMPLETION_FINITE
    assert effective_task_completion_mode("task", "ongoing") == TASK_COMPLETION_ONGOING
    assert effective_task_completion_mode("email", None) is None


def test_0050_backfills_tasks_and_leaves_other_kinds_null() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    task_id = uuid.uuid4()
    note_id = uuid.uuid4()
    command.downgrade(config, "0049")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO objects (id, user_id, kind, title, origin, state) "
                    "VALUES (:id, :user_id, :kind, :title, 'user', 'confirmed')"
                ),
                [
                    {
                        "id": task_id,
                        "user_id": BOOTSTRAP_USER_ID,
                        "kind": "task",
                        "title": "Legacy task",
                    },
                    {
                        "id": note_id,
                        "user_id": BOOTSTRAP_USER_ID,
                        "kind": "note",
                        "title": "Legacy note",
                    },
                ],
            )
        command.upgrade(config, "0050")
        with engine.begin() as connection:
            rows = connection.execute(
                text(
                    "SELECT id, completion_mode FROM objects WHERE id IN (:task_id, :note_id)"
                ),
                {"task_id": task_id, "note_id": note_id},
            ).all()
        modes = {row.id: row.completion_mode for row in rows}
        assert modes[task_id] == "finite"
        assert modes[note_id] is None
        assert "ck_objects_completion_mode" in {
            item["name"] for item in inspect(engine).get_check_constraints("objects")
        }
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM objects WHERE id IN (:task_id, :note_id)"),
                {"task_id": task_id, "note_id": note_id},
            )
        command.upgrade(config, "head")


def test_new_task_defaults_to_finite_and_non_task_mode_is_rejected(
    db_session,
) -> None:
    graph = GraphService(db_session, _BOOTSTRAP)
    task = graph.create_object(
        ObjectCreate(kind="task", title="Plain", origin="user", state=CONFIRMED_STATE)
    )
    assert task.completion_mode == "finite"
    assert task.due_at is None
    explicit = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Direction",
            origin="user",
            state=CONFIRMED_STATE,
            completion_mode="ongoing",
        )
    )
    assert explicit.completion_mode == "ongoing"
    note = graph.create_object(
        ObjectCreate(kind="note", title="Note", origin="user", state=CONFIRMED_STATE)
    )
    assert note.completion_mode is None
    try:
        graph.create_object(
            ObjectCreate(
                kind="note",
                title="Bad",
                origin="user",
                state=CONFIRMED_STATE,
                completion_mode="ongoing",
            )
        )
        raise AssertionError("non-task completion mode was accepted")
    except ValidationError as exc:
        assert "task" in exc.message
    out = ObjectOut.from_model(task)
    assert out.completion_mode == "finite"


def test_patch_completion_mode_and_lifecycle(db_session) -> None:
    graph = GraphService(db_session, _BOOTSTRAP)
    task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Work",
            origin="user",
            state=CONFIRMED_STATE,
            status="open",
            due_at=None,
        )
    )
    service = TaskMutationService(db_session, _BOOTSTRAP)
    ongoing = service.patch_task_fields(
        task.id,
        completion_mode="ongoing",
        fields_set={"completion_mode"},
    )
    assert ongoing.changed is True
    assert ongoing.object.completion_mode == "ongoing"
    assert ongoing.object.title == "Work"
    assert ongoing.object.due_at is None
    finite = service.patch_task_fields(
        task.id,
        completion_mode="finite",
        fields_set={"completion_mode"},
    )
    assert finite.object.completion_mode == "finite"
    service.patch_task_fields(
        task.id,
        completion_mode="ongoing",
        fields_set={"completion_mode"},
    )
    try:
        service.set_task_status(task.id, "done")
        raise AssertionError("ongoing task accepted done")
    except ValidationError:
        pass
    archived = service.set_task_status(task.id, "archived")
    assert archived.new_status == "archived"
    cancelled = service.set_task_status(task.id, "cancelled")
    assert cancelled.new_status == "cancelled"
    finite_task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Finite",
            origin="user",
            state=CONFIRMED_STATE,
            status="open",
        )
    )
    done = service.set_task_status(finite_task.id, "done")
    assert done.new_status == "done"
    try:
        service.patch_task_fields(
            finite_task.id,
            completion_mode="ongoing",
            fields_set={"completion_mode"},
        )
        raise AssertionError("done task accepted ongoing")
    except ValidationError:
        pass
    graph.update_object(task.id, ObjectUpdate(kind="note"))
    changed = graph.get_object(task.id)
    assert changed.kind == "note"
    assert changed.completion_mode is None
