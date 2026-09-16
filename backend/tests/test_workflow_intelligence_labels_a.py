"""Workflow Intelligence Pass A — canonical graph labels."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_embedding_service
from app.api.schemas import EdgeCreate, ObjectCreate, ObjectUpdate
from app.assistant.session import run_assistant_tool
from app.db.engine import engine
from app.db.models import Edge, ExternalActionAttempt, Job, Object, User
from app.domain.labels import EDGE_TYPE_LABELED_WITH, KIND_LABEL
from app.domain.object_visibility import tombstone_object
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
from app.main import app
from app.mcp.gateway_runner import execute_mcp_tool
from app.proactive.constants import PROACTIVE_READ_TOOL_NAMES
from app.services.context_service import ContextService
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.label_service import LabelService, normalize_label_name
from app.services.object_query_service import ObjectQueryService
from app.services.proactive_review_service import ProactiveReviewService
from app.services.provenance import REJECTED_STATE
from app.tools.registry import PROACTIVE_TOOL_DEFINITIONS
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import ToolError
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides


@pytest.fixture
def labels_client(db_session, auth_headers, fake_embedding_service):
    def override_get_db():
        yield db_session

    apply_embedding_service_overrides(fake_embedding_service)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_embedding_service] = lambda: fake_embedding_service
    with TestClient(app) as raw:
        yield AuthTestClient(raw, auth_headers)
    app.dependency_overrides.clear()


def _svc(session: Session, user_id=BOOTSTRAP_USER_ID) -> LabelService:
    return LabelService(session, user_id)


def _note(session: Session, title: str = "Note") -> Object:
    return GraphService(session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(kind="note", title=title, origin="user")
    )


def test_normalize_trim_case_whitespace_and_nfkc() -> None:
    display, key = normalize_label_name("  Work\t  ")
    assert display == "Work"
    assert key == "work"
    assert normalize_label_name("WORK")[1] == key
    composed = normalize_label_name("Café")[1]
    decomposed = normalize_label_name("Cafe\u0301")[1]
    assert composed == decomposed
    with pytest.raises(ValidationError):
        normalize_label_name("   ")
    with pytest.raises(ValidationError):
        normalize_label_name("x" * 81)


def test_create_is_idempotent_by_normalized_key(db_session) -> None:
    first = _svc(db_session).create_label("Work")
    second = _svc(db_session).create_label(" work ")
    third = _svc(db_session).create_label("WORK")
    assert first.created is True
    assert second.created is False
    assert third.created is False
    assert first.label.id == second.label.id == third.label.id
    labels = list(
        db_session.scalars(
            select(Object).where(Object.user_id == BOOTSTRAP_USER_ID, Object.kind == KIND_LABEL)
        )
    )
    assert len(labels) == 1


def test_list_rename_delete_and_recreate(db_session) -> None:
    service = _svc(db_session)
    created = service.create_label("Teaching")
    listed = service.list_labels()
    assert [item.title for item in listed] == ["Teaching"]
    renamed = service.rename_label(created.label.id, "teaching")
    assert renamed.changed is True
    assert renamed.label.title == "teaching"
    same_key = service.rename_label(created.label.id, "Teaching")
    assert same_key.changed is True
    other = service.create_label("Research")
    with pytest.raises(ConflictError):
        service.rename_label(other.label.id, "teaching")
    deleted = service.delete_label(created.label.id)
    assert deleted.changed is True
    again = service.delete_label(created.label.id)
    assert again.changed is False
    reborn = service.create_label("Teaching")
    assert reborn.created is True
    assert reborn.label.id != created.label.id


def test_assignment_idempotent_and_constraints(db_session) -> None:
    service = _svc(db_session)
    label = service.create_label("ADH").label
    note = _note(db_session)
    first = service.assign_label(note.id, label.id)
    second = service.assign_label(note.id, label.id)
    assert first.created is True
    assert second.created is False
    assert first.edge.id == second.edge.id
    edges = list(
        db_session.scalars(
            select(Edge).where(
                Edge.user_id == BOOTSTRAP_USER_ID,
                Edge.type == EDGE_TYPE_LABELED_WITH,
                Edge.state != REJECTED_STATE,
            )
        )
    )
    assert len(edges) == 1
    with pytest.raises(ValidationError):
        service.assign_label(label.id, label.id)
    other_user = uuid.uuid4()
    db_session.add(User(id=other_user, display_name="foreign-labels"))
    db_session.flush()
    foreign = LabelService(db_session, other_user).create_label("Secret").label
    with pytest.raises(NotFoundError):
        service.assign_label(note.id, foreign.id)
    with pytest.raises(NotFoundError):
        LabelService(db_session, other_user).assign_label(note.id, foreign.id)
    removed = service.remove_label(note.id, label.id)
    assert removed.changed is True
    again = service.remove_label(note.id, label.id)
    assert again.changed is False
    tombstone_object(note)
    db_session.flush()
    other = _note(db_session, "Other")
    with pytest.raises(ValidationError):
        service.assign_label(note.id, label.id)
    service.delete_label(label.id)
    with pytest.raises(ValidationError):
        service.assign_label(other.id, label.id)


def test_rejected_assignment_is_not_active(db_session) -> None:
    service = _svc(db_session)
    label = service.create_label("Customer").label
    note = _note(db_session)
    assigned = service.assign_label(note.id, label.id)
    assigned.edge.state = REJECTED_STATE
    db_session.flush()
    names = [item.title for item in service.get_object_labels(note.id)]
    assert names == []
    reassigned = service.assign_label(note.id, label.id)
    assert reassigned.created is True


def test_generic_paths_fail_closed(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    with pytest.raises(ValidationError, match="LabelService"):
        graph.create_object(ObjectCreate(kind=KIND_LABEL, title="Work", origin="user"))
    note = _note(db_session)
    label = _svc(db_session).create_label("Work").label
    with pytest.raises(ValidationError, match="assign_label"):
        graph.create_edge(
            EdgeCreate(
                source_id=note.id,
                target_id=label.id,
                type=EDGE_TYPE_LABELED_WITH,
                origin="user",
                state="confirmed",
            )
        )
    from app.services.domain_tool_service import DomainToolService
    from app.tools.schemas import LinkObjectsInput, RemoveRelationInput

    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, None)
    with pytest.raises(ToolError, match="assign_label"):
        tools.link_objects(
            LinkObjectsInput(
                source_id=note.id,
                target_id=label.id,
                relation_type=EDGE_TYPE_LABELED_WITH,
                confidence=0.9,
            )
        )
    assigned = _svc(db_session).assign_label(note.id, label.id)
    with pytest.raises(ToolError, match="remove_label"):
        tools.remove_relation(RemoveRelationInput(edge_id=assigned.edge.id))
    with pytest.raises(ValidationError, match="remove_label"):
        graph.set_edge_state(assigned.edge.id, REJECTED_STATE)
    removed = _svc(db_session).remove_label(note.id, label.id)
    assert removed.changed is True
    repeated = _svc(db_session).remove_label(note.id, label.id)
    assert repeated.changed is False


def test_generic_object_patch_cannot_bypass_label_service(labels_client, db_session) -> None:
    from unittest.mock import MagicMock

    note = labels_client.post("/objects", json={"kind": "note", "title": "Keep", "origin": "user"})
    assert note.status_code == 201
    note_id = note.json()["id"]
    patched = labels_client.patch(f"/objects/{note_id}", json={"kind": "label"})
    assert patched.status_code == 422
    remaining = labels_client.get(f"/objects/{note_id}")
    assert remaining.status_code == 200
    assert remaining.json()["kind"] == "note"
    created = labels_client.post("/labels", json={"name": "Course"})
    label_id = created.json()["label"]["id"]
    exact = labels_client.get(f"/objects/{label_id}")
    assert exact.status_code == 200
    assert exact.json()["kind"] == "label"
    title_patch = labels_client.patch(f"/objects/{label_id}", json={"title": "Hacked"})
    assert title_patch.status_code == 422
    metadata_patch = labels_client.patch(
        f"/objects/{label_id}", json={"metadata": {"label_key": "hacked"}, "kind": "note"}
    )
    assert metadata_patch.status_code == 422
    still = labels_client.get(f"/objects/{label_id}")
    assert still.json()["title"] == "Course"
    assert still.json()["metadata"]["label_key"] == "course"
    renamed = labels_client.patch(f"/labels/{label_id}", json={"name": "Courses"})
    assert renamed.status_code == 200
    assert renamed.json()["changed"] is True
    assert renamed.json()["label"]["title"] == "Courses"
    embed = MagicMock()
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, embed)
    with pytest.raises(ValidationError, match="LabelService"):
        graph.update_object(uuid.UUID(label_id), ObjectUpdate(title="Nope"))
    with pytest.raises(ValidationError, match="LabelService"):
        graph.update_object(uuid.UUID(note_id), ObjectUpdate(kind="label"))
    embed.embed.assert_not_called()


def test_list_labels_sql_limit_is_deterministic(db_session) -> None:
    service = _svc(db_session)
    names = ["Zeta", "Alpha", "Mu", "Beta", "Gamma"]
    created = {name: service.create_label(name).label for name in names}
    listed = service.list_labels(limit=3)
    assert [item.title for item in listed] == ["Alpha", "Beta", "Gamma"]
    assert len(listed) == 3
    assert [item.id for item in listed] == [created["Alpha"].id, created["Beta"].id, created["Gamma"].id]


def test_assistant_list_labels_is_bounded_and_collects_seen_ids(db_session) -> None:
    from app.assistant.constants import MAX_ASSISTANT_LIST_RESULTS, MAX_ASSISTANT_TOOL_OUTPUT_CHARS
    from app.assistant.reference_ids import collect_seen_object_ids_from_bounded_tool
    from app.assistant.tool_output import serialize_tool_output_for_assistant
    from app.services.domain_tool_service import DomainToolService
    from app.tools.schemas import ListLabelsInput

    service = _svc(db_session)
    created = []
    for index in range(MAX_ASSISTANT_LIST_RESULTS + 8):
        created.append(service.create_label(f"Label {index:02d}").label)
    raw = DomainToolService(db_session, BOOTSTRAP_USER_ID, None).list_labels(
        ListLabelsInput(limit=100)
    ).model_dump(mode="json")
    assert len(raw["labels"]) > MAX_ASSISTANT_LIST_RESULTS
    model_out = serialize_tool_output_for_assistant("list_labels", raw)
    payload = model_out.model_visible_payload
    assert "preview_chars" not in payload
    assert payload.get("truncated") is True
    visible = payload["labels"]
    assert 0 < len(visible) <= MAX_ASSISTANT_LIST_RESULTS
    assert [row["title"] for row in visible] == [item.title for item in created[: len(visible)]]
    assert "created_at" not in visible[0]
    assert "updated_at" not in visible[0]
    assert len(model_out.model_output_json) <= MAX_ASSISTANT_TOOL_OUTPUT_CHARS
    seen = collect_seen_object_ids_from_bounded_tool("list_labels", payload)
    assert seen == [uuid.UUID(str(row["id"])) for row in visible]
    assert created[0].id in seen
    assert created[-1].id not in seen


def test_query_objects_label_filters(db_session) -> None:
    service = _svc(db_session)
    label_a = service.create_label("A").label
    label_b = service.create_label("B").label
    only_a = _note(db_session, "only-a")
    only_b = _note(db_session, "only-b")
    both = _note(db_session, "both")
    _note(db_session, "none")
    service.assign_label(only_a.id, label_a.id)
    service.assign_label(only_b.id, label_b.id)
    service.assign_label(both.id, label_a.id)
    service.assign_label(both.id, label_b.id)
    query = ObjectQueryService(db_session, BOOTSTRAP_USER_ID)
    all_a = query.query(kinds=["note"], label_ids=[label_a.id], label_match="all", sort_by="title", sort_order="asc")
    assert [obj.title for obj in all_a] == ["both", "only-a"]
    all_ab = query.query(
        kinds=["note"],
        label_ids=[label_a.id, label_b.id],
        label_match="all",
        sort_by="title",
        sort_order="asc",
    )
    assert [obj.title for obj in all_ab] == ["both"]
    any_ab = query.query(
        kinds=["note"],
        label_ids=[label_a.id, label_b.id],
        label_match="any",
        sort_by="title",
        sort_order="asc",
        limit=10,
    )
    assert [obj.title for obj in any_ab] == ["both", "only-a", "only-b"]
    unlabeled = query.query(kinds=["note"], sort_by="title", sort_order="asc", limit=50)
    assert {obj.kind for obj in unlabeled} == {"note"}
    with pytest.raises(ValidationError):
        query.query(label_ids=[uuid.uuid4()])
    service.delete_label(label_a.id)
    with pytest.raises(ValidationError):
        query.query(label_ids=[label_a.id])


def test_neighbors_and_context_hide_tombstoned_label(db_session, fake_embedding_service) -> None:
    service = _svc(db_session)
    label = service.create_label("Important").label
    note = _note(db_session)
    service.assign_label(note.id, label.id)
    neighbors = GraphService(db_session, BOOTSTRAP_USER_ID).get_neighbors(note.id)
    assert any(edge.type == EDGE_TYPE_LABELED_WITH and neighbor.id == label.id for neighbor, edge, _ in neighbors)
    context = ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service).build_context(object_id=note.id)
    assert any(item.object_id == label.id for item in context.items)
    service.delete_label(label.id)
    neighbors_after = GraphService(db_session, BOOTSTRAP_USER_ID).get_neighbors(note.id)
    assert all(neighbor.id != label.id for neighbor, _edge, _ in neighbors_after)


def test_rest_crud_and_inbox_exclusion(labels_client, db_session) -> None:
    created = labels_client.post("/labels", json={"name": "Course"})
    assert created.status_code == 200
    assert created.json()["created"] is True
    label_id = created.json()["label"]["id"]
    listed = labels_client.get("/labels")
    assert listed.status_code == 200
    assert any(item["id"] == label_id for item in listed.json()["labels"])
    inbox = labels_client.get("/inbox")
    assert inbox.status_code == 200
    ids = {row["id"] for row in inbox.json()["recent_source_objects"]}
    assert label_id not in ids
    generic = labels_client.post("/objects", json={"kind": "label", "title": "Nope", "origin": "user"})
    assert generic.status_code == 422


def test_interactive_mutations_require_approval(db_session, fake_embedding_service) -> None:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="labels-policy"))
    db_session.flush()
    before = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.user_id == user_id, Object.kind == KIND_LABEL)
    )
    result = run_assistant_tool(user_id, "create_label", {"name": "Work"})
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    after = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.user_id == user_id, Object.kind == KIND_LABEL)
    )
    assert after == before
    # Taxonomy mutations stay approval-controlled. assign_label/remove_label are
    # ANNOTATE since Workflow Intelligence Pass C (see test_workflow_intelligence_relevance_c).
    for name, arguments in (
        ("rename_label", {"label_id": str(uuid.uuid4()), "name": "X"}),
        ("delete_label", {"label_id": str(uuid.uuid4())}),
    ):
        staged = run_assistant_tool(user_id, name, arguments)
        assert staged.status == ToolExecutionStatus.APPROVAL_REQUIRED


def test_approved_create_label_mutates_once(db_session, fake_embedding_service) -> None:
    from app.services.domain_tool_service import DomainToolService
    from app.services.domain_write_mode import DomainWriteMode
    from app.tools.execution_context import ExecutionContext
    from app.tools.gateway import ToolExecutionGateway

    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="approved-label"))
    db_session.flush()
    tools = DomainToolService(
        db_session,
        user_id,
        fake_embedding_service,
        write_mode=DomainWriteMode.APPROVED_CONFIRMED,
    )
    result = ToolExecutionGateway().execute(
        tools,
        "create_label",
        {"name": "Work"},
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert result.success is True
    labels = list(
        db_session.scalars(select(Object).where(Object.user_id == user_id, Object.kind == KIND_LABEL))
    )
    assert len(labels) == 1
    assert labels[0].title == "Work"
    again = ToolExecutionGateway().execute(
        tools,
        "create_label",
        {"name": " work "},
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert again.success is True
    assert again.raw_output.created is False
    labels_after = list(
        db_session.scalars(select(Object).where(Object.user_id == user_id, Object.kind == KIND_LABEL))
    )
    assert len(labels_after) == 1


def test_mcp_list_allowed_mutations_fail_closed(db_session, monkeypatch) -> None:
    from contextlib import contextmanager

    from app.mcp import gateway_runner
    from app.services.domain_tool_service import DomainToolService

    @contextmanager
    def fake_session():
        yield DomainToolService(db_session, BOOTSTRAP_USER_ID, None)

    monkeypatch.setattr(gateway_runner, "tool_session", fake_session)
    listed = execute_mcp_tool("list_labels", {"limit": 20})
    assert listed.labels == []
    with pytest.raises(ToolError, match="requires approval"):
        execute_mcp_tool("create_label", {"name": "Work"})


def test_proactive_allowlist_unchanged() -> None:
    assert tuple(item["name"] for item in PROACTIVE_TOOL_DEFINITIONS) == PROACTIVE_READ_TOOL_NAMES


def test_label_create_does_not_trip_proactive_gate(db_session, monkeypatch) -> None:
    from tests.test_proactive_secretary_c import (
        ScriptedProactiveProvider,
        _enable,
        _install_provider,
        _none_answer,
    )

    _enable(db_session)
    _svc(db_session).create_label("Bookkeeping")
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    monkeypatch.setattr(
        "app.services.proactive_review_service.ai_trace_session",
        lambda *args, **kwargs: __import__("contextlib").nullcontext(),
    )
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(
        {"window_start": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}
    )
    assert provider.calls == 0


def test_no_external_attempts_or_embed_jobs(db_session) -> None:
    before_plans = db_session.scalar(select(func.count()).select_from(ExternalActionAttempt))
    before_jobs = db_session.scalar(
        select(func.count()).select_from(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)
    )
    service = _svc(db_session)
    label = service.create_label("Personal").label
    note = _note(db_session)
    service.assign_label(note.id, label.id)
    service.rename_label(label.id, "personal")
    assert db_session.scalar(select(func.count()).select_from(ExternalActionAttempt)) == before_plans
    after_jobs = db_session.scalar(
        select(func.count()).select_from(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)
    )
    assert after_jobs == before_jobs


def test_concurrent_create_same_key() -> None:
    user_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(User(id=user_id, display_name=f"labels-{user_id}"))
        session.commit()
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            with Session(engine) as session:
                barrier.wait(timeout=10)
                LabelService(session, user_id).create_label("Work")
                session.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    try:
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        assert errors == []
        with Session(engine) as session:
            labels = list(
                session.scalars(
                    select(Object).where(
                        Object.user_id == user_id,
                        Object.kind == KIND_LABEL,
                        Object.deleted_at.is_(None),
                    )
                )
            )
            assert len(labels) == 1
    finally:
        with Session(engine) as session:
            session.execute(delete(Edge).where(Edge.user_id == user_id))
            session.execute(delete(Object).where(Object.user_id == user_id))
            session.execute(delete(User).where(User.id == user_id))
            session.commit()


def test_concurrent_assign_same_pair() -> None:
    user_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(User(id=user_id, display_name=f"labels-{user_id}"))
        session.flush()
        label = LabelService(session, user_id).create_label("ADH").label
        note = GraphService(session, user_id).create_object(
            ObjectCreate(kind="note", title="n", origin="user")
        )
        session.commit()
        label_id, note_id = label.id, note.id
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            with Session(engine) as session:
                barrier.wait(timeout=10)
                LabelService(session, user_id).assign_label(note_id, label_id)
                session.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    try:
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        assert errors == []
        with Session(engine) as session:
            edges = list(
                session.scalars(
                    select(Edge).where(
                        Edge.user_id == user_id,
                        Edge.type == EDGE_TYPE_LABELED_WITH,
                        Edge.state != REJECTED_STATE,
                    )
                )
            )
            assert len(edges) == 1
    finally:
        with Session(engine) as session:
            session.execute(delete(Edge).where(Edge.user_id == user_id))
            session.execute(delete(Object).where(Object.user_id == user_id))
            session.execute(delete(User).where(User.id == user_id))
            session.commit()


def test_concurrent_rename_collision() -> None:
    user_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(User(id=user_id, display_name=f"labels-{user_id}"))
        session.flush()
        first = LabelService(session, user_id).create_label("Alpha").label.id
        second = LabelService(session, user_id).create_label("Beta").label.id
        session.commit()
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker(label_id: uuid.UUID) -> None:
        try:
            with Session(engine) as session:
                barrier.wait(timeout=10)
                LabelService(session, user_id).rename_label(label_id, "Gamma")
                session.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    try:
        threads = [
            threading.Thread(target=worker, args=(first,)),
            threading.Thread(target=worker, args=(second,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        with Session(engine) as session:
            active = list(
                session.scalars(
                    select(Object).where(
                        Object.user_id == user_id,
                        Object.kind == KIND_LABEL,
                        Object.deleted_at.is_(None),
                    )
                )
            )
            keys = [item.metadata_.get("label_key") for item in active]
            assert keys.count("gamma") == 1
        assert any(isinstance(exc, ConflictError) for exc in errors) or len(errors) == 1
    finally:
        with Session(engine) as session:
            session.execute(delete(Object).where(Object.user_id == user_id))
            session.execute(delete(User).where(User.id == user_id))
            session.commit()
