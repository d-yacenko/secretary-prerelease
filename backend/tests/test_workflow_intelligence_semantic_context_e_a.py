"""Workflow Intelligence Pass E-A — personal semantic context and label semantics."""

from __future__ import annotations

import threading
import time
import uuid
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.engine import engine
from app.db.models import (
    AITraceEvent,
    ExternalActionAttempt,
    Notification,
    Object,
    PendingActionPlan,
    User,
    UserSemanticContext,
    UserSettings,
)
from app.domain.labels import LABEL_DESCRIPTION_MAX_CHARS
from app.llm.auto_label_classifier import FakeAutoLabelClassifier, classifier_request_payload
from app.main import app
from app.services.auto_label_constants import (
    AUTO_LABEL_MAX_IDENTITY_ITEM_CHARS,
    AUTO_LABEL_MAX_IDENTITY_ORGANIZATIONS,
    AUTO_LABEL_MAX_IDENTITY_ROLES,
    MAX_PERSONAL_SEMANTIC_CONTEXT_CHARS,
)
from app.services.auto_label_models import (
    AutoLabelAssignment,
    AutoLabelCandidate,
    AutoLabelObjectInput,
)
from app.services.auto_label_service import (
    AutoLabelService,
    enqueue_auto_label_object,
    load_auto_label_state,
)
from app.services.domain_tool_service import DomainToolService
from app.services.label_service import LabelService
from app.services.personal_semantic_context_service import (
    PersonalSemanticContext,
    PersonalSemanticContextService,
    bound_identity_semantic_projection,
)
from app.services.user_identity_context_service import UserIdentityProfileService
from app.services.user_serialization_gate import lock_user_serialization_row
from app.tools.schemas import CreateLabelCanonicalInput, ListLabelsInput
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient
from tests.test_workflow_intelligence_auto_label_d import (
    _auto_label_jobs,
    _auto_label_jobs_for,
    _count_active_edges,
    _enable_auto_label,
    _isolated_auto_label_user,
    _labels,
    _note,
    _seed_note_and_label,
)


class _SessionProxy:
    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(self._session, name)


@pytest.fixture(autouse=True)
def _share_test_session_for_traces(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ai_audit.context.SessionLocal", lambda: _SessionProxy(db_session)
    )


@pytest.fixture
def ea_client(db_session, auth_headers):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as raw:
        yield AuthTestClient(raw, auth_headers)
    app.dependency_overrides.clear()


def _identity_text(
    *,
    name: str = "Alice",
    email: str = "alice@example.com",
    roles: list[str] | None = None,
    orgs: list[str] | None = None,
) -> str:
    role_lines = "\n".join(f"- {item}" for item in (roles or ["Преподаватель"]))
    org_lines = "\n".join(f"- {item}" for item in (orgs or ["МГУ"]))
    return (
        f"Имя: {name}\n"
        f"Email:\n- {email}\n"
        f"Должности:\n{role_lines}\n"
        f"Организации:\n{org_lines}\n"
    )


def test_migration_0033_from_0032() -> None:
    versions = sorted(
        path.name
        for path in (Path(__file__).resolve().parents[1] / "alembic" / "versions").glob("*.py")
        if path.name[0].isdigit()
    )
    assert any(name.startswith("0032") for name in versions)
    assert any(name.startswith("0033") for name in versions)
    assert versions[-1].startswith("0040")
    module_path = Path(__file__).resolve().parents[1] / "alembic/versions/0033_user_semantic_contexts.py"
    text_src = module_path.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "0032"' in text_src
    assert "user_semantic_contexts" in text_src


def test_semantic_context_table_and_default_empty(db_session, ea_client) -> None:
    inspector = inspect(db_session.bind)
    assert "user_semantic_contexts" in inspector.get_table_names()
    response = ea_client.get("/me/semantic-context")
    assert response.status_code == 200
    assert response.json() == {"context_text": ""}
    assert db_session.get(UserSemanticContext, BOOTSTRAP_USER_ID) is None


