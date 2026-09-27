"""Explicit first-party binding of one exact email to an existing Person."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import Edge, Object, PersonIdentity, PersonIdentityEvidence, User
from app.domain.person_identity import normalize_email
from app.main import app
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_identity_service import PersonIdentityService
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


def test_explicit_email_binds_and_casefolds(people_client, db_session) -> None:
    person = _people(db_session).create_person("Ada")
    bound = _bind(people_client, person.id, "  Ada@Example.COM  ")
    assert bound.status_code == 200
    assert bound.json()["evidence_type"] == "user_confirmed"
    identity = _identities(db_session)[0]
    assert identity.person_object_id == person.id
    assert identity.identity_type == "email"
    assert identity.provider == "email"
    assert identity.realm == ""
    assert identity.canonical_value == "ada@example.com"
    shown = _root(people_client, person.id)
    contact = next(item for item in shown["identities"] if item["canonical_value"] == "ada@example.com")
    assert contact["state"] == "effective"
    row = db_session.get(PersonIdentityEvidence, uuid.UUID(bound.json()["evidence_id"]))
    assert row.evidence_type == "user_confirmed"
    assert row.provenance_kind == "user_feedback"
    assert row.provenance_key == "graph_ui:manual_email:ada@example.com"
    assert row.explanation == "explicit manual email binding"
    assert row.person_identity_id == identity.id


def test_repeat_bind_is_idempotent(people_client, db_session) -> None:
    person = _people(db_session).create_person("Ada")
    first = _bind(people_client, person.id, "ada@example.com")
    second = _bind(people_client, person.id, "Ada@Example.com")
    assert second.status_code == 200
    assert second.json()["evidence_id"] == first.json()["evidence_id"]
    assert len(_identities(db_session)) == 1
    assert _evidence_count(db_session) == 1


def test_other_person_ownership_fails_closed(people_client, db_session) -> None:
    people = _people(db_session)
    owner = people.create_person("Ada")
    other = people.create_person("Bea")
    people.attach(owner.id, normalize_email("ada@example.com"))
    before_identities = len(_identities(db_session))
    before_evidence = _evidence_count(db_session)
    blocked = _bind(people_client, other.id, "ada@example.com")
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "person email is already bound"
    assert len(_identities(db_session)) == before_identities
    assert _evidence_count(db_session) == before_evidence
    assert _people(db_session).resolve(normalize_email("ada@example.com")).id == owner.id


def test_other_confirmation_fails_closed_without_reassign(people_client, db_session) -> None:
    people = _people(db_session)
    person = people.create_person("Ada")
    other = people.create_person("Bea")
    identity = normalize_email("ada@example.com")
    PersonEvidenceService(db_session, BOOTSTRAP_USER_ID).record_confirmation(
        other.id,
        identity,
        f"test:user_confirmed:{identity.canonical_value}",
    )
    before_identities = len(_identities(db_session))
    blocked = _bind(people_client, person.id, "ada@example.com")
    assert blocked.status_code == 409
    assert len(_identities(db_session)) == before_identities
    assert _people(db_session).resolve(identity) is None


def test_malformed_email_writes_nothing(people_client, db_session) -> None:
    person = _people(db_session).create_person("Ada")
    before_identities = len(_identities(db_session))
    before_evidence = _evidence_count(db_session)
    blocked = _bind(people_client, person.id, "not-an-email")
    assert blocked.status_code == 422
    assert blocked.json()["detail"] == "email identity is malformed"
    assert len(_identities(db_session)) == before_identities
    assert _evidence_count(db_session) == before_evidence


def test_identity_correction_still_requires_a_candidate(people_client, db_session) -> None:
    person = _people(db_session).create_person("Ada")
    before_identities = len(_identities(db_session))
    blocked = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={
            "action": "confirm",
            "identity_type": "email",
            "provider": "email",
            "realm": "",
            "canonical_value": "ada@example.com",
        },
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"] == "person identity was not exposed as a candidate"
    assert len(_identities(db_session)) == before_identities


def test_rejection_suppresses_and_retraction_restores(people_client, db_session) -> None:
    person = _people(db_session).create_person("Ada")
    _email(db_session, "ada@example.com")
    assert _bind(people_client, person.id, "ada@example.com").status_code == 200
    assert [item["title"] for item in _root(people_client, person.id)["recent_communications"]] == ["Grounded"]
    payload = {
        "identity_type": "email",
        "provider": "email",
        "realm": "",
        "canonical_value": "ada@example.com",
    }
    rejected = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "reject", **payload},
    )
    assert rejected.status_code == 200
    shown = _root(people_client, person.id)
    assert shown["recent_communications"] == []
    assert next(item["state"] for item in shown["identities"] if item["canonical_value"] == "ada@example.com") == "rejected"
    restored = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "retract", **payload},
    )
    assert restored.status_code == 200
    shown = _root(people_client, person.id)
    assert [item["title"] for item in shown["recent_communications"]] == ["Grounded"]
    assert next(item["state"] for item in shown["identities"] if item["canonical_value"] == "ada@example.com") == "effective"


def test_binding_does_not_materialize_a_flow_edge(people_client, db_session) -> None:
    person = _people(db_session).create_person("Ada")
    _email(db_session, "ada@example.com")
    before = db_session.scalar(select(func.count()).select_from(Edge))
    assert _bind(people_client, person.id, "ada@example.com").status_code == 200
    assert db_session.scalar(select(func.count()).select_from(Edge)) == before


def test_binding_is_isolated_to_the_current_user(people_client, db_session, issue_bearer) -> None:
    person = _people(db_session).create_person("Ada")
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="other-r3"))
    db_session.flush()
    before = len(_identities(db_session))
    foreign = people_client.post(
        f"/graph/people/{person.id}/emails",
        json={"email": "ada@example.com"},
        headers={"Authorization": f"Bearer {issue_bearer(user_id)}"},
    )
    assert foreign.status_code == 404
    assert len(_identities(db_session)) == before


def _bind(people_client, person_id, email: str):
    return people_client.post(f"/graph/people/{person_id}/emails", json={"email": email})


def _root(people_client, person_id) -> dict:
    response = people_client.get("/graph/people-workspace", params={"root_id": str(person_id)})
    assert response.status_code == 200
    return next(item for item in response.json()["people"] if item["person_id"] == str(person_id))


def _people(db_session) -> PersonIdentityService:
    return PersonIdentityService(db_session, BOOTSTRAP_USER_ID)


def _identities(db_session) -> list[PersonIdentity]:
    return list(db_session.scalars(select(PersonIdentity)))


def _evidence_count(db_session) -> int:
    return db_session.scalar(select(func.count()).select_from(PersonIdentityEvidence))


def _email(db_session, sender: str) -> None:
    db_session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="email",
            provider="gmail",
            title="Grounded",
            origin="source",
            state="observed",
            occurred_at=NOW,
            metadata_={"sender": sender, "labels": ["INBOX"]},
        )
    )
    db_session.flush()
