"""Graph confirmation activates a grounded identity without enrichment."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import Edge, Object, PersonIdentity, PersonIdentityEvidence, User
from app.domain.person_identity import normalize_email, normalize_telegram_user_id
from app.main import app
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_enrichment_service import PersonEnrichmentService
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import REJECTED_STATE
from app.tools.schemas import FindPersonCommunicationsInput
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


def test_confirm_activates_email_without_enrichment_and_stays_idempotent(
    people_client, db_session, monkeypatch
) -> None:
    planned = {"calls": 0}

    def fail_plan(self, *args, **kwargs):
        planned["calls"] += 1
        raise AssertionError("enrichment plan")

    monkeypatch.setattr(PersonEnrichmentService, "plan", fail_plan)
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Ada Lovelace")
    message = _email(db_session, "Ada Lovelace <ada@example.com>")
    identity = normalize_email("ada@example.com")
    payload = _payload(identity)
    before = _card(people_client, person.id)
    assert _active_identities(db_session) == []
    assert before["ada@example.com"] == "candidate"

    confirmed = _correct(people_client, person.id, "confirm", payload)
    assert confirmed.status_code == 200
    row = db_session.get(PersonIdentityEvidence, uuid.UUID(confirmed.json()["evidence_id"]))
    identities = _active_identities(db_session)
    assert len(identities) == 1
    assert identities[0].state != REJECTED_STATE
    assert row is not None
    assert row.evidence_type == "user_confirmed"
    assert row.provenance_kind == "user_feedback"
    assert row.provenance_key.startswith("graph_ui:user_confirmed:")
    assert row.person_identity_id == identities[0].id
    shown = _card(people_client, person.id)
    assert shown["ada@example.com"] == "effective"
    assert "candidate" not in shown.values()
    rooted = people_client.get("/graph/people-workspace", params={"root_id": str(person.id)}).json()
    assert any(
        route["route_key"] == "email:ada@example.com" for route in rooted["people"][0]["routes"]
    )

    assistant = PersonAssistantService(db_session, BOOTSTRAP_USER_ID)
    resolved = assistant.resolve("ada@example.com")
    assert resolved.person_id == person.id
    found = assistant.find_communications(FindPersonCommunicationsInput(person_id=person.id))
    assert [item.id for item in found.objects] == [message.id]
    assert planned["calls"] == 0
    assert db_session.scalar(select(func.count()).select_from(Edge)) == 0

    repeated = _correct(people_client, person.id, "confirm", payload)
    assert repeated.json()["evidence_id"] == confirmed.json()["evidence_id"]
    assert len(_active_identities(db_session)) == 1
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(PersonIdentityEvidence)
            .where(
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.evidence_type == "user_confirmed",
            )
        )
        == 1
    )


def test_confirm_activates_a_telegram_candidate_route(
    people_client, db_session, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Olga Volkova")
    realm = str(uuid.uuid4())
    _telegram(db_session, realm)
    card = _card(people_client, person.id)
    assert card["42"] == "candidate"
    confirmed = _correct(
        people_client,
        person.id,
        "confirm",
        _payload(normalize_telegram_user_id(realm, 42)),
    )
    assert confirmed.status_code == 200
    shown = people_client.get("/graph/people-workspace", params={"root_id": str(person.id)}).json()
    assert _card(people_client, person.id)["42"] == "effective"
    assert any(
        route["provider"] == "telegram" and "42" in route["route_key"]
        for route in shown["people"][0]["routes"]
    )
    assert db_session.scalar(select(func.count()).select_from(Edge)) == 0


def test_retract_of_created_identity_offers_the_candidate_again(people_client, db_session) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Ada Lovelace")
    _email(db_session, "Ada Lovelace <ada@example.com>")
    identity = normalize_email("ada@example.com")
    payload = _payload(identity)
    _correct(people_client, person.id, "confirm", payload)
    retracted = _correct(people_client, person.id, "retract", payload)
    assert retracted.status_code == 200
    assert _active_identities(db_session) == []
    assert PersonIdentityService(db_session, BOOTSTRAP_USER_ID).resolve(identity) is None
    assert _card(people_client, person.id)["ada@example.com"] == "candidate"
    stored = db_session.scalars(select(PersonIdentity)).all()
    assert len(stored) == 1
    assert stored[0].state == REJECTED_STATE


def test_retract_of_preexisting_identity_does_not_detach(people_client, db_session) -> None:
    people = PersonIdentityService(db_session, BOOTSTRAP_USER_ID)
    person = people.create_person("Ada Lovelace")
    identity = normalize_email("ada@example.com")
    attached = people.attach(person.id, identity)
    _email(db_session, "Ada Lovelace <ada@example.com>")
    payload = _payload(identity)
    confirmed = _correct(people_client, person.id, "confirm", payload)
    row = db_session.get(PersonIdentityEvidence, uuid.UUID(confirmed.json()["evidence_id"]))
    assert row is not None
    assert row.person_identity_id is None
    assert len(_active_identities(db_session)) == 1
    retracted = _correct(people_client, person.id, "retract", payload)
    assert retracted.status_code == 200
    assert people.resolve(identity).id == person.id
    assert attached.person_object_id == person.id
    assert attached.state != REJECTED_STATE


def test_reject_after_activation_suppresses_without_deleting(people_client, db_session) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Ada Lovelace")
    _email(db_session, "Ada Lovelace <ada@example.com>")
    identity = normalize_email("ada@example.com")
    payload = _payload(identity)
    _correct(people_client, person.id, "confirm", payload)
    rejected = _correct(people_client, person.id, "reject", payload)
    assert rejected.status_code == 200
    assert _card(people_client, person.id)["ada@example.com"] == "rejected"
    stored = _active_identities(db_session)
    assert len(stored) == 1
    restored = _correct(people_client, person.id, "retract", payload)
    assert restored.status_code == 200
    assert _card(people_client, person.id)["ada@example.com"] == "effective"
    assert PersonIdentityService(db_session, BOOTSTRAP_USER_ID).resolve(identity).id == person.id
    assert stored[0].state != REJECTED_STATE


def test_foreign_owner_conflict_and_cross_user_create_nothing(
    people_client, db_session, issue_bearer
) -> None:
    people = PersonIdentityService(db_session, BOOTSTRAP_USER_ID)
    owner = people.create_person("Ada Lovelace")
    other = people.create_person("Other Ada")
    identity = normalize_email("ada@example.com")
    people.attach(owner.id, identity)
    _email(db_session, "Ada Lovelace <ada@example.com>")
    payload = _payload(identity)
    evidence = PersonEvidenceService(db_session, BOOTSTRAP_USER_ID)
    evidence.record_confirmation(
        other.id, identity, f"test:user_confirmed:{identity.canonical_value}"
    )
    before_identities = len(_active_identities(db_session))
    before_evidence = db_session.scalar(select(func.count()).select_from(PersonIdentityEvidence))
    blocked = _correct(people_client, other.id, "confirm", payload)
    assert blocked.status_code == 422
    assert len(_active_identities(db_session)) == before_identities
    assert (
        db_session.scalar(select(func.count()).select_from(PersonIdentityEvidence))
        == before_evidence
    )

    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="other-c2"))
    db_session.flush()
    foreign = people_client.post(
        f"/graph/people/{owner.id}/identity-correction",
        json={"action": "confirm", **payload},
        headers={"Authorization": f"Bearer {issue_bearer(user_id)}"},
    )
    assert foreign.status_code == 404
    assert len(_active_identities(db_session)) == before_identities


def test_existing_confirmation_row_links_the_identity_it_activates(
    people_client, db_session
) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Ada Lovelace")
    identity = normalize_email("ada@example.com")
    _email(db_session, "Ada Lovelace <ada@example.com>")
    prior = PersonEvidenceService(db_session, BOOTSTRAP_USER_ID).record_confirmation(
        person.id,
        identity,
        f"graph_ui:user_confirmed:{identity.canonical_value}",
    )
    assert prior.person_identity_id is None
    confirmed = _correct(people_client, person.id, "confirm", _payload(identity))
    assert confirmed.json()["evidence_id"] == str(prior.id)
    db_session.refresh(prior)
    assert prior.person_identity_id == _active_identities(db_session)[0].id


def _correct(people_client, person_id, action: str, payload: dict):
    return people_client.post(
        f"/graph/people/{person_id}/identity-correction",
        json={"action": action, **payload},
    )


def _card(people_client, person_id) -> dict[str, str]:
    shown = people_client.get("/graph/people-workspace", params={"root_id": str(person_id)})
    assert shown.status_code == 200
    return {
        item["canonical_value"]: item["state"] for item in shown.json()["people"][0]["identities"]
    }


def _payload(identity) -> dict:
    return {
        "identity_type": identity.identity_type,
        "provider": identity.provider,
        "realm": identity.realm,
        "canonical_value": identity.canonical_value,
    }


def _active_identities(db_session) -> list[PersonIdentity]:
    return list(
        db_session.scalars(select(PersonIdentity).where(PersonIdentity.state != REJECTED_STATE))
    )


def _email(db_session, sender: str) -> Object:
    message = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        provider="gmail",
        title="Hello",
        origin="source",
        state="observed",
        occurred_at=datetime.now(UTC),
        metadata_={"sender": sender, "labels": ["INBOX"]},
    )
    db_session.add(message)
    db_session.flush()
    return message


def _telegram(db_session, realm: str) -> Object:
    message = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider="telegram",
        title="note",
        origin="source",
        state="observed",
        occurred_at=datetime.now(UTC),
        metadata_={
            "transport": "mtproto",
            "account_id": realm,
            "peer_kind": "private",
            "peer_id": 42,
            "sender_peer_id": 42,
            "direction": "inbound",
            "peer_title": "Olga Volkova",
        },
    )
    db_session.add(message)
    db_session.flush()
    return message
