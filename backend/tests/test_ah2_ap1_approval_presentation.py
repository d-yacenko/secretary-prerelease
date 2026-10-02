import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.api.schemas import EdgeCreate, ObjectCreate
from app.assistant.approval_presentation import TITLE_MAX_CHARS
from app.assistant.temporal_finalization import build_temporal_display_facts
from app.db.models import Object, PendingActionPlan
from app.services.action_plan_service import ActionPlanService
from app.services.assistant_conversation_service import AssistantConversationService
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE, USER_ORIGIN
from app.users.bootstrap import BOOTSTRAP_USER_ID


def _graph(db_session) -> GraphService:
    return GraphService(db_session, BOOTSTRAP_USER_ID)


def _task(db_session, title: str, *, status: str = "open", kind: str = "task") -> Object:
    return _graph(db_session).create_object(
        ObjectCreate(
            kind=kind,
            title=title,
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
            status=status if kind == "task" else None,
        )
    )


def _presentation(plan_view) -> dict:
    return plan_view.actions[0]["presentation"]


def test_snapshot_is_stored_and_hydrated(db_session) -> None:
    task = _task(db_session, "Черновик")
    plan = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan(
        [
            {
                "tool_name": "update_task",
                "arguments": {
                    "object_id": str(task.id),
                    "due_at": "2026-10-09T23:59:00+03:00",
                },
            }
        ]
    )
    stored = db_session.get(PendingActionPlan, plan.id)
    assert stored.actions[0]["presentation"]["entities"][0]["title"] == "Черновик"
    hydrated = AssistantConversationService(db_session, BOOTSTRAP_USER_ID).hydrate_plan(plan.id)
    assert hydrated is not None
    assert hydrated.actions[0].presentation == stored.actions[0]["presentation"]


def test_snapshot_survives_rename_and_execution_keeps_object_id(db_session) -> None:
    task = _task(db_session, "Title A")
    service = ActionPlanService(db_session, BOOTSTRAP_USER_ID)
    plan = service.create_plan(
        [
            {
                "tool_name": "update_task",
                "arguments": {"object_id": str(task.id), "title": "Renamed by execution"},
            }
        ]
    )
    frozen = _presentation(plan)["entities"][0]["title"]
    assert frozen == "Title A"
    task.title = "Title B"
    db_session.flush()
    reread = db_session.get(PendingActionPlan, plan.id)
    assert reread.actions[0]["presentation"]["entities"][0]["title"] == "Title A"
    approved = service.approve(plan.id)
    db_session.refresh(task)
    assert task.title == "Renamed by execution"
    assert approved.actions[0]["arguments"]["object_id"] == str(task.id)
    assert approved.actions[0]["presentation"]["entities"][0]["title"] == "Title A"


def test_status_snapshot_keeps_open_to_open(db_session) -> None:
    task = _task(db_session, "Публикации", status="open")
    plan = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan(
        [
            {
                "tool_name": "set_task_status",
                "arguments": {"object_id": str(task.id), "status": "open"},
            }
        ]
    )
    snapshot = _presentation(plan)
    assert snapshot["entities"][0]["title"] == "Публикации"
    names = {item["name"]: item["value"] for item in snapshot["fields"]}
    assert names["current_status"] == "open"
    assert names["status"] == "open"
    assert str(task.id) not in json.dumps(snapshot["fields"])


def test_part_of_snapshot_keeps_child_to_parent(db_session) -> None:
    child = _task(db_session, "Бизнес")
    parent = _task(db_session, "Экспериментальная рубрика октября")
    plan = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan(
        [
            {
                "tool_name": "link_objects",
                "arguments": {
                    "source_id": str(child.id),
                    "target_id": str(parent.id),
                    "type": "part_of",
                },
            }
        ]
    )
    snapshot = _presentation(plan)
    assert snapshot["relation_type"] == "part_of"
    roles = {item["role"]: item["title"] for item in snapshot["entities"]}
    assert roles["source"] == "Бизнес"
    assert roles["target"] == "Экспериментальная рубрика октября"