def test_semantic_context_put_read_clear_bounds(ea_client, db_session) -> None:
    written = ea_client.put(
        "/me/semantic-context",
        json={"context_text": "Работа: Acme\r\nНаука: NLP  "},
    )
    assert written.status_code == 200
    assert written.json()["context_text"] == "Работа: Acme\nНаука: NLP"
    assert ea_client.get("/me/semantic-context").json()["context_text"] == "Работа: Acme\nНаука: NLP"
    cleared = ea_client.put("/me/semantic-context", json={"context_text": "   "})
    assert cleared.status_code == 200
    assert cleared.json()["context_text"] == ""
    too_long = "x" * (MAX_PERSONAL_SEMANTIC_CONTEXT_CHARS + 1)
    rejected = ea_client.put("/me/semantic-context", json={"context_text": too_long})
    assert rejected.status_code == 422


def test_semantic_context_write_uses_serialization_gate() -> None:
    user_sql = str(
        select(User)
        .where(User.id == BOOTSTRAP_USER_ID)
        .with_for_update(key_share=True)
        .compile(dialect=postgresql.dialect())
    )
    assert "FOR NO KEY UPDATE" in user_sql
    assert lock_user_serialization_row.__module__.endswith("user_serialization_gate")


def test_semantic_context_edit_does_not_enqueue_historical_jobs(
    db_session, ea_client
) -> None:
    _enable_auto_label(db_session)
    _labels(db_session).create_label("Work")
    _note(db_session, "Old")
    before = len(_auto_label_jobs(db_session))
    ea_client.put("/me/semantic-context", json={"context_text": "Работа: Acme"})
    UserIdentityProfileService.build(db_session).upsert_profile(
        BOOTSTRAP_USER_ID, _identity_text()
    )
    _labels(db_session).update_label(
        _labels(db_session).list_labels()[0].id,
        description="commercial work",
        description_set=True,
    )
    assert len(_auto_label_jobs(db_session)) == before


def test_label_description_create_read_update_clear_bound(ea_client) -> None:
    created = ea_client.post(
        "/labels",
        json={"name": "Работа", "description": "  коммерция, продукты  "},
    )
    assert created.status_code == 200
    label = created.json()["label"]
    assert label["description"] == "коммерция, продукты"
    listed = ea_client.get("/labels").json()["labels"]
    assert listed[0]["description"] == "коммерция, продукты"
    patched = ea_client.patch(
        f"/labels/{label['id']}", json={"description": "стратегия"}
    )
    assert patched.status_code == 200
    assert patched.json()["label"]["description"] == "стратегия"
    cleared = ea_client.patch(f"/labels/{label['id']}", json={"description": ""})
    assert cleared.json()["label"]["description"] is None
    empty = ea_client.patch(f"/labels/{label['id']}", json={})
    assert empty.status_code == 422
    too_long = ea_client.patch(
        f"/labels/{label['id']}",
        json={"description": "x" * (LABEL_DESCRIPTION_MAX_CHARS + 1)},
    )
    assert too_long.status_code == 422


def test_name_only_label_api_and_tool_remain_valid(ea_client, db_session) -> None:
    created = ea_client.post("/labels", json={"name": "Наука"})
    assert created.status_code == 200
    assert created.json()["label"]["description"] is None
    label_id = created.json()["label"]["id"]
    renamed = ea_client.patch(f"/labels/{label_id}", json={"name": "Science"})
    assert renamed.status_code == 200
    assert renamed.json()["label"]["title"] == "Science"
    listed = DomainToolService(db_session, BOOTSTRAP_USER_ID, None).list_labels(
        ListLabelsInput(limit=20)
    )
    titles = [item.title for item in listed.labels]
    assert "Science" in titles
    assert all(item.description is None for item in listed.labels)
    created_tool = DomainToolService(db_session, BOOTSTRAP_USER_ID, None).create_label(
        CreateLabelCanonicalInput(name="Курс")
    )
    assert created_tool.created is True
    assert created_tool.label.description is None


