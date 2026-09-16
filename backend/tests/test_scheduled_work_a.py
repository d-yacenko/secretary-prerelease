from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.api.schemas import ObjectCreate, ObjectUpdate
from app.db.models import Object, UserSettings
from app.domain.planned_execution import (
    PLANNED_INTERVAL_BOTH_OR_NEITHER,
    PLANNED_INTERVAL_END_AFTER_START,
    PLANNED_INTERVAL_TASKS_ONLY,
)
from app.domain.task_lifecycle import (
    LEGACY_TASK_STATUS_COMPLETED,
    TASK_STATUS_ARCHIVED,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_DELETED,
    TASK_STATUS_DONE,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_OPEN,
)
from app.domain.temporal_hint import KIND_TEMPORAL_HINT, LIFECYCLE_UNRESOLVED
from app.llm.embedding_service import FakeEmbeddingService
from app.services.calendar_event_query import WEEK_CALENDAR_PROVIDERS, active_event_predicates
from app.services.errors import ValidationError
from app.services.graph_service import GraphService
from app.services.temporal_signals_constants import (
    METADATA_END_PRECISION,
    METADATA_EVIDENCE_COUNT,
    METADATA_LIFECYCLE,
    METADATA_PARTICIPATION,
    METADATA_PRIMARY_EVIDENCE_KIND,
    METADATA_PRIMARY_EVIDENCE_PROVIDER,
    METADATA_START_PRECISION,
)
from app.services.week_service import WeekService
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import apply_embedding_service_overrides

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
WEEK_START = "2026-09-07"
WEEK_MONDAY = datetime(2026, 9, 7, 0, 0, tzinfo=AMSTERDAM)
START = WEEK_MONDAY + timedelta(hours=10)
END = WEEK_MONDAY + timedelta(hours=11)


def _graph(session) -> GraphService:
    return GraphService(session, BOOTSTRAP_USER_ID)


def _task(
    graph: GraphService,
    *,
    title: str = "Planned work",
    status: str | None = TASK_STATUS_OPEN,
    planned_start_at: datetime | None = START,
    planned_end_at: datetime | None = END,
    due_at: datetime | None = None,
    start_at: datetime | None = None,
) -> Object:
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin="user",
            status=status,
            start_at=start_at,
            due_at=due_at,
            planned_start_at=planned_start_at,
            planned_end_at=planned_end_at,
        )
    )


def _event(graph: GraphService, *, title: str, start_at: datetime, due_at: datetime) -> Object:
    return graph.create_object(
        ObjectCreate(
            kind="event",
            title=title,
            origin="source",
            state="observed",
            provider="google_calendar",
            start_at=start_at,
            due_at=due_at,
            external_id=f"evt-{title}",
        )
    )


def _hint(graph: GraphService, *, title: str, start_at: datetime) -> Object:
    return graph.create_object(
        ObjectCreate(
            kind=KIND_TEMPORAL_HINT,
            title=title,
            origin="system",
            state="observed",
            start_at=start_at,
            metadata={
                METADATA_LIFECYCLE: LIFECYCLE_UNRESOLVED,
                METADATA_START_PRECISION: "exact",
                METADATA_END_PRECISION: "unknown",
                METADATA_PARTICIPATION: "expected",
                METADATA_PRIMARY_EVIDENCE_PROVIDER: "gmail",
                METADATA_PRIMARY_EVIDENCE_KIND: "email",
                METADATA_EVIDENCE_COUNT: 1,
            },
            confidence=0.9,
        )
    )


def _enable_temporal(session, *, enabled: bool = True) -> None:
    row = session.get(UserSettings, BOOTSTRAP_USER_ID)
    if row is None:
        row = UserSettings(
            user_id=BOOTSTRAP_USER_ID,
            temporal_signals_enabled=enabled,
            timezone="Europe/Amsterdam",
        )
        session.add(row)
    else:
        row.temporal_signals_enabled = enabled
    session.flush()