def test_remove_relation_snapshot_uses_the_exact_edge(db_session) -> None:
    source = _task(db_session, "Экспериментальная рубрика октября")
    target = _task(db_session, "Приглашение_ЮФУ.pdf", kind="note", status=None)
    edge = _graph(db_session).create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type="references",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    plan = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan(
        [{"tool_name": "remove_relation", "arguments": {"edge_id": str(edge.id)}}]
    )
    snapshot = _presentation(plan)
    assert snapshot["relation_type"] == "references"
    roles = {item["role"]: item["title"] for item in snapshot["entities"]}
    assert roles["source"] == "Экспериментальная рубрика октября"
    assert roles["target"] == "Приглашение_ЮФУ.pdf"


def test_waiting_on_update_freezes_task_and_person_titles(db_session) -> None:
    task = _task(db_session, "Черновик")
    person = _task(db_session, "Марина", kind="person", status=None)
    plan = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan(
        [
            {
                "tool_name": "update_task",
                "arguments": {
                    "object_id": str(task.id),
                    "waiting_on_person_ids": [str(person.id)],
                },
            }
        ]
    )
    roles = {item["role"]: item for item in _presentation(plan)["entities"]}
    assert roles["target"]["title"] == "Черновик"
    assert roles["waiting_on"]["title"] == "Марина"
    assert roles["waiting_on"]["kind"] == "person"
    assert "relation_type" not in _presentation(plan)


def test_evidence_update_freezes_evidence_title_without_a_new_task(db_session) -> None:
    task = _task(db_session, "Публикации")
    pdf = _task(db_session, "Приглашение_ЮФУ.pdf", kind="note", status=None)
    before = db_session.scalar(select(Object.id))
    plan = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan(
        [
            {
                "tool_name": "update_task",
                "arguments": {
                    "object_id": str(task.id),
                    "evidence_object_ids": [str(pdf.id)],
                },
            }
        ]
    )
    roles = {item["role"]: item for item in _presentation(plan)["entities"]}
    assert roles["target"]["title"] == "Публикации"
    assert roles["evidence"]["title"] == "Приглашение_ЮФУ.pdf"
    assert roles["evidence"]["kind"] == "note"
    assert db_session.get(Object, pdf.id).kind == "note"
    assert before is not None


def test_temporal_update_freezes_interval_without_touching_finalization(db_session) -> None:
    task = _task(db_session, "Черновик")
    arguments = {
        "object_id": str(task.id),
        "planned_start_at": "2026-10-06T10:00:00+03:00",
        "planned_end_at": "2026-10-06T12:00:00+03:00",
        "due_at": "2026-10-09T23:59:00+03:00",
    }
    plan = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan(
        [{"tool_name": "update_task", "arguments": arguments}]
    )
    values = {item["name"]: item["value"] for item in _presentation(plan)["fields"]}
    assert values["planned_start_at"] == "2026-10-06T10:00:00+03:00"
    assert values["planned_end_at"] == "2026-10-06T12:00:00+03:00"
    assert values["due_at"] == "2026-10-09T23:59:00+03:00"
    facts = build_temporal_display_facts(
        [{"tool_name": "update_task", "arguments": arguments}],
        {
            "actions": [
                {
                    "tool_name": "update_task",
                    "output": {
                        "changed": True,
                        "object": {
                            "planned_start_at": "2026-10-06T09:00:00+02:00",
                            "planned_end_at": "2026-10-06T11:00:00+02:00",
                            "due_at": "2026-10-09T20:59:00Z",
                        },
                    },
                }
            ]
        },
    )
    assert any("calendar date 2026-10-09" in fact for fact in facts)
    assert "Temporal display facts" not in json.dumps(_presentation(plan))


