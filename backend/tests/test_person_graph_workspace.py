"""Grounded People workspace stays on canonical Person objects."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import Edge, Object, PersonIdentityEvidence, User
from app.domain.object_visibility import tombstone_object
from app.domain.person_identity import normalize_email, normalize_telegram_user_id
from app.main import app
from app.services.graph_service import GraphService
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE, USER_ORIGIN
from app.tools.schemas import ListPersonRoutesInput
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


def _identity_payload(identity) -> dict:
    return {
        "identity_type": identity.identity_type,
        "provider": identity.provider,
        "realm": identity.realm,
        "canonical_value": identity.canonical_value,
    }


def test_effective_identity_search_and_graph_ui_provenance(people_client, db_session) -> None:
    people = _people(db_session)
    person = people.create_person("Aaa Quiet")
    identity = normalize_email("quiet@example.com")
    people.attach(person.id, identity)
    payload = _identity_payload(identity)
    found = people_client.get("/graph/people-workspace", params={"q": identity.canonical_value})
    assert found.status_code == 200
    assert [node["id"] for node in found.json()["nodes"]] == [str(person.id)]

    rejected = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "reject", **payload},
    )
    assert rejected.status_code == 200
    missed = people_client.get("/graph/people-workspace", params={"q": identity.canonical_value})
    assert missed.json()["nodes"] == []
    by_title = people_client.get("/graph/people-workspace", params={"q": "Aaa Quiet"})
    assert [node["id"] for node in by_title.json()["nodes"]] == [str(person.id)]
    evidence = PersonEvidenceService(db_session, BOOTSTRAP_USER_ID)
    before = evidence.score(person.id, identity).score
    repeated = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "reject", **payload},
    )
    assert repeated.status_code == 200
    assert repeated.json()["evidence_id"] == rejected.json()["evidence_id"]
    assert evidence.score(person.id, identity).score == before
    row = db_session.get(PersonIdentityEvidence, uuid.UUID(rejected.json()["evidence_id"]))
    assert row is not None
    assert row.evidence_type == "user_rejected"
    assert row.provenance_kind == "user_feedback"
    assert row.provenance_key.startswith("graph_ui:user_rejected:")
    assert not row.provenance_key.startswith("assistant:")

    confirmed = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "confirm", **payload},
    )
    assert confirmed.status_code == 200
    restored = people_client.get("/graph/people-workspace", params={"q": identity.canonical_value})
    assert [node["id"] for node in restored.json()["nodes"]] == [str(person.id)]
    confirmed_row = db_session.get(PersonIdentityEvidence, uuid.UUID(confirmed.json()["evidence_id"]))
    assert confirmed_row is not None
    assert confirmed_row.evidence_type == "user_confirmed"
    assert confirmed_row.provenance_key.startswith("graph_ui:user_confirmed:")

    people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "reject", **payload},
    )
    retracted = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "retract", **payload},
    )
    assert retracted.status_code == 200
    assert db_session.get(PersonIdentityEvidence, row.id).state == "retracted"
    after = people_client.get("/graph/people-workspace", params={"q": identity.canonical_value})
    assert [node["id"] for node in after.json()["nodes"]] == [str(person.id)]

    invented = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "confirm", **_identity_payload(normalize_email("nobody@example.com"))},
    )
    assert invented.status_code == 422


def test_people_ui_reads_telegram_while_assistant_stays_gated(people_client, db_session, monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    people = _people(db_session)
    person = people.create_person("Olga Volkova")
    realm = str(uuid.uuid4())
    identity = normalize_telegram_user_id(realm, 7)
    people.attach(person.id, identity)
    private = _telegram(db_session, realm, peer_kind="private", sender=7, peer=7)
    _telegram(db_session, realm, peer_kind="group", sender=7, peer=-100)
    rooted = people_client.get("/graph/people-workspace", params={"root_id": str(person.id)})
    assert rooted.status_code == 200
    card = rooted.json()["people"][0]
    shown = {item["canonical_value"]: item["state"] for item in card["identities"]}
    assert shown["7"] == "effective"
    assert any(route["provider"] == "telegram" and "7" in route["route_key"] for route in card["routes"])
    assert all("-100" not in route["route_key"] for route in card["routes"])

    assistant = PersonAssistantService(db_session, BOOTSTRAP_USER_ID)
    hidden_routes = assistant.list_routes(ListPersonRoutesInput(person_id=person.id))
    assert hidden_routes.routes == []
    hidden_candidates = assistant.find_identity_candidates(person.id)
    assert hidden_candidates.candidates == []
    assert private.id


def test_people_ui_can_confirm_a_stored_telegram_candidate(people_client, db_session, monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    person = _people(db_session).create_person("Olga Volkova")
    realm = str(uuid.uuid4())
    _telegram(
        db_session,
        realm,
        peer_kind="private",
        sender=42,
        peer=42,
        peer_title="Olga Volkova",
    )
    rooted = people_client.get("/graph/people-workspace", params={"root_id": str(person.id)})
    candidates = [
        item for item in rooted.json()["people"][0]["identities"] if item["state"] == "candidate"
    ]
    assert len(candidates) == 1
    assert candidates[0]["confirmable"] is True
    assert candidates[0]["canonical_value"] == "42"
    assert PersonAssistantService(db_session, BOOTSTRAP_USER_ID).find_identity_candidates(person.id).candidates == []

    confirmed = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "confirm", **_identity_payload_from_card(candidates[0])},
    )
    assert confirmed.status_code == 200
    row = db_session.get(PersonIdentityEvidence, uuid.UUID(confirmed.json()["evidence_id"]))
    assert row is not None
    assert row.evidence_type == "user_confirmed"
    assert row.provenance_kind == "user_feedback"
    assert row.provenance_key.startswith("graph_ui:user_confirmed:")
    repeated = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "confirm", **_identity_payload_from_card(candidates[0])},
    )
    assert repeated.json()["evidence_id"] == confirmed.json()["evidence_id"]


def test_people_workspace_scans_are_capped(people_client, db_session, monkeypatch) -> None:
    import app.services.person_graph_workspace_service as workspace

    monkeypatch.setattr(workspace, "PEOPLE_EDGE_SCAN_CAP", 3)
    people = _people(db_session)
    person = people.create_person("Bounded")
    for index in range(6):
        _link_task(db_session, person.id, f"Task {index:02d}")
    rooted = people_client.get(
        "/graph/people-workspace",
        params={"root_id": str(person.id), "neighbor_limit": 12},
    )
    assert rooted.status_code == 200
    body = rooted.json()
    assert body["truncated"] is True
    assert len([node for node in body["nodes"] if node["kind"] == "task"]) == 3
    assert body["people"][0]["open_task_count"] == 6

    outside = None
    for index in range(8):
        quiet = people.create_person(f"Person {index:02d}")
        people.attach(quiet.id, normalize_email(f"person{index}@example.com"))
        if index == 7:
            outside = quiet
    found = people_client.get("/graph/people-workspace", params={"q": "person", "seed_limit": 2})
    assert found.status_code == 200
    assert len(found.json()["nodes"]) == 2
    assert found.json()["truncated"] is True
    assert outside is not None
    assert str(outside.id) not in {node["id"] for node in found.json()["nodes"]}
    reached = people_client.get("/graph/people-workspace", params={"q": "person7@example.com"})
    assert [node["id"] for node in reached.json()["nodes"]] == [str(outside.id)]


def _identity_payload_from_card(item: dict) -> dict:
    return {
        "identity_type": item["identity_type"],
        "provider": item["provider"],
        "realm": item["realm"],
        "canonical_value": item["canonical_value"],
    }


def _telegram(db_session, realm: str, *, peer_kind: str, sender: int, peer: int, peer_title: str | None = None):
    metadata = {
        "transport": "mtproto",
        "account_id": realm,
        "peer_kind": peer_kind,
        "peer_id": peer,
        "sender_peer_id": sender,
        "direction": "inbound",
    }
    if peer_title:
        metadata["peer_title"] = peer_title
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider="telegram",
        title="note",
        origin="source",
        state="observed",
        occurred_at=datetime.now(UTC),
        metadata_=metadata,
    )
    db_session.add(obj)
    db_session.flush()
    return obj
