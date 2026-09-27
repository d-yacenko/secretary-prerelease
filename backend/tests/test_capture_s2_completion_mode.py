import uuid

from sqlalchemy import select

from app.api.schemas import ObjectCreate
from app.db.models import Edge, Job, Object, User
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
from app.services.capture_service import PINNED_CONTEXT_ROLE
from app.services.graph_service import GraphService
from app.users.bootstrap import BOOTSTRAP_USER_ID


def _task(db_session, task_id: str) -> Object:
    task = db_session.get(Object, uuid.UUID(task_id))
    assert task is not None
    return task


def _embed_jobs(db_session, task_id: str) -> list[Job]:
    return [
        job
        for job in db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)).all()
        if job.payload.get("object_id") == task_id
    ]


def test_omitted_completion_mode_stores_finite(db_session, auth_client) -> None:
    response = auth_client.post("/capture/task", json={"text": "plain capture"})
    assert response.status_code == 201
    task = _task(db_session, response.json()["task_id"])
    assert task.kind == "task"
    assert task.completion_mode == "finite"
    assert task.origin == "user"
    assert task.state == "confirmed"
    assert task.status == "open"


def test_explicit_finite_and_ongoing(db_session, auth_client) -> None:
    finite = auth_client.post(
        "/capture/task",
        json={"text": "explicit finite", "completion_mode": "finite"},
    )
    ongoing = auth_client.post(
        "/capture/task",
        json={"text": "explicit ongoing", "completion_mode": "ongoing"},
    )
    assert finite.status_code == 201
    assert ongoing.status_code == 201
    assert _task(db_session, finite.json()["task_id"]).completion_mode == "finite"
    ongoing_task = _task(db_session, ongoing.json()["task_id"])
    assert ongoing_task.completion_mode == "ongoing"
    assert ongoing_task.status == "open"
    assert ongoing_task.kind == "task"


def test_null_and_invalid_completion_mode_rejected(auth_client) -> None:
    null_response = auth_client.post(
        "/capture/task",
        json={"text": "null mode", "completion_mode": None},
    )
    invalid_response = auth_client.post(
        "/capture/task",
        json={"text": "bad mode", "completion_mode": "weekly"},
    )
    assert null_response.status_code == 422
    assert invalid_response.status_code == 422
    assert "completion_mode must be finite or ongoing" in null_response.text


def test_ongoing_preserves_exact_body_and_optional_title(db_session, auth_client) -> None:
    body = "  \n  leading and trailing spaces  \n"
    response = auth_client.post(
        "/capture/task",
        json={"text": body, "title": "Pinned title", "completion_mode": "ongoing"},
    )
    assert response.status_code == 201
    task = _task(db_session, response.json()["task_id"])
    assert task.body == body
    assert task.title == "Pinned title"
    assert task.completion_mode == "ongoing"

    derived = auth_client.post(
        "/capture/task",
        json={"text": "Derived title line", "completion_mode": "ongoing"},
    )
    assert derived.status_code == 201
    derived_task = _task(db_session, derived.json()["task_id"])
    assert derived_task.title
    assert derived_task.completion_mode == "ongoing"


def test_ongoing_context_and_dependency_match_finite(db_session, auth_client) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    context = graph.create_object(
        ObjectCreate(kind="document", title="Context", origin="user", state="confirmed")
    )
    dependency = graph.create_object(
        ObjectCreate(kind="task", title="Dependency", origin="user", state="confirmed")
    )
    db_session.flush()
    payload = {
        "text": "linked capture",
        "context_object_ids": [str(context.id)],
        "depends_on_ids": [str(dependency.id)],
    }
    finite = auth_client.post("/capture/task", json={**payload, "completion_mode": "finite"})
    ongoing = auth_client.post(
        "/capture/task",
        json={**payload, "text": "linked ongoing", "completion_mode": "ongoing"},
    )
    assert finite.status_code == 201
    assert ongoing.status_code == 201

    def edges(task_id: str) -> list[Edge]:
        return list(
            db_session.scalars(select(Edge).where(Edge.source_id == uuid.UUID(task_id))).all()
        )

    finite_edges = edges(finite.json()["task_id"])
    ongoing_edges = edges(ongoing.json()["task_id"])
    assert sorted(edge.type for edge in finite_edges) == ["depends_on", "references"]
    assert sorted(edge.type for edge in ongoing_edges) == ["depends_on", "references"]
    assert all(edge.type != "part_of" for edge in ongoing_edges)
    reference = next(edge for edge in ongoing_edges if edge.type == "references")
    assert reference.metadata_["context_role"] == PINNED_CONTEXT_ROLE
    assert reference.metadata_["added_by"] == "user"


