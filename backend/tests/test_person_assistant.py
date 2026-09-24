from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.assistant import session as assistant_session_module
from app.assistant.tool_runner import BoundAssistantToolRunner, PerTurnToolBudget
from app.db.models import Object, PersonIdentity, User
from app.domain.object_visibility import tombstone_object
from app.domain.person_candidate_score import EXACT_IDENTIFIER
from app.domain.person_identity import (
    normalize_email,
    normalize_mattermost_user_id,
    normalize_teams_user_id,
    normalize_telegram_user_id,
)
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_enrichment_service import PersonEnrichmentService
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import REJECTED_STATE
from app.tools.schemas import FindPersonCommunicationsInput, PersonIdentityFeedbackInput

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
ACCOUNT = "account-1"
SERVER = "https://chat.example"
TENANT = "11111111-1111-1111-1111-111111111111"
TEAMS_USER = "22222222-2222-2222-2222-222222222222"


def test_exact_identifier_resolves_one_person(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    people.attach(person.id, normalize_email("olga@example.com"))
    resolved = PersonAssistantService(db_session, user_id, now=NOW).resolve("Olga <olga@example.com>")
    assert resolved.state == "resolved"
    assert resolved.person_id == person.id
    assert resolved.candidates[0].reasons == ("exact_identity",)


def test_alias_and_title_resolution_are_deterministic(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    people.attach(person.id, normalize_email("olga@example.com", display_value="VOA"))
    service = PersonAssistantService(db_session, user_id, now=NOW)
    by_alias = service.resolve("VOA")
    by_title = service.resolve("Olga Volkova")
    assert by_alias.state == "resolved"
    assert by_alias.person_id == person.id
    assert by_alias.candidates[0].reasons == ("alias",)
    assert by_title.person_id == person.id
    assert [item.person_id for item in service.resolve("Olga Volkova").candidates] == [
        item.person_id for item in by_title.candidates
    ]


def test_two_people_stay_ambiguous(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    focus = people.create_person("Olga Volkova")
    other = people.create_person("Olga Volkova")
    people.attach(focus.id, normalize_telegram_user_id(ACCOUNT, 7))
    _telegram(db_session, user_id, peer_kind="private", sender=7, peer=7, direction="inbound")
    _telegram(db_session, user_id, peer_kind="private", sender=7, peer=7, direction="outbound")
    resolved = PersonAssistantService(db_session, user_id, now=NOW).resolve("Olga Volkova")
    assert resolved.state == "ambiguous"
    assert resolved.person_id is None
    assert [item.person_id for item in resolved.candidates] == [focus.id, other.id]


def test_rejected_deleted_and_cross_user_people_are_excluded(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    rejected = people.create_person("Rejected Olga")
    rejected.state = REJECTED_STATE
    deleted = people.create_person("Deleted Olga")
    tombstone_object(deleted)
    other_user = _user(db_session)
    foreign = PersonIdentityService(db_session, other_user).create_person("Foreign Olga")
    db_session.flush()
    resolved = PersonAssistantService(db_session, user_id, now=NOW).resolve("Olga")
    seen = {item.person_id for item in resolved.candidates}
    assert rejected.id not in seen
    assert deleted.id not in seen
    assert foreign.id not in seen


def test_retrieval_uses_only_active_exact_identities(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    people.attach(person.id, normalize_email("olga@example.com"))
    linked = _email(db_session, user_id, "olga@example.com")
    _email(db_session, user_id, "other@example.com")
    page = PersonAssistantService(db_session, user_id, now=NOW).find_communications(
        FindPersonCommunicationsInput(person_id=person.id)
    )
    assert [item.id for item in page.objects] == [linked.id]


def test_display_name_only_message_is_not_linked(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    people.attach(person.id, normalize_mattermost_user_id(SERVER, "olga-id"))
    _chat(
        db_session,
        user_id,
        provider="mattermost",
        metadata={"server_url": SERVER, "author_display_name": "Olga Volkova", "channel_type": "O"},
    )
    page = PersonAssistantService(db_session, user_id, now=NOW).find_communications(
        FindPersonCommunicationsInput(person_id=person.id)
    )
    assert page.objects == []


def test_cross_provider_retrieval(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    people.attach(person.id, normalize_email("olga@example.com"))
    people.attach(person.id, normalize_mattermost_user_id(SERVER, "olga-id"))
    people.attach(person.id, normalize_teams_user_id(TENANT, TEAMS_USER))
    mail = _email(db_session, user_id, "olga@example.com")
    chat = _chat(
        db_session,
        user_id,
        provider="mattermost",
        metadata={"server_url": SERVER, "author_user_id": "olga-id", "channel_type": "D", "direction": "inbound"},
    )
    teams = _chat(
        db_session,
        user_id,
        provider="teams",
        metadata={
            "tenant_id": TENANT,
            "sender_id": TEAMS_USER,
            "sender_kind": "user",
            "chat_type": "oneOnOne",
            "direction": "inbound",
        },
    )
    page = PersonAssistantService(db_session, user_id, now=NOW).find_communications(
        FindPersonCommunicationsInput(person_id=person.id)
    )
    assert {item.id for item in page.objects} == {mail.id, chat.id, teams.id}


def test_telegram_retrieval_respects_ai_gate(db_session, monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    people.attach(person.id, normalize_email("olga@example.com"))
    people.attach(person.id, normalize_telegram_user_id(ACCOUNT, 7))
    mail = _email(db_session, user_id, "olga@example.com")
    _telegram(db_session, user_id, peer_kind="private", sender=7, peer=7, direction="inbound")
    service = PersonAssistantService(db_session, user_id, now=NOW)
    page = service.find_communications(FindPersonCommunicationsInput(person_id=person.id))
    resolved = service.resolve("Olga Volkova")
    rendered = resolved.model_dump(mode="json")
    assert [item.id for item in page.objects] == [mail.id]
    assert "7" not in str(rendered["candidates"][0]["identities"])


def test_returned_ids_are_seen_for_follow_up(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    people.attach(person.id, normalize_email("olga@example.com"))
    mail = _email(db_session, user_id, "olga@example.com")
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    resolved = runner("resolve_person", {"query": "olga@example.com"})
    assert resolved.success is True
    budget.commit_model_visible_outputs()
    found = runner("find_person_communications", {"person_id": str(person.id)})
    assert found.success is True
    budget.commit_model_visible_outputs()
    follow_up = runner("get_object", {"object_id": str(mail.id)})
    assert follow_up.success is True
    assert mail.id in budget.seen_object_ids


def test_confirmation_requires_same_turn_exposed_identity(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    identity = normalize_email("olga@example.com")
    PersonEvidenceService(db_session, user_id).record(
        person.id,
        identity,
        EXACT_IDENTIFIER,
        provenance_kind="provider_fact",
        provenance_key="source:test",
        explanation="stored exact candidate",
    )
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    blocked = runner("confirm_person_identity", _feedback(person.id, identity))
    assert blocked.success is False
    runner("resolve_person", {"query": "Olga Volkova"})
    budget.commit_model_visible_outputs()
    confirmed = runner("confirm_person_identity", _feedback(person.id, identity))
    assert confirmed.success is True
    assert confirmed.output["evidence_type"] == "user_confirmed"


def test_invented_identity_feedback_fails_closed(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    shown = normalize_email("olga@example.com")
    PersonEvidenceService(db_session, user_id).record(
        person.id,
        shown,
        EXACT_IDENTIFIER,
        provenance_kind="provider_fact",
        provenance_key="source:shown",
        explanation="stored exact candidate",
    )
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    runner("resolve_person", {"query": "Olga Volkova"})
    budget.commit_model_visible_outputs()
    invented = normalize_email("invented@example.com")
    for tool_name in ("confirm_person_identity", "reject_person_identity"):
        result = runner(tool_name, _feedback(person.id, invented))
        assert result.success is False
    assert _count(db_session, PersonIdentity, user_id) == 0


def test_rejection_suppresses_candidate_until_retraction(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    identity = normalize_email("olga@example.com")
    evidence = PersonEvidenceService(db_session, user_id)
    evidence.record(
        person.id,
        identity,
        EXACT_IDENTIFIER,
        provenance_kind="provider_fact",
        provenance_key="source:olga",
        explanation="stored exact candidate",
    )
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    runner("resolve_person", {"query": "olga@example.com"})
    budget.commit_model_visible_outputs()
    rejected = runner("reject_person_identity", _feedback(person.id, identity))
    assert rejected.success is True
    hidden = PersonAssistantService(db_session, user_id, now=NOW).resolve("olga@example.com")
    assert hidden.state == "none"
    runner("retract_person_identity_feedback", _feedback(person.id, identity))
    restored = PersonAssistantService(db_session, user_id, now=NOW).resolve("olga@example.com")
    assert restored.person_id == person.id
    history = evidence.history(person.id, identity)
    assert any(row.state == "retracted" and row.evidence_type == "user_rejected" for row in history)


def test_multiple_confirmations_do_not_merge(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    first = people.create_person("Olga Volkova")
    second = people.create_person("Other Olga")
    identity = normalize_email("olga@example.com")
    evidence = PersonEvidenceService(db_session, user_id)
    for person, key in ((first, "a"), (second, "b")):
        evidence.record(
            person.id,
            identity,
            EXACT_IDENTIFIER,
            provenance_kind="provider_fact",
            provenance_key=f"source:{key}",
            explanation="stored exact candidate",
        )
    service = PersonAssistantService(db_session, user_id, now=NOW)
    resolved = service.resolve("olga@example.com")
    assert resolved.state == "ambiguous"
    service.confirm_person_identity(PersonIdentityFeedbackInput(**_feedback(first.id, identity)))
    service.confirm_person_identity(PersonIdentityFeedbackInput(**_feedback(second.id, identity)))
    _email(db_session, user_id, "olga@example.com")
    plan = PersonEnrichmentService(db_session, user_id, now=NOW).plan()
    assert _count(db_session, PersonIdentity, user_id) == 0
    assert _count(db_session, Object, user_id, kind="person") == 2
    assert any("multiple_user_confirmations" in item.reasons for item in plan.candidates)


def test_feedback_does_not_send_or_merge() -> None:
    root = Path(__file__).resolve().parents[1]
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            root / "app/services/person_assistant_service.py",
            root / "app/domain/person_assistant.py",
        )
    )
    folded = source.casefold()
    for marker in ("send_email", "send_message", "httpx", "openai", "create_person", ".attach("):
        assert marker not in folded


def test_person_tools_are_not_send_routes() -> None:
    from app.tools.policy import ToolPermission
    from app.tools.registry import TOOL_REGISTRY

    for name in ("resolve_person", "find_person_communications"):
        assert TOOL_REGISTRY[name].permission == ToolPermission.READ
    for name in (
        "confirm_person_identity",
        "reject_person_identity",
        "retract_person_identity_feedback",
    ):
        assert TOOL_REGISTRY[name].permission == ToolPermission.ANNOTATE
        assert TOOL_REGISTRY[name].prepare_method is None


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


def _feedback(person_id, identity) -> dict:
    return {
        "person_id": str(person_id),
        "identity_type": identity.identity_type,
        "provider": identity.provider,
        "realm": identity.realm,
        "canonical_value": identity.canonical_value,
    }


def _count(db_session, model, user_id: uuid.UUID, *, kind: str | None = None) -> int:
    query = select(func.count()).select_from(model).where(model.user_id == user_id)
    if kind is not None:
        query = query.where(model.kind == kind)
    return int(db_session.scalar(query) or 0)


def _user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Owner"))
    db_session.flush()
    return user_id


def _email(db_session, user_id: uuid.UUID, sender: str) -> Object:
    obj = Object(
        user_id=user_id,
        kind="email",
        provider="gmail",
        title="mail",
        origin="source",
        state="observed",
        occurred_at=NOW - timedelta(hours=1),
        metadata_={"sender": sender, "labels": ["INBOX"]},
    )
    db_session.add(obj)
    db_session.flush()
    return obj


def _chat(db_session, user_id: uuid.UUID, *, provider: str, metadata: dict) -> Object:
    obj = Object(
        user_id=user_id,
        kind="chat_message",
        provider=provider,
        title="chat",
        origin="source",
        state="observed",
        occurred_at=NOW - timedelta(hours=1),
        metadata_=metadata,
    )
    db_session.add(obj)
    db_session.flush()
    return obj


def _telegram(db_session, user_id, *, peer_kind: str, sender: int, peer: int, direction: str) -> None:
    db_session.add(
        Object(
            user_id=user_id,
            kind="chat_message",
            provider="telegram",
            title="note",
            origin="source",
            state="observed",
            occurred_at=NOW - timedelta(hours=1),
            metadata_={
                "transport": "mtproto",
                "account_id": ACCOUNT,
                "peer_kind": peer_kind,
                "peer_id": peer,
                "sender_peer_id": sender,
                "direction": direction,
            },
        )
    )
    db_session.flush()
