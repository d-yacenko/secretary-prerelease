from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect

from alembic import command
from app.connectors.teams.normalize import normalize_teams_message
from app.db.engine import engine
from app.db.models import Object, PersonIdentity, User
from app.domain.person_identity import (
    PersonIdentityInputError,
    normalize_email,
    normalize_mattermost_user_id,
    normalize_mattermost_username,
    normalize_teams_user_id,
    normalize_telegram_user_id,
)
from app.domain.person_identity_evidence import extract_person_identity_evidence
from app.services.errors import ConflictError, ValidationError
from app.services.person_identity_service import PERSON_KIND, PersonIdentityService
from app.services.provenance import REJECTED_STATE

ROOT = Path(__file__).parents[1]
SERVER = "https://chat.example.com"
OTHER_SERVER = "https://other.example.com"
TENANT = "11111111-1111-1111-1111-111111111111"
TEAMS_USER = "22222222-2222-2222-2222-222222222222"
OTHER_TEAMS_USER = "33333333-3333-3333-3333-333333333333"


def test_0048_downgrade_and_upgrade() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    command.downgrade(config, "0047")
    names = set(inspect(engine).get_table_names())
    assert "person_identities" not in names
    assert "assistant_conversations" in names
    command.upgrade(config, "head")
    names = set(inspect(engine).get_table_names())
    assert "person_identities" in names


def test_email_normalization_casefolds() -> None:
    identity = normalize_email("  Olga <Olga@Example.COM>  ")
    assert identity.canonical_value == "olga@example.com"
    assert identity.provider == "email"
    assert identity.realm == ""
    assert identity.display_value == "Olga"


def test_malformed_identifiers_fail_closed() -> None:
    with pytest.raises(PersonIdentityInputError):
        normalize_email("not-an-email")
    with pytest.raises(PersonIdentityInputError):
        normalize_mattermost_user_id("http://chat.example.com", "user-1")
    with pytest.raises(PersonIdentityInputError):
        normalize_mattermost_username(SERVER, "Has Space")
    with pytest.raises(PersonIdentityInputError):
        normalize_teams_user_id(TENANT, "not-a-guid")
    with pytest.raises(PersonIdentityInputError):
        normalize_telegram_user_id("account-1", "abc")
    with pytest.raises(PersonIdentityInputError):
        normalize_telegram_user_id("account-1", 0)
    with pytest.raises(PersonIdentityInputError):
        normalize_telegram_user_id("account-1", -100)


def test_person_creation_and_exact_provider_uniqueness(db_session) -> None:
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Owner"))
    db_session.add(User(id=other_user_id, display_name="Other"))
    db_session.flush()
    service = PersonIdentityService(db_session, user_id)
    other = PersonIdentityService(db_session, other_user_id)

    person = service.create_person("  Olga  ")
    assert person.kind == PERSON_KIND
    assert person.user_id == user_id
    assert person.title == "Olga"

    email = normalize_email("Olga@Example.com")
    attached = service.attach(person.id, email)
    assert service.resolve(normalize_email("olga@example.com")).id == person.id
    assert service.attach(person.id, email).id == attached.id

    rival = service.create_person("Olga")
    with pytest.raises(ConflictError, match="person_identity_conflict"):
        service.attach(rival.id, normalize_email("olga@example.com"))
    assert service.resolve(email).id == person.id

    mattermost = normalize_mattermost_user_id(SERVER, "mm-user-1", display_value="Olga")
    service.attach(person.id, mattermost)
    same_server_other = service.create_person("Other server person")
    with pytest.raises(ConflictError, match="person_identity_conflict"):
        service.attach(same_server_other.id, normalize_mattermost_user_id(SERVER.upper(), "mm-user-1"))
    service.attach(
        same_server_other.id,
        normalize_mattermost_user_id(OTHER_SERVER, "mm-user-1"),
    )
    username = normalize_mattermost_username(SERVER, "Olga.User")
    service.attach(person.id, username)
    assert username.canonical_value == "olga.user"
    with pytest.raises(ConflictError, match="person_identity_conflict"):
        service.attach(rival.id, normalize_mattermost_username(SERVER, "olga.user"))

    teams = normalize_teams_user_id(TENANT, TEAMS_USER, display_value="Olga")
    service.attach(person.id, teams)
    with pytest.raises(ConflictError, match="person_identity_conflict"):
        service.attach(rival.id, normalize_teams_user_id(TENANT.upper(), TEAMS_USER))
    service.attach(rival.id, normalize_teams_user_id(TENANT, OTHER_TEAMS_USER))

    account = str(uuid.uuid4())
    telegram = normalize_telegram_user_id(account, "00042")
    assert telegram.canonical_value == "42"
    assert telegram.provider == "telegram_mtproto"
    service.attach(person.id, telegram)
    with pytest.raises(ConflictError, match="person_identity_conflict"):
        service.attach(rival.id, normalize_telegram_user_id(account, 42))
    other_account = str(uuid.uuid4())
    service.attach(rival.id, normalize_telegram_user_id(other_account, 42))

    other_person = other.create_person("Olga")
    other.attach(other_person.id, email)
    other.attach(other_person.id, mattermost)
    other.attach(other_person.id, teams)
    other.attach(other_person.id, telegram)
    assert other.resolve(email).id == other_person.id
    assert service.resolve(email).id == person.id

    assert service.resolve(normalize_email("olga@example.com")).title == "Olga"
    listed = service.list_identities(person.id)
    assert {row.identity_type for row in listed} >= {
        "email",
        "mattermost_user_id",
        "mattermost_username",
        "teams_user_id",
        "telegram_user_id",
    }


