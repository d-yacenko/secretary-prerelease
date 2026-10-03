"""REL1B-B confirmed Task context and model-visible role evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.api.schemas import EdgeCreate, ObjectCreate
from app.domain.object_visibility import tombstone_object
from app.domain.person_identity import normalize_email
from app.domain.task_relations import DELEGATED_TO, INVOLVES, REQUESTED_BY, WAITING_ON
from app.personal_relevance.models import (
    PERSONAL_RELEVANCE_EVIDENCE_VERSION,
    PERSONAL_RELEVANCE_MAX_RELATED_TASKS_PER_OBJECT,
    PROACTIVE_MAX_KNOWN_PEOPLE_PER_SEED_OBJECT,
    PROACTIVE_MAX_RELATED_TASKS_PER_SEED_OBJECT,
    PROACTIVE_MAX_ROLES_PER_KNOWN_PERSON,
)
from app.proactive.instructions import PROACTIVE_SYSTEM_INSTRUCTIONS
from app.services.graph_service import GraphService
from app.services.person_identity_service import PersonIdentityService
from app.services.person_role_service import PersonRoleService
from app.services.proactive_review_service import (
    ProactiveReviewService,
    seed_context_from_evidence,
)
from app.services.provenance import CONFIRMED_STATE, PROPOSED_STATE, REJECTED_STATE, USER_ORIGIN
from app.services.task_relation_service import TaskRelationService
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_proactive_secretary_c import (
    ScriptedProactiveProvider,
    _enable,
    _insight_answer,
    _install_provider,
    _new_notifications,
    _none_answer,
    _noop_trace,
    _notification_ids,
    _proactive_payload,
)
from tests.test_workflow_intelligence_personal_relevance_e_b import _service, _user

DUE = datetime(2026, 10, 8, 9, tzinfo=UTC)
PLANNED_START = datetime(2026, 10, 6, 9, tzinfo=UTC)
PLANNED_END = datetime(2026, 10, 6, 11, tzinfo=UTC)
START = datetime(2026, 10, 5, 9, tzinfo=UTC)


def test_evidence_version_is_three() -> None:
    assert PERSONAL_RELEVANCE_EVIDENCE_VERSION == 3


def test_confirmed_actor_context_includes_timing_and_exact_role(db_session) -> None:
    user_id = _user(db_session)
    person = _person(db_session, user_id, "Ada", "ada@example.com")
    task = _task(
        db_session,
        user_id,
        "Ship the note",
        due_at=DUE,
        start_at=START,
        planned_start_at=PLANNED_START,
        planned_end_at=PLANNED_END,
    )
    TaskRelationService(db_session, user_id).add_actor(task.id, person.id, REQUESTED_BY)
    email = _email(db_session, user_id, "ada@example.com")
    record = _one(db_session, user_id, email.id)
    assert len(record.related_tasks) == 1
    related = record.related_tasks[0]
    assert related.task_id == task.id
    assert related.title == "Ship the note"
    assert related.status == "open"
    assert related.due_at == DUE
    assert related.start_at == START
    assert related.planned_start_at == PLANNED_START
    assert related.planned_end_at == PLANNED_END
    assert [(item.person_id, item.actor_role) for item in related.actor_links] == [
        (person.id, REQUESTED_BY)
    ]
    assert record.related_tasks_truncated is False


def test_all_four_actor_roles_stay_unmapped(db_session) -> None:
    user_id = _user(db_session)
    person = _person(db_session, user_id, "Ada", "ada@example.com")
    task = _task(db_session, user_id, "Four roles")
    relations = TaskRelationService(db_session, user_id)
    for role in (WAITING_ON, REQUESTED_BY, INVOLVES, DELEGATED_TO):
        relations.add_actor(task.id, person.id, role)
    email = _email(db_session, user_id, "ada@example.com")
    links = _one(db_session, user_id, email.id).related_tasks[0].actor_links
    assert [item.actor_role for item in links] == [
        REQUESTED_BY,
        DELEGATED_TO,
        WAITING_ON,
        INVOLVES,
    ]


def test_proposed_actor_edge_is_absent(db_session) -> None:
    user_id = _user(db_session)
    person = _person(db_session, user_id, "Ada", "ada@example.com")
    task = _task(db_session, user_id, "Proposed link")
    _edge(db_session, user_id, task.id, person.id, REQUESTED_BY, state=PROPOSED_STATE)
    email = _email(db_session, user_id, "ada@example.com")
    record = _one(db_session, user_id, email.id)
    assert record.related_tasks == ()
    assert record.related_tasks_truncated is False


def test_proposed_task_is_absent(db_session) -> None:
    user_id = _user(db_session)
    person = _person(db_session, user_id, "Ada", "ada@example.com")
    task = _task(db_session, user_id, "Proposed task", state=PROPOSED_STATE)
    _edge(db_session, user_id, task.id, person.id, DELEGATED_TO, state=CONFIRMED_STATE)
    email = _email(db_session, user_id, "ada@example.com")
    assert _one(db_session, user_id, email.id).related_tasks == ()


def test_terminal_rejected_deleted_and_foreign_tasks_are_absent(db_session) -> None:
    user_id = _user(db_session)
    person = _person(db_session, user_id, "Ada", "ada@example.com")
    graph = GraphService(db_session, user_id)
    done = _task(db_session, user_id, "Done", status="done")
    rejected = _task(db_session, user_id, "Rejected", state=REJECTED_STATE)
    deleted = _task(db_session, user_id, "Deleted")
    tombstone_object(deleted)
    relations = TaskRelationService(db_session, user_id)
    relations.add_actor(done.id, person.id, REQUESTED_BY)
    _edge(db_session, user_id, rejected.id, person.id, INVOLVES, state=CONFIRMED_STATE)
    _edge(db_session, user_id, deleted.id, person.id, WAITING_ON, state=CONFIRMED_STATE)
    other = _user(db_session)
    foreign_person = _person(db_session, other, "Other", "ada@example.com")
    foreign_task = _task(db_session, other, "Foreign")
    TaskRelationService(db_session, other).add_actor(
        foreign_task.id, foreign_person.id, REQUESTED_BY
    )
    email = _email(db_session, user_id, "ada@example.com")
    assert graph is not None
    assert _one(db_session, user_id, email.id).related_tasks == ()


def test_related_to_is_not_actor_evidence(db_session) -> None:
    user_id = _user(db_session)
    person = _person(db_session, user_id, "Ada", "ada@example.com")
    task = _task(db_session, user_id, "Generic")
    _edge(db_session, user_id, task.id, person.id, "related_to", state=CONFIRMED_STATE)
    email = _email(db_session, user_id, "ada@example.com")
    assert _one(db_session, user_id, email.id).related_tasks == ()


def test_same_task_is_deduped_across_people_and_edges(db_session) -> None:
    user_id = _user(db_session)
    ada = _person(db_session, user_id, "Ada", "ada@example.com")
    bea = _person(db_session, user_id, "Bea", "bea@example.com")
    task = _task(db_session, user_id, "Shared")
    relations = TaskRelationService(db_session, user_id)
    relations.add_actor(task.id, ada.id, REQUESTED_BY)
    relations.add_actor(task.id, bea.id, DELEGATED_TO)
    _edge(db_session, user_id, task.id, ada.id, REQUESTED_BY, state=CONFIRMED_STATE)
    email = _email_recipients(db_session, user_id, ["ada@example.com", "bea@example.com"])
    related = _one(db_session, user_id, email.id).related_tasks
    assert len(related) == 1
    assert [(item.person_id, item.actor_role) for item in related[0].actor_links] == sorted(
        [(ada.id, REQUESTED_BY), (bea.id, DELEGATED_TO)],
        key=lambda item: (item[0].bytes, 0 if item[1] == REQUESTED_BY else 1),
    )


def test_task_bound_is_uuid_neutral_not_due_order(db_session) -> None:
    user_id = _user(db_session)
    person = _person(db_session, user_id, "Ada", "ada@example.com")
    relations = TaskRelationService(db_session, user_id)
    tasks = []
    for index in range(PERSONAL_RELEVANCE_MAX_RELATED_TASKS_PER_OBJECT + 1):
        task = _task(
            db_session,
            user_id,
            f"Task {index}",
            due_at=DUE + timedelta(days=index),
        )
        relations.add_actor(task.id, person.id, INVOLVES)
        tasks.append(task)
    latest_uuid = max(tasks, key=lambda item: item.id.bytes)
    latest_uuid.due_at = DUE - timedelta(days=30)
    db_session.flush()
    email = _email(db_session, user_id, "ada@example.com")
    record = _one(db_session, user_id, email.id)
    expected = sorted((item.id for item in tasks), key=lambda item: item.bytes)[
        :PERSONAL_RELEVANCE_MAX_RELATED_TASKS_PER_OBJECT
    ]
    assert [item.task_id for item in record.related_tasks] == expected
    assert record.related_tasks_truncated is True
    assert latest_uuid.id not in expected
    assert latest_uuid.due_at == DUE - timedelta(days=30)


def test_related_task_query_is_not_per_object(db_session) -> None:
    user_id = _user(db_session)
    relations = TaskRelationService(db_session, user_id)
    emails = []
    for index in range(3):
        person = _person(db_session, user_id, f"Person {index}", f"p{index}@example.com")
        task = _task(db_session, user_id, f"Work {index}")
        relations.add_actor(task.id, person.id, WAITING_ON)
        emails.append(_email(db_session, user_id, f"p{index}@example.com"))
    statements: list[str] = []

    def before(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    event.listen(db_session.connection(), "before_cursor_execute", before)
    try:
        snapshot = _service(db_session).build_snapshot(user_id, [item.id for item in emails])
    finally:
        event.remove(db_session.connection(), "before_cursor_execute", before)
    task_queries = [
        item
        for item in statements
        if "rel1b_related_tasks" in item
    ]
    assert len(task_queries) == 1
    assert all(item.related_tasks for item in snapshot.objects)


def test_signatures_follow_relevant_actor_and_task_fields_only(db_session) -> None:
    user_id = _user(db_session)
    person = _person(db_session, user_id, "Ada", "ada@example.com")
    relevant = _task(db_session, user_id, "Relevant", due_at=DUE)
    unrelated = _task(db_session, user_id, "Unrelated", due_at=DUE)
    email = _email(db_session, user_id, "ada@example.com")
    before = _signature(db_session, user_id, email.id)
    proposed = _task(db_session, user_id, "Proposed", state=PROPOSED_STATE)
    _edge(db_session, user_id, proposed.id, person.id, REQUESTED_BY, state=CONFIRMED_STATE)
    _edge(db_session, user_id, relevant.id, person.id, REQUESTED_BY, state=PROPOSED_STATE)
    assert _signature(db_session, user_id, email.id) == before
    edge, _created = TaskRelationService(db_session, user_id).add_actor(
        relevant.id, person.id, REQUESTED_BY
    )
    added = _signature(db_session, user_id, email.id)
    assert added != before
    TaskRelationService(db_session, user_id).remove_actor(relevant.id, edge.id)
    assert _signature(db_session, user_id, email.id) == before
    TaskRelationService(db_session, user_id).add_actor(relevant.id, person.id, DELEGATED_TO)
    baseline = _signature(db_session, user_id, email.id)
    relevant.title = "Renamed"
    db_session.flush()
    renamed = _signature(db_session, user_id, email.id)
    assert renamed != baseline
    relevant.status = "in_progress"
    relevant.due_at = DUE + timedelta(hours=2)
    relevant.planned_start_at = PLANNED_START
    relevant.planned_end_at = PLANNED_END
    db_session.flush()
    assert _signature(db_session, user_id, email.id) != renamed
    held = _signature(db_session, user_id, email.id)
    unrelated.title = "Elsewhere"
    unrelated.due_at = DUE + timedelta(days=3)
    unrelated.status = "in_progress"
    db_session.flush()
    assert _signature(db_session, user_id, email.id) == held


def test_seed_projection_caps_and_hides_role_internals(db_session) -> None:
    user_id = _user(db_session)
    people = []
    for index in range(PROACTIVE_MAX_KNOWN_PEOPLE_PER_SEED_OBJECT + 1):
        person = _person(db_session, user_id, f"Person {index}", f"p{index}@example.com")
        roles = PersonRoleService(db_session, user_id)
        for role_index in range(PROACTIVE_MAX_ROLES_PER_KNOWN_PERSON + 1):
            roles.assign(person.id, f"role-{index}-{role_index}", f"context-{role_index}")
        people.append(person)
    relations = TaskRelationService(db_session, user_id)
    tasks = []
    for index in range(PROACTIVE_MAX_RELATED_TASKS_PER_SEED_OBJECT + 1):
        task = _task(db_session, user_id, f"Visible task {index}", due_at=DUE)
        relations.add_actor(task.id, people[0].id, INVOLVES)
        tasks.append(task)
    email = _email_recipients(
        db_session, user_id, [f"p{index}@example.com" for index in range(len(people))]
    )
    snapshot = _service(db_session).build_snapshot(user_id, [email.id])
    payload = seed_context_from_evidence([email], snapshot)
    assert payload["evidence_version"] == 3
    assert "semantic_context" in payload["user_context"]
    seed = payload["seed_objects"][0]
    assert "user_participation_roles" in seed
    assert "assigned_labels" in seed
    assert len(seed["known_people"]) == PROACTIVE_MAX_KNOWN_PEOPLE_PER_SEED_OBJECT
    assert seed["known_people_truncated"] is True
    assert len(seed["known_people"][0]["roles"]) == PROACTIVE_MAX_ROLES_PER_KNOWN_PERSON
    assert seed["known_people"][0]["roles_truncated"] is True
    assert len(seed["related_tasks"]) == PROACTIVE_MAX_RELATED_TASKS_PER_SEED_OBJECT
    assert seed["related_tasks_truncated"] is True
    internal_people = [str(item.person_id) for item in snapshot.objects[0].known_people]
    internal_tasks = [str(item.task_id) for item in snapshot.objects[0].related_tasks]
    assert [item["person_id"] for item in seed["known_people"]] == internal_people[
        :PROACTIVE_MAX_KNOWN_PEOPLE_PER_SEED_OBJECT
    ]
    assert [item["task_id"] for item in seed["related_tasks"]] == internal_tasks[
        :PROACTIVE_MAX_RELATED_TASKS_PER_SEED_OBJECT
    ]
    dumped = json.dumps(seed)
    assert "role_term_id" not in dumped
    assert "canonical_value" not in dumped
    assert "provenance" not in dumped
    assert "role-0-0" in dumped
    assert "Visible task 0" in dumped or any(
        item["title"].startswith("Visible task") for item in seed["related_tasks"]
    )
    assert PROACTIVE_SYSTEM_INSTRUCTIONS.find("role-0-0") == -1


def test_instructions_treat_roles_and_task_actors_as_evidence() -> None:
    text = PROACTIVE_SYSTEM_INSTRUCTIONS
    assert "default decision is NONE" in text
    assert "Silence is a successful result" in text
    assert "not a rank, permission, hierarchy, or automatic priority" in text
    assert "They are not Person roles" in text
    assert "do not deterministically map to" in text
    assert "does not automatically outrank" in text
    assert "not by itself a reason to interrupt" in text
    assert "use get_task_profile before" in text
    assert "Never treat omitted evidence as negative proof" in text
    assert "known Person names" in text
    assert "Person role terms" in text
    assert "role contexts" in text
    assert "related Task titles" in text
    assert "Task actor roles" in text
    assert "директор" not in text
    assert "+50" not in text


def test_role_alone_does_not_force_a_notification(db_session, monkeypatch) -> None:
    _silence(monkeypatch)
    _enable(db_session)
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Ada")
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).attach(
        person.id, normalize_email("ada@example.com")
    )
    PersonRoleService(db_session, BOOTSTRAP_USER_ID).assign(person.id, "наставник", "курс")
    _email(db_session, BOOTSTRAP_USER_ID, "ada@example.com", title="Routine digest")
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    baseline = _notification_ids(db_session)
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 1
    assert "наставник" in provider.last_ui_context
    assert _new_notifications(db_session, baseline) == []


def test_unknown_critical_source_can_win_over_known_role(db_session, monkeypatch) -> None:
    _silence(monkeypatch)
    _enable(db_session)
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Ada")
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).attach(
        person.id, normalize_email("ada@example.com")
    )
    PersonRoleService(db_session, BOOTSTRAP_USER_ID).assign(person.id, "наставник")
    _email(db_session, BOOTSTRAP_USER_ID, "ada@example.com", title="Weekly newsletter")
    critical = _email(
        db_session,
        BOOTSTRAP_USER_ID,
        "unknown@example.com",
        title="CRITICAL production outage",
    )
    provider = _install_provider(
        monkeypatch, ScriptedProactiveProvider(_insight_answer(critical.id))
    )
    baseline = _notification_ids(db_session)
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    notes = _new_notifications(db_session, baseline)
    assert provider.calls == 1
    assert len(notes) == 1
    assert notes[0].source_object_id == critical.id
    assert "does not automatically outrank" in PROACTIVE_SYSTEM_INSTRUCTIONS


def test_known_person_with_active_task_can_be_accepted(db_session, monkeypatch) -> None:
    _silence(monkeypatch)
    _enable(db_session)
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Ada")
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).attach(
        person.id, normalize_email("ada@example.com")
    )
    PersonRoleService(db_session, BOOTSTRAP_USER_ID).assign(person.id, "наставник")
    task = _task(db_session, BOOTSTRAP_USER_ID, "Active confirmed work")
    TaskRelationService(db_session, BOOTSTRAP_USER_ID).add_actor(task.id, person.id, WAITING_ON)
    source = _email(db_session, BOOTSTRAP_USER_ID, "ada@example.com", title="Small status note")
    _install_provider(monkeypatch, ScriptedProactiveProvider(_insight_answer(source.id)))
    baseline = _notification_ids(db_session)
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    notes = _new_notifications(db_session, baseline)
    assert len(notes) == 1
    assert notes[0].source_object_id == source.id


def test_production_code_has_no_role_score_or_known_person_override() -> None:
    backend = Path(__file__).resolve().parents[1] / "app"
    paths = [
        backend / "personal_relevance/models.py",
        backend / "personal_relevance/related_tasks.py",
        backend / "services/personal_relevance_evidence_service.py",
        backend / "services/proactive_review_service.py",
        backend / "proactive/instructions.py",
        backend / "services/task_relation_service.py",
        backend / "services/graph_service.py",
    ]
    forbidden = ("ROLE_SCORE", "role_weights", "known_person_wins", "+50", "студент =")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text


def _silence(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.proactive_review_service.ai_trace_session",
        _noop_trace,
    )


def _person(session: Session, user_id, title: str, email: str):
    people = PersonIdentityService(session, user_id)
    person = people.create_person(title)
    people.attach(person.id, normalize_email(email))
    return person


def _task(session: Session, user_id, title: str, **fields):
    payload = {
        "kind": "task",
        "title": title,
        "origin": USER_ORIGIN,
        "state": fields.pop("state", CONFIRMED_STATE),
        "status": fields.pop("status", "open"),
    }
    payload.update(fields)
    return GraphService(session, user_id).create_object(ObjectCreate(**payload))


def _email(session: Session, user_id, sender: str, *, title: str = "Mail"):
    return GraphService(session, user_id).create_object(
        ObjectCreate(
            kind="email",
            title=title,
            origin="source",
            provider="gmail",
            metadata={"sender": sender},
        )
    )


def _email_recipients(session: Session, user_id, recipients: list[str]):
    return GraphService(session, user_id).create_object(
        ObjectCreate(
            kind="email",
            title="Several people",
            origin="source",
            provider="gmail",
            metadata={"recipients": recipients},
        )
    )


def _edge(session: Session, user_id, source_id, target_id, edge_type: str, *, state: str):
    return GraphService(session, user_id).create_edge(
        EdgeCreate(
            source_id=source_id,
            target_id=target_id,
            type=edge_type,
            origin=USER_ORIGIN,
            state=state,
            confidence=0.8 if state == PROPOSED_STATE else None,
        )
    )


def _one(session: Session, user_id, object_id):
    snapshot = _service(session).build_snapshot(user_id, [object_id])
    return snapshot.objects[0]


def _signature(session: Session, user_id, object_id) -> str:
    snapshot = _service(session).build_snapshot(user_id, [object_id])
    return snapshot.object_evidence_signatures[str(object_id)]