def test_object_labels_include_optional_description(ea_client, db_session) -> None:
    label = ea_client.post(
        "/labels", json={"name": "Work", "description": "office"}
    ).json()["label"]
    note = _note(db_session)
    assigned = ea_client.post(f"/objects/{note.id}/labels/{label['id']}")
    assert assigned.status_code == 200
    rows = ea_client.get(f"/objects/{note.id}/labels").json()["labels"]
    assert rows[0]["description"] == "office"


def test_classifier_receives_descriptions_context_roles_not_identifiers(
    db_session,
) -> None:
    _enable_auto_label(db_session)
    PersonalSemanticContextService.build(db_session).upsert_context(
        BOOTSTRAP_USER_ID, "Работа: Acme products"
    )
    UserIdentityProfileService.build(db_session).upsert_profile(
        BOOTSTRAP_USER_ID,
        _identity_text(
            name="Secret Name",
            email="hidden@example.com",
            roles=["CTO"],
            orgs=["Acme"],
        ),
    )
    label = _labels(db_session).create_label(
        "Работа", description="commercial work"
    ).label
    note = _note(db_session, body="quarterly product review")
    fake = FakeAutoLabelClassifier(
        assignments=[
            AutoLabelAssignment(label_id=label.id, confidence=0.99, rationale="work")
        ]
    )
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(
        _auto_label_jobs(db_session)[0].payload
    )
    request = fake.last_request
    assert request is not None
    assert request["labels"][0]["description"] == "commercial work"
    assert request["personal_semantic_context"]["context_text"] == "Работа: Acme products"
    assert request["personal_semantic_context"]["roles"] == ["CTO"]
    assert request["personal_semantic_context"]["organizations"] == ["Acme"]
    blob = str(request)
    assert "Secret Name" not in blob
    assert "hidden@example.com" not in blob
    assert "google:" not in blob
    assert "preferred_name" not in blob
    assert "aliases" not in blob
    payload = _auto_label_jobs(db_session)[0].payload
    assert "context_text" not in payload
    assert "roles" not in payload
    assert "commercial work" not in str(payload)
    assert "semantic_context_signature" in payload


def test_semantic_and_identity_and_description_change_signatures(db_session) -> None:
    _enable_auto_label(db_session)
    label = _labels(db_session).create_label("Work").label
    note = _note(db_session, body="item")
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    first = load_auto_label_state(db_session, BOOTSTRAP_USER_ID, note.id)
    assert first is not None
    PersonalSemanticContextService.build(db_session).upsert_context(
        BOOTSTRAP_USER_ID, "Наука: NLP"
    )
    after_context = load_auto_label_state(db_session, BOOTSTRAP_USER_ID, note.id)
    assert after_context is not None
    assert after_context.classification_sig != first.classification_sig
    assert after_context.semantic_context_sig != first.semantic_context_sig
    UserIdentityProfileService.build(db_session).upsert_profile(
        BOOTSTRAP_USER_ID, _identity_text(roles=["Teacher"], orgs=["MSU"])
    )
    after_roles = load_auto_label_state(db_session, BOOTSTRAP_USER_ID, note.id)
    assert after_roles is not None
    assert after_roles.classification_sig != after_context.classification_sig
    UserIdentityProfileService.build(db_session).upsert_profile(
        BOOTSTRAP_USER_ID,
        _identity_text(name="Bob", email="bob@x.com", roles=["Teacher"], orgs=["MSU"]),
    )
    after_name = load_auto_label_state(db_session, BOOTSTRAP_USER_ID, note.id)
    assert after_name is not None
    assert after_name.semantic_context_sig == after_roles.semantic_context_sig
    assert after_name.classification_sig == after_roles.classification_sig
    _labels(db_session).update_label(
        label.id, description="when to use", description_set=True
    )
    after_desc = load_auto_label_state(db_session, BOOTSTRAP_USER_ID, note.id)
    assert after_desc is not None
    assert after_desc.vocabulary_sig != after_name.vocabulary_sig
    assert after_desc.classification_sig != after_name.classification_sig


