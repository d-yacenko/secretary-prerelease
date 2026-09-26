"""Explicit first-party Person creation stays a named Object only."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import Edge, Object, PersonIdentity, PersonIdentityEvidence, User
from app.main import app
from app.services.provenance import CONFIRMED_STATE, USER_ORIGIN
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


def test_post_people_creates_trimmed_confirmed_user_person(people_client, db_session) -> None:
    response = people_client.post("/graph/people", json={"title": "  Ada Lovelace  "})
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "person"
    assert body["title"] == "Ada Lovelace"
    assert body["origin"] == USER_ORIGIN
    assert body["state"] == CONFIRMED_STATE
    person = db_session.get(Object, uuid.UUID(body["id"]))
    assert person is not None
    assert person.kind == "person"
    assert person.title == "Ada Lovelace"


def test_blank_and_overlong_titles_fail(people_client) -> None:
    blank = people_client.post("/graph/people", json={"title": "   "})
    assert blank.status_code == 422
    assert blank.json()["detail"] == "person title is required"
    overlong = people_client.post("/graph/people", json={"title": "a" * 201})
    assert overlong.status_code == 422
    assert overlong.json()["detail"] == "person title is required"


def test_duplicate_titles_create_distinct_people_without_identity_or_edges(
    people_client, db_session
) -> None:
    first = people_client.post("/graph/people", json={"title": "Ada"})
    second = people_client.post("/graph/people", json={"title": "Ada"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert db_session.scalar(select(func.count()).select_from(PersonIdentity)) == 0
    assert db_session.scalar(select(func.count()).select_from(PersonIdentityEvidence)) == 0
    assert db_session.scalar(select(func.count()).select_from(Edge)) == 0


def test_created_person_is_isolated_and_visible_in_people_workspace(
    people_client, db_session, issue_bearer
) -> None:
    created = people_client.post("/graph/people", json={"title": "Ada"})
    person_id = created.json()["id"]
    workspace = people_client.get("/graph/people-workspace")
    assert workspace.status_code == 200
    assert person_id in {node["id"] for node in workspace.json()["nodes"]}

    other_id = uuid.uuid4()
    db_session.add(User(id=other_id, display_name="other-person-create"))
    db_session.flush()
    other = people_client.get(
        "/graph/people-workspace",
        headers={"Authorization": f"Bearer {issue_bearer(other_id)}"},
    )
    assert other.status_code == 200
    assert person_id not in {node["id"] for node in other.json()["nodes"]}