def test_display_name_alone_does_not_resolve_or_merge(db_session) -> None:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Owner"))
    db_session.flush()
    service = PersonIdentityService(db_session, user_id)
    first = service.create_person("Olga")
    second = service.create_person("Olga")
    display_only = Object(
        user_id=user_id,
        kind="chat_message",
        provider="mattermost",
        title="Olga",
        origin="source",
        state="observed",
        metadata_={"author_display_name": "Olga", "server_url": SERVER},
    )
    assert extract_person_identity_evidence(display_only) == ()
    assert service.list_identities(first.id) == []
    assert service.list_identities(second.id) == []
    assert first.id != second.id


def test_non_person_target_is_rejected(db_session) -> None:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Owner"))
    db_session.flush()
    message = Object(
        user_id=user_id,
        kind="email",
        title="Hello",
        origin="source",
        state="observed",
        metadata_={"sender": "olga@example.com"},
    )
    db_session.add(message)
    db_session.flush()
    service = PersonIdentityService(db_session, user_id)
    with pytest.raises(ValidationError, match="must be a person"):
        service.attach(message.id, normalize_email("olga@example.com"))


def test_detach_and_reassign_are_explicit(db_session) -> None:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Owner"))
    db_session.flush()
    service = PersonIdentityService(db_session, user_id)
    first = service.create_person("Olga")
    second = service.create_person("Correct Olga")
    row = service.attach(first.id, normalize_email("olga@example.com"))
    moved = service.reassign(row.id, second.id)
    assert moved.person_object_id == second.id
    assert service.resolve(normalize_email("olga@example.com")).id == second.id
    assert db_session.get(PersonIdentity, row.id).state == REJECTED_STATE
    service.detach(moved.id)
    assert service.resolve(normalize_email("olga@example.com")) is None
    rebound = service.attach(first.id, normalize_email("olga@example.com"))
    assert rebound.person_object_id == first.id


def _source(user_id: uuid.UUID, *, provider: str, kind: str, metadata: dict) -> Object:
    return Object(
        user_id=user_id,
        kind=kind,
        provider=provider,
        title="note",
        origin="source",
        state="observed",
        metadata_=metadata,
    )


def test_extractors_are_read_only_and_provider_scoped(db_session) -> None:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Owner"))
    db_session.flush()
    account = str(uuid.uuid4())
    shared = {
        "sender": "Olga <Olga@Example.com>",
        "server_url": SERVER,
        "author_user_id": "mm-user-1",
        "author_username": "Olga.User",
        "author_display_name": "Olga",
        "tenant_id": TENANT,
        "sender_id": TEAMS_USER,
        "sender_display_name": "Olga",
        "sender_kind": "user",
        "transport": "mtproto",
        "account_id": account,
        "sender_peer_id": 42,
    }
    email = _source(user_id, provider="gmail", kind="email", metadata=dict(shared))
    mattermost = _source(user_id, provider="mattermost", kind="chat_message", metadata=dict(shared))
    teams = _source(user_id, provider="teams", kind="chat_message", metadata=dict(shared))
    telegram = _source(user_id, provider="telegram", kind="chat_message", metadata=dict(shared))
    yandex = _source(user_id, provider="yandex_mail", kind="email", metadata=dict(shared))
    db_session.add_all([email, mattermost, teams, telegram, yandex])
    db_session.flush()
    before = dict(email.metadata_)
    email_keys = {
        (item.provider, item.identity_type, item.canonical_value)
        for item in extract_person_identity_evidence(email)
    }
    assert email.metadata_ == before
    assert email_keys == {("email", "email", "olga@example.com")}
    assert {
        (item.provider, item.identity_type, item.canonical_value)
        for item in extract_person_identity_evidence(yandex)
    } == {("email", "email", "olga@example.com")}
    assert {
        (item.provider, item.identity_type, item.canonical_value)
        for item in extract_person_identity_evidence(mattermost)
    } == {
        ("mattermost", "mattermost_user_id", "mm-user-1"),
        ("mattermost", "mattermost_username", "olga.user"),
    }
    assert {
        (item.provider, item.identity_type, item.canonical_value)
        for item in extract_person_identity_evidence(teams)
    } == {("teams", "teams_user_id", TEAMS_USER)}
    assert {
        (item.provider, item.identity_type, item.canonical_value)
        for item in extract_person_identity_evidence(telegram)
    } == {("telegram_mtproto", "telegram_user_id", "42")}
    unsupported = _source(user_id, provider="telegram", kind="task", metadata=dict(shared))
    assert extract_person_identity_evidence(unsupported) == ()


