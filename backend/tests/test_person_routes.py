"""Person route discovery and send-by-person through the existing send tools."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet

from app.assistant import session as assistant_session_module
from app.assistant.tool_runner import BoundAssistantToolRunner, PerTurnToolBudget
from app.connectors.google.constants import GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.mattermost.credentials import MattermostAccountStore
from app.connectors.mattermost.normalize import build_external_id
from app.core.config import settings
from app.db.models import Object, PersonIdentity, PersonIdentityEvidence, User
from app.domain.person_identity import (
    normalize_email,
    normalize_mattermost_user_id,
    normalize_teams_user_id,
    normalize_telegram_user_id,
)
from app.services.domain_tool_service import DomainToolService
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_identity_service import PersonIdentityService
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.schemas import (
    ListPersonRoutesInput,
    SendEmailOutput,
    SendMessageOutput,
)

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
SERVER = "https://mm.example.com"
TENANT = "11111111-1111-1111-1111-111111111111"
TEAMS_USER = "22222222-2222-2222-2222-222222222222"
ACCOUNT = "account-1"


def test_one_email_route_is_exposed(db_session) -> None:
    user_id = _user(db_session)
    person = _person_with_email(db_session, user_id, "olga@example.com")
    page = PersonAssistantService(db_session, user_id, now=NOW).list_routes(
        ListPersonRoutesInput(person_id=person.id)
    )
    assert page.ambiguous is False
    assert [route.route_key for route in page.routes] == ["email:olga@example.com"]
    assert page.routes[0].route_kind == "email"


def test_two_email_routes_stay_ambiguous_until_one_is_named(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    person = _person_with_email(db_session, user_id, "olga@example.com")
    PersonIdentityService(db_session, user_id).attach(person.id, normalize_email("work@example.com"))
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    runner("resolve_person", {"query": "olga@example.com"})
    budget.commit_model_visible_outputs()
    listed = runner("list_person_routes", {"person_id": str(person.id)})
    assert listed.output["ambiguous"] is True
    assert len(listed.output["routes"]) == 2
    assert budget.staged_actions == []
    budget.commit_model_visible_outputs()
    invented = runner(
        "send_email",
        {
            "person_id": str(person.id),
            "to": ["other@example.com"],
            "subject": "Hi",
            "body": "Moved",
        },
    )
    assert invented.success is False
    assert budget.staged_actions == []


def test_provider_constraint_narrows_email_and_teams(db_session) -> None:
    user_id = _user(db_session)
    person = _person_with_email(db_session, user_id, "olga@example.com")
    PersonIdentityService(db_session, user_id).attach(
        person.id, normalize_teams_user_id(TENANT, TEAMS_USER)
    )
    _teams(db_session, user_id, chat_type="oneOnOne", sender=TEAMS_USER, direction="inbound")
    service = PersonAssistantService(db_session, user_id, now=NOW)
    both = service.list_routes(ListPersonRoutesInput(person_id=person.id))
    email_only = service.list_routes(ListPersonRoutesInput(person_id=person.id, provider="email"))
    assert both.ambiguous is True
    assert {route.provider for route in both.routes} == {"email", "teams"}
    assert [route.provider for route in email_only.routes] == ["email"]
    assert email_only.ambiguous is False


def test_rejected_identity_is_not_a_route(db_session) -> None:
    user_id = _user(db_session)
    person = _person_with_email(db_session, user_id, "olga@example.com")
    rejected = normalize_email("old@example.com")
    PersonIdentityService(db_session, user_id).attach(person.id, rejected)
    PersonEvidenceService(db_session, user_id).record_rejection(person.id, rejected, "reject-old")
    page = PersonAssistantService(db_session, user_id, now=NOW).list_routes(
        ListPersonRoutesInput(person_id=person.id)
    )
    assert [route.route_key for route in page.routes] == ["email:olga@example.com"]


def test_deleted_person_is_excluded(db_session) -> None:
    from app.domain.object_visibility import tombstone_object
    from app.services.errors import NotFoundError

    user_id = _user(db_session)
    person = _person_with_email(db_session, user_id, "olga@example.com")
    tombstone_object(person)
    db_session.flush()
    with pytest.raises(NotFoundError):
        PersonAssistantService(db_session, user_id, now=NOW).list_routes(
            ListPersonRoutesInput(person_id=person.id)
        )
    other = _user(db_session)
    foreign = _person_with_email(db_session, other, "foreign@example.com")
    with pytest.raises(NotFoundError):
        PersonAssistantService(db_session, user_id, now=NOW).list_routes(
            ListPersonRoutesInput(person_id=foreign.id)
        )


def test_mattermost_public_channel_is_not_a_person_route(db_session) -> None:
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    PersonIdentityService(db_session, user_id).attach(
        person.id, normalize_mattermost_user_id(SERVER, "olga-id")
    )
    _mattermost(
        db_session, user_id, channel_type="O", channel_id="town", author="olga-id", post_id="town-1"
    )
    direct = _mattermost(
        db_session, user_id, channel_type="D", channel_id="dm-1", author="olga-id", post_id="dm-1"
    )
    page = PersonAssistantService(db_session, user_id, now=NOW).list_routes(
        ListPersonRoutesInput(person_id=person.id)
    )
    assert [route.anchor_object_id for route in page.routes] == [direct.id]
    assert page.routes[0].provider == "mattermost"


def test_teams_group_is_not_a_person_route(db_session) -> None:
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    PersonIdentityService(db_session, user_id).attach(
        person.id, normalize_teams_user_id(TENANT, TEAMS_USER)
    )
    _teams(db_session, user_id, chat_type="group", sender=TEAMS_USER, direction="inbound")
    direct = _teams(db_session, user_id, chat_type="oneOnOne", sender=TEAMS_USER, direction="inbound")
    page = PersonAssistantService(db_session, user_id, now=NOW).list_routes(
        ListPersonRoutesInput(person_id=person.id)
    )
    assert [route.anchor_object_id for route in page.routes] == [direct.id]


def test_telegram_routes_follow_ai_eligibility(db_session, monkeypatch) -> None:
    from app.db.models import TelegramMtprotoAccount, TelegramMtprotoChatSelection

    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    user_id = _user(db_session)
    account = TelegramMtprotoAccount(
        user_id=user_id, telegram_user_id=616161, session_encrypted="encrypted"
    )
    db_session.add(account)
    db_session.flush()
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    PersonIdentityService(db_session, user_id).attach(
        person.id, normalize_telegram_user_id(str(account.id), 7)
    )
    db_session.add(
        TelegramMtprotoChatSelection(
            account_id=account.id,
            peer_id=7,
            peer_kind="private",
            provider_peer_reference_encrypted="encrypted",
            title="Olga",
            manual_selected=False,
            scope_active=True,
        )
    )
    db_session.flush()
    _telegram(
        db_session,
        user_id,
        peer_kind="group",
        sender=7,
        peer=-100,
        direction="inbound",
        account_id=str(account.id),
    )
    inbound = _telegram(
        db_session,
        user_id,
        peer_kind="private",
        sender=7,
        peer=7,
        direction="inbound",
        account_id=str(account.id),
    )
    hidden = PersonAssistantService(db_session, user_id, now=NOW).list_routes(
        ListPersonRoutesInput(person_id=person.id)
    )
    assert hidden.routes == []
    assert "telegram_user_id" not in hidden.model_dump_json()
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    visible = PersonAssistantService(db_session, user_id, now=NOW).list_routes(
        ListPersonRoutesInput(person_id=person.id)
    )
    assert [route.anchor_object_id for route in visible.routes] == [inbound.id]


def test_explicit_route_choice_is_idempotent_preference(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    people.attach(person.id, normalize_email("olga@example.com"))
    people.attach(person.id, normalize_email("work@example.com"))
    service = PersonAssistantService(db_session, user_id, now=NOW)
    evidence = PersonEvidenceService(db_session, user_id)
    first = service.record_route_choice(person.id, "email:work@example.com")
    score = evidence.score(person.id, normalize_email("work@example.com")).score
    second = service.record_route_choice(person.id, "email:work@example.com")
    page = service.list_routes(ListPersonRoutesInput(person_id=person.id))
    assert first.evidence_id == second.evidence_id
    assert first.evidence_type == "user_route_choice"
    assert evidence.score(person.id, normalize_email("work@example.com")).score == score
    assert page.ambiguous is True
    assert page.routes[0].route_key == "email:work@example.com"
    assert page.routes[0].has_route_choice is True
    assert _count(db_session, PersonIdentity, user_id) == 2
    assert _count(db_session, PersonIdentityEvidence, user_id) == 1


def test_teams_route_choice_stays_on_one_conversation(db_session) -> None:
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    identity = normalize_teams_user_id(TENANT, TEAMS_USER)
    PersonIdentityService(db_session, user_id).attach(person.id, identity)
    _teams(
        db_session,
        user_id,
        chat_type="oneOnOne",
        sender=TEAMS_USER,
        direction="inbound",
        chat_id="chat-a",
        occurred_at=NOW - timedelta(hours=2),
    )
    _teams(
        db_session,
        user_id,
        chat_type="oneOnOne",
        sender=TEAMS_USER,
        direction="inbound",
        chat_id="chat-b",
        occurred_at=NOW - timedelta(hours=1),
    )
    service = PersonAssistantService(db_session, user_id, now=NOW)
    evidence = PersonEvidenceService(db_session, user_id)
    before = service.list_routes(ListPersonRoutesInput(person_id=person.id))
    key_a = f"teams:{TENANT}:chat-a"
    key_b = f"teams:{TENANT}:chat-b"
    assert {route.route_key for route in before.routes} == {key_a, key_b}
    assert before.ambiguous is True
    assert all(route.has_route_choice is False for route in before.routes)
    first = service.record_route_choice(person.id, key_a)
    score = evidence.score(person.id, identity).score
    second = service.record_route_choice(person.id, key_a)
    chosen = {
        route.route_key: route
        for route in service.list_routes(ListPersonRoutesInput(person_id=person.id)).routes
    }
    assert first.evidence_id == second.evidence_id
    assert evidence.score(person.id, identity).score == score
    assert chosen[key_a].has_route_choice is True
    assert chosen[key_b].has_route_choice is False
    assert next(iter(chosen)) == key_a
    assert len(chosen) == 2
    later = service.record_route_choice(person.id, key_b)
    both = service.list_routes(ListPersonRoutesInput(person_id=person.id))
    assert later.evidence_id != first.evidence_id
    assert {route.route_key for route in both.routes if route.has_route_choice} == {key_a, key_b}
    assert both.ambiguous is True
    assert _count(db_session, PersonIdentityEvidence, user_id) == 2
    assert db_session.get(PersonIdentityEvidence, first.evidence_id).state == "active"


def test_filtered_route_choice_is_not_starved_by_other_providers(db_session) -> None:
    from app.domain.object_visibility import tombstone_object
    from app.domain.person_assistant import MAX_PERSON_ROUTES
    from app.services.errors import ValidationError

    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    PersonIdentityService(db_session, user_id).attach(
        person.id, normalize_mattermost_user_id(SERVER, "olga-id")
    )
    PersonIdentityService(db_session, user_id).attach(
        person.id, normalize_teams_user_id(TENANT, TEAMS_USER)
    )
    for index in range(MAX_PERSON_ROUTES):
        _mattermost(
            db_session,
            user_id,
            channel_type="D",
            channel_id=f"dm-{index}",
            author="olga-id",
            post_id=f"post-{index}",
            occurred_at=NOW - timedelta(minutes=index),
        )
    teams = _teams(
        db_session,
        user_id,
        chat_type="oneOnOne",
        sender=TEAMS_USER,
        direction="inbound",
        chat_id="chat-old",
        occurred_at=NOW - timedelta(days=3),
    )
    service = PersonAssistantService(db_session, user_id, now=NOW)
    unfiltered = service.list_routes(ListPersonRoutesInput(person_id=person.id))
    teams_key = f"teams:{TENANT}:chat-old"
    assert teams_key not in {route.route_key for route in unfiltered.routes}
    assert unfiltered.truncated is True
    filtered = service.list_routes(ListPersonRoutesInput(person_id=person.id, provider="teams"))
    assert [route.route_key for route in filtered.routes] == [teams_key]
    recorded = service.record_route_choice(person.id, teams_key)
    assert recorded.evidence_type == "user_route_choice"
    visible = service.list_routes(ListPersonRoutesInput(person_id=person.id, provider="teams"))
    assert visible.routes[0].has_route_choice is True
    tombstone_object(teams)
    db_session.flush()
    with pytest.raises(ValidationError, match="person route was not exposed"):
        service.record_route_choice(person.id, teams_key)
    with pytest.raises(ValidationError, match="person route was not exposed"):
        service.record_route_choice(person.id, "not-a-route")


def test_same_turn_allowlist_blocks_an_unexposed_route(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    person = _person_with_email(db_session, user_id, "olga@example.com")
    PersonIdentityService(db_session, user_id).attach(
        person.id, normalize_teams_user_id(TENANT, TEAMS_USER)
    )
    _teams(db_session, user_id, chat_type="oneOnOne", sender=TEAMS_USER, direction="inbound")
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    runner("resolve_person", {"query": "olga@example.com"})
    budget.commit_model_visible_outputs()
    runner("list_person_routes", {"person_id": str(person.id), "provider": "email"})
    budget.commit_model_visible_outputs()
    blocked = runner(
        "record_person_route_choice",
        {"person_id": str(person.id), "route_key": f"teams:{TENANT}:chat-1"},
    )
    assert blocked.success is False
    assert "not exposed" in (blocked.error or "")
    assert _count(db_session, PersonIdentityEvidence, user_id) == 0


def test_person_email_stages_existing_send_and_stays_frozen(
    db_session, monkeypatch, tmp_path
) -> None:
    _patch_session(db_session, monkeypatch)
    key = Fernet.generate_key().decode()
    client_file = tmp_path / "google-oauth-client.json"
    client_file.write_text(
        '{"web": {"client_id": "test-client-id", "client_secret": "test-client-secret"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "secretary_credential_key", key)
    monkeypatch.setattr(settings, "google_oauth_client_file", str(client_file))
    monkeypatch.setattr(settings, "google_redirect_uri", "http://localhost/auth/google/callback")
    user_id = _user(db_session)
    GoogleAccountStore(db_session, CredentialEncryption(key)).upsert_tokens(
        user_id=user_id,
        email="me@example.com",
        scopes=[GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
    )
    person = _person_with_email(db_session, user_id, "olga@example.com")
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    runner("resolve_person", {"query": "olga@example.com"})
    budget.commit_model_visible_outputs()
    runner("list_person_routes", {"person_id": str(person.id)})
    budget.commit_model_visible_outputs()
    staged = runner(
        "send_email",
        {
            "person_id": str(person.id),
            "to": ["olga@example.com"],
            "subject": "Meeting",
            "body": "Moved",
        },
    )
    assert staged.approval_required is True
    frozen = budget.staged_actions[0]["arguments"]
    assert frozen["provider"] == "google"
    assert frozen["account_email"] == "me@example.com"
    assert frozen["to"] == ["olga@example.com"]
    assert frozen["subject"] == "Meeting"
    assert frozen["body"] == "Moved"
    assert frozen["operation_id"]
    assert frozen["rfc822_message_id"]
    assert "person_id" not in frozen
    PersonEvidenceService(db_session, user_id).record_rejection(
        person.id, normalize_email("olga@example.com"), "reject-after-stage"
    )
    captured: list = []

    def _capture_send(self, payload):
        captured.append(payload)
        return SendEmailOutput(
            provider="gmail",
            account_email=payload.account_email,
            to=list(payload.to),
            subject=payload.subject,
            provider_message_id="m1",
            delivery_status="sent",
            changed=True,
        )

    monkeypatch.setattr(
        "app.services.domain_tool_service.DomainToolService.send_email", _capture_send
    )
    executed = ToolExecutionGateway().execute(
        DomainToolService(db_session, user_id, None),
        "send_email",
        frozen,
        ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert executed.success is True
    assert captured[0].to == ["olga@example.com"]


def test_person_chat_stages_existing_send_and_stays_frozen(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "secretary_credential_key", key)
    monkeypatch.setattr(settings, "mattermost_allowed_base_urls", SERVER)
    user_id = _user(db_session)
    account = MattermostAccountStore(
        db_session, MattermostAccountStore.build_encryption(key)
    ).upsert_account(
        user_id=user_id,
        normalized_server_url=SERVER,
        remote_user_id="me-id",
        username="me",
        access_token="mattermost-token",
        display_name="Me",
        email="me@example.com",
    )
    db_session.flush()
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    attached = PersonIdentityService(db_session, user_id).attach(
        person.id, normalize_mattermost_user_id(SERVER, "olga-id")
    )
    anchor = _mattermost(
        db_session,
        user_id,
        channel_type="D",
        channel_id="dm-1",
        author="olga-id",
        account_id=str(account.id),
        post_id="post-1",
    )
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    runner("resolve_person", {"query": "Olga Volkova"})
    budget.commit_model_visible_outputs()
    runner("list_person_routes", {"person_id": str(person.id)})
    budget.commit_model_visible_outputs()
    plain = runner(
        "send_message",
        {"conversation_object_id": str(anchor.id), "body": "Hello"},
    )
    assert plain.approval_required is True
    budget2 = PerTurnToolBudget()
    runner2 = BoundAssistantToolRunner(budget2, user_id)
    runner2("resolve_person", {"query": "Olga Volkova"})
    budget2.commit_model_visible_outputs()
    runner2("list_person_routes", {"person_id": str(person.id)})
    budget2.commit_model_visible_outputs()
    staged = runner2(
        "send_message",
        {
            "person_id": str(person.id),
            "conversation_object_id": str(anchor.id),
            "body": "Hello",
        },
    )
    assert staged.approval_required is True
    frozen = budget2.staged_actions[0]["arguments"]
    assert frozen["provider"] == "mattermost"
    assert frozen["anchor_object_id"] == str(anchor.id)
    assert frozen["route"]["channel_id"] == "dm-1"
    assert frozen["route"]["account_id"] == str(account.id)
    assert frozen["body"] == "Hello"
    assert frozen["operation_id"]
    assert "person_id" not in frozen
    PersonIdentityService(db_session, user_id).detach(attached.id)
    captured: list = []

    def _capture_send(self, payload):
        captured.append(payload)
        return SendMessageOutput(
            provider="mattermost",
            mode=payload.mode,
            provider_message_id="p1",
            delivery_status="sent",
            changed=True,
        )

    monkeypatch.setattr(
        "app.services.domain_tool_service.DomainToolService.send_message", _capture_send
    )
    executed = ToolExecutionGateway().execute(
        DomainToolService(db_session, user_id, None),
        "send_message",
        frozen,
        ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert executed.success is True
    assert captured[0].route.channel_id == "dm-1"


class _SessionProxy:
    def __init__(self, session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def commit(self) -> None:
        self._session.flush()

    def rollback(self) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(self._session, name)


def _patch_session(db_session, monkeypatch) -> None:
    monkeypatch.setattr(assistant_session_module, "SessionLocal", lambda: _SessionProxy(db_session))
    monkeypatch.setattr(
        "app.assistant.session.resolve_embedding_service_for_user",
        lambda session, user_id: None,
    )


def _user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Owner"))
    db_session.flush()
    return user_id


def _person_with_email(db_session, user_id, address: str):
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    PersonIdentityService(db_session, user_id).attach(person.id, normalize_email(address))
    return person


def _count(db_session, model, user_id: uuid.UUID) -> int:
    from sqlalchemy import func, select

    return int(db_session.scalar(select(func.count()).select_from(model).where(model.user_id == user_id)) or 0)


def _mattermost(
    db_session,
    user_id,
    *,
    channel_type: str,
    channel_id: str,
    author: str,
    account_id: str = ACCOUNT,
    post_id: str = "post-1",
    occurred_at: datetime | None = None,
) -> Object:
    obj = Object(
        user_id=user_id,
        kind="chat_message",
        provider="mattermost",
        title="Olga",
        origin="source",
        state="observed",
        external_id=build_external_id(SERVER, post_id),
        occurred_at=NOW - timedelta(hours=1) if occurred_at is None else occurred_at,
        metadata_={
            "server_url": SERVER,
            "account_id": account_id,
            "post_id": post_id,
            "channel_id": channel_id,
            "channel_type": channel_type,
            "channel_display_name": "Olga",
            "author_user_id": author,
            "direction": "inbound",
        },
    )
    db_session.add(obj)
    db_session.flush()
    return obj


def _teams(
    db_session,
    user_id,
    *,
    chat_type: str,
    sender: str,
    direction: str,
    chat_id: str = "chat-1",
    occurred_at: datetime | None = None,
) -> Object:
    obj = Object(
        user_id=user_id,
        kind="chat_message",
        provider="teams",
        title="Olga",
        origin="source",
        state="observed",
        occurred_at=NOW - timedelta(hours=1) if occurred_at is None else occurred_at,
        metadata_={
            "tenant_id": TENANT,
            "sender_id": sender,
            "sender_kind": "user",
            "chat_type": chat_type,
            "chat_id": chat_id,
            "direction": direction,
        },
    )
    db_session.add(obj)
    db_session.flush()
    return obj


def _telegram(
    db_session,
    user_id,
    *,
    peer_kind: str,
    sender: int,
    peer: int,
    direction: str,
    account_id: str,
) -> Object:
    obj = Object(
        user_id=user_id,
        kind="chat_message",
        provider="telegram",
        title="note",
        origin="source",
        state="observed",
        occurred_at=NOW - timedelta(hours=1),
        metadata_={
            "transport": "mtproto",
            "account_id": account_id,
            "peer_kind": peer_kind,
            "peer_id": peer,
            "sender_peer_id": sender,
            "direction": direction,
        },
    )
    db_session.add(obj)
    db_session.flush()
    return obj
