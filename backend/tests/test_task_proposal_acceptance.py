"""Canonical Notification task-proposal acceptance."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.api.schemas import ObjectCreate
from app.db.models import Edge, Job, Object, User
from app.domain.object_visibility import tombstone_object
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
from app.notifications.constants import NOTIFICATION_STATUS_ACCEPTED, NOTIFICATION_STATUS_NEW
from app.services.errors import ValidationError
from app.services.graph_service import GraphService
from app.services.notification_service import NotificationService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE, USER_ORIGIN
from app.services.task_profile_service import TaskProfileService
from app.services.today_service import TodayService
from app.users.bootstrap import BOOTSTRAP_USER_ID

AMSTERDAM = ZoneInfo("Europe/Amsterdam")


@pytest.fixture
def user_b_id(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="User B"))
    db_session.flush()
    return user_id


def _service(db_session) -> NotificationService:
    return NotificationService(db_session, BOOTSTRAP_USER_ID)


def _proposal(**extra) -> dict:
    payload = {
        "type": "task",
        "title": "Send forecast",
        "description": "Send updated forecast",
        "confidence": 0.86,
        "evidence": [],
    }
    payload.update(extra)
    return payload


def _email(db_session, user_id=BOOTSTRAP_USER_ID) -> Object:
    return GraphService(db_session, user_id).create_object(
        ObjectCreate(kind="email", title="Inbound email", origin="source", body="Body")
    )


def _task_count(db_session, notification_id) -> int:
    return db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.kind == "task",
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.metadata_["accepted_from_notification_id"].as_string() == str(notification_id),
        )
    )


def _embed_count(db_session, object_id) -> int:
    return db_session.scalar(
        select(func.count()).select_from(Job).where(
            Job.type == JOB_TYPE_EMBED_OBJECT,
            Job.user_id == BOOTSTRAP_USER_ID,
            Job.payload["object_id"].as_string() == str(object_id),
        )
    )


def test_accept_creates_open_confirmed_task_with_source_evidence(db_session) -> None:
    email = _email(db_session)
    due_at = datetime(2026, 8, 29, 12, 0, tzinfo=AMSTERDAM)
    start_at = datetime(2026, 8, 29, 9, 0, tzinfo=AMSTERDAM)
    notification = _service(db_session).create(
        title="Follow up",
        body="Notification body",
        priority="high",
        source_object_id=email.id,
        proposal=_proposal(due_at=due_at.isoformat(), start_at=start_at.isoformat()),
    )
    accepted = _service(db_session).accept(notification.id)
    task = db_session.get(Object, accepted.result_object_id)
    assert accepted.status == NOTIFICATION_STATUS_ACCEPTED
    assert task.kind == "task"
    assert task.origin == "agent"
    assert task.state == "confirmed"
    assert task.status == "open"
    assert task.title == "Send forecast"
    assert task.body == "Send updated forecast"
    assert task.confidence == 0.86
    assert task.due_at == due_at
    assert task.start_at == start_at
    assert task.planned_start_at is None
    assert task.planned_end_at is None
    edges = list(
        db_session.scalars(
            select(Edge).where(Edge.source_id == task.id, Edge.type == "references")
        )
    )
    assert len(edges) == 1
    assert edges[0].target_id == email.id
    assert edges[0].state == "confirmed"
    assert edges[0].origin == "agent"
    assert _embed_count(db_session, task.id) == 1


def test_accept_without_source_still_creates_task(db_session) -> None:
    notification = _service(db_session).create(
        title="Follow up",
        body=None,
        priority="normal",
        proposal=_proposal(),
    )
    accepted = _service(db_session).accept(notification.id)
    task = db_session.get(Object, accepted.result_object_id)
    assert task.status == "open"
    assert db_session.scalar(
        select(func.count()).select_from(Edge).where(Edge.source_id == task.id)
    ) == 0


def test_invalid_source_and_payload_fail_before_task_creation(db_session, user_b_id) -> None:
    service = _service(db_session)
    foreign = _email(db_session, user_b_id)
    deleted = _email(db_session)
    tombstone_object(deleted)
    rejected = _email(db_session)
    rejected.state = REJECTED_STATE
    other_task = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(kind="task", title="Other", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    db_session.flush()

    cases = [
        (_proposal(title="  "), None, "Follow up"),
        (_proposal(due_at="not-a-date"), None, "Follow up"),
        (_proposal(), foreign.id, "Follow up"),
        (_proposal(), deleted.id, "Follow up"),
        (_proposal(), rejected.id, "Follow up"),
        (_proposal(), other_task.id, "Follow up"),
    ]
    # The first case needs an empty notification title so the effective title is blank.
    notifications = []
    blank = service.create(
        title="placeholder",
        body=None,
        priority="normal",
        proposal=_proposal(title="  "),
    )
    blank.title = "   "
    notifications.append(blank)
    for proposal, source_id, title in cases[1:]:
        note = service.create(title=title, body=None, priority="normal", proposal=proposal)
        note.source_object_id = source_id
        notifications.append(note)
    db_session.flush()

    before_tasks = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.kind == "task")
    )
    before_jobs = db_session.scalar(select(func.count()).select_from(Job))
    for note in notifications:
        with pytest.raises(ValidationError):
            service.accept(note.id)
        db_session.refresh(note)
        assert note.status == NOTIFICATION_STATUS_NEW
        assert note.result_object_id is None
    assert db_session.scalar(
        select(func.count()).select_from(Object).where(Object.kind == "task")
    ) == before_tasks
    assert db_session.scalar(select(func.count()).select_from(Job)) == before_jobs


def test_repeated_acceptance_does_not_duplicate_task_edge_or_embedding(db_session) -> None:
    email = _email(db_session)
    service = _service(db_session)
    notification = service.create(
        title="Follow up",
        body=None,
        priority="normal",
        source_object_id=email.id,
        proposal=_proposal(),
    )
    first = service.accept(notification.id)
    second = service.accept(notification.id)
    assert first.result_object_id == second.result_object_id
    assert second.status == NOTIFICATION_STATUS_ACCEPTED
    assert _task_count(db_session, notification.id) == 1
    assert db_session.scalar(
        select(func.count()).select_from(Edge).where(
            Edge.source_id == first.result_object_id,
            Edge.type == "references",
        )
    ) == 1
    assert _embed_count(db_session, first.result_object_id) == 1


def test_inconsistent_result_object_fails_closed(db_session) -> None:
    service = _service(db_session)
    notification = service.create(
        title="Follow up",
        body=None,
        priority="normal",
        proposal=_proposal(),
    )
    note = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(kind="note", title="Not a task", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    notification.result_object_id = note.id
    db_session.flush()
    before = db_session.scalar(select(func.count()).select_from(Object).where(Object.kind == "task"))
    with pytest.raises(ValidationError, match="inconsistent"):
        service.accept(notification.id)
    db_session.refresh(notification)
    assert notification.status == NOTIFICATION_STATUS_NEW
    assert notification.result_object_id == note.id
    assert db_session.scalar(
        select(func.count()).select_from(Object).where(Object.kind == "task")
    ) == before


def test_ignore_creates_no_task(db_session) -> None:
    notification = _service(db_session).create(
        title="Follow up",
        body=None,
        priority="normal",
        proposal=_proposal(),
    )
    _service(db_session).ignore(notification.id)
    assert _task_count(db_session, notification.id) == 0


def test_accepted_task_is_on_profile_and_today(db_session) -> None:
    reference = datetime.now(AMSTERDAM)
    due_at = reference - timedelta(hours=1)
    notification = _service(db_session).create(
        title="Follow up",
        body=None,
        priority="normal",
        proposal=_proposal(due_at=due_at.isoformat()),
    )
    accepted = _service(db_session).accept(notification.id)
    profile = TaskProfileService(db_session, BOOTSTRAP_USER_ID).get_profile(
        accepted.result_object_id
    )
    assert profile.status == "open"
    assert profile.evidence == []
    assert profile.operational.operational_state == "actionable"
    assert profile.operational.is_overdue is True
    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(reference_at=reference)
    match = next(task for task in snapshot["tasks"] if task.id == accepted.result_object_id)
    projection = snapshot["task_projections"][match.id]
    assert projection.operational_state == "actionable"
    assert projection.is_overdue is True
