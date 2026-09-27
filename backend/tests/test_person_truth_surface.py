"""Rooted People detail projects existing Task, Flow, and salience facts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.schemas import EdgeCreate, ObjectCreate
from app.core.config import settings
from app.db.models import Object
from app.domain.object_visibility import tombstone_object
from app.domain.person_identity import normalize_email, normalize_telegram_user_id
from app.domain.task_relations import DELEGATED_TO, INVOLVES, REQUESTED_BY, WAITING_ON
from app.main import app
from app.services.graph_service import GraphService
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_identity_service import PersonIdentityService
from app.services.person_salience_service import PersonSalienceService
from app.services.provenance import AGENT_ORIGIN, CONFIRMED_STATE, PROPOSED_STATE, USER_ORIGIN
from app.services.task_relation_service import TaskRelationService
from app.tools.schemas import FindPersonCommunicationsInput
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


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


def test_rooted_detail_lists_exact_actor_roles(people_client, db_session) -> None:
    person = _people(db_session).create_person("Ada")
    asked = _task(db_session, "Ask", due_at=NOW)
    delegated = _task(db_session, "Do", due_at=NOW + timedelta(days=1))
    waiting = _task(db_session, "Wait", due_at=NOW + timedelta(days=2), completion_mode="ongoing")
    involved = _task(db_session, "Join", due_at=NOW + timedelta(days=3))
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    relations.add_actor(asked.id, person.id, REQUESTED_BY)
    relations.add_actor(delegated.id, person.id, DELEGATED_TO)
    relations.add_actor(waiting.id, person.id, WAITING_ON)
    relations.add_actor(
        involved.id,
        person.id,
        INVOLVES,
        origin=AGENT_ORIGIN,
        state=PROPOSED_STATE,
        confidence=0.6,
    )
    generic = _task(db_session, "Generic")
    _graph(db_session).create_edge(
        EdgeCreate(
            source_id=generic.id,
            target_id=person.id,
            type="related_to",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    done = _task(db_session, "Done", status="done")
    relations.add_actor(done.id, person.id, REQUESTED_BY)
    deleted = _task(db_session, "Deleted")
    relations.add_actor(deleted.id, person.id, REQUESTED_BY)
    deleted.status = "deleted"
    hidden = _task(db_session, "Hidden")
    relations.add_actor(hidden.id, person.id, REQUESTED_BY)
    tombstone_object(hidden)
    rejected_task = _task(db_session, "Rejected edge")
    rejected = relations.add_actor(rejected_task.id, person.id, REQUESTED_BY)[0]
    rejected.state = "rejected"
    db_session.flush()

    rows = _root(people_client, person.id)["task_involvement"]
    assert [(row["title"], row["role"], row["edge_state"], row["edge_origin"]) for row in rows] == [
        ("Ask", "requested_by", "confirmed", "user"),
        ("Do", "delegated_to", "confirmed", "user"),
        ("Wait", "waiting_on", "confirmed", "user"),
        ("Join", "involves", "proposed", "agent"),
    ]
    assert rows[2]["completion_mode"] == "ongoing"
    assert _root(people_client, person.id)["open_task_count"] >= 5


def test_task_involvement_is_capped_in_due_order(people_client, db_session) -> None:
    person = _people(db_session).create_person("Ada")
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    for index in range(9):
        task = _task(db_session, f"Task {index:02d}", due_at=NOW + timedelta(days=index))
        relations.add_actor(task.id, person.id, INVOLVES)
    body = _root(people_client, person.id)
    assert [row["title"] for row in body["task_involvement"]] == [f"Task {index:02d}" for index in range(8)]
    assert body["task_involvement_truncated"] is True


def test_recent_flow_follows_effective_identity(people_client, db_session) -> None:
    person = _people(db_session).create_person("Ada")
    identity = normalize_email("ada@example.com")
    _people(db_session).attach(person.id, identity)
    _email(db_session, "ada@example.com", title="Grounded", when=NOW)
    _email(db_session, "other@example.com", title="Someone else", when=NOW)
    shown = _root(people_client, person.id)["recent_communications"]
    assert [item["title"] for item in shown] == ["Grounded"]
    PersonEvidenceService(db_session, BOOTSTRAP_USER_ID).record_rejection(
        person.id,
        identity,
        "test:reject",
        explanation="test",
    )
    assert _root(people_client, person.id)["recent_communications"] == []


def test_first_party_flow_includes_telegram_while_assistant_stays_gated(
    people_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    person = _people(db_session).create_person("Olga")
    realm = str(uuid.uuid4())
    _people(db_session).attach(person.id, normalize_telegram_user_id(realm, 7))
    _telegram(db_session, realm, peer_kind="private", sender=7, peer=7, title="Private note")
    shown = _root(people_client, person.id)["recent_communications"]
    assert [item["title"] for item in shown] == ["Private note"]
    assistant = PersonAssistantService(db_session, BOOTSTRAP_USER_ID, now=NOW)
    page = assistant.find_communications(FindPersonCommunicationsInput(person_id=person.id))
    assert page.objects == []


def test_salience_projection_matches_the_canonical_service(people_client, db_session) -> None:
    person = _people(db_session).create_person("Ada")
    expected = PersonSalienceService(db_session, BOOTSTRAP_USER_ID, now=NOW).evaluate(person.id)
    body = _root(people_client, person.id)["salience"]
    assert body["score"] == expected.score
    assert body["tier"] == expected.tier
    assert body["truncated"] is expected.truncated
    assert body["window_days"] == expected.window_days
    assert body["claims_object_importance"] is False
    assert [(item["name"], item["value"]) for item in body["components"]] == [
        (item.name, item.value) for item in expected.components
    ]


def test_overview_and_search_do_not_load_rooted_truth(people_client, db_session, monkeypatch) -> None:
    calls = {"evaluate": 0, "communications": 0}
    original_evaluate = PersonSalienceService.evaluate
    original_find = PersonAssistantService.find_communications

    def evaluate(self, person_id):
        calls["evaluate"] += 1
        return original_evaluate(self, person_id)

    def find_communications(self, payload, *, include_quarantined_telegram=False):
        calls["communications"] += 1
        return original_find(self, payload, include_quarantined_telegram=include_quarantined_telegram)

    monkeypatch.setattr(PersonSalienceService, "evaluate", evaluate)
    monkeypatch.setattr(PersonAssistantService, "find_communications", find_communications)
    _people(db_session).create_person("Ada")
    overview = people_client.get("/graph/people-workspace")
    search = people_client.get("/graph/people-workspace", params={"q": "Ada"})
    assert overview.status_code == 200
    assert search.status_code == 200
    for body in (overview.json(), search.json()):
        person = body["people"][0]
        assert person["task_involvement"] == []
        assert person["recent_communications"] == []
        assert person["salience"] is None
    assert calls == {"evaluate": 0, "communications": 0}


def _root(people_client, person_id) -> dict:
    response = people_client.get("/graph/people-workspace", params={"root_id": str(person_id)})
    assert response.status_code == 200
    people = response.json()["people"]
    return next(item for item in people if item["person_id"] == str(person_id))


def _people(db_session) -> PersonIdentityService:
    return PersonIdentityService(db_session, BOOTSTRAP_USER_ID)


def _graph(db_session) -> GraphService:
    return GraphService(db_session, BOOTSTRAP_USER_ID)


def _task(
    db_session,
    title: str,
    *,
    status: str = "open",
    due_at: datetime | None = None,
    completion_mode: str = "finite",
) -> Object:
    return _graph(db_session).create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
            status=status,
            due_at=due_at,
            completion_mode=completion_mode,
        )
    )


def _email(db_session, sender: str, *, title: str, when: datetime) -> None:
    db_session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="email",
            provider="gmail",
            title=title,
            origin="source",
            state="observed",
            occurred_at=when,
            metadata_={"sender": sender, "labels": ["INBOX"]},
        )
    )
    db_session.flush()


def _telegram(
    db_session,
    realm: str,
    *,
    peer_kind: str,
    sender: int,
    peer: int,
    title: str,
) -> None:
    db_session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="chat_message",
            provider="telegram",
            title=title,
            origin="source",
            state="observed",
            occurred_at=NOW,
            metadata_={
                "transport": "mtproto",
                "account_id": realm,
                "peer_kind": peer_kind,
                "peer_id": peer,
                "sender_peer_id": sender,
                "direction": "inbound",
            },
        )
    )
    db_session.flush()
