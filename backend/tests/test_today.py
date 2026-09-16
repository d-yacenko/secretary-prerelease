import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.api.schemas import ObjectCreate
from app.db.models import Job, Object, User
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
from app.notifications.constants import NOTIFICATION_STATUS_ACCEPTED
from app.services.errors import NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.notification_service import NotificationService
from app.services.today_service import TODAY_MAX_TASKS, TodayService
from app.users.bootstrap import BOOTSTRAP_USER_ID

AMSTERDAM = ZoneInfo("Europe/Amsterdam")


@pytest.fixture
def user_b_id(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="User B"))
    db_session.flush()
    return user_id


@pytest.fixture
def notification_service(db_session) -> NotificationService:
    return NotificationService(db_session, BOOTSTRAP_USER_ID)


def _local_day_bounds(reference: datetime) -> tuple[datetime, datetime]:
    local = reference.astimezone(AMSTERDAM)
    day_start = datetime.combine(local.date(), datetime.min.time(), tzinfo=AMSTERDAM)
    day_end = day_start + timedelta(days=1)
    return day_start, day_end


def test_today_includes_task_due_today(db_session, monkeypatch) -> None:
    reference = datetime(2026, 8, 28, 15, 0, tzinfo=AMSTERDAM)
    day_start, _ = _local_day_bounds(reference)
    due_today = day_start + timedelta(hours=10)

    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    graph.create_object(
        ObjectCreate(
            kind="task",
            title="Due today",
            origin="user",
            state="confirmed",
            due_at=due_today,
        )
    )

    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(reference_at=reference)
    assert any(task.title == "Due today" for task in snapshot["tasks"])


def test_today_includes_overdue_task(db_session, monkeypatch) -> None:
    reference = datetime(2026, 8, 28, 15, 0, tzinfo=AMSTERDAM)
    day_start, _ = _local_day_bounds(reference)

    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    graph.create_object(
        ObjectCreate(
            kind="task",
            title="Overdue",
            origin="user",
            state="confirmed",
            due_at=day_start - timedelta(hours=2),
        )
    )

    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(reference_at=reference)
    assert any(task.title == "Overdue" for task in snapshot["tasks"])


def test_today_excludes_future_task(db_session, monkeypatch) -> None:
    reference = datetime(2026, 8, 28, 15, 0, tzinfo=AMSTERDAM)
    _, day_end = _local_day_bounds(reference)

    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    graph.create_object(
        ObjectCreate(
            kind="task",
            title="Future",
            origin="user",
            state="confirmed",
            due_at=day_end + timedelta(days=1),
        )
    )

    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(reference_at=reference)
    assert all(task.title != "Future" for task in snapshot["tasks"])


def test_today_excludes_terminal_task(db_session, monkeypatch) -> None:
    reference = datetime(2026, 8, 28, 15, 0, tzinfo=AMSTERDAM)
    day_start, _ = _local_day_bounds(reference)

    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    done = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Done task",
            origin="user",
            state="confirmed",
            due_at=day_start + timedelta(hours=1),
        )
    )
    done.status = "done"

    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(reference_at=reference)
    assert all(task.title != "Done task" for task in snapshot["tasks"])


def test_today_includes_event_today(db_session, monkeypatch) -> None:
    reference = datetime(2026, 8, 28, 15, 0, tzinfo=AMSTERDAM)
    day_start, _ = _local_day_bounds(reference)

    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    graph.create_object(
        ObjectCreate(
            kind="event",
            title="Meeting",
            origin="source",
            state="observed",
            start_at=day_start + timedelta(hours=2),
            due_at=day_start + timedelta(hours=3),
        )
    )

    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(reference_at=reference)
    assert any(event.title == "Meeting" for event in snapshot["calendar_events"])


def test_today_excludes_event_outside_day(db_session, monkeypatch) -> None:
    reference = datetime(2026, 8, 28, 15, 0, tzinfo=AMSTERDAM)
    _, day_end = _local_day_bounds(reference)

    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    graph.create_object(
        ObjectCreate(
            kind="event",
            title="Tomorrow",
            origin="source",
            state="observed",
            start_at=day_end + timedelta(hours=1),
            due_at=day_end + timedelta(hours=2),
        )
    )

    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(reference_at=reference)
    assert all(event.title != "Tomorrow" for event in snapshot["calendar_events"])