def test_scheduled_activity_snapshot_has_title_and_run_at(db_session) -> None:
    plan = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan(
        [
            {
                "tool_name": "create_scheduled_activity",
                "arguments": {
                    "title": "Позвонить в издательство",
                    "run_at": "2026-10-02T09:00:00+03:00",
                    "priority": "normal",
                    "body": "secret body that must stay out of the card",
                },
            }
        ]
    )
    snapshot = _presentation(plan)
    values = {item["name"]: item["value"] for item in snapshot["fields"]}
    assert snapshot["operation"] == "create_scheduled_activity"
    assert values["title"] == "Позвонить в издательство"
    assert values["run_at"] == "2026-10-02T09:00:00+03:00"
    assert values["priority"] == "normal"
    assert "body" not in values
    assert "secret body" not in json.dumps(snapshot)


def test_tampered_presentation_does_not_change_execution(db_session) -> None:
    task = _task(db_session, "Черновик", status="open")
    service = ActionPlanService(db_session, BOOTSTRAP_USER_ID)
    plan = service.create_plan(
        [
            {
                "tool_name": "set_task_status",
                "arguments": {"object_id": str(task.id), "status": "done"},
            }
        ]
    )
    row = db_session.get(PendingActionPlan, plan.id)
    row.actions[0]["presentation"]["fields"] = [
        {"name": "current_status", "value": "done"},
        {"name": "status", "value": "open"},
    ]
    row.actions[0]["presentation"]["entities"][0]["title"] = "Not the target"
    flag_modified(row, "actions")
    db_session.flush()
    approved = service.approve(plan.id)
    db_session.refresh(task)
    assert approved.status == "executed"
    assert task.status == "done"
    assert approved.actions[0]["arguments"]["status"] == "done"


def test_legacy_plan_without_presentation_still_loads(db_session) -> None:
    task = _task(db_session, "Legacy")
    row = PendingActionPlan(
        user_id=BOOTSTRAP_USER_ID,
        status="pending",
        actions=[
            {
                "tool_name": "set_task_status",
                "arguments": {"object_id": str(task.id), "status": "done"},
            }
        ],
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db_session.add(row)
    db_session.flush()
    rejected = ActionPlanService(db_session, BOOTSTRAP_USER_ID).reject(row.id)
    assert rejected.status == "rejected"
    assert "presentation" not in rejected.actions[0]
    hydrated = AssistantConversationService(db_session, BOOTSTRAP_USER_ID).hydrate_plan(row.id)
    assert hydrated is not None
    assert hydrated.actions[0].presentation is None


def test_titles_are_bounded_and_hidden_payloads_stay_out(db_session) -> None:
    long_title = "Я" * (TITLE_MAX_CHARS + 40)
    plan = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan(
        [
            {
                "tool_name": "create_task",
                "arguments": {
                    "title": long_title,
                    "confidence": 0.2,
                    "completion_mode": "ongoing",
                    "operation_id": "secret-op",
                    "body": "do not copy this body",
                },
            }
        ]
    )
    snapshot = _presentation(plan)
    assert snapshot["operation"] == "create_direction"
    title = next(item["value"] for item in snapshot["fields"] if item["name"] == "title")
    assert len(title) == TITLE_MAX_CHARS
    assert title.endswith("…")
    encoded = json.dumps(snapshot)
    assert "do not copy this body" not in encoded
    assert "secret-op" not in encoded
    assert "confidence" not in encoded
    assert "metadata" not in encoded
    assert "embedding" not in encoded


def test_other_users_object_title_is_not_snapshotted(db_session) -> None:
    from app.db.models import User

    other_id = uuid.uuid4()
    db_session.add(User(id=other_id, display_name="other"))
    db_session.flush()
    foreign = GraphService(db_session, other_id).create_object(
        ObjectCreate(
            kind="task",
            title="Чужое",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
            status="open",
        )
    )
    plan = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan(
        [
            {
                "tool_name": "update_task",
                "arguments": {"object_id": str(foreign.id), "title": "Nope"},
            }
        ]
    )
    assert _presentation(plan)["entities"] == []
    assert "Чужое" not in json.dumps(_presentation(plan))
