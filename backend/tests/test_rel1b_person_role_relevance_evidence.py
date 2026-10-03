"""REL1B-A grounded known-Person role evidence in Personal Relevance snapshots."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy import event

from app.api.schemas import ObjectCreate
from app.domain.object_visibility import tombstone_object
from app.domain.person_identity import (
    normalize_email,
    normalize_mattermost_user_id,
    normalize_teams_user_id,
    normalize_telegram_user_id,
)
from app.personal_relevance.models import (
    PERSONAL_RELEVANCE_EVIDENCE_VERSION,
    PERSONAL_RELEVANCE_MAX_KNOWN_PEOPLE_PER_OBJECT,
    PERSONAL_RELEVANCE_MAX_ROLES_PER_KNOWN_PERSON,
)
from app.proactive.instructions import PROACTIVE_SYSTEM_INSTRUCTIONS
from app.services.graph_service import GraphService
from app.services.person_identity_service import PersonIdentityService
from app.services.person_role_service import PersonRoleService
from app.services.proactive_review_service import seed_context_from_evidence
from app.services.provenance import REJECTED_STATE
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_proactive_secretary_c import (
    _enable,
    _insight_answer,
    _install_provider,
    _noop_trace,
    _notifications,
)
from tests.test_workflow_intelligence_personal_relevance_e_b import (
    _graph,
    _identity,
    _labels,
    _service,
    _user,
)
from tests.test_workflow_intelligence_proactive_personalization_e_c import (
    ScriptedProactiveProvider,
    _proactive_payload,
)

MM_SERVER = "https://chat.example.com"


def test_evidence_version_is_two() -> None:
    assert PERSONAL_RELEVANCE_EVIDENCE_VERSION == 2


def test_exact_email_sender_role_appears_without_raw_address(db_session) -> None:
    user_id = _user(db_session)
    person = _people(db_session, user_id).create_person("Иван Роль")
    _people(db_session, user_id).attach(person.id, normalize_email("boss@example.com"))
    _roles(db_session, user_id).assign(person.id, "директор", "Arenadata")
    email = _email(
        db_session,
        user_id,
        {"sender": "Boss <boss@example.com>", "recipients": ["other@example.com"], "cc": []},
    )
    record = _one(db_session, user_id, email.id)
    assert len(record.known_people) == 1
    known = record.known_people[0]
    assert known.person_id == person.id
    assert known.display_name == "Иван Роль"
    assert known.source_roles == ("sender",)
    assert known.roles_truncated is False
    assert len(known.roles) == 1
    assert known.roles[0].role == "директор"
    assert known.roles[0].context == "Arenadata"
    dumped = json.dumps(known.to_payload())
    assert "boss@example.com" not in dumped
    assert "normalized_key" not in dumped


def test_unknown_sender_has_no_known_people(db_session) -> None:
    user_id = _user(db_session)
    email = _email(
        db_session,
        user_id,
        {"sender": "Nobody <nobody@example.com>", "recipients": ["other@example.com"]},
    )
    record = _one(db_session, user_id, email.id)
    assert record.known_people == ()
    assert record.known_people_truncated is False
    dumped = json.dumps(record.to_payload())
    assert "Nobody" not in dumped


def test_calendar_organizer_and_attendee_are_factual(db_session) -> None:
    user_id = _user(db_session)
    people = _people(db_session, user_id)
    organizer = people.create_person("Организатор")
    guest = people.create_person("Гость")
    people.attach(organizer.id, normalize_email("boss@example.com"))
    people.attach(guest.id, normalize_email("guest@example.com"))
    event = _graph(db_session, user_id).create_object(
        ObjectCreate(
            kind="event",
            title="Sync",
            origin="source",
            provider="google_calendar",
            metadata={
                "organizer": "Boss Name <boss@example.com>",
                "attendees": [{"email": "guest@example.com", "displayName": "Not A Key"}],
            },
        )
    )
    record = _one(db_session, user_id, event.id)
    by_id = {item.person_id: item for item in record.known_people}
    assert by_id[organizer.id].source_roles == ("organizer",)
    assert by_id[guest.id].source_roles == ("attendee",)
    assert "Not A Key" not in json.dumps(record.to_payload())


def test_chat_providers_use_exact_canonical_identities(db_session) -> None:
    user_id = _user(db_session)
    people = _people(db_session, user_id)
    author = people.create_person("Автор")
    peer = people.create_person("Собеседник")
    teammate = people.create_person("Коллега")
    mm = normalize_mattermost_user_id(MM_SERVER, "mm-author")
    account_id = str(uuid.uuid4())
    tg = normalize_telegram_user_id(account_id, 4242)
    tenant = str(uuid.uuid4())
    sender = str(uuid.uuid4())
    teams = normalize_teams_user_id(tenant, sender)
    people.attach(author.id, mm)
    people.attach(peer.id, tg)
    people.attach(teammate.id, teams)
    graph = _graph(db_session, user_id)
    mm_message = graph.create_object(
        ObjectCreate(
            kind="chat_message",
            title="MM",
            origin="source",
            provider="mattermost",
            metadata={
                "server_url": "https://chat.example.com/",
                "author_user_id": "mm-author",
                "author_display_name": "Display Only",
            },
        )
    )
    tg_message = graph.create_object(
        ObjectCreate(
            kind="chat_message",
            title="TG",
            origin="source",
            provider="telegram",
            metadata={
                "transport": "mtproto",
                "account_id": account_id,
                "direction": "outbound",
                "peer_kind": "private",
                "peer_id": 4242,
                "peer_title": "Visible Name",
            },
        )
    )
    teams_message = graph.create_object(
        ObjectCreate(
            kind="chat_message",
            title="Teams",
            origin="source",
            provider="teams",
            metadata={
                "sender_kind": "user",
                "direction": "inbound",
                "tenant_id": tenant,
                "sender_id": sender,
                "sender_display_name": "Teams Name",
            },
        )
    )
    outbound = graph.create_object(
        ObjectCreate(
            kind="chat_message",
            title="Teams out",
            origin="source",
            provider="teams",
            metadata={
                "sender_kind": "user",
                "direction": "outbound",
                "tenant_id": tenant,
                "sender_id": sender,
            },
        )
    )
    snapshot = _service(db_session).build_snapshot(
        user_id, [mm_message.id, tg_message.id, teams_message.id, outbound.id]
    )
    by_id = {item.object_id: item for item in snapshot.objects}
    assert by_id[mm_message.id].known_people[0].source_roles == ("author",)
    assert by_id[tg_message.id].known_people[0].source_roles == ("conversation_peer",)
    assert by_id[teams_message.id].known_people[0].source_roles == ("sender",)
    assert by_id[outbound.id].known_people == ()
    dumped = json.dumps(snapshot.to_payload())
    assert "Display Only" not in dumped
    assert "Visible Name" not in dumped
    assert "Teams Name" not in dumped


def test_same_person_unions_source_roles(db_session) -> None:
    user_id = _user(db_session)
    people = _people(db_session, user_id)
    person = people.create_person("Один")
    people.attach(person.id, normalize_email("boss@example.com"))
    people.attach(person.id, normalize_email("copy@example.com"))
    email = _email(
        db_session,
        user_id,
        {
            "sender": "boss@example.com",
            "recipients": ["other@example.com"],
            "cc": ["copy@example.com"],
        },
    )
    known = _one(db_session, user_id, email.id).known_people
    assert len(known) == 1
    assert known[0].source_roles == ("sender", "copied_recipient")


def test_hidden_and_foreign_people_are_absent(db_session) -> None:
    user_id = _user(db_session)
    other_id = _user(db_session)
    people = _people(db_session, user_id)
    rejected = people.create_person("Скрытый отказ")
    merged = people.create_person("Слитый")
    people.attach(rejected.id, normalize_email("rejected@example.com"))
    people.attach(merged.id, normalize_email("merged@example.com"))
    rejected.state = REJECTED_STATE
    tombstone_object(merged)
    db_session.flush()
    foreign = _people(db_session, other_id).create_person("Чужой")
    _people(db_session, other_id).attach(foreign.id, normalize_email("foreign@example.com"))
    email = _email(
        db_session,
        user_id,
        {
            "sender": "rejected@example.com",
            "recipients": ["merged@example.com"],
            "cc": ["foreign@example.com"],
        },
    )
    assert _one(db_session, user_id, email.id).known_people == ()


def test_only_active_roles_and_near_duplicates_stay_distinct(db_session) -> None:
    user_id = _user(db_session)
    person = _people(db_session, user_id).create_person("Роли")
    _people(db_session, user_id).attach(person.id, normalize_email("boss@example.com"))
    roles = _roles(db_session, user_id)
    roles.assign(person.id, "директор", "Arenadata")
    roles.assign(person.id, "генеральный директор")
    retracted = roles.assign(person.id, "наблюдатель")
    roles.retract(person.id, retracted.id)
    known = _one(
        db_session,
        user_id,
        _email(db_session, user_id, {"sender": "boss@example.com", "recipients": []}).id,
    ).known_people[0]
    assert [item.role for item in known.roles] == ["генеральный директор", "директор"]
    assert known.roles[1].context == "Arenadata"
    assert "наблюдатель" not in json.dumps(known.to_payload())


def test_role_cap_is_deterministic(db_session) -> None:
    user_id = _user(db_session)
    person = _people(db_session, user_id).create_person("Много ролей")
    _people(db_session, user_id).attach(person.id, normalize_email("boss@example.com"))
    names = [
        f"role-{index:02d}" for index in range(PERSONAL_RELEVANCE_MAX_ROLES_PER_KNOWN_PERSON + 1)
    ]
    for name in reversed(names):
        _roles(db_session, user_id).assign(person.id, name)
    known = _one(
        db_session,
        user_id,
        _email(db_session, user_id, {"sender": "boss@example.com", "recipients": []}).id,
    ).known_people[0]
    assert [item.role for item in known.roles] == names[
        :PERSONAL_RELEVANCE_MAX_ROLES_PER_KNOWN_PERSON
    ]
    assert known.roles_truncated is True


def test_known_person_cap_is_uuid_order_not_salience(db_session) -> None:
    user_id = _user(db_session)
    people = _people(db_session, user_id)
    created = []
    recipients = []
    for index in range(PERSONAL_RELEVANCE_MAX_KNOWN_PEOPLE_PER_OBJECT + 1):
        person = people.create_person(f"Person {index}")
        email = f"person-{index}@example.com"
        people.attach(person.id, normalize_email(email))
        created.append(person.id)
        recipients.append(email)
    email = _email(db_session, user_id, {"sender": "nobody@example.com", "recipients": recipients})
    record = _one(db_session, user_id, email.id)
    expected = tuple(sorted(created)[:PERSONAL_RELEVANCE_MAX_KNOWN_PEOPLE_PER_OBJECT])
    assert tuple(item.person_id for item in record.known_people) == expected
    assert record.known_people_truncated is True


def test_participant_role_changes_only_that_object_signature(db_session) -> None:
    user_id = _user(db_session)
    person = _people(db_session, user_id).create_person("Участник")
    other = _people(db_session, user_id).create_person("Другой")
    _people(db_session, user_id).attach(person.id, normalize_email("boss@example.com"))
    _people(db_session, user_id).attach(other.id, normalize_email("other@example.com"))
    email = _email(db_session, user_id, {"sender": "boss@example.com", "recipients": []})
    before = _signature(db_session, user_id, email.id)
    assignment = _roles(db_session, user_id).assign(person.id, "директор")
    changed = _signature(db_session, user_id, email.id)
    assert changed != before
    _roles(db_session, user_id).retract(person.id, assignment.id)
    assert _signature(db_session, user_id, email.id) == before
    _roles(db_session, user_id).assign(other.id, "наблюдатель")
    assert _signature(db_session, user_id, email.id) == before


def test_existing_evidence_remains(db_session) -> None:
    user_id = _user(db_session)
    _identity(db_session, user_id, email="alice@example.com")
    person = _people(db_session, user_id).create_person("Босс")
    _people(db_session, user_id).attach(person.id, normalize_email("boss@example.com"))
    _roles(db_session, user_id).assign(person.id, "директор")
    email = _email(
        db_session,
        user_id,
        {"sender": "boss@example.com", "recipients": ["alice@example.com"], "cc": []},
        title="Status",
    )
    label = _labels(db_session, user_id).create_label("Важно")
    _labels(db_session, user_id).assign_label(email.id, label.label.id)
    record = _one(db_session, user_id, email.id)
    assert record.title == "Status"
    assert record.updated_at is not None
    assert record.user_participation_roles == ("direct_recipient",)
    assert record.assigned_labels[0].title == "Важно"
    assert record.labels_truncated is False
    assert record.known_people[0].roles[0].role == "директор"


def test_roles_load_once_for_many_objects(db_session) -> None:
    user_id = _user(db_session)
    person = _people(db_session, user_id).create_person("Общий")
    _people(db_session, user_id).attach(person.id, normalize_email("boss@example.com"))
    _roles(db_session, user_id).assign(person.id, "директор")
    first = _email(db_session, user_id, {"sender": "boss@example.com", "recipients": []})
    second = _email(
        db_session, user_id, {"sender": "boss@example.com", "recipients": []}, title="Two"
    )
    statements: list[str] = []

    def before(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(db_session.connection(), "before_cursor_execute", before)
    try:
        snapshot = _service(db_session).build_snapshot(user_id, [first.id, second.id])
    finally:
        event.remove(db_session.connection(), "before_cursor_execute", before)
    identity_selects = [
        item
        for item in statements
        if "person_identities" in item and item.lstrip().startswith("select")
    ]
    role_selects = [
        item
        for item in statements
        if "person_role_assignments" in item and item.lstrip().startswith("select")
    ]
    assert len(identity_selects) == 1
    assert len(role_selects) == 1
    assert all(item.known_people[0].person_id == person.id for item in snapshot.objects)


def test_proactive_seed_does_not_expose_known_people(db_session) -> None:
    user_id = _user(db_session)
    person = _people(db_session, user_id).create_person("Скрытый носитель")
    _people(db_session, user_id).attach(person.id, normalize_email("boss@example.com"))
    _roles(db_session, user_id).assign(person.id, "директор-rel1b", "контекст-rel1b")
    email = _email(db_session, user_id, {"sender": "boss@example.com", "recipients": []})
    snapshot = _service(db_session).build_snapshot(user_id, [email.id])
    payload = seed_context_from_evidence([email], snapshot)
    dumped = json.dumps(payload)
    assert payload["evidence_version"] == 2
    assert "known_people" not in dumped
    assert "директор-rel1b" not in dumped
    assert "контекст-rel1b" not in dumped
    assert "Скрытый носитель" not in dumped
    seed = payload["seed_objects"][0]
    assert "user_participation_roles" in seed
    assert "assigned_labels" in seed
    assert "known_people" not in PROACTIVE_SYSTEM_INSTRUCTIONS


def test_role_change_discards_pending_notify(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.proactive_review_service.ai_trace_session",
        _noop_trace,
    )
    _enable(db_session)
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Участник")
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).attach(
        person.id, normalize_email("boss@example.com")
    )
    source = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="email",
            title="Role fence",
            origin="source",
            provider="gmail",
            metadata={"sender": "boss@example.com", "recipients": []},
        )
    )

    def mutate():
        PersonRoleService(db_session, BOOTSTRAP_USER_ID).assign(person.id, "директор")
        db_session.flush()

    provider = _install_provider(
        monkeypatch,
        ScriptedProactiveProvider(_insight_answer(source.id), after_tools=mutate),
    )
    before = len(_notifications(db_session))
    from app.services.proactive_review_service import ProactiveReviewService

    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 1
    assert len(_notifications(db_session)) == before


def test_no_role_weight_machinery() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "personal_relevance"
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert "director=" not in text
    assert "salience" not in text
    assert "priority_weight" not in text
    assert "role_weight" not in text


def _people(db_session, user_id) -> PersonIdentityService:
    return PersonIdentityService(db_session, user_id)


def _roles(db_session, user_id) -> PersonRoleService:
    return PersonRoleService(db_session, user_id)


def _email(db_session, user_id, metadata: dict, *, title: str = "Mail"):
    return _graph(db_session, user_id).create_object(
        ObjectCreate(
            kind="email",
            title=title,
            origin="source",
            provider="gmail",
            metadata=metadata,
        )
    )


def _one(db_session, user_id, object_id):
    snapshot = _service(db_session).build_snapshot(user_id, [object_id])
    assert len(snapshot.objects) == 1
    return snapshot.objects[0]


def _signature(db_session, user_id, object_id) -> str:
    snapshot = _service(db_session).build_snapshot(user_id, [object_id])
    return snapshot.object_evidence_signatures[str(object_id)]
