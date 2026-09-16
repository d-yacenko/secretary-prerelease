import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Edge, Object
from app.users.bootstrap import BOOTSTRAP_USER_ID


def test_create_project_task_email_and_edges(db_session: Session) -> None:
    session = db_session

    project = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="project",
        title="Website redesign",
        origin="system",
    )
    task = Object(user_id=BOOTSTRAP_USER_ID, kind="task", title="Write spec", origin="system")
    email = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        title="Client question",
        origin="system",
        provider="gmail",
        external_id=f"msg-{uuid.uuid4().hex}",
    )
    subtask = Object(user_id=BOOTSTRAP_USER_ID, kind="task", title="Draft outline", origin="system")

    session.add_all([project, task, email, subtask])
    session.flush()

    related = Edge(
        user_id=BOOTSTRAP_USER_ID,
        source_id=task.id,
        target_id=email.id,
        type="related_to",
        origin="system",
        state="observed",
    )
    parent = Edge(
        user_id=BOOTSTRAP_USER_ID,
        source_id=task.id,
        target_id=subtask.id,
        type="parent_of",
        origin="system",
        state="observed",
    )
    session.add_all([related, parent])
    session.flush()
    session.expire_all()

    object_ids = {project.id, task.id, email.id, subtask.id}
    edge_ids = {related.id, parent.id}
    stored_objects = session.scalars(select(Object).where(Object.id.in_(object_ids))).all()
    stored_edges = session.scalars(select(Edge).where(Edge.id.in_(edge_ids))).all()

    assert len(stored_objects) == 4
    kinds = {obj.kind for obj in stored_objects}
    assert kinds == {"project", "task", "email"}

    assert len(stored_edges) == 2
    edge_types = {(e.type, e.source_id, e.target_id) for e in stored_edges}
    assert (related.type, related.source_id, related.target_id) in edge_types
    assert (parent.type, parent.source_id, parent.target_id) in edge_types


def test_same_kind_relation_allowed(db_session: Session) -> None:
    session = db_session

    parent_task = Object(user_id=BOOTSTRAP_USER_ID, kind="task", title="Parent task", origin="system")
    child_task = Object(user_id=BOOTSTRAP_USER_ID, kind="task", title="Child task", origin="system")
    session.add_all([parent_task, child_task])
    session.flush()

    edge = Edge(
        user_id=BOOTSTRAP_USER_ID,
        source_id=parent_task.id,
        target_id=child_task.id,
        type="parent_of",
        origin="system",
        state="observed",
    )
    session.add(edge)
    session.flush()

    assert edge.id is not None


def test_edge_rejects_nonexistent_object(db_session: Session) -> None:
    session = db_session

    task = Object(user_id=BOOTSTRAP_USER_ID, kind="task", title="Lonely task", origin="system")
    session.add(task)
    session.flush()

    edge = Edge(
        user_id=BOOTSTRAP_USER_ID,
        source_id=task.id,
        target_id=uuid.uuid4(),
        type="related_to",
        origin="system",
        state="observed",
    )
    session.add(edge)

    with pytest.raises(IntegrityError):
        session.flush()


def test_metadata_defaults_to_empty_object(db_session: Session) -> None:
    session = db_session

    obj = Object(user_id=BOOTSTRAP_USER_ID, kind="note", title="Empty metadata", origin="system")
    session.add(obj)
    session.flush()

    assert obj.metadata_ == {}


def test_external_object_uniqueness(db_session: Session) -> None:
    session = db_session

    external_id = f"dup-{uuid.uuid4().hex}"
    first = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        title="First",
        origin="system",
        provider="gmail",
        external_id=external_id,
    )
    session.add(first)
    session.flush()

    duplicate = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        title="Duplicate",
        origin="system",
        provider="gmail",
        external_id=external_id,
    )
    session.add(duplicate)

    with pytest.raises(IntegrityError):
        session.flush()