def test_today_includes_high_priority_unresolved_notification(
    db_session, notification_service, monkeypatch
) -> None:
    reference = datetime(2026, 8, 28, 15, 0, tzinfo=AMSTERDAM)
    notification_service.create(
        title="Important",
        body=None,
        priority="high",
        proposal={"type": "task", "confidence": 0.8, "evidence": []},
    )

    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(reference_at=reference)
    assert any(n.title == "Important" for n in snapshot["notifications"])


def test_today_excludes_ignored_notification(
    db_session, notification_service, monkeypatch
) -> None:
    reference = datetime(2026, 8, 28, 15, 0, tzinfo=AMSTERDAM)
    ignored = notification_service.create(
        title="Ignored",
        body=None,
        priority="urgent",
        proposal={"type": "task", "confidence": 0.8, "evidence": []},
    )
    notification_service.ignore(ignored.id)

    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(reference_at=reference)
    assert all(n.title != "Ignored" for n in snapshot["notifications"])


def test_today_user_isolation(db_session, user_b_id, monkeypatch) -> None:
    reference = datetime(2026, 8, 28, 15, 0, tzinfo=AMSTERDAM)
    day_start, _ = _local_day_bounds(reference)

    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID)
    graph_b = GraphService(db_session, user_b_id)
    graph_a.create_object(
        ObjectCreate(
            kind="task",
            title="A task",
            origin="user",
            state="confirmed",
            due_at=day_start + timedelta(hours=1),
        )
    )
    graph_b.create_object(
        ObjectCreate(
            kind="task",
            title="B task",
            origin="user",
            state="confirmed",
            due_at=day_start + timedelta(hours=1),
        )
    )

    snapshot_a = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(reference_at=reference)
    snapshot_b = TodayService(db_session, user_b_id).snapshot(reference_at=reference)
    assert {task.title for task in snapshot_a["tasks"]} == {"A task"}
    assert {task.title for task in snapshot_b["tasks"]} == {"B task"}


def test_notification_task_accept_creates_confirmed_task(
    db_session, notification_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    email = graph.create_object(
        ObjectCreate(kind="email", title="Inbound email", origin="source", body="Body")
    )
    due_at = datetime(2026, 8, 29, 12, 0, tzinfo=AMSTERDAM)
    notification = notification_service.create(
        title="Follow up",
        body="Notification body",
        priority="high",
        source_object_id=email.id,
        proposal={
            "type": "task",
            "title": "Send forecast",
            "description": "Send updated forecast",
            "confidence": 0.86,
            "due_at": due_at.isoformat(),
            "evidence": [],
        },
    )

    accepted = notification_service.accept(notification.id)
    assert accepted.status == NOTIFICATION_STATUS_ACCEPTED
    assert accepted.result_object_id is not None

    task = db_session.get(Object, accepted.result_object_id)
    assert task is not None
    assert task.kind == "task"
    assert task.user_id == BOOTSTRAP_USER_ID
    assert task.origin == "agent"
    assert task.state == "confirmed"
    assert task.title == "Send forecast"
    assert task.body == "Send updated forecast"
    assert task.due_at == due_at
    assert task.metadata_["accepted_from_notification_id"] == str(notification.id)

    jobs = list(
        db_session.scalars(
            select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT, Job.user_id == BOOTSTRAP_USER_ID)
        )
    )
    assert any(job.payload.get("object_id") == str(task.id) for job in jobs)

    from app.db.models import Edge

    edge = db_session.scalar(
        select(Edge).where(
            Edge.source_id == task.id,
            Edge.target_id == email.id,
            Edge.type == "references",
        )
    )
    assert edge is not None
    assert edge.origin == "agent"
    assert edge.state == "confirmed"


