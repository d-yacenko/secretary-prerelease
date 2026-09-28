"""Assisted Person promotion stays exact, bounded, and approval-gated."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.models import (
    Edge,
    MattermostAccount,
    Object,
    PersonIdentity,
    PersonIdentityEvidence,
    PersonPromotionFeedback,
    User,
)
from app.domain.person_assistant import MAX_PERSON_SCAN_ROWS
from app.domain.person_identity import normalize_email, normalize_mattermost_user_id
from app.services.errors import ConflictError, ValidationError
from app.services.person_graph_workspace_service import PersonGraphWorkspaceService
from app.services.person_identity_service import PersonIdentityService
from app.services.person_promotion_service import PersonPromotionService


def test_two_direct_email_hits_become_one_candidate(db_session) -> None:
    user_id = _user(db_session)
    _mail(db_session, user_id, sender="Ada <ada@example.com>")
    _mail(db_session, user_id, sender="ada@example.com")
    candidates, truncated, _hidden = _overview(db_session, user_id)
    assert truncated is False
    assert len(candidates) == 1
    assert candidates[0]["canonical_value"] == "ada@example.com"
    assert candidates[0]["direct_hit_count"] == 2
    assert candidates[0]["reasons"] == ["repeated_direct_contact"]
    assert candidates[0]["display_value"] == "Ada"


def test_one_direct_hit_is_not_a_candidate(db_session) -> None:
    user_id = _user(db_session)
    _mail(db_session, user_id, sender="ada@example.com")
    candidates, _truncated, _hidden = _overview(db_session, user_id)
    assert candidates == []


def test_public_email_exposure_is_not_a_candidate(db_session) -> None:
    user_id = _user(db_session)
    _mail(db_session, user_id, sender="ada@example.com", to=["me@example.com", "other@example.com"])
    _mail(db_session, user_id, sender="ada@example.com", to=["me@example.com", "other@example.com"])
    candidates, _truncated, _hidden = _overview(db_session, user_id)
    assert candidates == []


def test_owned_exact_identity_is_not_promoted(db_session) -> None:
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Ada")
    PersonIdentityService(db_session, user_id).attach(person.id, normalize_email("ada@example.com"))
    _mail(db_session, user_id, sender="ada@example.com")
    _mail(db_session, user_id, sender="ada@example.com")
    candidates, _truncated, _hidden = _overview(db_session, user_id)
    assert candidates == []


def test_email_spelling_dedupes_to_one_candidate(db_session) -> None:
    user_id = _user(db_session)
    _mail(db_session, user_id, sender="Ada@Example.com")
    _mail(db_session, user_id, sender="ada@example.com")
    candidates, _truncated, _hidden = _overview(db_session, user_id)
    assert len(candidates) == 1
    assert candidates[0]["direct_hit_count"] == 2


def test_mattermost_dm_qualifies(db_session) -> None:
    user_id = _user(db_session)
    account = _mattermost_account(db_session, user_id)
    for _index in range(2):
        _mattermost(db_session, user_id, account, author="user-ada", name="Ada")
    candidates, _truncated, _hidden = _overview(db_session, user_id)
    assert len(candidates) == 1
    assert candidates[0]["provider"] == "mattermost"
    assert candidates[0]["identity_type"] == "mattermost_user_id"
    assert candidates[0]["canonical_value"] == "user-ada"


def test_mattermost_self_author_is_not_a_candidate(db_session) -> None:
    user_id = _user(db_session)
    account = _mattermost_account(db_session, user_id, remote_user_id="self-user")
    for _index in range(2):
        _mattermost(db_session, user_id, account, author="self-user", name="Me")
    candidates, _truncated, _hidden = _overview(db_session, user_id)
    assert candidates == []


def test_mattermost_mixed_self_and_remote_needs_two_remote_hits(db_session) -> None:
    user_id = _user(db_session)
    account = _mattermost_account(db_session, user_id, remote_user_id="self-user")
    _mattermost(db_session, user_id, account, author="self-user", name="Me")
    _mattermost(db_session, user_id, account, author="user-ada", name="Ada")
    candidates, _truncated, _hidden = _overview(db_session, user_id)
    assert candidates == []


def test_mattermost_account_verification_fails_closed(db_session) -> None:
    other = _user(db_session)
    foreign = _mattermost_account(db_session, other, server="https://other.example.com")
    cases = (
        {"account_id": None},
        {"account_id": "not-a-uuid"},
        {"account_id": str(uuid.uuid4())},
        {"account": foreign},
        {"server": "https://elsewhere.example.com"},
        {"channel_type": "O"},
    )
    for case in cases:
        user_id = _user(db_session)
        account = case.get("account") or _mattermost_account(db_session, user_id)
        for _index in range(2):
            _mattermost(
                db_session,
                user_id,
                account,
                author="user-ada",
                name="Ada",
                server=case.get("server", "https://chat.example.com"),
                account_id=case["account_id"] if "account_id" in case else str(account.id),
                channel_type=case.get("channel_type", "D"),
            )
        candidates, _truncated, _hidden = _overview(db_session, user_id)
        assert candidates == []


def test_mattermost_self_approval_does_not_create_a_person(db_session) -> None:
    user_id = _user(db_session)
    account = _mattermost_account(db_session, user_id, remote_user_id="self-user")
    for _index in range(2):
        _mattermost(db_session, user_id, account, author="self-user", name="Me")
    identity = normalize_mattermost_user_id("https://chat.example.com", "self-user")
    before = _counts(db_session, user_id)
    with pytest.raises(ValidationError, match="promotion candidate is not exposed"):
        PersonPromotionService(db_session, user_id).approve(identity)
    db_session.commit()
    assert _counts(db_session, user_id) == before
    again, _truncated, _hidden = _overview(db_session, user_id)
    assert again == []


def test_teams_one_on_one_qualifies_and_group_does_not(db_session) -> None:
    user_id = _user(db_session)
    tenant = "33333333-3333-4333-8333-333333333333"
    direct = "11111111-1111-4111-8111-111111111111"
    group = "22222222-2222-4222-8222-222222222222"
    for chat_type, sender in (("oneOnOne", direct), ("group", group)):
        for _index in range(2):
            _chat(
                db_session,
                user_id,
                provider="teams",
                metadata={
                    "sender_kind": "user",
                    "direction": "inbound",
                    "chat_type": chat_type,
                    "tenant_id": tenant,
                    "sender_id": sender,
                    "sender_display_name": "Ada",
                },
            )
    candidates, _truncated, _hidden = _overview(db_session, user_id)
    assert [item["canonical_value"] for item in candidates] == [direct]


def test_telegram_private_qualifies_for_first_party_and_group_does_not(db_session) -> None:
    user_id = _user(db_session)
    for peer_kind in ("private", "group"):
        for _index in range(2):
            _chat(
                db_session,
                user_id,
                provider="telegram",
                metadata={
                    "transport": "mtproto",
                    "account_id": "account-1",
                    "peer_kind": peer_kind,
                    "direction": "inbound",
                    "sender_peer_id": 42 if peer_kind == "private" else 77,
                    "sender_display_name": "Ada",
                },
            )
    first_party, _truncated, _hidden = _overview(db_session, user_id)
    gated, _gated_truncated, _gated_hidden = PersonPromotionService(db_session, user_id).overview(
        include_quarantined_telegram=False
    )
    assert [item["canonical_value"] for item in first_party] == ["42"]
    assert gated == []


def test_scan_boundary_reports_truncation_without_passing_400(db_session) -> None:
    assert MAX_PERSON_SCAN_ROWS == 400
    inside = _user(db_session)
    _mail(db_session, inside, sender="ada@example.com", when=datetime.now(UTC))
    _mail(
        db_session, inside, sender="ada@example.com", when=datetime.now(UTC) - timedelta(minutes=1)
    )
    _noise(db_session, inside, 399)
    candidates, truncated, _hidden = _overview(db_session, inside)
    assert truncated is True
    assert len(candidates) == 1
    outside = _user(db_session)
    _noise(db_session, outside, 400)
    _mail(db_session, outside, sender="ada@example.com", when=datetime.now(UTC) - timedelta(days=2))
    _mail(
        db_session,
        outside,
        sender="ada@example.com",
        when=datetime.now(UTC) - timedelta(days=2, minutes=1),
    )
    missed, missed_truncated, _hidden = _overview(db_session, outside)
    assert missed_truncated is True
    assert missed == []


def test_source_previews_are_bounded_and_body_free(db_session) -> None:
    user_id = _user(db_session)
    for index in range(4):
        _mail(
            db_session,
            user_id,
            sender="Ada <ada@example.com>",
            title=f"note {index}",
            body="secret body",
            when=datetime.now(UTC) - timedelta(minutes=index),
        )
    candidates, _truncated, _hidden = _overview(db_session, user_id)
    sources = candidates[0]["sources"]
    assert len(sources) == 3
    assert all("body" not in source for source in sources)
    assert all(source["title"].startswith("note ") for source in sources)


def test_candidate_read_does_not_write(db_session) -> None:
    user_id = _user(db_session)
    _mail(db_session, user_id, sender="ada@example.com")
    _mail(db_session, user_id, sender="ada@example.com")
    before = _counts(db_session, user_id)
    _overview(db_session, user_id)
    assert _counts(db_session, user_id) == before


def test_suppression_is_exact_and_reversible(db_session) -> None:
    user_id = _user(db_session)
    _mail(db_session, user_id, sender="Ada <ada@example.com>")
    _mail(db_session, user_id, sender="ada@example.com")
    _mail(db_session, user_id, sender="Ada <ada.other@example.com>")
    _mail(db_session, user_id, sender="ada.other@example.com")
    service = PersonPromotionService(db_session, user_id)
    ada = normalize_email("ada@example.com")
    service.suppress(ada)
    candidates, _truncated, hidden = _overview(db_session, user_id)
    assert [item["canonical_value"] for item in candidates] == ["ada.other@example.com"]
    assert [item["canonical_value"] for item in hidden] == ["ada@example.com"]
    service.retract(ada)
    candidates, _truncated, hidden = _overview(db_session, user_id)
    assert {item["canonical_value"] for item in candidates} == {
        "ada@example.com",
        "ada.other@example.com",
    }
    assert hidden == []


def test_approval_creates_person_identity_and_confirmation_without_edges(db_session) -> None:
    user_id = _user(db_session)
    _mail(db_session, user_id, sender="Ada <ada@example.com>")
    _mail(db_session, user_id, sender="ada@example.com")
    service = PersonPromotionService(db_session, user_id)
    created = service.approve(normalize_email("ada@example.com"))
    repeated = service.approve(normalize_email("ADA@example.com"))
    assert repeated.id == created.id
    identities = list(
        db_session.scalars(
            select(PersonIdentity).where(PersonIdentity.person_object_id == created.id)
        )
    )
    evidence = list(
        db_session.scalars(
            select(PersonIdentityEvidence).where(
                PersonIdentityEvidence.person_object_id == created.id,
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.evidence_type == "user_confirmed",
            )
        )
    )
    edges = list(db_session.scalars(select(Edge).where(or_edges(user_id, created.id))))
    people = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(Object.user_id == user_id, Object.kind == "person")
    )
    assert people == 1
    assert created.title == "Ada"
    assert len(identities) == 1
    assert identities[0].canonical_value == "ada@example.com"
    assert identities[0].state == "confirmed"
    assert len(evidence) == 1
    assert edges == []
    candidates, _truncated, _hidden = _overview(db_session, user_id)
    assert candidates == []
    assert identities[0].display_value == "Ada"


def test_list_id_email_is_not_promoted(db_session) -> None:
    user_id = _user(db_session)
    for _index in range(2):
        _mail(
            db_session,
            user_id,
            sender="Ada <ada@example.com>",
            headers={"list-id": "<news.example.com>"},
        )
    candidates, _truncated, _hidden = _overview(db_session, user_id)
    assert candidates == []


def test_automated_mailbox_is_not_promoted_and_support_remains(db_session) -> None:
    user_id = _user(db_session)
    blocked = (
        "calendar-notification@google.com",
        "no-reply@example.com",
        "noreply@example.com",
        "do-not-reply@example.com",
        "donotreply@example.com",
        "mailer-daemon@example.com",
        "postmaster@example.com",
    )
    for sender in blocked:
        _mail(db_session, user_id, sender=sender)
        _mail(db_session, user_id, sender=sender)
    _mail(db_session, user_id, sender="Support <support@example.com>")
    _mail(db_session, user_id, sender="support@example.com")
    candidates, _truncated, _hidden = _overview(db_session, user_id)
    assert [item["canonical_value"] for item in candidates] == ["support@example.com"]


def test_automated_email_approval_is_rejected(db_session) -> None:
    user_id = _user(db_session)
    _mail(db_session, user_id, sender="calendar-notification@google.com")
    _mail(db_session, user_id, sender="calendar-notification@google.com")
    before = _counts(db_session, user_id)
    with pytest.raises(ValidationError, match="not exposed"):
        PersonPromotionService(db_session, user_id).approve(
            normalize_email("calendar-notification@google.com")
        )
    assert _counts(db_session, user_id) == before


def test_mattermost_display_name_survives_approval(db_session) -> None:
    user_id = _user(db_session)
    account = _mattermost_account(db_session, user_id)
    for _index in range(2):
        _mattermost(db_session, user_id, account, author="user-ada", name="Ada Lovelace")
    service = PersonPromotionService(db_session, user_id)
    candidates, _truncated, _hidden = service.overview(include_quarantined_telegram=True)
    assert candidates[0]["display_value"] == "Ada Lovelace"
    created = service.approve(normalize_mattermost_user_id("https://chat.example.com", "user-ada"))
    identity = db_session.scalar(
        select(PersonIdentity).where(PersonIdentity.person_object_id == created.id)
    )
    assert created.title == "Ada Lovelace"
    assert identity.display_value == "Ada Lovelace"
    assert identity.canonical_value == "user-ada"


def test_mattermost_username_fallback_survives_approval(db_session) -> None:
    user_id = _user(db_session)
    account = _mattermost_account(db_session, user_id)
    for _index in range(2):
        _mattermost(db_session, user_id, account, author="user-ada", username="ada")
    service = PersonPromotionService(db_session, user_id)
    candidates, _truncated, _hidden = service.overview(include_quarantined_telegram=True)
    assert candidates[0]["display_value"] == "ada"
    created = service.approve(
        normalize_mattermost_user_id(
            "https://chat.example.com",
            "user-ada",
            display_value="client-supplied",
        )
    )
    identity = db_session.scalar(
        select(PersonIdentity).where(PersonIdentity.person_object_id == created.id)
    )
    assert created.title == "ada"
    assert identity.display_value == "ada"


def test_mattermost_without_display_uses_canonical_title(db_session) -> None:
    user_id = _user(db_session)
    account = _mattermost_account(db_session, user_id)
    for _index in range(2):
        _mattermost(db_session, user_id, account, author="user-ada")
    service = PersonPromotionService(db_session, user_id)
    candidates, _truncated, _hidden = service.overview(include_quarantined_telegram=True)
    assert candidates[0]["display_value"] == "user-ada"
    created = service.approve(normalize_mattermost_user_id("https://chat.example.com", "user-ada"))
    identity = db_session.scalar(
        select(PersonIdentity).where(PersonIdentity.person_object_id == created.id)
    )
    assert created.title == "user-ada"
    assert identity.display_value is None


def test_conflicting_ownership_does_not_create_an_orphan(db_session) -> None:
    user_id = _user(db_session)
    owner = PersonIdentityService(db_session, user_id).create_person("Existing")
    PersonIdentityService(db_session, user_id).attach(owner.id, normalize_email("ada@example.com"))
    _mail(db_session, user_id, sender="ada@example.com")
    _mail(db_session, user_id, sender="ada@example.com")
    before = _counts(db_session, user_id)
    try:
        PersonPromotionService(db_session, user_id).approve(normalize_email("ada@example.com"))
    except ConflictError as exc:
        assert exc.message == "person identity is already bound"
    else:
        raise AssertionError("expected conflict")
    assert _counts(db_session, user_id) == before


def test_workspace_overview_exposes_promotions_and_rooted_does_not(db_session) -> None:
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Known")
    _mail(db_session, user_id, sender="Ada <ada@example.com>")
    _mail(db_session, user_id, sender="ada@example.com")
    workspace = PersonGraphWorkspaceService(db_session, user_id)
    overview = workspace.get_workspace()
    rooted = workspace.get_workspace(root_id=person.id)
    assert len(overview.promotion_candidates) == 1
    assert rooted.promotion_candidates == []
    assert rooted.promotion_suppressions == []


def _overview(db_session, user_id):
    return PersonPromotionService(db_session, user_id).overview(include_quarantined_telegram=True)


def _counts(db_session, user_id) -> tuple[int, int, int, int]:
    def count(model) -> int:
        return db_session.scalar(
            select(func.count()).select_from(model).where(model.user_id == user_id)
        )

    return (
        count(Object),
        count(PersonIdentity),
        count(PersonIdentityEvidence),
        count(PersonPromotionFeedback),
    )


def or_edges(user_id, person_id):
    return (Edge.user_id == user_id) & (
        (Edge.source_id == person_id) | (Edge.target_id == person_id)
    )


def _user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Promotion"))
    db_session.flush()
    return user_id


def _mail(
    db_session,
    user_id,
    *,
    sender: str,
    to="me@example.com",
    title="note",
    body=None,
    when=None,
    headers=None,
) -> None:
    metadata = {"folder": "inbox", "sender": sender, "to": to}
    if headers is not None:
        metadata["headers"] = headers
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
            metadata_=metadata,
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


def _mattermost_account(
    db_session,
    user_id,
    *,
    remote_user_id: str = "self-user",
    server: str = "https://chat.example.com",
) -> MattermostAccount:
    account = MattermostAccount(
        user_id=user_id,
        server_url=server,
        remote_user_id=remote_user_id,
        username="me",
        access_token_encrypted="token",
    )
    db_session.add(account)
    db_session.flush()
    return account


def _mattermost(
    db_session,
    user_id,
    account: MattermostAccount,
    *,
    author: str,
    name: str | None = None,
    username: str | None = None,
    server: str = "https://chat.example.com",
    account_id: str | None = "",
    channel_type: str = "D",
) -> None:
    metadata = {
        "server_url": server,
        "channel_type": channel_type,
        "author_user_id": author,
    }
    if name is not None:
        metadata["author_display_name"] = name
    if username is not None:
        metadata["author_username"] = username
    if account_id != "":
        metadata["account_id"] = account_id
    else:
        metadata["account_id"] = str(account.id)
    _chat(db_session, user_id, provider="mattermost", metadata=metadata)


def _noise(db_session, user_id, count: int) -> None:
    base = datetime.now(UTC) - timedelta(days=1)
    for index in range(count):
        _mail(
            db_session,
            user_id,
            sender=f"noise-{index}@example.com",
            when=base - timedelta(seconds=index),
        )