def _snapshot(session, *, week_start: str = WEEK_START):
    return WeekService(session, BOOTSTRAP_USER_ID).snapshot(
        week_start=week_start,
        timezone="Europe/Amsterdam",
        reference_at=WEEK_MONDAY + timedelta(hours=12),
    )


def test_migration_0038_revises_0037(db_session) -> None:
    versions = sorted(
        path.name
        for path in (Path(__file__).resolve().parents[1] / "alembic" / "versions").glob("*.py")
        if path.name[0].isdigit()
    )
    assert versions[-1].startswith("0043")
    module_path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/0038_objects_planned_execution_interval.py"
    )
    text_src = module_path.read_text(encoding="utf-8")
    assert 'revision: str = "0038"' in text_src
    assert 'down_revision: str | None = "0037"' in text_src
    inspector = inspect(db_session.bind)
    columns = {col["name"]: col for col in inspector.get_columns("objects")}
    assert columns["planned_start_at"]["nullable"] is True
    assert columns["planned_end_at"]["nullable"] is True
    checks = {item["name"] for item in inspector.get_check_constraints("objects")}
    assert "ck_objects_planned_execution_interval" in checks


def test_create_task_with_valid_planned_interval(db_session) -> None:
    task = _task(_graph(db_session), title="Write brief")
    assert task.planned_start_at == START
    assert task.planned_end_at == END
    assert task.due_at is None


def test_update_task_planned_interval(db_session) -> None:
    graph = _graph(db_session)
    task = _task(graph)
    new_start = START + timedelta(hours=2)
    new_end = END + timedelta(hours=2)
    updated = graph.update_object(
        task.id,
        ObjectUpdate(planned_start_at=new_start, planned_end_at=new_end),
    )
    assert updated.planned_start_at == new_start
    assert updated.planned_end_at == new_end
    assert updated.due_at is None
    assert updated.start_at is None


def test_clear_planned_interval(db_session) -> None:
    graph = _graph(db_session)
    task = _task(graph)
    updated = graph.update_object(
        task.id,
        ObjectUpdate(planned_start_at=None, planned_end_at=None),
    )
    assert updated.planned_start_at is None
    assert updated.planned_end_at is None


def test_reject_only_one_side_interval(db_session) -> None:
    graph = _graph(db_session)
    with pytest.raises(Exception, match=PLANNED_INTERVAL_BOTH_OR_NEITHER):
        graph.create_object(
            ObjectCreate(
                kind="task",
                title="Half",
                origin="user",
                planned_start_at=START,
            )
        )
    task = _task(graph)
    with pytest.raises(ValidationError, match=PLANNED_INTERVAL_BOTH_OR_NEITHER):
        graph.update_object(task.id, ObjectUpdate(planned_end_at=None))


def test_reject_planned_end_at_not_after_start(db_session) -> None:
    graph = _graph(db_session)
    with pytest.raises(Exception, match=PLANNED_INTERVAL_END_AFTER_START):
        graph.create_object(
            ObjectCreate(
                kind="task",
                title="Inverted",
                origin="user",
                planned_start_at=END,
                planned_end_at=START,
            )
        )
    with pytest.raises(Exception, match=PLANNED_INTERVAL_END_AFTER_START):
        graph.create_object(
            ObjectCreate(
                kind="task",
                title="Equal",
                origin="user",
                planned_start_at=START,
                planned_end_at=START,
            )
        )


def test_reject_planned_interval_on_non_task(db_session) -> None:
    graph = _graph(db_session)
    with pytest.raises(Exception, match=PLANNED_INTERVAL_TASKS_ONLY):
        graph.create_object(
            ObjectCreate(
                kind="note",
                title="Note",
                origin="user",
                planned_start_at=START,
                planned_end_at=END,
            )
        )
    note = graph.create_object(ObjectCreate(kind="note", title="Note", origin="user"))
    with pytest.raises(ValidationError, match=PLANNED_INTERVAL_TASKS_ONLY):
        graph.update_object(
            note.id,
            ObjectUpdate(planned_start_at=START, planned_end_at=END),
        )