def test_notification_task_accept_is_idempotent(db_session, notification_service) -> None:
    notification = notification_service.create(
        title="Task proposal",
        body=None,
        priority="normal",
        proposal={
            "type": "task",
            "title": "Once",
            "description": "Only once",
            "confidence": 0.7,
            "evidence": [],
        },
    )
    first = notification_service.accept(notification.id)
    second = notification_service.accept(notification.id)
    assert first.result_object_id == second.result_object_id

    task_count = db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.kind == "task",
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.metadata_["accepted_from_notification_id"].as_string() == str(notification.id),
        )
    )
    assert task_count == 1

    job_count = db_session.scalar(
        select(func.count()).select_from(Job).where(
            Job.type == JOB_TYPE_EMBED_OBJECT,
            Job.user_id == BOOTSTRAP_USER_ID,
        )
    )
    assert job_count == 1


def test_cannot_accept_ignored_task_notification(db_session, notification_service) -> None:
    notification = notification_service.create(
        title="Ignored task",
        body=None,
        priority="normal",
        proposal={"type": "task", "title": "Nope", "confidence": 0.5, "evidence": []},
    )
    notification_service.ignore(notification.id)
    with pytest.raises(ValidationError):
        notification_service.accept(notification.id)


def test_list_unresolved_notifications(db_session, notification_service) -> None:
    notification_service.create(
        title="New",
        body=None,
        priority="normal",
        proposal={"type": "note", "confidence": 0.5, "evidence": []},
    )
    read = notification_service.create(
        title="Read",
        body=None,
        priority="normal",
        proposal={"type": "note", "confidence": 0.5, "evidence": []},
    )
    notification_service.mark_read(read.id)
    accepted = notification_service.create(
        title="Accepted",
        body=None,
        priority="normal",
        proposal={"type": "note", "confidence": 0.5, "evidence": []},
    )
    notification_service.accept(accepted.id)

    unresolved = notification_service.list_notifications(status="unresolved")
    titles = {row.title for row in unresolved}
    assert titles == {"New", "Read"}


def test_notification_task_accept_user_isolation(
    db_session, user_b_id, notification_service
) -> None:
    graph_b = GraphService(db_session, user_b_id)
    email_b = graph_b.create_object(
        ObjectCreate(kind="email", title="B email", origin="source")
    )
    service_b = NotificationService(db_session, user_b_id)
    notification_b = service_b.create(
        title="B proposal",
        body=None,
        priority="normal",
        source_object_id=email_b.id,
        proposal={
            "type": "task",
            "title": "B task",
            "description": "B only",
            "confidence": 0.8,
            "evidence": [],
        },
    )

    service_a = NotificationService(db_session, BOOTSTRAP_USER_ID)
    with pytest.raises(NotFoundError):
        service_a.accept(notification_b.id)

    accepted = service_b.accept(notification_b.id)
    task = db_session.get(Object, accepted.result_object_id)
    assert task is not None
    assert task.user_id == user_b_id
    assert task.title == "B task"


def test_http_unresolved_notifications(db_session, auth_client, notification_service) -> None:
    notification_service.create(
        title="Unresolved new",
        body=None,
        priority="normal",
        proposal={"type": "note", "confidence": 0.5, "evidence": []},
    )
    read = notification_service.create(
        title="Unresolved read",
        body=None,
        priority="normal",
        proposal={"type": "note", "confidence": 0.5, "evidence": []},
    )
    notification_service.mark_read(read.id)
    ignored = notification_service.create(
        title="Ignored item",
        body=None,
        priority="normal",
        proposal={"type": "note", "confidence": 0.5, "evidence": []},
    )
    notification_service.ignore(ignored.id)
    db_session.flush()

    response = auth_client.get("/notifications", params={"status": "unresolved"})
    assert response.status_code == 200
    titles = {row["title"] for row in response.json()["notifications"]}
    assert titles == {"Unresolved new", "Unresolved read"}