def test_identity_projection_bounds_independent_of_profile_parser() -> None:
    roles = [f"role-{index}-{'y' * 200}" for index in range(20)]
    orgs = [f"org-{index}-{'z' * 200}" for index in range(20)]
    bounded_roles, bounded_orgs = bound_identity_semantic_projection(roles, orgs)
    assert len(bounded_roles) == AUTO_LABEL_MAX_IDENTITY_ROLES
    assert len(bounded_orgs) == AUTO_LABEL_MAX_IDENTITY_ORGANIZATIONS
    assert all(len(item) <= AUTO_LABEL_MAX_IDENTITY_ITEM_CHARS for item in bounded_roles)
    extra_role = list(bounded_roles) + ["ignored-13"]
    again, _ = bound_identity_semantic_projection(extra_role, [])
    assert again == bounded_roles


def _stale_during_classify(mutator) -> None:
    with _isolated_auto_label_user() as user_id:
        _note_id, label_id, payload = _seed_note_and_label(user_id)

        def after_classify() -> None:
            with Session(engine) as other:
                mutator(other, user_id, label_id)
                other.commit()

        fake = FakeAutoLabelClassifier(
            assignments=[
                AutoLabelAssignment(label_id=label_id, confidence=0.99, rationale="stale")
            ]
        )
        with patch(
            "app.services.auto_label_service.ai_trace_session",
            lambda *args, **kwargs: nullcontext(),
        ), Session(engine) as worker:
            AutoLabelService(
                worker, user_id, classifier=fake, after_classify=after_classify
            ).run_job(payload)
            worker.commit()
        with Session(engine) as session:
            assert _count_active_edges(session, user_id) == 0
            jobs = _auto_label_jobs_for(session, user_id)
            current = {
                job.payload["classification_signature"] for job in jobs if job.status != "failed"
            }
            assert payload["classification_signature"] in current
            assert len(current) == 2


def test_semantic_context_change_during_classifier_requeues() -> None:
    def mutate(session: Session, user_id: UUID, _label_id: UUID) -> None:
        PersonalSemanticContextService.build(session).upsert_context(user_id, "new context")

    _stale_during_classify(mutate)


def test_roles_org_change_during_classifier_requeues() -> None:
    def mutate(session: Session, user_id: UUID, _label_id: UUID) -> None:
        UserIdentityProfileService.build(session).upsert_profile(
            user_id, _identity_text(roles=["Dean"], orgs=["ITMO"])
        )

    _stale_during_classify(mutate)


def test_label_description_change_during_classifier_requeues() -> None:
    def mutate(session: Session, user_id: UUID, label_id: UUID) -> None:
        LabelService(session, user_id).update_label(
            label_id, description="updated meaning", description_set=True
        )

    _stale_during_classify(mutate)


def test_semantic_mutation_after_authority_serializes_behind_worker() -> None:
    with _isolated_auto_label_user() as user_id:
        _note_id, label_id, payload = _seed_note_and_label(user_id)
        saved = threading.Event()
        started = threading.Event()
        errors: list[BaseException] = []
        racer_thread: list[threading.Thread] = []

        def racer() -> None:
            try:
                started.set()
                with Session(engine) as other:
                    PersonalSemanticContextService.build(other).upsert_context(
                        user_id, "blocked until commit"
                    )
                    other.commit()
                saved.set()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def after_authority() -> None:
            thread = threading.Thread(target=racer)
            racer_thread.append(thread)
            thread.start()
            assert started.wait(timeout=5)
            time.sleep(0.2)
            assert not saved.is_set()

        fake = FakeAutoLabelClassifier(
            assignments=[
                AutoLabelAssignment(label_id=label_id, confidence=0.99, rationale="locked")
            ]
        )
        with patch(
            "app.services.auto_label_service.ai_trace_session",
            lambda *args, **kwargs: nullcontext(),
        ), Session(engine) as worker:
            AutoLabelService(
                worker, user_id, classifier=fake, after_authority=after_authority
            ).run_job(payload)
            assert not saved.is_set()
            worker.commit()
        assert racer_thread
        racer_thread[0].join(timeout=15)
        assert saved.is_set()
        assert errors == []
        with Session(engine) as session:
            assert _count_active_edges(session, user_id) == 1