def test_db_check_rejects_half_filled_interval(db_session) -> None:
    db_session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="task",
            title="Half row",
            origin="user",
            planned_start_at=START,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_db_check_rejects_planned_interval_on_note(db_session) -> None:
    db_session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="note",
            title="Note row",
            origin="user",
            planned_start_at=START,
            planned_end_at=END,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deadline_only_task_does_not_appear_in_scheduled_work(db_session) -> None:
    graph = _graph(db_session)
    _task(
        graph,
        title="Deadline only",
        planned_start_at=None,
        planned_end_at=None,
        due_at=START,
    )
    snapshot = _snapshot(db_session)
    monday = snapshot["days"][0]
    assert monday["scheduled_work"] == []
    assert monday["events"] == []


def test_scheduled_open_and_in_progress_appear(db_session) -> None:
    graph = _graph(db_session)
    open_task = _task(graph, title="Open work", status=TASK_STATUS_OPEN)
    progress = _task(
        graph,
        title="In progress work",
        status=TASK_STATUS_IN_PROGRESS,
        planned_start_at=START + timedelta(hours=2),
        planned_end_at=END + timedelta(hours=2),
    )
    monday = _snapshot(db_session)["days"][0]
    titles = [obj.title for obj in monday["scheduled_work"]]
    assert titles == ["Open work", "In progress work"]
    assert [obj.id for obj in monday["scheduled_work"]] == [open_task.id, progress.id]


def test_done_scheduled_task_remains_in_historical_week(db_session) -> None:
    graph = _graph(db_session)
    done = _task(graph, title="Finished work", status=TASK_STATUS_DONE)
    monday = _snapshot(db_session)["days"][0]
    assert [obj.title for obj in monday["scheduled_work"]] == ["Finished work"]
    assert monday["scheduled_work"][0].id == done.id
    assert monday["scheduled_work"][0].status == TASK_STATUS_DONE


def test_cancelled_archived_deleted_excluded(db_session) -> None:
    graph = _graph(db_session)
    _task(graph, title="Cancelled work", status=TASK_STATUS_CANCELLED)
    _task(
        graph,
        title="Archived work",
        status=TASK_STATUS_ARCHIVED,
        planned_start_at=START + timedelta(minutes=5),
        planned_end_at=END + timedelta(minutes=5),
    )
    _task(
        graph,
        title="Deleted work",
        status=TASK_STATUS_DELETED,
        planned_start_at=START + timedelta(minutes=10),
        planned_end_at=END + timedelta(minutes=10),
    )
    monday = _snapshot(db_session)["days"][0]
    assert monday["scheduled_work"] == []


def test_null_status_scheduled_task_excluded(db_session) -> None:
    graph = _graph(db_session)
    task = _task(graph, title="Null status work", status=None)
    assert task.status is None
    monday = _snapshot(db_session)["days"][0]
    assert monday["scheduled_work"] == []


def test_legacy_completed_scheduled_task_excluded(db_session) -> None:
    graph = _graph(db_session)
    task = _task(
        graph,
        title="Legacy completed work",
        status=LEGACY_TASK_STATUS_COMPLETED,
    )
    assert task.status == LEGACY_TASK_STATUS_COMPLETED
    monday = _snapshot(db_session)["days"][0]
    assert monday["scheduled_work"] == []


def test_unknown_status_scheduled_task_excluded(db_session) -> None:
    graph = _graph(db_session)
    task = _task(graph, title="Mystery work", status="mystery")
    assert task.status == "mystery"
    monday = _snapshot(db_session)["days"][0]
    assert monday["scheduled_work"] == []