def test_telegram_non_user_sender_emits_no_person_evidence() -> None:
    user_id = uuid.uuid4()
    positive = normalize_telegram_user_id("account-1", 42)
    assert positive.canonical_value == "42"
    source = _source(
        user_id,
        provider="telegram",
        kind="chat_message",
        metadata={"transport": "mtproto", "account_id": "account-1", "sender_peer_id": 42},
    )
    assert extract_person_identity_evidence(source)[0].canonical_value == "42"
    for sender in (0, -100, "-7"):
        negative = _source(
            user_id,
            provider="telegram",
            kind="chat_message",
            metadata={
                "transport": "mtproto",
                "account_id": "account-1",
                "sender_peer_id": sender,
            },
        )
        assert extract_person_identity_evidence(negative) == ()


def test_teams_sender_kind_gates_person_evidence() -> None:
    account_id = uuid.uuid4()
    user_message = normalize_teams_message(
        message={
            "id": "message-1",
            "messageType": "message",
            "createdDateTime": "2026-09-16T08:00:00Z",
            "body": {"contentType": "text", "content": "hello"},
            "from": {"user": {"id": TEAMS_USER, "displayName": "Olga"}},
        },
        account_id=account_id,
        tenant_id=TENANT,
        microsoft_user_id=OTHER_TEAMS_USER,
        chat_id="chat-1",
        chat_type="oneOnOne",
        chat_display_title="Olga",
    )
    assert user_message is not None
    assert user_message["metadata"]["sender_kind"] == "user"
    assert user_message["title"].startswith("Olga:")
    user_source = _source(
        uuid.uuid4(),
        provider="teams",
        kind="chat_message",
        metadata=user_message["metadata"],
    )
    assert extract_person_identity_evidence(user_source)[0].canonical_value == TEAMS_USER

    app_message = normalize_teams_message(
        message={
            "id": "message-2",
            "messageType": "message",
            "createdDateTime": "2026-09-16T08:00:00Z",
            "body": {"contentType": "text", "content": "hello"},
            "from": {"application": {"id": TEAMS_USER, "displayName": "Bot"}},
        },
        account_id=account_id,
        tenant_id=TENANT,
        microsoft_user_id=OTHER_TEAMS_USER,
        chat_id="chat-1",
        chat_type="oneOnOne",
        chat_display_title="Bot",
    )
    assert app_message is not None
    assert app_message["metadata"]["sender_kind"] == "application"
    assert app_message["metadata"]["sender_id"] == TEAMS_USER
    assert app_message["title"].startswith("Bot:")
    app_source = _source(
        uuid.uuid4(),
        provider="teams",
        kind="chat_message",
        metadata=app_message["metadata"],
    )
    assert extract_person_identity_evidence(app_source) == ()
    for sender_kind in (None, "", "bot", "unknown"):
        legacy = _source(
            uuid.uuid4(),
            provider="teams",
            kind="chat_message",
            metadata={
                "tenant_id": TENANT,
                "sender_id": TEAMS_USER,
                "sender_display_name": "Olga",
                "sender_kind": sender_kind,
            },
        )
        assert extract_person_identity_evidence(legacy) == ()
    missing = _source(
        uuid.uuid4(),
        provider="teams",
        kind="chat_message",
        metadata={"tenant_id": TENANT, "sender_id": TEAMS_USER, "sender_display_name": "Olga"},
    )
    assert extract_person_identity_evidence(missing) == ()


def test_source_message_deletion_does_not_remove_person_identity(db_session) -> None:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Owner"))
    db_session.flush()
    message = Object(
        user_id=user_id,
        kind="email",
        title="Hello",
        origin="source",
        state="observed",
        metadata_={"sender": "olga@example.com"},
    )
    db_session.add(message)
    db_session.flush()
    service = PersonIdentityService(db_session, user_id)
    person = service.create_person("Olga")
    identity = service.attach(person.id, normalize_email(message.metadata_["sender"]))
    message.state = REJECTED_STATE
    db_session.delete(message)
    db_session.flush()
    assert db_session.get(PersonIdentity, identity.id) is not None
    assert service.resolve(normalize_email("olga@example.com")).id == person.id


def test_identity_layer_does_not_reference_ai_or_provider_calls() -> None:
    domain = (ROOT / "app/domain/person_identity.py").read_text()
    evidence = (ROOT / "app/domain/person_identity_evidence.py").read_text()
    service = (ROOT / "app/services/person_identity_service.py").read_text()
    combined = f"{domain}\n{evidence}\n{service}"
    assert "TELEGRAM_MTPROTO_AI" not in combined
    assert "openai" not in combined
    assert "EmbeddingService" not in combined
    assert "assistant" not in combined
