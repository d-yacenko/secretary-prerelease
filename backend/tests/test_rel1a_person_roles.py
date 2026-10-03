"""REL1A emergent Person role vocabulary and manual assignments."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.orm import Session

from alembic import command
from app.api.schemas import ObjectCreate
from app.db.engine import engine
from app.db.models import (
    Edge,
    Object,
    PersonIdentity,
    PersonIdentityEvidence,
    PersonRoleAssignment,
    PersonRoleTerm,
    User,
)
from app.domain.object_visibility import tombstone_object
from app.main import app
from app.services.errors import NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.person_graph_workspace_service import PersonGraphWorkspaceService
from app.services.person_identity_service import PersonIdentityService
from app.services.person_role_service import MAX_ACTIVE_ASSIGNMENTS, PersonRoleService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE, USER_ORIGIN
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides

ROOT = Path(__file__).parents[1]


@pytest.fixture
def people_client(db_session, fake_embedding_service, auth_headers):
    from app.api.deps import get_db

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


def _people(db_session, user_id=BOOTSTRAP_USER_ID) -> PersonIdentityService:
    return PersonIdentityService(db_session, user_id)


def _roles(db_session, user_id=BOOTSTRAP_USER_ID) -> PersonRoleService:
    return PersonRoleService(db_session, user_id)


def test_0053_upgrade_downgrade_preserves_person_data() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    user_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(User(id=user_id, display_name="rel1a-migration"))
        session.flush()
        person = PersonIdentityService(session, user_id).create_person("Migration Person")
        task = GraphService(session, user_id).create_object(
            ObjectCreate(
                kind="task",
                title="Migration Task",
                origin=USER_ORIGIN,
                state=CONFIRMED_STATE,
                status="open",
            )
        )
        session.commit()
        person_id = person.id
        task_id = task.id
    try:
        names = set(inspect(engine).get_table_names())
        assert "person_role_terms" in names
        assert "person_role_assignments" in names
        indexes = {item["name"] for item in inspect(engine).get_indexes("person_role_assignments")}
        assert "uq_person_role_assignments_active" in indexes
        command.downgrade(config, "0052")
        names = set(inspect(engine).get_table_names())
        assert "person_role_terms" not in names
        assert "person_role_assignments" not in names
        with Session(engine) as session:
            assert session.get(Object, person_id) is not None
            assert session.get(Object, task_id) is not None
        command.upgrade(config, "head")
        with Session(engine) as session:
            assert session.get(Object, person_id).title == "Migration Person"
            assert session.get(Object, task_id).title == "Migration Task"
            assert (
                inspect(engine).get_table_names().count("person_role_terms")
                or "person_role_terms" in inspect(engine).get_table_names()
            )
    finally:
        command.upgrade(config, "head")
        with Session(engine) as session:
            session.execute(
                text("DELETE FROM objects WHERE user_id = :user_id"), {"user_id": user_id}
            )
            session.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
            session.commit()


def test_exact_role_forms_reuse_one_term(db_session) -> None:
    person = _people(db_session).create_person("Иван")
    service = _roles(db_session)
    first = service.assign(person.id, "Директор")
    second = service.assign(person.id, " директор ")
    third = service.assign(person.id, "ДИРЕКТОР")
    terms = list(
        db_session.scalars(
            select(PersonRoleTerm).where(PersonRoleTerm.user_id == BOOTSTRAP_USER_ID)
        )
    )
    assert len(terms) == 1
    assert terms[0].display_text == "Директор"
    assert terms[0].normalized_key == "директор"
    assert first.id == second.id == third.id


def test_near_duplicates_stay_distinct(db_session) -> None:
    person = _people(db_session).create_person("Иван")
    service = _roles(db_session)
    plain = service.assign(person.id, "директор")
    general = service.assign(person.id, "генеральный директор")
    assert plain.role_term_id != general.role_term_id
    keys = set(
        db_session.scalars(
            select(PersonRoleTerm.normalized_key).where(PersonRoleTerm.user_id == BOOTSTRAP_USER_ID)
        )
    )
    assert keys == {"директор", "генеральный директор"}


def test_vocabulary_is_isolated_per_user(db_session) -> None:
    other_id = uuid.uuid4()
    db_session.add(User(id=other_id, display_name="Other"))
    db_session.flush()
    owner_person = _people(db_session).create_person("Owner person")
    other_person = _people(db_session, other_id).create_person("Other person")
    _roles(db_session).assign(owner_person.id, "студент")
    _roles(db_session, other_id).assign(other_person.id, "студент")
    assert len(_roles(db_session).search("студент")) == 1
    assert len(_roles(db_session, other_id).search("студент")) == 1
    assert _roles(db_session).search("студент")[0].user_id == BOOTSTRAP_USER_ID


def test_new_term_is_created_with_the_assignment(db_session) -> None:
    person = _people(db_session).create_person("Анна")
    before = db_session.scalar(select(func.count()).select_from(PersonRoleTerm))
    row = _roles(db_session).assign(person.id, "заведующий кафедрой", "МГУ")
    after = db_session.scalar(select(func.count()).select_from(PersonRoleTerm))
    assert after == before + 1
    assert row.state == "active"
    assert row.origin == "user"
    assert row.provenance_kind == "user_manual"
    assert row.context_text == "МГУ"


def test_several_roles_and_contexts_stay_distinct(db_session) -> None:
    person = _people(db_session).create_person("Пётр")
    service = _roles(db_session)
    plain = service.assign(person.id, "директор")
    company = service.assign(person.id, "директор", "Arenadata")
    other = service.assign(person.id, "директор", "МГУ")
    folded = service.assign(person.id, "Директор", " arenadata ")
    assert len({plain.id, company.id, other.id}) == 3
    assert folded.id == company.id
    active = service.active_for_people([person.id])[person.id]
    assert len(active) == 3


def test_bounds_cap_and_retract_frees_capacity(db_session) -> None:
    person = _people(db_session).create_person("Иван")
    service = _roles(db_session)
    with pytest.raises(ValidationError):
        service.assign(person.id, "   ")
    with pytest.raises(ValidationError):
        service.assign(person.id, "д" * 121)
    with pytest.raises(ValidationError):
        service.assign(person.id, "директор", "к" * 201)
    rows = [service.assign(person.id, f"роль {index}") for index in range(MAX_ACTIVE_ASSIGNMENTS)]
    with pytest.raises(ValidationError, match="cap"):
        service.assign(person.id, "ещё одна роль")
    service.retract(person.id, rows[0].id)
    created = service.assign(person.id, "ещё одна роль")
    assert created.state == "active"
    again = service.retract(person.id, rows[0].id)
    assert again.state == "retracted"
    assert again.retracted_at is not None
    term = db_session.get(PersonRoleTerm, rows[0].role_term_id)
    assert term is not None
    service.retract(person.id, created.id)
    reused = service.assign(person.id, term.display_text)
    assert reused.role_term_id == term.id
    assert reused.id != rows[0].id
    assert reused.state == "active"


def test_non_person_targets_fail_closed(db_session) -> None:
    other_id = uuid.uuid4()
    db_session.add(User(id=other_id, display_name="Other"))
    db_session.flush()
    foreign = _people(db_session, other_id).create_person("Чужой")
    task = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="task",
            title="Не человек",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
            status="open",
        )
    )
    rejected = _people(db_session).create_person("Отклонён")
    rejected.state = REJECTED_STATE
    deleted = _people(db_session).create_person("Удалён")
    tombstone_object(deleted)
    db_session.flush()
    service = _roles(db_session)
    with pytest.raises(NotFoundError):
        service.assign(foreign.id, "директор")
    with pytest.raises(ValidationError):
        service.assign(task.id, "директор")
    with pytest.raises(ValidationError):
        service.assign(rejected.id, "директор")
    with pytest.raises(ValidationError):
        service.assign(deleted.id, "директор")
    assert db_session.scalar(select(func.count()).select_from(PersonRoleAssignment)) == 0


def test_assignment_does_not_touch_graph_identity_or_tasks(db_session) -> None:
    person = _people(db_session).create_person("Иван")
    identity = _people(db_session).attach(
        person.id,
        __import__("app.domain.person_identity", fromlist=["normalize_email"]).normalize_email(
            "ivan@example.com"
        ),
    )
    task = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="task", title="Черновик", origin=USER_ORIGIN, state=CONFIRMED_STATE, status="open"
        )
    )
    edge = GraphService(db_session, BOOTSTRAP_USER_ID).create_edge(
        __import__("app.api.schemas", fromlist=["EdgeCreate"]).EdgeCreate(
            source_id=task.id,
            target_id=person.id,
            type="waiting_on",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    before = _counts(db_session)
    _roles(db_session).assign(person.id, "директор", "Arenadata")
    after = _counts(db_session)
    assert after["edges"] == before["edges"]
    assert after["identities"] == before["identities"]
    assert after["evidence"] == before["evidence"]
    assert after["objects"] == before["objects"]
    assert db_session.get(Edge, edge.id).type == "waiting_on"
    assert db_session.get(PersonIdentity, identity.id).state != REJECTED_STATE


def test_search_is_lexical_bounded_and_ordered(db_session) -> None:
    person = _people(db_session).create_person("Иван")
    service = _roles(db_session)
    service.assign(person.id, "директор")
    service.assign(person.id, "директор компании")
    service.assign(person.id, "студент")
    found = service.search("ДИР")
    assert [term.normalized_key for term in found] == ["директор", "директор компании"]
    page = service.search(None, limit=1)
    assert len(page) == 1
    assert service.search("zzzz-no-such-role") == []


def test_workspace_projects_active_roles_in_one_query(db_session) -> None:
    ivan = _people(db_session).create_person("Иван Роли")
    anna = _people(db_session).create_person("Анна Роли")
    service = _roles(db_session)
    service.assign(ivan.id, "студент")
    service.assign(ivan.id, "директор", "Arenadata")
    dropped = service.assign(anna.id, "оппонент")
    service.retract(anna.id, dropped.id)
    statements: list[str] = []

    def before(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "person_role_assignments" in statement.lower():
            statements.append(statement)

    event.listen(db_session.connection(), "before_cursor_execute", before)
    try:
        result = PersonGraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(
            root_id=ivan.id,
            query=None,
            seed_limit=20,
            neighbor_limit=5,
        )
    finally:
        event.remove(db_session.connection(), "before_cursor_execute", before)
    selects = [item for item in statements if item.lstrip().lower().startswith("select")]
    assert len(selects) == 1
    by_id = {item["person_id"]: item for item in result.people}
    ivan_roles = by_id[ivan.id]["role_assignments"]
    assert [item["role_display_text"] for item in ivan_roles] == ["директор", "студент"]
    assert ivan_roles[0]["context"] == "Arenadata"
    assert all(item["state"] == "active" for item in ivan_roles)
    anna_view = PersonGraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(
        root_id=anna.id,
        query=None,
        seed_limit=20,
        neighbor_limit=5,
    )
    anna_row = next(item for item in anna_view.people if item["person_id"] == anna.id)
    assert anna_row["role_assignments"] == []


def test_role_api_search_assign_and_retract(people_client, db_session) -> None:
    person = _people(db_session).create_person("API Person")
    created = people_client.post(
        f"/graph/people/{person.id}/roles",
        json={"role": "научный руководитель", "context": "МФТИ"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["role_display_text"] == "научный руководитель"
    assert body["context"] == "МФТИ"
    assert body["origin"] == "user"
    assert body["state"] == "active"
    again = people_client.post(
        f"/graph/people/{person.id}/roles",
        json={"role": " Научный руководитель ", "context": "мфти"},
    )
    assert again.status_code == 200
    assert again.json()["id"] == body["id"]
    found = people_client.get("/graph/person-role-terms", params={"q": "науч"})
    assert found.status_code == 200
    assert found.json()["terms"][0]["display_text"] == "научный руководитель"
    retracted = people_client.delete(f"/graph/people/{person.id}/roles/{body['id']}")
    assert retracted.status_code == 200
    assert retracted.json()["state"] == "retracted"
    repeat = people_client.delete(f"/graph/people/{person.id}/roles/{body['id']}")
    assert repeat.status_code == 200
    assert repeat.json()["state"] == "retracted"
    workspace = people_client.get("/graph/people-workspace", params={"root_id": str(person.id)})
    assert workspace.status_code == 200
    person_row = next(
        item for item in workspace.json()["people"] if item["person_id"] == str(person.id)
    )
    assert person_row["role_assignments"] == []


def _counts(db_session) -> dict[str, int]:
    return {
        "edges": db_session.scalar(select(func.count()).select_from(Edge)),
        "identities": db_session.scalar(select(func.count()).select_from(PersonIdentity)),
        "evidence": db_session.scalar(select(func.count()).select_from(PersonIdentityEvidence)),
        "objects": db_session.scalar(select(func.count()).select_from(Object)),
    }