def test_http_task_accept_and_today(db_session, auth_client) -> None:
    day_start, _ = _local_day_bounds(datetime.now(AMSTERDAM))
    due_at = day_start + timedelta(hours=12)

    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    email = graph.create_object(
        ObjectCreate(kind="email", title="Source email", origin="source")
    )
    service = NotificationService(db_session, BOOTSTRAP_USER_ID)
    notification = service.create(
        title="Proposal",
        body="Body",
        priority="high",
        source_object_id=email.id,
        proposal={
            "type": "task",
            "title": "Today task",
            "description": "Do it",
            "confidence": 0.9,
            "due_at": due_at.isoformat(),
            "evidence": [],
        },
    )
    db_session.flush()

    accept = auth_client.post(f"/notifications/{notification.id}/accept")
    assert accept.status_code == 200
    payload = accept.json()
    assert payload["status"] == NOTIFICATION_STATUS_ACCEPTED
    assert payload["result_object_id"] is not None

    today = auth_client.get("/today")
    assert today.status_code == 200
    today_payload = today.json()
    assert any(task["title"] == "Today task" for task in today_payload["tasks"])


def test_today_returns_day_start(db_session) -> None:
    reference = datetime(2026, 8, 29, 12, 0, tzinfo=AMSTERDAM)
    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(reference_at=reference)
    assert snapshot["day_start"] == datetime(2026, 8, 29, 0, 0, tzinfo=AMSTERDAM)


def test_today_excludes_terminal_tasks_before_limit(db_session) -> None:
    reference = datetime(2026, 8, 28, 15, 0, tzinfo=AMSTERDAM)
    day_start, _ = _local_day_bounds(reference)

    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    for i in range(TODAY_MAX_TASKS):
        done = graph.create_object(
            ObjectCreate(
                kind="task",
                title=f"Done {i}",
                origin="user",
                state="confirmed",
                due_at=day_start - timedelta(hours=TODAY_MAX_TASKS - i),
            )
        )
        done.status = "done"

    graph.create_object(
        ObjectCreate(
            kind="task",
            title="Valid task",
            origin="user",
            state="confirmed",
            due_at=day_start + timedelta(hours=12),
        )
    )

    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(reference_at=reference)
    titles = {task.title for task in snapshot["tasks"]}
    assert "Valid task" in titles
    assert not any(title.startswith("Done") for title in titles)
    assert len(snapshot["tasks"]) <= TODAY_MAX_TASKS


def test_http_accept_ignored_task_returns_422(
    db_session, auth_client, notification_service
) -> None:
    notification = notification_service.create(
        title="Ignored task",
        body=None,
        priority="normal",
        proposal={"type": "task", "title": "Nope", "confidence": 0.5, "evidence": []},
    )
    notification_service.ignore(notification.id)
    db_session.flush()

    response = auth_client.post(f"/notifications/{notification.id}/accept")
    assert response.status_code == 422

    task_count = db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.kind == "task",
            Object.metadata_["accepted_from_notification_id"].as_string() == str(notification.id),
        )
    )
    assert task_count == 0


def test_http_accept_resolved_task_returns_422(
    db_session, auth_client, notification_service
) -> None:
    notification = notification_service.create(
        title="Resolved task",
        body=None,
        priority="normal",
        proposal={"type": "task", "title": "Nope", "confidence": 0.5, "evidence": []},
    )
    notification_service.resolve(notification.id)
    db_session.flush()

    response = auth_client.post(f"/notifications/{notification.id}/accept")
    assert response.status_code == 422

    task_count = db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.kind == "task",
            Object.metadata_["accepted_from_notification_id"].as_string() == str(notification.id),
        )
    )
    assert task_count == 0


def test_http_accept_task_idempotent(db_session, auth_client, notification_service) -> None:
    notification = notification_service.create(
        title="Once",
        body=None,
        priority="normal",
        proposal={
            "type": "task",
            "title": "Once task",
            "description": "Only once",
            "confidence": 0.7,
            "evidence": [],
        },
    )
    db_session.flush()

    first = auth_client.post(f"/notifications/{notification.id}/accept")
    second = auth_client.post(f"/notifications/{notification.id}/accept")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["result_object_id"] == second.json()["result_object_id"]

    task_count = db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.kind == "task",
            Object.metadata_["accepted_from_notification_id"].as_string() == str(notification.id),
        )
    )
    assert task_count == 1


def test_http_today_includes_day_start(auth_client) -> None:
    response = auth_client.get("/today")
    assert response.status_code == 200
    payload = response.json()
    assert "day_start" in payload
    assert payload["timezone"] == "Europe/Amsterdam"
