"""Rooted People review of source-derived identity candidates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.deps import get_db
from app.core.config import settings
from app.db.models import Edge, Object, PersonIdentity, User
from app.domain.object_visibility import tombstone_object
from app.domain.person_assistant import MAX_PERSON_CANDIDATES
from app.domain.person_identity import (
    normalize_email,
    normalize_mattermost_user_id,
    normalize_teams_user_id,
    normalize_telegram_user_id,
)
from app.domain.person_identity_evidence import extract_person_identity_evidence
from app.main import app
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_enrichment_service import PersonEnrichmentService
from app.services.person_identity_service import PersonIdentityService
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)
SERVER = "https://chat.example"
TENANT = "11111111-1111-4111-8111-111111111111"
TEAMS_USER = "22222222-2222-4222-8222-222222222222"
NAME = "R4qx Reviewname"


@pytest.fixture
def people_client(db_session, fake_embedding_service, auth_headers):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


def test_rooted_person_exposes_email_candidate_with_reason_and_source(
    people_client, db_session
) -> None:
    person = _person(db_session)
    message = _email(db_session, f"{NAME} <ada@example.com>", title="Ada wrote", body="secret body")
    card = _root(people_client, person.id)
    candidates = card["identity_candidates"]
    assert len(candidates) == 1
    item = candidates[0]
    assert item["provider"] == "email"
    assert item["identity_type"] == "email"
    assert item["canonical_value"] == "ada@example.com"
    assert item["display_value"] == NAME
    assert item["confirmable"] is True
    assert item["state"] == "candidate"
    assert item["reasons"] == ["name_similarity"]
    assert item["sources"] == [
        {
            "object_id": str(message.id),
            "kind": "email",
            "provider": "gmail",
            "title": "Ada wrote",
            "occurred_at": message.occurred_at.isoformat().replace("+00:00", "Z"),
        }
    ]
    assert "secret body" not in str(item)
    assert all(row["canonical_value"] != "ada@example.com" for row in card["identities"])


def test_telegram_private_candidate_is_first_party_while_model_stays_gated(
    people_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    person = _person(db_session)
    realm = "account-r4"
    _telegram(db_session, realm, peer_kind="private", sender=7, peer=7, peer_title=NAME)
    card = _root(people_client, person.id)
    identity = normalize_telegram_user_id(realm, 7)
    item = _one(card, identity.canonical_value)
    assert item["provider"] == identity.provider
    assert item["identity_type"] == identity.identity_type
    assert item["realm"] == realm
    assert item["confirmable"] is True
    hidden = PersonAssistantService(db_session, BOOTSTRAP_USER_ID).find_identity_candidates(
        person.id
    )
    assert hidden.candidates == []


def test_mattermost_dm_candidate_keeps_exact_realm_tuple(people_client, db_session) -> None:
    person = _person(db_session)
    _chat(
        db_session,
        provider="mattermost",
        metadata={
            "server_url": SERVER,
            "author_user_id": "olga-id",
            "author_display_name": NAME,
            "channel_type": "D",
        },
    )
    expected = normalize_mattermost_user_id(SERVER, "olga-id", display_value=NAME)
    item = _one(_root(people_client, person.id), expected.canonical_value)
    assert item["provider"] == expected.provider
    assert item["identity_type"] == expected.identity_type
    assert item["realm"] == expected.realm
    assert item["canonical_value"] == expected.canonical_value


def test_teams_one_on_one_candidate_keeps_tenant_scope(people_client, db_session) -> None:
    person = _person(db_session)
    _chat(
        db_session,
        provider="teams",
        metadata={
            "sender_kind": "user",
            "tenant_id": TENANT,
            "sender_id": TEAMS_USER,
            "sender_display_name": NAME,
            "chat_type": "oneOnOne",
        },
    )
    expected = normalize_teams_user_id(TENANT, TEAMS_USER, display_value=NAME)
    item = _one(_root(people_client, person.id), expected.canonical_value)
    assert item["provider"] == expected.provider
    assert item["identity_type"] == expected.identity_type
    assert item["realm"] == expected.realm
    assert item["canonical_value"] == expected.canonical_value


def test_non_eligible_contexts_stay_outside_current_extractor_candidates(
    people_client, db_session
) -> None:
    person = _person(db_session)
    recipient = _email(
        db_session, "noise@example.com", metadata={"to": f"{NAME} <ada@example.com>"}
    )
    bot = _chat(
        db_session,
        provider="teams",
        metadata={
            "sender_kind": "bot",
            "tenant_id": TENANT,
            "sender_id": TEAMS_USER,
            "sender_display_name": NAME,
            "chat_type": "group",
        },
    )
    unlabeled = _chat(
        db_session,
        provider="mattermost",
        metadata={"author_display_name": NAME, "channel_type": "O"},
    )
    group = _telegram(db_session, "account-r4", peer_kind="group", sender=7, peer=-100)
    extracted = extract_person_identity_evidence(recipient)
    assert extracted
    assert all(item.canonical_value != "ada@example.com" for item in extracted)
    assert extract_person_identity_evidence(bot) == ()
    assert extract_person_identity_evidence(unlabeled) == ()
    assert extract_person_identity_evidence(group) != ()
    assert _root(people_client, person.id)["identity_candidates"] == []


def test_candidate_list_preserves_existing_truncation(people_client, db_session) -> None:
    person = _person(db_session)
    for index in range(MAX_PERSON_CANDIDATES + 1):
        _email(db_session, f"{NAME} <ada{index}@example.com>")
    card = _root(people_client, person.id)
    assert len(card["identity_candidates"]) == MAX_PERSON_CANDIDATES
    assert card["identity_candidates_truncated"] is True


def test_source_previews_are_same_user_active_bounded_and_body_free(
    people_client, db_session
) -> None:
    person = _person(db_session)
    kept = [
        _email(db_session, f"{NAME} <ada@example.com>", title=f"note {index}", body="hidden body")
        for index in range(4)
    ]
    removed = kept[0]
    tombstone_object(removed)
    db_session.flush()
    other = uuid.uuid4()
    db_session.add(User(id=other, display_name="Other"))
    db_session.flush()
    foreign = Object(
        user_id=other,
        kind="email",
        provider="gmail",
        title="foreign",
        origin="source",
        state="observed",
        occurred_at=NOW,
        metadata_={"sender": f"{NAME} <ada@example.com>", "body": "other body"},
    )
    db_session.add(foreign)
    db_session.flush()
    item = _one(_root(people_client, person.id), "ada@example.com")
    sources = item["sources"]
    assert 1 <= len(sources) <= 3
    ids = {row["object_id"] for row in sources}
    assert str(removed.id) not in ids
    assert str(foreign.id) not in ids
    for row in sources:
        assert set(row) == {"object_id", "kind", "provider", "title", "occurred_at"}
        assert "hidden body" not in str(row)


def test_reading_candidates_does_not_create_person_identity(
    people_client, db_session, monkeypatch
) -> None:
    person = _person(db_session)
    _email(db_session, f"{NAME} <ada@example.com>")

    def fail_plan(self):
        raise AssertionError("enrichment plan")

    monkeypatch.setattr(PersonEnrichmentService, "plan", fail_plan)
    before = _count(db_session, PersonIdentity)
    edges = _count(db_session, Edge)
    card = _root(people_client, person.id)
    assert card["identity_candidates"]
    assert _count(db_session, PersonIdentity) == before
    assert _count(db_session, Edge) == edges


def test_confirm_uses_existing_correction_and_moves_endpoint_to_known(
    people_client, db_session
) -> None:
    person = _person(db_session)
    _email(db_session, f"{NAME} <ada@example.com>")
    item = _one(_root(people_client, person.id), "ada@example.com")
    confirmed = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "confirm", **_payload(item)},
    )
    assert confirmed.status_code == 200
    card = _root(people_client, person.id)
    assert card["identity_candidates"] == []
    known = [row for row in card["identities"] if row["canonical_value"] == "ada@example.com"]
    assert len(known) == 1
    assert known[0]["state"] == "effective"
    assert known[0]["provider"] == "email"


def test_other_person_ownership_stays_conflicted_and_is_not_reassigned(
    people_client, db_session
) -> None:
    person = _person(db_session)
    other = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Other owner")
    owned = normalize_email(f"{NAME} <ada@example.com>")
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).attach(other.id, owned)
    _email(db_session, f"{NAME} <ada@example.com>")
    item = _one(_root(people_client, person.id), "ada@example.com")
    assert item["confirmable"] is False
    assert item["state"] == "conflicted"
    assert "identity_conflict" in item["reasons"]
    assert item["conflicting_person_id"] is None
    blocked = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "confirm", **_payload(item)},
    )
    assert blocked.status_code == 422
    owner = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).resolve(owned)
    assert owner is not None and owner.id == other.id
    assert _root(people_client, person.id)["identities"] == []


def test_unrelated_owned_identity_is_not_a_merge_suggestion(people_client, db_session) -> None:
    person = _person(db_session)
    other = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Unrelated owner")
    owned = normalize_email("zzz-opaque@example.com")
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).attach(other.id, owned)
    _email(db_session, "zzz-opaque@example.com")
    card = _root(people_client, person.id)
    assert all(item["canonical_value"] != "zzz-opaque@example.com" for item in card["identity_candidates"])
    assert all(item["conflicting_person_id"] is None for item in card["identity_candidates"])


def test_same_source_cooccurrence_exposes_merge_target(people_client, db_session) -> None:
    person = _person(db_session)
    people = PersonIdentityService(db_session, BOOTSTRAP_USER_ID)
    people.attach(person.id, normalize_email(f"{NAME} <ada@example.com>"))
    other = people.create_person("Other owner")
    people.attach(other.id, normalize_email("other@example.com"))
    _email(
        db_session,
        f"{NAME} <ada@example.com>",
        metadata={"reply_to": "Other <other@example.com>"},
    )
    item = _one(_root(people_client, person.id), "other@example.com")
    assert item["state"] == "conflicted"
    assert item["confirmable"] is False
    assert "identity_conflict" in item["reasons"]
    assert item["conflicting_person_id"] == str(other.id)


def test_reject_suppresses_the_active_candidate(people_client, db_session) -> None:
    person = _person(db_session)
    _email(db_session, f"{NAME} <ada@example.com>")
    item = _one(_root(people_client, person.id), "ada@example.com")
    rejected = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "reject", **_payload(item)},
    )
    assert rejected.status_code == 200
    card = _root(people_client, person.id)
    assert card["identity_candidates"] == []
    assert card["identities"] == []


def test_rejected_candidate_is_reversible_and_retract_rediscovers_it(
    people_client, db_session
) -> None:
    person = _person(db_session)
    _email(db_session, f"{NAME} <ada@example.com>")
    item = _one(_root(people_client, person.id), "ada@example.com")
    people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "reject", **_payload(item)},
    )
    rejected = _root(people_client, person.id)["rejected_identity_candidates"]
    assert len(rejected) == 1
    assert rejected[0]["canonical_value"] == "ada@example.com"
    assert rejected[0]["provider"] == "email"
    restored = people_client.post(
        f"/graph/people/{person.id}/identity-correction",
        json={"action": "retract", **_payload(rejected[0])},
    )
    assert restored.status_code == 200
    card = _root(people_client, person.id)
    assert card["rejected_identity_candidates"] == []
    assert _one(card, "ada@example.com")["state"] == "candidate"


def test_overview_and_search_do_not_fan_out_candidates(
    people_client, db_session, monkeypatch
) -> None:
    person = _person(db_session)
    _email(db_session, f"{NAME} <ada@example.com>")
    calls = {"count": 0}
    original = PersonAssistantService.find_identity_candidates

    def wrapped(self, person_id, **kwargs):
        calls["count"] += 1
        return original(self, person_id, **kwargs)

    monkeypatch.setattr(PersonAssistantService, "find_identity_candidates", wrapped)
    overview = people_client.get("/graph/people-workspace").json()
    searched = people_client.get("/graph/people-workspace", params={"q": NAME}).json()
    assert calls["count"] == 0
    for payload in (overview, searched):
        for card in payload["people"]:
            assert card["identity_candidates"] == []
            assert card["rejected_identity_candidates"] == []
    rooted = people_client.get("/graph/people-workspace", params={"root_id": str(person.id)}).json()
    assert calls["count"] == 1
    assert rooted["people"][0]["identity_candidates"]


def test_candidate_review_does_not_create_person_flow_edge(people_client, db_session) -> None:
    person = _person(db_session)
    message = _email(db_session, f"{NAME} <ada@example.com>")
    before = _count(db_session, Edge)
    _root(people_client, person.id)
    assert _count(db_session, Edge) == before
    linked = db_session.scalar(
        select(func.count())
        .select_from(Edge)
        .where((Edge.source_id == message.id) | (Edge.target_id == message.id))
    )
    assert linked == 0


def _person(db_session):
    return PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(NAME)


def _root(people_client, person_id) -> dict:
    response = people_client.get("/graph/people-workspace", params={"root_id": str(person_id)})
    assert response.status_code == 200
    return response.json()["people"][0]


def _one(card: dict, canonical: str) -> dict:
    found = [item for item in card["identity_candidates"] if item["canonical_value"] == canonical]
    assert len(found) == 1
    return found[0]


def _payload(item: dict) -> dict:
    return {
        "identity_type": item["identity_type"],
        "provider": item["provider"],
        "realm": item["realm"],
        "canonical_value": item["canonical_value"],
    }


def _count(db_session, model) -> int:
    return db_session.scalar(select(func.count()).select_from(model))


def _email(
    db_session,
    sender: str,
    *,
    title: str = "mail",
    body: str | None = None,
    metadata: dict | None = None,
):
    payload = {"sender": sender, "labels": ["INBOX"]}
    if body is not None:
        payload["body"] = body
    if metadata:
        payload.update(metadata)
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        provider="gmail",
        title=title,
        origin="source",
        state="observed",
        occurred_at=NOW,
        metadata_=payload,
    )
    db_session.add(obj)
    db_session.flush()
    return obj


def _chat(db_session, *, provider: str, metadata: dict) -> Object:
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider=provider,
        title="chat",
        origin="source",
        state="observed",
        occurred_at=NOW,
        metadata_=metadata,
    )
    db_session.add(obj)
    db_session.flush()
    return obj


def _telegram(
    db_session, realm: str, *, peer_kind: str, sender: int, peer: int, peer_title: str | None = None
):
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
    return _chat(db_session, provider="telegram", metadata=metadata)
