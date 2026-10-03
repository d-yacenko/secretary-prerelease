"""Canonical Task world-space persistence. No placement and no public API."""

from __future__ import annotations

import uuid

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select

from app.api.schemas import ObjectCreate
from app.db.models import TaskLayoutPosition, TaskLayoutState, User
from app.services.errors import ConflictError, ValidationError
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE, USER_ORIGIN
from app.services.task_layout_service import TaskLayoutCenter, TaskLayoutService
from app.users.bootstrap import BOOTSTRAP_USER_ID


def test_migration_0052_is_single_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["0054"]
    revision = script.get_revision("0052")
    assert revision is not None
    assert revision.down_revision == "0051"
    parent = script.get_revision("0053")
    assert parent is not None
    assert parent.down_revision == "0052"
    head = script.get_revision("0054")
    assert head is not None
    assert head.down_revision == "0053"


def test_users_receive_isolated_layout_state(db_session, nornickel_user_id) -> None:
    first = TaskLayoutService(db_session, BOOTSTRAP_USER_ID).read()
    second = TaskLayoutService(db_session, nornickel_user_id).read()

    assert first.user_id == BOOTSTRAP_USER_ID
    assert second.user_id == nornickel_user_id
    assert first.topology_revision == 1
    assert second.topology_revision == 1
    assert first.usable is False
    assert second.usable is False
    assert first.positions == ()
    assert second.positions == ()
    assert db_session.scalar(
        select(func.count()).select_from(TaskLayoutState).where(
            TaskLayoutState.user_id == BOOTSTRAP_USER_ID
        )
    ) == 1


def test_snapshot_round_trip_keeps_exact_centers(db_session, owner) -> None:
    left = _task(db_session, owner, "Left")
    right = _task(db_session, owner, "Right")
    service = TaskLayoutService(db_session, owner)
    stored = service.replace_snapshot(
        expected_topology_revision=1,
        algorithm_version="pl1-g1-test",
        positions=[
            TaskLayoutCenter(right.id, 12.5, -3.25),
            TaskLayoutCenter(left.id, 0.0, 4.0),
        ],
    )
    again = service.read()

    assert stored.usable is True
    assert stored.snapshot_revision == 1
    assert stored.topology_revision == 1
    assert stored.algorithm_version == "pl1-g1-test"
    assert again.positions == _by_task_id(
        TaskLayoutCenter(left.id, 0.0, 4.0),
        TaskLayoutCenter(right.id, 12.5, -3.25),
    )


def test_stale_revision_writes_nothing(db_session, owner) -> None:
    task = _task(db_session, owner, "Kept")
    service = TaskLayoutService(db_session, owner)
    service.replace_snapshot(
        expected_topology_revision=1,
        algorithm_version="v1",
        positions=[TaskLayoutCenter(task.id, 1.0, 2.0)],
    )

    with pytest.raises(ConflictError, match="stale"):
        service.replace_snapshot(
            expected_topology_revision=0,
            algorithm_version="v2",
            positions=[TaskLayoutCenter(task.id, 9.0, 9.0)],
        )

    current = service.read()
    assert current.usable is True
    assert current.algorithm_version == "v1"
    assert current.positions == (TaskLayoutCenter(task.id, 1.0, 2.0),)
    assert _position_count(db_session, owner) == 1

    empty_user = uuid.uuid4()
    db_session.add(User(id=empty_user, display_name="No layout yet"))
    db_session.flush()
    with pytest.raises(ConflictError, match="stale"):
        TaskLayoutService(db_session, empty_user).replace_snapshot(
            expected_topology_revision=4,
            algorithm_version="v",
            positions=[TaskLayoutCenter(task.id, 3.0, 3.0)],
        )
    assert db_session.get(TaskLayoutState, empty_user) is None
    assert _position_count(db_session, empty_user) == 0


