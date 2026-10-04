"""Role-import participant discovery stays separate from generic promotion."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.db.models import (
    AITrace,
    MattermostAccount,
    Object,
    PersonIdentity,
    PersonRoleAssignment,
    TelegramMtprotoAccount,
    TelegramMtprotoChatSelection,
    User,
)
from app.domain.person_identity import normalize_email
from app.domain.person_promotion import MIN_DIRECT_HITS
from app.services.action_plan_service import ActionPlanService
from app.services.errors import ValidationError
from app.services.person_identity_service import PersonIdentityService
from app.services.person_promotion_service import PersonPromotionService
from app.services.person_role_import_batch_models import (
    ApplyRoleImportBatchInput,
    RoleImportBatchSelection,
)
from app.services.person_role_import_batch_service import PersonRoleImportBatchService
from app.services.person_role_import_grounding_service import (
    PersonRoleImportGroundingService,
    RoleImportGroundInputItem,
    RoleImportGroundRequest,
)
from app.services.person_role_import_source_service import PersonRoleImportSourceService
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_rel1d_role_import_source import _text_object

_ROLE = "rel1dhg14роль"


def test_one_inbound_sender_is_a_role_import_candidate(db_session, tmp_path) -> None:
    name = "REL1DHG14 Входящий"
    _mail(db_session, sender=f"{name} <rel1dhg14-in@example.com>")
    item = _ground_one(db_session, tmp_path, name)
    candidate = item.person_resolution.promotion_candidates[0]
    assert item.person_resolution.state == "promotion_candidates"
    assert candidate.display_name == name
    assert candidate.provider == "email"
    assert candidate.direct_hit_count == 1
    dumped = item.model_dump_json()
    assert "rel1dhg14-in@example.com" not in dumped
    assert candidate.candidate_key not in candidate.display_name


def test_one_outbound_recipient_is_a_role_import_candidate(db_session, tmp_path) -> None:
    name = "REL1DHG14 Исходящий"
    _mail(
        db_session,
        sender="me@example.com",
        metadata={"folder": "sent", "sender": "me@example.com", "to": f"{name} <rel1dhg14-out@example.com>"},
    )
    item = _ground_one(db_session, tmp_path, name)
    assert item.person_resolution.promotion_candidates[0].direct_hit_count == 1


def test_cc_participant_is_a_role_import_candidate(db_session, tmp_path) -> None:
    name = "REL1DHG14 Копия"
    _mail(
        db_session,
        sender="other@example.com",
        metadata={
            "sender": "other@example.com",
            "to": "me@example.com",
            "cc": f"{name} <rel1dhg14-cc@example.com>",
        },
    )
    item = _ground_one(db_session, tmp_path, name)
    assert item.person_resolution.state == "promotion_candidates"


def test_bare_recipient_without_display_name_is_omitted(db_session, tmp_path) -> None:
    _mail(
        db_session,
        sender="other@example.com",
        metadata={"sender": "other@example.com", "to": "rel1dhg14-bare@example.com"},
    )
    assert _ground_items(db_session, tmp_path, [_row("REL1DHG14 Голый", _ROLE)]) == []


def test_body_mention_is_not_a_participant(db_session, tmp_path) -> None:
    name = "REL1DHG14 ТолькоТекст"
    _mail(
        db_session,
        sender="other@example.com",
        title=name,
        body=f"{name} упомянут только в тексте",
        metadata={"sender": "other@example.com", "to": "me@example.com", "subject": name},
    )
    assert _ground_items(db_session, tmp_path, [_row(name, _ROLE)]) == []


def test_mattermost_channel_author_is_a_candidate_and_not_a_generic_contact(db_session) -> None:
    user = _user(db_session)
    account = _mattermost_account(db_session, user.id)
    _chat(
        db_session,
        user.id,
        provider="mattermost",
        metadata={
            "server_url": "https://chat.example.com",
            "channel_type": "O",
            "account_id": str(account.id),
            "author_user_id": "user-hg14",
            "author_display_name": "REL1DHG14 Канал",
        },
    )
    promotion = PersonPromotionService(db_session, user.id)
    participants = promotion.eligible_role_import_participants()
    assert [item.display_value for item in participants] == ["REL1DHG14 Канал"]
    assert promotion.eligible_direct_contacts() == []


def test_teams_group_sender_is_a_candidate_and_not_a_generic_contact(db_session) -> None:
    user = _user(db_session)
    _chat(
        db_session,
        user.id,
        provider="teams",
        metadata={
            "sender_kind": "user",
            "direction": "inbound",
            "chat_type": "group",
            "tenant_id": "33333333-3333-4333-8333-333333333333",
            "sender_id": "22222222-2222-4222-8222-222222222222",
            "sender_display_name": "REL1DHG14 Команда",
        },
    )
    promotion = PersonPromotionService(db_session, user.id)
    assert [item.display_value for item in promotion.eligible_role_import_participants()] == [
        "REL1DHG14 Команда"
    ]
    assert promotion.eligible_direct_contacts() == []
    _chat(
        db_session,
        user.id,
        provider="teams",
        metadata={
            "sender_kind": "application",
            "chat_type": "group",
            "tenant_id": "33333333-3333-4333-8333-333333333333",
            "sender_id": "bot",
            "sender_display_name": "REL1DHG14 Бот",
        },
    )
    assert "REL1DHG14 Бот" not in [
        item.display_value for item in promotion.eligible_role_import_participants()
    ]


def test_telegram_sender_follows_the_ai_gate_and_channel_title_does_not(
    db_session, monkeypatch
) -> None:
    user = _user(db_session)
    account = TelegramMtprotoAccount(
        user_id=user.id,
        telegram_user_id=880_014_014,
        session_encrypted="encrypted",
    )
    db_session.add(account)
    db_session.flush()
    db_session.add(
        TelegramMtprotoChatSelection(
            account_id=account.id,
            peer_id=88001,
            peer_kind="group",
            provider_peer_reference_encrypted="encrypted",
            title="REL1DHG14 Канал",
            scope_active=True,
            manual_selected=False,
        )
    )
    db_session.flush()
    _chat(
        db_session,
        user.id,
        provider="telegram",
        metadata={
            "transport": "mtproto",
            "account_id": str(account.id),
            "peer_id": "88001",
            "peer_kind": "group",
            "peer_title": "REL1DHG14 Канал",
            "direction": "inbound",
            "sender_peer_id": 88002,
            "sender_display_name": "REL1DHG14 Телеграм",
        },
    )
    _chat(
        db_session,
        user.id,
        provider="telegram",
        metadata={
            "transport": "mtproto",
            "account_id": str(account.id),
            "peer_id": "88001",
            "peer_kind": "group",
            "peer_title": "REL1DHG14 ТолькоЗаголовок",
            "direction": "inbound",
        },
    )
    promotion = PersonPromotionService(db_session, user.id)
    assert promotion.eligible_role_import_participants() == []
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    participants = promotion.eligible_role_import_participants()
    assert [item.display_value for item in participants] == ["REL1DHG14 Телеграм"]
    assert "REL1DHG14 ТолькоЗаголовок" not in [item.display_value for item in participants]
    assert "REL1DHG14 Канал" not in [item.display_value for item in participants]


def test_generic_promotion_threshold_and_approve_stay_unchanged(db_session) -> None:
    assert MIN_DIRECT_HITS == 2
    user = _user(db_session)
    _mail(db_session, sender="REL1DHG14 Порог <rel1dhg14-threshold@example.com>", user_id=user.id)
    promotion = PersonPromotionService(db_session, user.id)
    identity = normalize_email("REL1DHG14 Порог <rel1dhg14-threshold@example.com>")
    assert promotion.eligible_direct_contacts() == []
    assert len(promotion.eligible_role_import_participants()) == 1
    with pytest.raises(ValidationError, match="promotion candidate is not exposed"):
        promotion.approve(identity)
    _mail(
        db_session,
        sender="REL1DHG14 Порог <rel1dhg14-threshold@example.com>",
        user_id=user.id,
    )
    approved = promotion.approve(identity)
    assert approved.title == "REL1DHG14 Порог"
    assert promotion.eligible_direct_contacts() == []


def test_participant_approval_creates_one_person_identity_and_role(db_session, tmp_path) -> None:
    name = "REL1DHG14 План"
    address = "rel1dhg14-plan@example.com"
    _mail(db_session, sender=f"{name} <{address}>")
    items = [_row(name, _ROLE)]
    source, revision, proposal = _proposal(db_session, tmp_path, items)
    candidate = proposal.items[0].person_resolution.promotion_candidates[0]
    before_traces = _count(db_session, AITrace)
    plan = _prepare(db_session, tmp_path, source, revision, proposal, items, [
        {"row_index": 0, "promotion_candidate_key": candidate.candidate_key}
    ])
    assert plan.actions[0]["arguments"] == {}
    view = ActionPlanService(db_session, BOOTSTRAP_USER_ID).approve(plan.id)
    assert view.status == "executed"
    assert _count(db_session, AITrace) == before_traces
    identity = db_session.scalar(
        select(PersonIdentity).where(
            PersonIdentity.user_id == BOOTSTRAP_USER_ID,
            PersonIdentity.canonical_value == address,
        )
    )
    assert identity is not None
    person = db_session.get(Object, identity.person_object_id)
    assert person.title == name
    assignments = list(
        db_session.scalars(
            select(PersonRoleAssignment).where(
                PersonRoleAssignment.person_object_id == person.id
            )
        )
    )
    assert len(assignments) == 1
    same = db_session.scalar(
        select(func.count()).select_from(PersonIdentity).where(
            PersonIdentity.user_id == BOOTSTRAP_USER_ID,
            PersonIdentity.canonical_value == address,
        )
    )
    assert same == 1


def test_removed_participant_evidence_does_not_create_a_person(db_session, tmp_path) -> None:
    name = "REL1DHG14 Снято"
    sender = f"{name} <rel1dhg14-gone@example.com>"
    _mail(db_session, sender=sender)
    items = [_row(name, _ROLE)]
    source, revision, proposal = _proposal(db_session, tmp_path, items)
    key = proposal.items[0].person_resolution.promotion_candidates[0].candidate_key
    plan = _prepare(db_session, tmp_path, source, revision, proposal, items, [
        {"row_index": 0, "promotion_candidate_key": key}
    ])
    mail = db_session.scalar(select(Object).where(Object.metadata_["sender"].astext == sender))
    db_session.delete(mail)
    db_session.flush()
    before_people = _count_people(db_session)
    before_assignments = _count(db_session, PersonRoleAssignment)
    view = ActionPlanService(db_session, BOOTSTRAP_USER_ID).approve(plan.id)
    assert view.status == "failed"
    assert "role_import_grounding_changed" in view.failure
    assert _count_people(db_session) == before_people
    assert _count(db_session, PersonRoleAssignment) == before_assignments


def test_bound_participant_identity_does_not_create_a_duplicate(db_session, tmp_path) -> None:
    name = "REL1DHG14 Занято"
    address = "rel1dhg14-bound@example.com"
    _mail(db_session, sender=f"{name} <{address}>")
    items = [_row(name, _ROLE)]
    source, revision, proposal = _proposal(db_session, tmp_path, items)
    key = proposal.items[0].person_resolution.promotion_candidates[0].candidate_key
    plan = _prepare(db_session, tmp_path, source, revision, proposal, items, [
        {"row_index": 0, "promotion_candidate_key": key}
    ])
    other = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("REL1DHG14 Другой")
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).attach(other.id, normalize_email(address))
    before = _count_people(db_session)
    view = ActionPlanService(db_session, BOOTSTRAP_USER_ID).approve(plan.id)
    assert view.status == "failed"
    assert "role_import_grounding_changed" in view.failure
    assert _count_people(db_session) == before


def test_owned_and_suppressed_identities_are_not_role_import_candidates(db_session, tmp_path) -> None:
    owned_name = "REL1DHG14 ЧужоеИмя"
    owned = normalize_email(f"{owned_name} <rel1dhg14-owned@example.com>")
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("REL1DHG14 УжеЧеловек")
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).attach(person.id, owned)
    _mail(db_session, sender=f"{owned_name} <rel1dhg14-owned@example.com>")
    hidden_name = "REL1DHG14 Скрытый"
    hidden = normalize_email(f"{hidden_name} <rel1dhg14-hidden@example.com>")
    _mail(db_session, sender=f"{hidden_name} <rel1dhg14-hidden@example.com>")
    PersonPromotionService(db_session, BOOTSTRAP_USER_ID).suppress(hidden)
    items = _ground_items(
        db_session, tmp_path, [_row(owned_name, _ROLE), _row(hidden_name, _ROLE)]
    )
    assert [item.person_name for item in items] == [owned_name]
    assert items[0].person_resolution.state == "resolved"
    assert items[0].person_resolution.person_id == person.id
    assert items[0].person_resolution.promotion_candidates == []


def test_same_display_name_stays_an_explicit_choice(db_session, tmp_path) -> None:
    name = "REL1DHG14 ДвеПочты"
    _mail(db_session, sender=f"{name} <rel1dhg14-a@example.com>")
    _mail(db_session, sender=f"{name} <rel1dhg14-b@example.com>")
    item = _ground_one(db_session, tmp_path, name)
    assert item.person_resolution.state == "promotion_candidates"
    assert item.person_resolution.person_id is None
    keys = [candidate.candidate_key for candidate in item.person_resolution.promotion_candidates]
    assert len(keys) == 2
    assert keys == sorted(keys)


def test_original_row_index_survives_participant_filtering(db_session, tmp_path) -> None:
    name = "REL1DHG14 Индекс"
    _mail(db_session, sender=f"{name} <rel1dhg14-index@example.com>")
    items = _ground_items(
        db_session,
        tmp_path,
        [_row("REL1DHG14 Пусто", _ROLE), _row(name, _ROLE)],
    )
    assert [item.row_index for item in items] == [1]


def test_participant_discovery_does_not_call_a_provider(db_session, tmp_path, monkeypatch) -> None:
    def _forbid(*_args, **_kwargs):
        raise AssertionError("provider was constructed")

    monkeypatch.setattr(
        "app.llm.openai_role_import_provider.OpenAIRoleImportExtractionProvider.for_user",
        _forbid,
    )
    name = "REL1DHG14 БезМодели"
    _mail(db_session, sender=f"{name} <rel1dhg14-model@example.com>")
    before = _count(db_session, AITrace)
    item = _ground_one(db_session, tmp_path, name)
    assert item.person_resolution.state == "promotion_candidates"
    assert _count(db_session, AITrace) == before


def test_truncated_scan_keeps_a_seen_hit_and_omits_an_unseen_name(db_session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.services.person_promotion_service.MAX_PERSON_SCAN_ROWS", 1)
    seen = "REL1DHG14 Видно"
    missed = "REL1DHG14 Невидно"
    _mail(
        db_session,
        sender=f"{missed} <rel1dhg14-miss@example.com>",
        when=datetime.now(UTC) - timedelta(days=1),
    )
    _mail(db_session, sender=f"{seen} <rel1dhg14-seen@example.com>")
    items = _ground_items(db_session, tmp_path, [_row(seen, _ROLE), _row(missed, _ROLE)])
    assert [item.person_name for item in items] == [seen]


def _ground_one(db_session, tmp_path, name: str):
    items = _ground_items(db_session, tmp_path, [_row(name, _ROLE)])
    assert len(items) == 1
    return items[0]


def _ground_items(db_session, tmp_path, rows: list[dict]):
    source = _text_object(db_session, "role import participant source")
    revision = PersonRoleImportSourceService(
        db_session, BOOTSTRAP_USER_ID, tmp_path / "uploads"
    ).load(source.id).source_revision
    proposal = PersonRoleImportGroundingService(
        db_session, BOOTSTRAP_USER_ID, tmp_path / "uploads"
    ).ground(
        RoleImportGroundRequest(
            source_object_id=source.id,
            source_revision=revision,
            items_truncated=False,
            items=[RoleImportGroundInputItem.model_validate(row) for row in rows],
        )
    )
    return proposal.items


def _proposal(db_session, tmp_path, items):
    source = _text_object(db_session, "role import participant plan")
    revision = PersonRoleImportSourceService(
        db_session, BOOTSTRAP_USER_ID, tmp_path / "uploads"
    ).load(source.id).source_revision
    proposal = PersonRoleImportGroundingService(
        db_session, BOOTSTRAP_USER_ID, tmp_path / "uploads"
    ).ground(
        RoleImportGroundRequest(
            source_object_id=source.id,
            source_revision=revision,
            items_truncated=False,
            items=[RoleImportGroundInputItem.model_validate(row) for row in items],
        )
    )
    return source, revision, proposal


def _prepare(db_session, tmp_path, source, revision, proposal, items, selections):
    return PersonRoleImportBatchService(
        db_session, BOOTSTRAP_USER_ID, tmp_path / "uploads"
    ).prepare_plan(
        ApplyRoleImportBatchInput(
            source_object_id=source.id,
            source_revision=revision,
            grounding_revision=proposal.grounding_revision,
            items_truncated=False,
            items=[RoleImportGroundInputItem.model_validate(item) for item in items],
            selections=[RoleImportBatchSelection.model_validate(item) for item in selections],
        )
    )


def _row(name: str, role: str) -> dict:
    return {
        "person_name": name,
        "role": role,
        "context": None,
        "evidence_text": "цитата",
        "source_locator": None,
    }


def _mail(
    db_session,
    *,
    sender: str,
    user_id=BOOTSTRAP_USER_ID,
    metadata: dict | None = None,
    title: str = "note",
    body: str = "",
    when: datetime | None = None,
) -> None:
    db_session.add(
        Object(
            user_id=user_id,
            kind="email",
            provider="yandex_mail",
            title=title,
            body=body,
            origin="source",
            state="observed",
            occurred_at=when or datetime.now(UTC),
            metadata_=metadata or {"folder": "inbox", "sender": sender, "to": "me@example.com"},
        )
    )
    db_session.flush()


def _chat(db_session, user_id, *, provider: str, metadata: dict) -> None:
    db_session.add(
        Object(
            user_id=user_id,
            kind="chat_message",
            provider=provider,
            title="chat",
            origin="source",
            state="observed",
            occurred_at=datetime.now(UTC),
            metadata_=metadata,
        )
    )
    db_session.flush()


def _user(db_session) -> User:
    user = User(display_name="REL1DHG14 user")
    db_session.add(user)
    db_session.flush()
    return user


def _mattermost_account(db_session, user_id) -> MattermostAccount:
    account = MattermostAccount(
        user_id=user_id,
        server_url="https://chat.example.com",
        remote_user_id="self-hg14",
        username="me",
        access_token_encrypted="token",
    )
    db_session.add(account)
    db_session.flush()
    return account


def _count(db_session, model) -> int:
    return db_session.scalar(select(func.count()).select_from(model))


def _count_people(db_session) -> int:
    return db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.kind == "person",
        )
    )
