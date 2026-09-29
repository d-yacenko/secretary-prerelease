"""Confirmed Task anchors for later People Landscape projection."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.schemas import EdgeCreate, ObjectCreate
from app.domain.object_visibility import tombstone_object
from app.domain.task_relations import DELEGATED_TO, INVOLVES, REQUESTED_BY, WAITING_ON
from app.main import app
from app.services.graph_service import GraphService
from app.services.person_graph_workspace_service import PEOPLE_LANDSCAPE_TASK_ANCHOR_CAP
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import (
    AGENT_ORIGIN,
    CONFIRMED_STATE,
    PROPOSED_STATE,
    REJECTED_STATE,
    USER_ORIGIN,
)
from app.services.task_relation_service import TaskRelationService
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


def test_confirmed_actor_tasks_are_distinct_anchors(people_client, db_session) -> None:
    ada = _people(db_session).create_person("Landscape-anchor Ada")
    bea = _people(db_session).create_person("Landscape-anchor Bea")
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    shared = _task(db_session, "Shared")
    other = _task(db_session, "Other")
    proposed = _task(db_session, "Proposed")
    rejected_task = _task(db_session, "Rejected")
    generic = _task(db_session, "Generic")
    done = _task(db_session, "Done", status="done")
    hidden = _task(db_session, "Hidden")
    rejected_object = _task(db_session, "Rejected object")
    relations.add_actor(shared.id, ada.id, REQUESTED_BY)
    relations.add_actor(shared.id, ada.id, WAITING_ON)
    relations.add_actor(other.id, ada.id, DELEGATED_TO)
    relations.add_actor(
        proposed.id,
        ada.id,
        INVOLVES,
        origin=AGENT_ORIGIN,
        state=PROPOSED_STATE,
        confidence=0.6,
    )
    rejected = relations.add_actor(rejected_task.id, ada.id, REQUESTED_BY)[0]
    rejected.state = "rejected"
    _graph(db_session).create_edge(
        EdgeCreate(
            source_id=generic.id,
            target_id=ada.id,
            type="related_to",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    relations.add_actor(done.id, ada.id, REQUESTED_BY)
    relations.add_actor(hidden.id, ada.id, REQUESTED_BY)
    relations.add_actor(rejected_object.id, ada.id, DELEGATED_TO)
    tombstone_object(hidden)
    rejected_object.state = REJECTED_STATE
    db_session.flush()

    found = people_client.get(
        "/graph/people-workspace",
        params={"q": "landscape-anchor", "seed_limit": 24},
    )
    assert found.status_code == 200
    by_id = {item["person_id"]: item for item in found.json()["people"]}
    assert by_id[str(ada.id)]["landscape_task_ids"] == sorted([str(shared.id), str(other.id)])
    assert by_id[str(ada.id)]["landscape_task_ids_complete"] is True
    assert by_id[str(bea.id)]["landscape_task_ids"] == []
    assert by_id[str(bea.id)]["landscape_task_ids_complete"] is True

    rooted = _person(people_client, ada.id)
    assert {row["task_id"] for row in rooted["task_involvement"] if row["edge_state"] == "proposed"} == {
        str(proposed.id)
    }
    assert str(proposed.id) not in rooted["landscape_task_ids"]
    assert str(rejected_object.id) not in rooted["landscape_task_ids"]


def test_anchor_cap_is_deterministic_and_incomplete(people_client, db_session) -> None:
    ada = _people(db_session).create_person("Landscape-cap Ada")
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    task_ids = []
    for index in range(PEOPLE_LANDSCAPE_TASK_ANCHOR_CAP + 1):
        task = _task(db_session, f"Cap {index:02d}")
        relations.add_actor(task.id, ada.id, INVOLVES)
        task_ids.append(str(task.id))
    db_session.flush()

    body = _person(people_client, ada.id)
    expected = sorted(task_ids)[:PEOPLE_LANDSCAPE_TASK_ANCHOR_CAP]
    assert body["landscape_task_ids"] == expected
    assert len(body["landscape_task_ids"]) == PEOPLE_LANDSCAPE_TASK_ANCHOR_CAP
    assert body["landscape_task_ids_complete"] is False


def _person(people_client, person_id) -> dict:
    response = people_client.get("/graph/people-workspace", params={"root_id": str(person_id)})
    assert response.status_code == 200
    return next(item for item in response.json()["people"] if item["person_id"] == str(person_id))


def _people(db_session) -> PersonIdentityService:
    return PersonIdentityService(db_session, BOOTSTRAP_USER_ID)


def _graph(db_session) -> GraphService:
    return GraphService(db_session, BOOTSTRAP_USER_ID)


def _task(db_session, title: str, *, status: str = "open"):
    return _graph(db_session).create_object(
        ObjectCreate(kind="task", title=title, origin=USER_ORIGIN, state=CONFIRMED_STATE, status=status)
    )