def test_duplicate_foreign_and_non_task_ids_fail_closed(db_session, owner, nornickel_user_id) -> None:
    task = _task(db_session, owner, "Owned")
    note = GraphService(db_session, owner).create_object(
        ObjectCreate(kind="note", title="Not a task", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    foreign = GraphService(db_session, nornickel_user_id).create_object(
        ObjectCreate(kind="task", title="Foreign", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    service = TaskLayoutService(db_session, owner)

    with pytest.raises(ValidationError, match="duplicate"):
        service.replace_snapshot(
            expected_topology_revision=1,
            algorithm_version="v",
            positions=[
                TaskLayoutCenter(task.id, 1.0, 1.0),
                TaskLayoutCenter(task.id, 2.0, 2.0),
            ],
        )
    with pytest.raises(ValidationError, match="another user"):
        service.replace_snapshot(
            expected_topology_revision=1,
            algorithm_version="v",
            positions=[TaskLayoutCenter(foreign.id, 1.0, 1.0)],
        )
    with pytest.raises(ValidationError, match="not a task"):
        service.replace_snapshot(
            expected_topology_revision=1,
            algorithm_version="v",
            positions=[TaskLayoutCenter(note.id, 1.0, 1.0)],
        )
    with pytest.raises(ValidationError, match="not found"):
        service.replace_snapshot(
            expected_topology_revision=1,
            algorithm_version="v",
            positions=[TaskLayoutCenter(uuid.uuid4(), 1.0, 1.0)],
        )

    assert db_session.get(TaskLayoutState, owner) is None
    assert _position_count(db_session, owner) == 0


def test_non_finite_coordinates_fail_closed(db_session, owner) -> None:
    task = _task(db_session, owner, "Finite")
    service = TaskLayoutService(db_session, owner)
    for coordinates in ((float("nan"), 1.0), (1.0, float("inf")), (float("-inf"), 0.0)):
        with pytest.raises(ValidationError, match="finite"):
            service.replace_snapshot(
                expected_topology_revision=1,
                algorithm_version="v",
                positions=[TaskLayoutCenter(task.id, coordinates[0], coordinates[1])],
            )
    assert _position_count(db_session, owner) == 0


def test_invalidation_keeps_rows_and_the_next_snapshot_is_usable(db_session, owner) -> None:
    first = _task(db_session, owner, "First")
    second = _task(db_session, owner, "Second")
    service = TaskLayoutService(db_session, owner)
    service.replace_snapshot(
        expected_topology_revision=1,
        algorithm_version="v1",
        positions=[
            TaskLayoutCenter(first.id, 8.0, 1.0),
            TaskLayoutCenter(second.id, 20.0, 5.0),
        ],
    )
    stale = service.invalidate_topology()

    assert stale.topology_revision == 2
    assert stale.snapshot_revision == 1
    assert stale.usable is False
    assert stale.positions == _by_task_id(
        TaskLayoutCenter(first.id, 8.0, 1.0),
        TaskLayoutCenter(second.id, 20.0, 5.0),
    )
    assert _position_count(db_session, owner) == 2

    current = service.replace_snapshot(
        expected_topology_revision=2,
        algorithm_version="v2",
        positions=[
            TaskLayoutCenter(first.id, 8.0, 1.0),
            TaskLayoutCenter(second.id, 20.0, 5.0),
        ],
    )
    assert current.usable is True
    assert current.topology_revision == 2
    assert current.snapshot_revision == 2
    assert current.algorithm_version == "v2"
    assert current.positions == _by_task_id(
        TaskLayoutCenter(first.id, 8.0, 1.0),
        TaskLayoutCenter(second.id, 20.0, 5.0),
    )
    assert _position_count(db_session, owner) == 4
    assert db_session.scalar(
        select(func.count()).select_from(TaskLayoutPosition).where(
            TaskLayoutPosition.user_id == owner,
            TaskLayoutPosition.snapshot_revision == 1,
            TaskLayoutPosition.task_id == first.id,
        )
    ) == 1


def test_users_cannot_read_or_overwrite_each_other(db_session, owner, nornickel_user_id) -> None:
    owned = _task(db_session, owner, "Bootstrap task")
    foreign_task = GraphService(db_session, nornickel_user_id).create_object(
        ObjectCreate(kind="task", title="Other task", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    owner_layout = TaskLayoutService(db_session, owner)
    other = TaskLayoutService(db_session, nornickel_user_id)
    owner_layout.replace_snapshot(
        expected_topology_revision=1,
        algorithm_version="owner",
        positions=[TaskLayoutCenter(owned.id, 3.0, 4.0)],
    )
    other.replace_snapshot(
        expected_topology_revision=1,
        algorithm_version="other",
        positions=[TaskLayoutCenter(foreign_task.id, 30.0, 40.0)],
    )

    assert owner_layout.read().positions == (TaskLayoutCenter(owned.id, 3.0, 4.0),)
    assert other.read().positions == (TaskLayoutCenter(foreign_task.id, 30.0, 40.0),)
    with pytest.raises(ValidationError, match="another user"):
        other.replace_snapshot(
            expected_topology_revision=1,
            algorithm_version="steal",
            positions=[TaskLayoutCenter(owned.id, 0.0, 0.0)],
        )
    assert owner_layout.read().algorithm_version == "owner"
    assert owner_layout.read().positions == (TaskLayoutCenter(owned.id, 3.0, 4.0),)


def test_deleting_a_task_or_user_removes_layout_rows(db_session, owner) -> None:
    task = _task(db_session, owner, "Disposable")
    service = TaskLayoutService(db_session, owner)
    service.replace_snapshot(
        expected_topology_revision=1,
        algorithm_version="v",
        positions=[TaskLayoutCenter(task.id, 1.0, 1.0)],
    )
    db_session.delete(task)
    db_session.flush()
    assert _position_count(db_session, owner) == 0

    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Layout only"))
    db_session.flush()
    layout = TaskLayoutService(db_session, user_id)
    layout.read()
    db_session.delete(db_session.get(User, user_id))
    db_session.flush()
    assert db_session.get(TaskLayoutState, user_id) is None


@pytest.fixture
def owner(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Layout owner"))
    db_session.flush()
    return user_id


def _task(db_session, user_id: uuid.UUID, title: str):
    return GraphService(db_session, user_id).create_object(
        ObjectCreate(kind="task", title=title, origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )


def _by_task_id(*centers: TaskLayoutCenter) -> tuple[TaskLayoutCenter, ...]:
    return tuple(sorted(centers, key=lambda center: center.task_id))


def _position_count(db_session, user_id: uuid.UUID) -> int:
    return db_session.scalar(
        select(func.count()).select_from(TaskLayoutPosition).where(
            TaskLayoutPosition.user_id == user_id
        )
    )
