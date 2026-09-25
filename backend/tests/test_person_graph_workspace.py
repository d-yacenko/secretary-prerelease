"""Grounded People workspace stays on canonical Person objects."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import Edge, Object, User
from app.domain.object_visibility import tombstone_object
from app.domain.person_identity import normalize_email
from app.main import app
from app.services.graph_service import GraphService
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE, USER_ORIGIN
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides


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


def _people(db_session) -> PersonIdentityService:
    return PersonIdentityService(db_session, BOOTSTRAP_USER_ID)


def _graph(db_session) -> GraphService:
    return GraphService(db_session, BOOTSTRAP_USER_ID)


def _link_task(db_session, person_id, title: str):
    task = _graph(db_session).create_object(
        ObjectCreate(kind="task", title=title, origin=USER_ORIGIN, state=CONFIRMED_STATE, status="open")
    )
    _graph(db_session).create_edge(
        EdgeCreate(
            source_id=person_id,
            target_id=task.id,
            type="related_to",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    return task


def test_overview_orders_by_salience_and_search_reaches_the_rest(people_client, db_session) -> None:
    people = _people(db_session)
    quiet = people.create_person("Aaa Quiet")
    people.attach(quiet.id, normalize_email("quiet@example.com"))
    salient = people.create_person("Zzz Salient")
    _link_task(db_session, salient.id, "Open commitment")
    author = _graph(db_session).create_object(
        ObjectCreate(
            kind="chat_message",
            title="incidental author",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    rejected = people.create_person("Rejected Person")
    rejected.state = REJECTED_STATE
    deleted = people.create_person("Deleted Person")
    tombstone_object(deleted)
    db_session.flush()

    overview = people_client.get("/graph/people-workspace", params={"seed_limit": 1})
    assert overview.status_code == 200
    body = overview.json()
    assert body["truncated"] is True
    assert [node["kind"] for node in body["nodes"]] == ["person"]
    assert body["nodes"][0]["id"] == str(salient.id)
    assert author.id not in {uuid.UUID(node["id"]) for node in body["nodes"]}
    assert str(rejected.id) not in {node["id"] for node in body["nodes"]}
    assert str(deleted.id) not in {node["id"] for node in body["nodes"]}

    found = people_client.get("/graph/people-workspace", params={"q": "quiet@example.com"})
    assert found.status_code == 200
    assert found.json()["nodes"][0]["id"] == str(quiet.id)
    by_title = people_client.get("/graph/people-workspace", params={"q": "Aaa Quiet"})
    assert by_title.json()["nodes"][0]["id"] == str(quiet.id)


def test_rooted_view_tasks_and_safe_identities(people_client, db_session) -> None:
    people = _people(db_session)
    person = people.create_person("Olga")
    identity = people.attach(person.id, normalize_email("olga@example.com"))
    task = _link_task(db_session, person.id, "Reply to Olga")
    other = people.create_person("Other")
    before = db_session.scalar(select(func.count()).select_from(Edge).where(Edge.user_id == BOOTSTRAP_USER_ID))

    rooted = people_client.get("/graph/people-workspace", params={"root_id": str(person.id)})
    assert rooted.status_code == 200
    body = rooted.json()
    ids = {node["id"] for node in body["nodes"]}
    assert str(person.id) in ids
    assert str(task.id) in ids
    assert str(other.id) not in ids
    shown = body["people"][0]
    assert shown["open_task_count"] == 1
    assert shown["identities"][0]["display_value"] == identity.canonical_value
    assert shown["identities"][0]["state"] == "effective"
    dumped = str(body)
    assert "session" not in dumped
    assert "encrypted" not in dumped
    assert "access_token" not in dumped
    after = db_session.scalar(select(func.count()).select_from(Edge).where(Edge.user_id == BOOTSTRAP_USER_ID))
    assert after == before
    kinds = {edge.type for edge in db_session.scalars(select(Edge).where(Edge.user_id == BOOTSTRAP_USER_ID))}
    assert kinds.isdisjoint({"member_of", "role_at", "manager_of", "works_with"})

    outsider = User(id=uuid.uuid4(), display_name="outsider")
    db_session.add(outsider)
    db_session.flush()
    foreign = PersonIdentityService(db_session, outsider.id).create_person("Foreign")
    assert people_client.get("/graph/people-workspace", params={"root_id": str(foreign.id)}).status_code == 404
    message = _graph(db_session).create_object(
        ObjectCreate(kind="chat_message", title="not a person", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    assert people_client.get("/graph/people-workspace", params={"root_id": str(message.id)}).status_code == 404

    unlinked = people_client.get("/graph/people-workspace", params={"root_id": str(other.id)})
    assert unlinked.status_code == 200
    assert all(node["id"] != str(task.id) for node in unlinked.json()["nodes"])
    assert unlinked.json()["people"][0]["open_task_count"] == 0


def test_rejection_conflict_and_reversible_correction(people_client, db_session) -> None:
    people = _people(db_session)
    person = people.create_person("Olga")
    identity = normalize_email("olga@example.com")
    people.attach(person.id, identity)
    payload = {
        "identity_type": identity.identity_type,
        "provider": identity.provider,
        "realm": identity.realm,
        "canonical_value": identity.canonical_value,
    }
    rejected = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "reject", **payload},
    )
    assert rejected.status_code == 200
    shown = people_client.get("/graph/people-workspace", params={"root_id": str(person.id)}).json()
    states = {item["canonical_value"]: item["state"] for item in shown["people"][0]["identities"]}
    assert states[identity.canonical_value] == "rejected"

    restored = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "retract", **payload},
    )
    assert restored.status_code == 200
    shown = people_client.get("/graph/people-workspace", params={"root_id": str(person.id)}).json()
    states = {item["canonical_value"]: item["state"] for item in shown["people"][0]["identities"]}
    assert states[identity.canonical_value] == "effective"

    other = people.create_person("Other owner")
    PersonEvidenceService(db_session, BOOTSTRAP_USER_ID).record_confirmation(
        other.id,
        identity,
        f"test:user_confirmed:{identity.canonical_value}",
    )
    conflicted = people_client.get("/graph/people-workspace", params={"root_id": str(person.id)}).json()
    card = conflicted["people"][0]
    assert card["identity_conflict"] is True
    assert card["identities"][0]["state"] == "conflicted"
    blocked = people_client.post(
        f"/graph/people/{other.id}/identity-correction",
        json={"action": "confirm", **payload},
    )
    assert blocked.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(Object).where(Object.kind == "person")) >= 2
