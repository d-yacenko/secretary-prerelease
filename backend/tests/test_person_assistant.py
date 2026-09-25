from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.assistant import session as assistant_session_module
from app.assistant.tool_runner import BoundAssistantToolRunner, PerTurnToolBudget
from app.db.models import Object, PersonIdentity, PersonIdentityEvidence, User
from app.domain.object_visibility import tombstone_object
from app.domain.person_assistant import MAX_PERSON_SCAN, MAX_PERSON_SCAN_ROWS
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


def test_rejected_attached_identity_does_not_resolve_or_retrieve(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    identity = normalize_email("olga@example.com")
    people.attach(person.id, identity)
    PersonEvidenceService(db_session, user_id).record_rejection(person.id, identity, "reject-olga")
    _email(db_session, user_id, "olga@example.com")
    service = PersonAssistantService(db_session, user_id, now=NOW)
    resolved = service.resolve("olga@example.com")
    page = service.find_communications(FindPersonCommunicationsInput(person_id=person.id))
    assert resolved.state == "none"
    assert page.objects == []
    PersonEvidenceService(db_session, user_id).retract(
        PersonEvidenceService(db_session, user_id).history(person.id, identity)[0].id
    )
    restored = service.resolve("olga@example.com")
    again = service.find_communications(FindPersonCommunicationsInput(person_id=person.id))
    assert restored.person_id == person.id
    assert again.objects
    history = PersonEvidenceService(db_session, user_id).history(person.id, identity)
    assert any(row.state == "retracted" for row in history)


def test_confirmation_restores_rejected_attached_identity(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    identity = normalize_email("olga@example.com")
    people.attach(person.id, identity)
    evidence = PersonEvidenceService(db_session, user_id)
    evidence.record_rejection(person.id, identity, "reject-olga")
    evidence.record_confirmation(person.id, identity, "confirm-olga")
    resolved = PersonAssistantService(db_session, user_id, now=NOW).resolve("olga@example.com")
    history = evidence.history(person.id, identity)
    assert resolved.person_id == person.id
    assert any(row.evidence_type == "user_rejected" and row.state == "retracted" for row in history)
    assert any(row.evidence_type == "user_confirmed" and row.state == "active" for row in history)


def test_owned_source_identity_is_conflict_not_confirmable(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    shown = people.create_person("Olga Volkova")
    owner = people.create_person("Real Owner")
    identity = normalize_email("owned@example.com")
    people.attach(owner.id, identity)
    _email(db_session, user_id, "Olga Volkova <owned@example.com>")
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    runner("resolve_person", {"query": "Olga Volkova"})
    budget.commit_model_visible_outputs()
    listed = runner("find_person_identity_candidates", {"person_id": str(shown.id)})
    assert listed.success is True
    assert listed.output["candidates"][0]["confirmable"] is False
    assert "identity_conflict" in listed.output["candidates"][0]["reasons"]
    budget.commit_model_visible_outputs()
    blocked = runner("confirm_person_identity", _feedback(shown.id, identity))
    assert blocked.success is False


def test_owner_plus_other_confirmation_is_a_conflict(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    owner = people.create_person("Olga Volkova")
    other = people.create_person("Other Olga")
    identity = normalize_email("olga@example.com")
    people.attach(owner.id, identity)
    PersonEvidenceService(db_session, user_id).record_confirmation(other.id, identity, "confirm-other")
    resolved = PersonAssistantService(db_session, user_id, now=NOW).resolve("olga@example.com")
    assert resolved.state == "ambiguous"
    assert resolved.person_id is None
    assert {item.person_id for item in resolved.candidates} == {owner.id, other.id}
    assert all("identity_conflict" in item.reasons for item in resolved.candidates)


def test_multiple_confirmations_with_owner_stay_ambiguous(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    owner = people.create_person("Olga Volkova")
    other = people.create_person("Other Olga")
    identity = normalize_email("olga@example.com")
    people.attach(owner.id, identity)
    evidence = PersonEvidenceService(db_session, user_id)
    evidence.record_confirmation(owner.id, identity, "confirm-owner")
    evidence.record_confirmation(other.id, identity, "confirm-other")
    resolved = PersonAssistantService(db_session, user_id, now=NOW).resolve("olga@example.com")
    assert resolved.state == "ambiguous"
    assert resolved.person_id is None
    assert any("multiple_user_confirmations" in item.reasons for item in resolved.candidates)
    assert _count(db_session, PersonIdentity, user_id) == 1


def test_ambiguous_person_cannot_retrieve_until_resolved(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    first = people.create_person("Olga Volkova")
    second = people.create_person("Olga Volkova")
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    resolved = runner("resolve_person", {"query": "Olga Volkova"})
    assert resolved.output["state"] == "ambiguous"
    budget.commit_model_visible_outputs()
    for person in (first, second):
        blocked = runner("find_person_communications", {"person_id": str(person.id)})
        assert blocked.success is False
        inspected = runner("get_object", {"object_id": str(person.id)})
        assert inspected.success is True
    exact = people.attach(first.id, normalize_email("olga@example.com"))
    del exact
    chosen = runner("resolve_person", {"query": "olga@example.com"})
    assert chosen.output["state"] == "resolved"
    budget.commit_model_visible_outputs()
    allowed = runner("find_person_communications", {"person_id": str(first.id)})
    assert allowed.success is True


def test_email_retrieval_includes_both_directions(db_session) -> None:
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    PersonIdentityService(db_session, user_id).attach(person.id, normalize_email("olga@example.com"))
    inbound = _email(db_session, user_id, "olga@example.com")
    outbound = _email(
        db_session,
        user_id,
        "me@example.com",
        labels=["SENT"],
        metadata={"recipients": ["olga@example.com"]},
    )
    page = PersonAssistantService(db_session, user_id, now=NOW).find_communications(
        FindPersonCommunicationsInput(person_id=person.id)
    )
    assert {item.id for item in page.objects} == {inbound.id, outbound.id}
    inbound_only = PersonAssistantService(db_session, user_id, now=NOW).find_communications(
        FindPersonCommunicationsInput(person_id=person.id, direction="inbound")
    )
    assert [item.id for item in inbound_only.objects] == [inbound.id]


def test_yandex_direction_filter_uses_folder(db_session) -> None:
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    PersonIdentityService(db_session, user_id).attach(person.id, normalize_email("olga@example.com"))
    inbox = _provider_email(
        db_session, user_id, "yandex_mail", {"sender": "olga@example.com", "folder": "Inbox"}
    )
    sent = _provider_email(
        db_session,
        user_id,
        "yandex_mail",
        {"sender": "me@example.com", "folder": "Sent", "recipients": ["olga@example.com"]},
    )
    service = PersonAssistantService(db_session, user_id, now=NOW)
    outbound = service.find_communications(
        FindPersonCommunicationsInput(person_id=person.id, direction="outbound")
    )
    inbound = service.find_communications(
        FindPersonCommunicationsInput(person_id=person.id, direction="inbound")
    )
    assert [item.id for item in outbound.objects] == [sent.id]
    assert [item.id for item in inbound.objects] == [inbox.id]


def test_private_telegram_outbound_follows_ai_eligibility(db_session, monkeypatch) -> None:
    from app.core.config import settings
    from app.db.models import TelegramMtprotoAccount, TelegramMtprotoChatSelection

    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    user_id = _user(db_session)
    account = TelegramMtprotoAccount(
        user_id=user_id, telegram_user_id=424242, session_encrypted="encrypted"
    )
    db_session.add(account)
    db_session.flush()
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    PersonIdentityService(db_session, user_id).attach(
        person.id, normalize_telegram_user_id(str(account.id), 7)
    )
    for peer_id, peer_kind, title in ((7, "private", "Olga"), (-100, "group", "Group")):
        db_session.add(
            TelegramMtprotoChatSelection(
                account_id=account.id,
                peer_id=peer_id,
                peer_kind=peer_kind,
                provider_peer_reference_encrypted="encrypted",
                title=title,
                manual_selected=False,
                scope_active=True,
            )
        )
    db_session.flush()
    outbound = _telegram(
        db_session,
        user_id,
        peer_kind="private",
        sender=424242,
        peer=7,
        direction="outbound",
        account_id=str(account.id),
    )
    group = _telegram(
        db_session,
        user_id,
        peer_kind="group",
        sender=424242,
        peer=-100,
        direction="outbound",
        account_id=str(account.id),
    )
    page = PersonAssistantService(db_session, user_id, now=NOW).find_communications(
        FindPersonCommunicationsInput(person_id=person.id)
    )
    assert [item.id for item in page.objects] == [outbound.id]
    assert group.id not in {item.id for item in page.objects}


def test_direct_chat_outbound_requires_inbound_anchor(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    people.attach(person.id, normalize_teams_user_id(TENANT, TEAMS_USER))
    people.attach(person.id, normalize_mattermost_user_id(SERVER, "olga-id"))
    teams_out = _chat(
        db_session,
        user_id,
        provider="teams",
        metadata={
            "tenant_id": TENANT,
            "sender_id": "33333333-3333-3333-3333-333333333333",
            "sender_kind": "user",
            "chat_type": "oneOnOne",
            "chat_id": "chat-1",
            "direction": "outbound",
        },
    )
    page = PersonAssistantService(db_session, user_id, now=NOW).find_communications(
        FindPersonCommunicationsInput(person_id=person.id)
    )
    assert teams_out.id not in {item.id for item in page.objects}
    teams_in = _chat(
        db_session,
        user_id,
        provider="teams",
        metadata={
            "tenant_id": TENANT,
            "sender_id": TEAMS_USER,
            "sender_kind": "user",
            "chat_type": "oneOnOne",
            "chat_id": "chat-1",
            "direction": "inbound",
        },
    )
    group_out = _chat(
        db_session,
        user_id,
        provider="teams",
        metadata={
            "tenant_id": TENANT,
            "sender_id": "33333333-3333-3333-3333-333333333333",
            "sender_kind": "user",
            "chat_type": "group",
            "chat_id": "group-1",
            "direction": "outbound",
        },
    )
    mm_in = _chat(
        db_session,
        user_id,
        provider="mattermost",
        metadata={
            "server_url": SERVER,
            "author_user_id": "olga-id",
            "channel_type": "D",
            "channel_id": "dm-1",
            "direction": "inbound",
        },
    )
    mm_out = _chat(
        db_session,
        user_id,
        provider="mattermost",
        metadata={
            "server_url": SERVER,
            "author_user_id": "me-id",
            "channel_type": "D",
            "channel_id": "dm-1",
            "direction": "outbound",
        },
    )
    public_out = _chat(
        db_session,
        user_id,
        provider="mattermost",
        metadata={
            "server_url": SERVER,
            "author_user_id": "me-id",
            "channel_type": "O",
            "channel_id": "town",
            "direction": "outbound",
        },
    )
    page = PersonAssistantService(db_session, user_id, now=NOW).find_communications(
        FindPersonCommunicationsInput(person_id=person.id)
    )
    found = {item.id for item in page.objects}
    assert {teams_in.id, teams_out.id, mm_in.id, mm_out.id} <= found
    assert group_out.id not in found
    assert public_out.id not in found


def test_source_identity_can_be_confirmed_after_read(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    _email(db_session, user_id, "Olga Volkova <new@example.com>")
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    runner("resolve_person", {"query": "Olga Volkova"})
    budget.commit_model_visible_outputs()
    blocked = runner(
        "confirm_person_identity",
        _feedback(person.id, normalize_email("new@example.com")),
    )
    assert blocked.success is False
    listed = runner("find_person_identity_candidates", {"person_id": str(person.id)})
    assert listed.success is True
    assert listed.output["candidates"][0]["confirmable"] is True
    budget.commit_model_visible_outputs()
    confirmed = runner(
        "confirm_person_identity",
        _feedback(person.id, normalize_email("new@example.com")),
    )
    assert confirmed.success is True
    invented = runner(
        "confirm_person_identity",
        _feedback(person.id, normalize_email("invented@example.com")),
    )
    assert invented.success is False
    assert _count(db_session, PersonIdentity, user_id) == 0


def test_rejected_source_candidate_stays_hidden_until_retraction(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    identity = normalize_email("new@example.com")
    _email(db_session, user_id, "Olga Volkova <new@example.com>")
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    runner("resolve_person", {"query": "Olga Volkova"})
    budget.commit_model_visible_outputs()
    runner("find_person_identity_candidates", {"person_id": str(person.id)})
    budget.commit_model_visible_outputs()
    runner("reject_person_identity", _feedback(person.id, identity))
    hidden = PersonAssistantService(db_session, user_id, now=NOW).find_identity_candidates(person.id)
    assert hidden.candidates == []
    runner("retract_person_identity_feedback", _feedback(person.id, identity))
    restored = PersonAssistantService(db_session, user_id, now=NOW).find_identity_candidates(person.id)
    assert restored.candidates
    assert restored.candidates[0].confirmable is True


def test_telegram_source_candidate_is_hidden_when_gate_is_closed(db_session, monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    _telegram(db_session, user_id, peer_kind="private", sender=42, peer=42, direction="inbound")
    page = PersonAssistantService(db_session, user_id, now=NOW).find_identity_candidates(person.id)
    assert page.candidates == []
    assert "telegram_user_id" not in page.model_dump_json()


def test_rejected_attached_identity_is_not_repromoted(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    identity = normalize_email("olga@example.com")
    people.attach(person.id, identity)
    PersonEvidenceService(db_session, user_id).record_rejection(person.id, identity, "reject-olga")
    _email(db_session, user_id, "olga@example.com")
    before = _count(db_session, PersonIdentityEvidence, user_id)
    plan = PersonEnrichmentService(db_session, user_id, now=NOW).plan()
    assert _count(db_session, PersonIdentityEvidence, user_id) == before
    assert any("user_rejected" in item.reasons for item in plan.candidates)


def test_rejected_display_alias_does_not_resolve_person(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    identity = normalize_email("olga@example.com", display_value="VOA")
    people.attach(person.id, identity)
    evidence = PersonEvidenceService(db_session, user_id)
    evidence.record_rejection(person.id, identity, "reject-voa")
    service = PersonAssistantService(db_session, user_id, now=NOW)
    hidden = service.resolve("VOA")
    titled = service.resolve("Olga Volkova")
    assert hidden.state == "none"
    assert titled.person_id == person.id
    evidence.record_confirmation(person.id, identity, "confirm-voa")
    restored = service.resolve("VOA")
    history = evidence.history(person.id, identity)
    assert restored.person_id == person.id
    assert any(row.evidence_type == "user_rejected" and row.state == "retracted" for row in history)
    assert any(row.evidence_type == "user_confirmed" and row.state == "active" for row in history)


def test_noise_does_not_hide_recent_email_pair(db_session) -> None:
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    PersonIdentityService(db_session, user_id).attach(person.id, normalize_email("olga@example.com"))
    _noise(db_session, user_id, MAX_PERSON_SCAN + 1)
    inbound = _email(db_session, user_id, "olga@example.com", when=NOW - timedelta(days=2))
    outbound = _email(
        db_session,
        user_id,
        "me@example.com",
        labels=["SENT"],
        metadata={"recipients": ["olga@example.com"]},
        when=NOW - timedelta(days=2, minutes=1),
    )
    page = PersonAssistantService(db_session, user_id, now=NOW).find_communications(
        FindPersonCommunicationsInput(person_id=person.id)
    )
    assert {item.id for item in page.objects} == {inbound.id, outbound.id}
    assert page.truncated is False


def test_noise_does_not_hide_eligible_telegram(db_session, monkeypatch) -> None:
    from app.core.config import settings
    from app.db.models import TelegramMtprotoAccount, TelegramMtprotoChatSelection

    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    user_id = _user(db_session)
    account = TelegramMtprotoAccount(
        user_id=user_id, telegram_user_id=525252, session_encrypted="encrypted"
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
    _noise(db_session, user_id, MAX_PERSON_SCAN + 1)
    outbound = _telegram(
        db_session,
        user_id,
        peer_kind="private",
        sender=525252,
        peer=7,
        direction="outbound",
        account_id=str(account.id),
        when=NOW - timedelta(days=2),
    )
    page = PersonAssistantService(db_session, user_id, now=NOW).find_communications(
        FindPersonCommunicationsInput(person_id=person.id)
    )
    assert [item.id for item in page.objects] == [outbound.id]


def test_noise_does_not_hide_direct_chat_anchor(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    people.attach(person.id, normalize_teams_user_id(TENANT, TEAMS_USER))
    people.attach(person.id, normalize_mattermost_user_id(SERVER, "olga-id"))
    _noise(db_session, user_id, MAX_PERSON_SCAN + 1)
    older = NOW - timedelta(days=2)
    teams_out = _chat(
        db_session,
        user_id,
        provider="teams",
        metadata={
            "tenant_id": TENANT,
            "sender_id": "33333333-3333-3333-3333-333333333333",
            "sender_kind": "user",
            "chat_type": "oneOnOne",
            "chat_id": "chat-1",
            "direction": "outbound",
        },
        when=older,
    )
    teams_in = _chat(
        db_session,
        user_id,
        provider="teams",
        metadata={
            "tenant_id": TENANT,
            "sender_id": TEAMS_USER,
            "sender_kind": "user",
            "chat_type": "oneOnOne",
            "chat_id": "chat-1",
            "direction": "inbound",
        },
        when=older - timedelta(minutes=1),
    )
    mm_out = _chat(
        db_session,
        user_id,
        provider="mattermost",
        metadata={
            "server_url": SERVER,
            "author_user_id": "me-id",
            "channel_type": "D",
            "channel_id": "dm-1",
            "direction": "outbound",
        },
        when=older - timedelta(minutes=2),
    )
    mm_in = _chat(
        db_session,
        user_id,
        provider="mattermost",
        metadata={
            "server_url": SERVER,
            "author_user_id": "olga-id",
            "channel_type": "D",
            "channel_id": "dm-1",
            "direction": "inbound",
        },
        when=older - timedelta(minutes=3),
    )
    group = _chat(
        db_session,
        user_id,
        provider="teams",
        metadata={
            "tenant_id": TENANT,
            "sender_id": "33333333-3333-3333-3333-333333333333",
            "sender_kind": "user",
            "chat_type": "group",
            "chat_id": "group-1",
            "direction": "outbound",
        },
        when=older - timedelta(minutes=4),
    )
    page = PersonAssistantService(db_session, user_id, now=NOW).find_communications(
        FindPersonCommunicationsInput(person_id=person.id)
    )
    found = {item.id for item in page.objects}
    assert {teams_in.id, teams_out.id, mm_in.id, mm_out.id} <= found
    assert group.id not in found


def test_noise_does_not_hide_source_identity_candidate(db_session) -> None:
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    _noise(db_session, user_id, MAX_PERSON_SCAN + 1)
    _email(db_session, user_id, "Olga Volkova <new@example.com>", when=NOW - timedelta(days=2))
    page = PersonAssistantService(db_session, user_id, now=NOW).find_identity_candidates(person.id)
    assert page.truncated is False
    assert page.candidates
    assert page.candidates[0].confirmable is True
    assert page.candidates[0].identity.canonical_value == "new@example.com"


def test_scan_budget_exhaustion_is_truncated(db_session) -> None:
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    PersonIdentityService(db_session, user_id).attach(person.id, normalize_email("olga@example.com"))
    _noise(db_session, user_id, MAX_PERSON_SCAN_ROWS + 1)
    hidden = _email(db_session, user_id, "olga@example.com", when=NOW - timedelta(days=3))
    page = PersonAssistantService(db_session, user_id, now=NOW).find_communications(
        FindPersonCommunicationsInput(person_id=person.id)
    )
    assert page.truncated is True
    assert hidden.id not in {item.id for item in page.objects}


def test_provider_and_date_filters_bound_the_scan(db_session) -> None:
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    PersonIdentityService(db_session, user_id).attach(person.id, normalize_email("olga@example.com"))
    _noise(db_session, user_id, MAX_PERSON_SCAN_ROWS + 1, provider="yandex_mail")
    older = _email(db_session, user_id, "olga@example.com", when=NOW - timedelta(days=3))
    newer = _email(db_session, user_id, "olga@example.com", when=NOW - timedelta(days=1))
    service = PersonAssistantService(db_session, user_id, now=NOW)
    gmail = service.find_communications(
        FindPersonCommunicationsInput(person_id=person.id, provider="gmail")
    )
    assert [item.id for item in gmail.objects] == [newer.id, older.id]
    assert gmail.truncated is False
    recent = service.find_communications(
        FindPersonCommunicationsInput(
            person_id=person.id,
            provider="gmail",
            occurred_from=NOW - timedelta(days=2),
        )
    )
    assert [item.id for item in recent.objects] == [newer.id]


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


def _noise(db_session, user_id: uuid.UUID, count: int, *, provider: str = "gmail") -> None:
    rows = [
        Object(
            user_id=user_id,
            kind="email",
            provider=provider,
            title="noise",
            origin="source",
            state="observed",
            occurred_at=NOW - timedelta(minutes=index),
            metadata_={"sender": f"noise-{index}@example.com", "labels": ["INBOX"]},
        )
        for index in range(count)
    ]
    db_session.add_all(rows)
    db_session.flush()


def _email(
    db_session,
    user_id: uuid.UUID,
    sender: str,
    *,
    labels: list[str] | None = None,
    metadata: dict | None = None,
    when: datetime | None = None,
) -> Object:
    payload = {"sender": sender, "labels": labels or ["INBOX"]}
    if metadata:
        payload.update(metadata)
    obj = Object(
        user_id=user_id,
        kind="email",
        provider="gmail",
        title="mail",
        origin="source",
        state="observed",
        occurred_at=when or (NOW - timedelta(hours=1)),
        metadata_=payload,
    )
    db_session.add(obj)
    db_session.flush()
    return obj


def _chat(
    db_session,
    user_id: uuid.UUID,
    *,
    provider: str,
    metadata: dict,
    when: datetime | None = None,
) -> Object:
    obj = Object(
        user_id=user_id,
        kind="chat_message",
        provider=provider,
        title="chat",
        origin="source",
        state="observed",
        occurred_at=when or (NOW - timedelta(hours=1)),
        metadata_=metadata,
    )
    db_session.add(obj)
    db_session.flush()
    return obj


def _provider_email(db_session, user_id: uuid.UUID, provider: str, metadata: dict) -> Object:
    obj = Object(
        user_id=user_id,
        kind="email",
        provider=provider,
        title="mail",
        origin="source",
        state="observed",
        occurred_at=NOW - timedelta(hours=1),
        metadata_=metadata,
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
    account_id: str = ACCOUNT,
    when: datetime | None = None,
) -> Object:
    obj = Object(
        user_id=user_id,
        kind="chat_message",
        provider="telegram",
        title="note",
        origin="source",
        state="observed",
        occurred_at=when or (NOW - timedelta(hours=1)),
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
