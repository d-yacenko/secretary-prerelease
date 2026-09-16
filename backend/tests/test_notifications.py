import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.api.schemas import ContextBuildResult, ContextItem, ObjectCreate
from app.db.models import Object
from app.llm.fake_secretary_provider import FakeSecretaryProvider
from app.notifications.constants import (
    NOTIFICATION_STATUS_ACCEPTED,
    NOTIFICATION_STATUS_IGNORED,
    NOTIFICATION_STATUS_NEW,
    NOTIFICATION_STATUS_READ,
)
from app.services.graph_service import GraphService
from app.services.notification_service import NotificationService
from app.services.secretary_notification_service import create_notifications_from_analysis
from app.services.secretary_service import SecretaryService
from app.users.bootstrap import BOOTSTRAP_USER_ID

FIXED_REFERENCE = datetime(2026, 8, 28, 10, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
EMAIL_TEXT = (
    "Let's meet tomorrow at 13:30. Please send the updated forecast before the meeting."
)


@pytest.fixture
def notification_service(db_session) -> NotificationService:
    return NotificationService(db_session, BOOTSTRAP_USER_ID)


def _email_context(db_session) -> ContextBuildResult:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    email = graph.create_object(
        ObjectCreate(
            kind="email",
            title="Inbound email",
            origin="source",
            body=EMAIL_TEXT,
        )
    )
    return ContextBuildResult(
        items=[
            ContextItem(
                object_id=email.id,
                kind="email",
                title="Inbound email",
                content=EMAIL_TEXT,
                origin="source",
                state="observed",
                why_included="target object",
            )
        ],
        total_chars=len(EMAIL_TEXT),
        truncated=False,
    )


def test_create_notification_has_status_new(notification_service) -> None:
    notification = notification_service.create(
        title="Review proposal",
        body="Please review",
        priority="normal",
        proposal={"type": "task", "confidence": 0.7, "evidence": []},
    )
    assert notification.status == NOTIFICATION_STATUS_NEW
    assert notification.read_at is None


def test_create_notification_preserves_source_object_link(
    db_session, notification_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = graph.create_object(
        ObjectCreate(kind="email", title="Source email", origin="source")
    )
    notification = notification_service.create(
        title="Follow up",
        body="Reply needed",
        priority="high",
        source_object_id=source.id,
        proposal={"type": "task", "confidence": 0.8, "evidence": []},
    )
    assert notification.source_object_id == source.id


def test_proposal_json_preserves_confidence_evidence_type(notification_service) -> None:
    proposal = {
        "type": "meeting",
        "title": "Team sync",
        "confidence": 0.84,
        "evidence": [
            {
                "context_index": 0,
                "object_id": str(uuid.uuid4()),
                "why_included": "target object",
            }
        ],
    }
    notification = notification_service.create(
        title="Team sync",
        body="Meeting inferred",
        priority="high",
        proposal=proposal,
    )
    assert notification.proposal_["type"] == "meeting"
    assert notification.proposal_["confidence"] == 0.84
    assert notification.proposal_["evidence"][0]["object_id"]


def test_list_notifications_returns_newest_first(db_session, notification_service) -> None:
    first = notification_service.create(
        title="Older",
        body=None,
        priority="low",
        proposal={"type": "note", "confidence": 0.5, "evidence": []},
    )
    second = notification_service.create(
        title="Newer",
        body=None,
        priority="normal",
        proposal={"type": "note", "confidence": 0.6, "evidence": []},
    )
    db_session.flush()
    second.created_at = first.created_at + timedelta(seconds=1)
    db_session.flush()

    rows = notification_service.list_notifications()
    assert rows[0].title == "Newer"
    assert rows[1].title == "Older"


def test_list_notifications_status_filter(notification_service) -> None:
    notification_service.create(
        title="Unread",
        body=None,
        priority="normal",
        proposal={"type": "note", "confidence": 0.5, "evidence": []},
    )
    read = notification_service.create(
        title="Read item",
        body=None,
        priority="normal",
        proposal={"type": "note", "confidence": 0.5, "evidence": []},
    )
    notification_service.mark_read(read.id)

    new_only = notification_service.list_notifications(status=NOTIFICATION_STATUS_NEW)
    assert all(row.status == NOTIFICATION_STATUS_NEW for row in new_only)
    assert {row.title for row in new_only} == {"Unread"}


def test_mark_read_sets_read_at(notification_service) -> None:
    notification = notification_service.create(
        title="Unread",
        body=None,
        priority="normal",
        proposal={"type": "note", "confidence": 0.5, "evidence": []},
    )
    updated = notification_service.mark_read(notification.id)
    assert updated.status == NOTIFICATION_STATUS_READ
    assert updated.read_at is not None


def test_accept_changes_status_to_accepted(notification_service) -> None:
    notification = notification_service.create(
        title="Proposal",
        body=None,
        priority="normal",
        proposal={"type": "task", "confidence": 0.7, "evidence": []},
    )
    updated = notification_service.accept(notification.id)
    assert updated.status == NOTIFICATION_STATUS_ACCEPTED
    assert updated.read_at is not None


def test_ignore_changes_status_to_ignored(notification_service) -> None:
    notification = notification_service.create(
        title="Proposal",
        body=None,
        priority="normal",
        proposal={"type": "task", "confidence": 0.7, "evidence": []},
    )
    updated = notification_service.ignore(notification.id)
    assert updated.status == NOTIFICATION_STATUS_IGNORED
    assert updated.read_at is not None


def test_deleting_source_object_keeps_notification(
    db_session, notification_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = graph.create_object(
        ObjectCreate(kind="email", title="Disposable source", origin="source")
    )
    notification = notification_service.create(
        title="Historical item",
        body=None,
        priority="normal",
        source_object_id=source.id,
        proposal={"type": "note", "confidence": 0.5, "evidence": []},
    )
    notification_id = notification.id
    graph.delete_object(source.id)

    stored = notification_service.get(notification_id)
    assert stored.source_object_id is None
    assert stored.title == "Historical item"


def test_secretary_analysis_creates_notifications_with_evidence(db_session) -> None:
    service = NotificationService(db_session, BOOTSTRAP_USER_ID)
    secretary = SecretaryService(FakeSecretaryProvider())
    context = _email_context(db_session)
    result = secretary.analyze(
        trigger="analyze inbound email",
        context=context,
        reference_datetime=FIXED_REFERENCE,
        timezone="Europe/Amsterdam",
    )
    assert result.success and result.analysis is not None

    notifications = create_notifications_from_analysis(service, result.analysis, context)
    assert len(notifications) >= 2
    meeting = next(
        n for n in notifications if n.proposal_.get("type") == "meeting"
    )
    assert meeting.proposal_["confidence"] == 0.84
    assert meeting.proposal_["evidence"][0]["object_id"] == str(context.items[0].object_id)
    assert meeting.proposal_["evidence"][0]["origin"] == "source"
    assert meeting.proposal_["evidence"][0]["state"] == "observed"
    assert meeting.source_object_id == context.items[0].object_id


def test_secretary_notification_ignores_nonexistent_target_object_id(db_session) -> None:
    from app.llm.secretary_models import SecretaryAnalysis, SecretaryProposal

    service = NotificationService(db_session, BOOTSTRAP_USER_ID)
    context = _email_context(db_session)
    missing_target = uuid.uuid4()
    analysis = SecretaryAnalysis(
        proposals=[
            SecretaryProposal(
                type="relation",
                title="Link to missing object",
                confidence=0.72,
                evidence_item_indices=[0],
                relation_type="related_to",
                target_object_id=missing_target,
            )
        ]
    )
    notifications = create_notifications_from_analysis(service, analysis, context)
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.related_object_id is None
    assert notification.proposal_["target_object_id"] == str(missing_target)


def test_secretary_notifications_do_not_create_tasks_or_edges(db_session) -> None:
    service = NotificationService(db_session, BOOTSTRAP_USER_ID)
    secretary = SecretaryService(FakeSecretaryProvider())
    context = _email_context(db_session)
    before_objects = db_session.scalar(select(func.count()).select_from(Object))
    result = secretary.analyze(
        trigger="analyze inbound email",
        context=context,
        reference_datetime=FIXED_REFERENCE,
    )
    create_notifications_from_analysis(service, result.analysis, context)
    after_objects = db_session.scalar(select(func.count()).select_from(Object))
    assert before_objects == after_objects


def test_notification_api_list_and_read(db_session, auth_headers) -> None:
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.main import app
    from tests.conftest import AuthTestClient

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    client = AuthTestClient(TestClient(app), auth_headers)

    service = NotificationService(db_session, BOOTSTRAP_USER_ID)
    created = service.create(
        title="API notification",
        body="Body",
        priority="normal",
        proposal={"type": "note", "confidence": 0.5, "evidence": []},
    )
    db_session.flush()

    listed = client.get("/notifications")
    assert listed.status_code == 200
    payload = listed.json()
    assert any(row["id"] == str(created.id) for row in payload["notifications"])

    read = client.post(f"/notifications/{created.id}/read")
    assert read.status_code == 200
    assert read.json()["status"] == NOTIFICATION_STATUS_READ
    assert read.json()["read_at"] is not None

    app.dependency_overrides.clear()


def test_notification_api_invalid_status_returns_422(db_session, auth_headers) -> None:
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.main import app
    from tests.conftest import AuthTestClient

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    client = AuthTestClient(TestClient(app), auth_headers)

    response = client.get("/notifications", params={"status": "invalid"})
    assert response.status_code == 422

    app.dependency_overrides.clear()