def test_disable_still_wins_with_semantic_inputs() -> None:
    with _isolated_auto_label_user() as user_id:
        _note_id, label_id, payload = _seed_note_and_label(user_id)
        with Session(engine) as session:
            PersonalSemanticContextService.build(session).upsert_context(
                user_id, "context"
            )
            session.commit()

        def after_classify() -> None:
            with Session(engine) as other:
                settings = other.get(UserSettings, user_id)
                assert settings is not None
                settings.auto_label_enabled = False
                other.commit()

        fake = FakeAutoLabelClassifier(
            assignments=[
                AutoLabelAssignment(label_id=label_id, confidence=0.99, rationale="late")
            ]
        )
        with patch(
            "app.services.auto_label_service.ai_trace_session",
            lambda *args, **kwargs: nullcontext(),
        ), Session(engine) as worker:
            AutoLabelService(
                worker, user_id, classifier=fake, after_classify=after_classify
            ).run_job(payload)
            worker.commit()
        with Session(engine) as session:
            assert _count_active_edges(session, user_id) == 0


def test_no_side_effects_from_semantic_writes(db_session, ea_client) -> None:
    pap = db_session.scalar(select(func.count()).select_from(PendingActionPlan)) or 0
    eaa = db_session.scalar(select(func.count()).select_from(ExternalActionAttempt)) or 0
    notes = db_session.scalar(select(func.count()).select_from(Notification)) or 0
    tasks = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.kind == "task")
    ) or 0
    ea_client.put("/me/semantic-context", json={"context_text": "x"})
    ea_client.put("/me/identity", json={"profile_text": _identity_text()})
    assert (db_session.scalar(select(func.count()).select_from(PendingActionPlan)) or 0) == pap
    assert (
        db_session.scalar(select(func.count()).select_from(ExternalActionAttempt)) or 0
    ) == eaa
    assert (db_session.scalar(select(func.count()).select_from(Notification)) or 0) == notes
    assert (
        db_session.scalar(select(func.count()).select_from(Object).where(Object.kind == "task"))
        or 0
    ) == tasks
    settings = db_session.get(UserSettings, BOOTSTRAP_USER_ID)
    if settings is not None:
        assert settings.proactive_enabled is False


def test_classifier_request_payload_separates_data() -> None:
    personal = PersonalSemanticContext(
        context_text="Работа: Acme",
        roles=("CTO",),
        organizations=("Acme",),
    )
    payload = classifier_request_payload(
        obj=AutoLabelObjectInput(
            object_id=uuid.uuid4(),
            kind="note",
            title="t",
            provider=None,
            content="c",
            content_source="body",
        ),
        candidates=[
            AutoLabelCandidate(label_id=uuid.uuid4(), title="Work", description="office")
        ],
        personal=personal,
    )
    assert "personal_semantic_context" in payload
    assert payload["labels"][0]["description"] == "office"


def test_audit_result_does_not_store_raw_context(db_session) -> None:
    from app.ai_audit.context import set_current_job_id

    _enable_auto_label(db_session)
    PersonalSemanticContextService.build(db_session).upsert_context(
        BOOTSTRAP_USER_ID, "secret-context-token"
    )
    label = _labels(db_session).create_label("Work").label
    note = _note(db_session, body="work")
    fake = FakeAutoLabelClassifier(
        assignments=[
            AutoLabelAssignment(label_id=label.id, confidence=0.99, rationale="work")
        ]
    )
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    job = _auto_label_jobs(db_session)[0]
    token = set_current_job_id(job.id)
    try:
        AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(job.payload)
    finally:
        from app.ai_audit.context import reset_current_job_id

        reset_current_job_id(token)
    events = list(db_session.scalars(select(AITraceEvent)))
    result_events = [item for item in events if item.event_type == "auto_label_result"]
    assert result_events
    meta = result_events[-1].metadata_ or {}
    assert "secret-context-token" not in str(meta)
    assert meta["semantic_context_char_count"] == len("secret-context-token")
