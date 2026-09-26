"""People recent_communication_count follows identity attribution, not edges."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.schemas import EdgeCreate
from app.db.models import Object, User
from app.domain.object_visibility import tombstone_object
from app.domain.person_identity import (
    normalize_email,
    normalize_mattermost_user_id,
    normalize_teams_user_id,
    normalize_telegram_user_id,
)
from app.main import app
from app.services.graph_service import GraphService
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE, USER_ORIGIN
from app.tools.schemas import FindPersonCommunicationsInput
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
SERVER = "https://chat.example"
TENANT = "11111111-1111-1111-1111-111111111111"
TEAMS_USER = "22222222-2222-2222-2222-222222222222"


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


def test_effective_email_counts_matching_mail_once_without_an_edge(
    people_client, db_session
) -> None:
    person = _people(db_session).create_person("Ada Lovelace")
    _people(db_session).attach(person.id, normalize_email("ada@example.com"))
    matched = _email(db_session, "ada@example.com", when=NOW)
    _email(db_session, "other@example.com", when=NOW - timedelta(hours=1))
    second = _email(db_session, "ada@example.com", when=NOW - timedelta(hours=2))
    third = _email(db_session, "ada@example.com", when=NOW - timedelta(hours=3))
    body = _workspace(people_client, person.id)
    assert body["people"][0]["recent_communication_count"] == 3
    assert body["people"][0]["open_task_count"] == 0
    assert str(matched.id) not in {node["id"] for node in body["nodes"]}
    assert {str(second.id), str(third.id)}.isdisjoint({node["id"] for node in body["nodes"]})
    assert body["edges"] == []


def test_edge_does_not_double_count_or_inflate_unrelated_mail(people_client, db_session) -> None:
    people = _people(db_session)
    person = people.create_person("Ada Lovelace")
    people.attach(person.id, normalize_email("ada@example.com"))
    matched = _email(db_session, "ada@example.com")
    unrelated = _email(db_session, "other@example.com", when=NOW - timedelta(hours=1))
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    for target in (matched, unrelated):
        graph.create_edge(
            EdgeCreate(
                source_id=person.id,
                target_id=target.id,
                type="related_to",
                origin=USER_ORIGIN,
                state=CONFIRMED_STATE,
            )
        )
    assert _count(people_client, person.id) == 1


def test_reject_and_retract_change_the_count(people_client, db_session) -> None:
    person = _people(db_session).create_person("Ada Lovelace")
    identity = normalize_email("ada@example.com")
    _people(db_session).attach(person.id, identity)
    _email(db_session, "Ada Lovelace <ada@example.com>")
    payload = _payload(identity)
    assert _count(people_client, person.id) == 1
    rejected = _correct(people_client, person.id, "reject", payload)
    assert rejected.status_code == 200
    assert _count(people_client, person.id) == 0
    restored = _correct(people_client, person.id, "retract", payload)
    assert restored.status_code == 200
    assert _count(people_client, person.id) == 1


def test_c2_confirm_and_retract_change_the_count(people_client, db_session) -> None:
    person = _people(db_session).create_person("Ada Lovelace")
    _email(db_session, "Ada Lovelace <ada@example.com>")
    payload = _payload(normalize_email("ada@example.com"))
    assert _count(people_client, person.id) == 0
    confirmed = _correct(people_client, person.id, "confirm", payload)
    assert confirmed.status_code == 200
    assert _count(people_client, person.id) == 1
    retracted = _correct(people_client, person.id, "retract", payload)
    assert retracted.status_code == 200
    assert _count(people_client, person.id) == 0


def test_hidden_and_foreign_mail_does_not_count(people_client, db_session) -> None:
    person = _people(db_session).create_person("Ada Lovelace")
    _people(db_session).attach(person.id, normalize_email("ada@example.com"))
    visible = _email(db_session, "ada@example.com")
    rejected = _email(db_session, "ada@example.com", when=NOW - timedelta(hours=1))
    rejected.state = REJECTED_STATE
    deleted = _email(db_session, "ada@example.com", when=NOW - timedelta(hours=2))
    tombstone_object(deleted, when=NOW)
    other_id = uuid.uuid4()
    db_session.add(User(id=other_id, display_name="other-c3"))
    db_session.flush()
    foreign = Object(
        user_id=other_id,
        kind="email",
        provider="gmail",
        title="foreign",
        origin="source",
        state="observed",
        occurred_at=NOW - timedelta(hours=3),
        metadata_={"sender": "ada@example.com", "labels": ["INBOX"]},
    )
    db_session.add(foreign)
    db_session.flush()
    assert _count(people_client, person.id) == 1
    assert visible.id != foreign.id


def test_direct_chats_count_and_name_only_groups_do_not(people_client, db_session) -> None:
    people = _people(db_session)
    person = people.create_person("Ada Lovelace")
    people.attach(person.id, normalize_mattermost_user_id(SERVER, "ada-id"))
    people.attach(person.id, normalize_teams_user_id(TENANT, TEAMS_USER))
    _chat(
        db_session,
        "mattermost",
        {
            "server_url": SERVER,
            "author_user_id": "ada-id",
            "channel_type": "D",
            "channel_id": "dm-1",
            "direction": "inbound",
        },
    )
    _chat(
        db_session,
        "mattermost",
        {
            "server_url": SERVER,
            "author_display_name": "Ada Lovelace",
            "channel_type": "O",
            "channel_id": "town",
            "direction": "inbound",
        },
        when=NOW - timedelta(hours=1),
    )
    _chat(
        db_session,
        "teams",
        {
            "tenant_id": TENANT,
            "sender_id": TEAMS_USER,
            "sender_kind": "user",
            "chat_type": "oneOnOne",
            "direction": "inbound",
        },
        when=NOW - timedelta(hours=2),
    )
    _chat(
        db_session,
        "teams",
        {
            "tenant_id": TENANT,
            "sender_display_name": "Ada Lovelace",
            "sender_kind": "application",
            "chat_type": "group",
            "direction": "inbound",
        },
        when=NOW - timedelta(hours=3),
    )
    assert _count(people_client, person.id) == 2


def test_first_party_telegram_counts_while_assistant_stays_gated(
    people_client, db_session, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    person = _people(db_session).create_person("Olga Volkova")
    realm = str(uuid.uuid4())
    _people(db_session).attach(person.id, normalize_telegram_user_id(realm, 7))
    _telegram(db_session, realm, peer_kind="private", sender=7, peer=7)
    _telegram(
        db_session,
        realm,
        peer_kind="group",
        sender=99,
        peer=-100,
        peer_title="Olga Volkova",
        when=NOW - timedelta(hours=1),
    )
    assert _count(people_client, person.id) == 1
    assistant = PersonAssistantService(db_session, BOOTSTRAP_USER_ID, now=NOW)
    page = assistant.find_communications(FindPersonCommunicationsInput(person_id=person.id))
    assert page.objects == []


def test_count_stops_at_the_communication_scan_budget(
    people_client, db_session, monkeypatch
) -> None:
    import app.services.person_assistant_service as assistant_module

    monkeypatch.setattr(assistant_module, "MAX_PERSON_SCAN_ROWS", 1)
    person = _people(db_session).create_person("Ada Lovelace")
    _people(db_session).attach(person.id, normalize_email("ada@example.com"))
    _email(db_session, "ada@example.com", when=NOW)
    _email(db_session, "ada@example.com", when=NOW - timedelta(hours=1))
    assert _count(people_client, person.id) == 1


def test_overview_attributes_people_from_one_shared_scan(
    people_client, db_session, monkeypatch
) -> None:
    import app.services.person_assistant_service as assistant_module

    calls = {"n": 0}
    original = assistant_module.PersonAssistantService._message_chunks

    def wrapped(self, payload, *, apply_telegram_ai_gate=True):
        calls["n"] += 1
        yield from original(self, payload, apply_telegram_ai_gate=apply_telegram_ai_gate)

    monkeypatch.setattr(assistant_module.PersonAssistantService, "_message_chunks", wrapped)
    people = _people(db_session)
    ada = people.create_person("Ada Lovelace")
    grace = people.create_person("Grace Hopper")
    people.attach(ada.id, normalize_email("ada@example.com"))
    people.attach(grace.id, normalize_email("grace@example.com"))
    _email(db_session, "ada@example.com")
    _email(db_session, "grace@example.com", when=NOW - timedelta(minutes=5))
    _email(db_session, "grace@example.com", when=NOW - timedelta(minutes=10))
    overview = people_client.get("/graph/people-workspace")
    assert overview.status_code == 200
    counts = {
        item["title"]: item["recent_communication_count"] for item in overview.json()["people"]
    }
    assert counts["Ada Lovelace"] == 1
    assert counts["Grace Hopper"] == 2
    assert calls["n"] == 1


def _people(db_session) -> PersonIdentityService:
    return PersonIdentityService(db_session, BOOTSTRAP_USER_ID)


def _workspace(people_client, person_id):
    response = people_client.get("/graph/people-workspace", params={"root_id": str(person_id)})
    assert response.status_code == 200
    return response.json()


def _count(people_client, person_id) -> int:
    return _workspace(people_client, person_id)["people"][0]["recent_communication_count"]


def _correct(people_client, person_id, action: str, payload: dict):
    return people_client.post(
        f"/graph/people/{person_id}/identity-correction",
        json={"action": action, **payload},
    )


def _payload(identity) -> dict:
    return {
        "identity_type": identity.identity_type,
        "provider": identity.provider,
        "realm": identity.realm,
        "canonical_value": identity.canonical_value,
    }


def _email(db_session, sender: str, *, when: datetime | None = None) -> Object:
    message = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        provider="gmail",
        title="Hello",
        origin="source",
        state="observed",
        occurred_at=when or NOW,
        metadata_={"sender": sender, "labels": ["INBOX"]},
    )
    db_session.add(message)
    db_session.flush()
    return message


def _chat(db_session, provider: str, metadata: dict, *, when: datetime | None = None) -> Object:
    message = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider=provider,
        title="chat",
        origin="source",
        state="observed",
        occurred_at=when or NOW,
        metadata_=metadata,
    )
    db_session.add(message)
    db_session.flush()
    return message


def _telegram(
    db_session,
    realm: str,
    *,
    peer_kind: str,
    sender: int,
    peer: int,
    peer_title: str | None = None,
    when: datetime | None = None,
) -> Object:
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
    return _chat(db_session, "telegram", metadata, when=when)