def test_interval_crossing_day_boundary_is_projected(db_session) -> None:
    graph = _graph(db_session)
    start = WEEK_MONDAY + timedelta(hours=23)
    end = WEEK_MONDAY + timedelta(days=1, hours=1)
    task = _task(graph, title="Overnight work", planned_start_at=start, planned_end_at=end)
    snapshot = _snapshot(db_session)
    monday = snapshot["days"][0]
    tuesday = snapshot["days"][1]
    assert [obj.id for obj in monday["scheduled_work"]] == [task.id]
    assert [obj.id for obj in tuesday["scheduled_work"]] == [task.id]
    assert snapshot["days"][2]["scheduled_work"] == []


def test_scheduled_work_separate_from_events_and_hints(db_session) -> None:
    _enable_temporal(db_session)
    graph = _graph(db_session)
    event = _event(graph, title="Office", start_at=START, due_at=END)
    task = _task(graph, title="Desk work")
    hint = _hint(graph, title="Possible call", start_at=WEEK_MONDAY + timedelta(hours=16))
    monday = _snapshot(db_session)["days"][0]
    assert [obj.id for obj in monday["events"]] == [event.id]
    assert [obj.id for obj in monday["scheduled_work"]] == [task.id]
    assert [obj.id for obj in monday["temporal_hints"]] == [hint.id]
    assert event.id not in {obj.id for obj in monday["scheduled_work"]}
    assert task.id not in {obj.id for obj in monday["events"]}
    assert hint.id not in {obj.id for obj in monday["scheduled_work"]}
    assert hint.id not in {obj.id for obj in monday["events"]}


def test_scheduled_task_is_not_calendar_busy(db_session) -> None:
    graph = _graph(db_session)
    task = _task(graph)
    rows = list(db_session.scalars(select(Object).where(*active_event_predicates(BOOTSTRAP_USER_ID))))
    assert task not in rows
    assert task.kind == "task"
    assert task.provider is None
    assert "task" not in WEEK_CALENDAR_PROVIDERS
    monday = _snapshot(db_session)["days"][0]
    assert monday["events"] == []
    assert monday["scheduled_work"][0].id == task.id


def test_overlap_with_confirmed_event_does_not_hide_either(db_session) -> None:
    graph = _graph(db_session)
    event = _event(graph, title="Office", start_at=START, due_at=END)
    task = _task(graph, title="Desk work")
    monday = _snapshot(db_session)["days"][0]
    assert [obj.id for obj in monday["events"]] == [event.id]
    assert [obj.id for obj in monday["scheduled_work"]] == [task.id]


def test_http_object_and_week_scheduled_work(db_session, auth_client) -> None:
    apply_embedding_service_overrides(FakeEmbeddingService())
    created = auth_client.post(
        "/objects",
        json={
            "kind": "task",
            "title": "HTTP planned",
            "origin": "user",
            "status": "open",
            "planned_start_at": START.isoformat(),
            "planned_end_at": END.isoformat(),
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["planned_start_at"] is not None
    assert body["planned_end_at"] is not None
    assert body["due_at"] is None

    half = auth_client.post(
        "/objects",
        json={
            "kind": "task",
            "title": "HTTP half",
            "origin": "user",
            "planned_start_at": START.isoformat(),
        },
    )
    assert half.status_code == 422

    note = auth_client.post(
        "/objects",
        json={
            "kind": "note",
            "title": "HTTP note",
            "origin": "user",
            "planned_start_at": START.isoformat(),
            "planned_end_at": END.isoformat(),
        },
    )
    assert note.status_code == 422

    week = auth_client.get(
        "/week",
        params={"week_start": WEEK_START, "client_timezone_id": "Europe/Amsterdam"},
    )
    assert week.status_code == 200
    monday = week.json()["days"][0]
    assert [row["title"] for row in monday["scheduled_work"]] == ["HTTP planned"]
    assert monday["scheduled_work"][0]["id"] == body["id"]
    UUID(monday["scheduled_work"][0]["id"])
    assert monday["events"] == []
    assert "body" not in monday["scheduled_work"][0]
    cleared = auth_client.patch(
        f"/objects/{body['id']}",
        json={"planned_start_at": None, "planned_end_at": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["planned_start_at"] is None
    assert cleared.json()["planned_end_at"] is None