def test_ongoing_cross_user_context_and_dependency_fail_closed(db_session, auth_client) -> None:
    other = User(id=uuid.uuid4(), display_name="Other")
    db_session.add(other)
    db_session.flush()
    foreign_graph = GraphService(db_session, other.id)
    foreign = foreign_graph.create_object(
        ObjectCreate(kind="document", title="Foreign", origin="user", state="confirmed")
    )
    db_session.flush()
    context = auth_client.post(
        "/capture/task",
        json={
            "text": "cross context ongoing",
            "completion_mode": "ongoing",
            "context_object_ids": [str(foreign.id)],
        },
    )
    dependency = auth_client.post(
        "/capture/task",
        json={
            "text": "cross dependency ongoing",
            "completion_mode": "ongoing",
            "depends_on_ids": [str(foreign.id)],
        },
    )
    assert context.status_code == 404
    assert dependency.status_code == 404
    stored = db_session.scalars(
        select(Object).where(Object.body.in_(["cross context ongoing", "cross dependency ongoing"]))
    ).all()
    assert stored == []


def test_ongoing_enqueue_matches_finite_and_wording_does_not_infer_mode(
    db_session, auth_client
) -> None:
    finite = auth_client.post("/capture/task", json={"text": "finite embed"})
    ongoing = auth_client.post(
        "/capture/task",
        json={"text": "ongoing embed", "completion_mode": "ongoing"},
    )
    wording = auth_client.post(
        "/capture/task",
        json={"text": "every week this is an ongoing direction forever"},
    )
    assert finite.status_code == 201
    assert ongoing.status_code == 201
    assert wording.status_code == 201
    assert len(_embed_jobs(db_session, finite.json()["task_id"])) == 1
    assert len(_embed_jobs(db_session, ongoing.json()["task_id"])) == 1
    wording_task = _task(db_session, wording.json()["task_id"])
    assert wording_task.completion_mode == "finite"
    assert wording_task.kind == "task"


def test_old_capture_payload_without_schedule_fields_stays_valid(db_session, auth_client) -> None:
    response = auth_client.post("/capture/task", json={"text": "legacy capture"})
    assert response.status_code == 201
    task = _task(db_session, response.json()["task_id"])
    assert task.completion_mode == "finite"
    assert task.due_at is None
    assert task.planned_start_at is None
    assert task.planned_end_at is None


def test_capture_due_and_planned_interval(db_session, auth_client) -> None:
    due = auth_client.post(
        "/capture/task",
        json={"text": "with due", "due_at": "2026-10-02T09:30:00Z"},
    )
    planned = auth_client.post(
        "/capture/task",
        json={
            "text": "with interval",
            "planned_start_at": "2026-10-02T10:00:00Z",
            "planned_end_at": "2026-10-02T11:00:00Z",
        },
    )
    assert due.status_code == 201
    assert planned.status_code == 201
    due_task = _task(db_session, due.json()["task_id"])
    planned_task = _task(db_session, planned.json()["task_id"])
    assert due_task.due_at is not None
    assert due_task.planned_start_at is None
    assert planned_task.planned_start_at is not None
    assert planned_task.planned_end_at is not None
    assert planned_task.completion_mode == "finite"


def test_half_planned_interval_rejected(auth_client) -> None:
    response = auth_client.post(
        "/capture/task",
        json={"text": "half interval", "planned_start_at": "2026-10-02T10:00:00Z"},
    )
    assert response.status_code == 422


def test_ongoing_capture_keeps_mode_with_due_and_planned(db_session, auth_client) -> None:
    response = auth_client.post(
        "/capture/task",
        json={
            "text": "direction with time",
            "completion_mode": "ongoing",
            "due_at": "2026-10-03T08:00:00Z",
            "planned_start_at": "2026-10-03T09:00:00Z",
            "planned_end_at": "2026-10-03T10:00:00Z",
        },
    )
    assert response.status_code == 201
    task = _task(db_session, response.json()["task_id"])
    assert task.kind == "task"
    assert task.completion_mode == "ongoing"
    assert task.status == "open"
    assert task.due_at is not None
    assert task.planned_end_at > task.planned_start_at
