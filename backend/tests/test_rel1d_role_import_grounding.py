"""Deterministic read-only grounding for a role-import proposal."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError as ModelValidationError
from sqlalchemy import func, select

from app.core.config import settings
from app.db.models import (
    AITrace,
    AITraceEvent,
    Edge,
    Notification,
    Object,
    PendingActionPlan,
    PersonIdentity,
    PersonIdentityEvidence,
    PersonPromotionFeedback,
    PersonRoleAssignment,
    PersonRoleTerm,
    User,
)
from app.domain.person_identity import normalize_email
from app.domain.person_promotion import promotion_candidate_key
from app.domain.person_role_text import role_term_identity
from app.services.errors import NotFoundError, ValidationError
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_identity_service import PersonIdentityService
from app.services.person_promotion_service import PersonPromotionService
from app.services.person_role_import_grounding_service import (
    PersonRoleImportGroundingService,
    RoleImportGroundInputItem,
    RoleImportGroundRequest,
    _exact_terms,
    _suggestion_texts,
)
from app.services.person_role_import_source_service import (
    ROLE_IMPORT_MAX_SOURCE_TEXT_CHARS,
    PersonRoleImportSourceService,
)
from app.services.person_role_service import PersonRoleService
from app.services.provenance import REJECTED_STATE
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_rel1d_role_import_source import PNG, _register_raster, _text_object

_NAME = "REL1DB Резолв Один"
_AMBIGUOUS = "REL1DB Двойной"
_VARIANT_CANON = "Ольга REL1DBФамилия"
_VARIANT_QUERY = "Оля REL1DBФамилия"
_PROMO = "REL1DB Уникада"
_ROLE = "rel1dbдиректор"
_NEAR = "генеральный rel1dbдиректор"


def test_unchanged_source_revision_grounds(db_session, tmp_path) -> None:
    obj, revision = _image(db_session, tmp_path)
    proposal = _ground(db_session, tmp_path, obj.id, revision, [_row(_NAME, _ROLE)])
    assert proposal.source_object_id == obj.id
    assert proposal.source_revision == revision
    assert proposal.source_kind == "image"
    assert proposal.items == []
    assert proposal.grounding_revision


def test_changed_image_bytes_reject_stale_revision(db_session, tmp_path) -> None:
    obj, revision = _image(db_session, tmp_path)
    path = Path(obj.metadata_["upload_path"])
    updated = PNG + b"\x00changed"
    path.write_bytes(updated)
    digest = hashlib.sha256(updated).hexdigest()
    obj.metadata_ = {**obj.metadata_, "content_hash": digest}
    db_session.flush()
    with pytest.raises(ValidationError, match="role_import_source_changed"):
        _ground(db_session, tmp_path, obj.id, revision, [_row(_NAME, _ROLE)])
    fresh = _ground(db_session, tmp_path, obj.id, digest, [_row(_NAME, _ROLE)])
    assert fresh.source_revision == digest


def test_changed_text_revision_rejects_stale_grounding(db_session, tmp_path) -> None:
    obj = _text_object(db_session, "alpha text")
    revision = _sources(db_session, tmp_path).load(obj.id).source_revision
    obj.body = "beta text"
    db_session.flush()
    with pytest.raises(ValidationError, match="role_import_source_changed"):
        _ground(db_session, tmp_path, obj.id, revision, [_row(_NAME, _ROLE)])


def test_request_rejects_injected_ids(auth_client, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "resource_upload_root", str(tmp_path))
    response = auth_client.post(
        "/people/role-import/ground",
        json={
            "source_object_id": "00000000-0000-0000-0000-000000000001",
            "source_revision": "abc",
            "items_truncated": False,
            "person_id": "00000000-0000-0000-0000-000000000002",
            "role_term_id": "00000000-0000-0000-0000-000000000003",
            "assignment_id": "00000000-0000-0000-0000-000000000004",
            "selected_candidate": "ada",
            "items": [_row(_NAME, _ROLE)],
        },
    )
    assert response.status_code == 422


def test_unique_person_resolves_without_salience(db_session, tmp_path) -> None:
    person = _known_person(db_session, _NAME)
    obj, revision = _image(db_session, tmp_path)
    item = _ground(db_session, tmp_path, obj.id, revision, [_row(_NAME, _ROLE)]).items[0]
    assert item.person_resolution.state == "resolved"
    assert item.person_resolution.person_id == person.id
    assert item.person_resolution.title == _NAME
    dumped = item.person_resolution.model_dump()
    assert "salience_score" not in dumped
    assert "salience_tier" not in dumped


def test_ambiguous_people_stay_ambiguous_and_sort_neutrally(db_session, tmp_path) -> None:
    second = _known_person(db_session, _AMBIGUOUS)
    first = _known_person(db_session, _AMBIGUOUS)
    obj, revision = _image(db_session, tmp_path)
    item = _ground(db_session, tmp_path, obj.id, revision, [_row(_AMBIGUOUS, _ROLE)]).items[0]
    assert item.person_resolution.state == "ambiguous"
    assert item.person_resolution.person_id is None
    titles = [candidate.title for candidate in item.person_resolution.candidates]
    assert titles == [_AMBIGUOUS, _AMBIGUOUS]
    ordered = sorted((str(first.id), str(second.id)))
    assert [str(candidate.person_id) for candidate in item.person_resolution.candidates] == ordered


def test_name_variant_stays_ambiguous(db_session, tmp_path) -> None:
    person = _known_person(db_session, _VARIANT_CANON)
    obj, revision = _image(db_session, tmp_path)
    item = _ground(db_session, tmp_path, obj.id, revision, [_row(_VARIANT_QUERY, _ROLE)]).items[0]
    assert item.person_resolution.state == "ambiguous"
    assert item.person_resolution.person_id is None
    assert item.person_resolution.candidates[0].person_id == person.id
    assert "name_variant" in item.person_resolution.candidates[0].reasons
    assert item.person_resolution.promotion_candidates == []


def test_no_match_is_omitted(db_session, tmp_path) -> None:
    obj, revision = _image(db_session, tmp_path)
    proposal = _ground(db_session, tmp_path, obj.id, revision, [_row("Никого Нет Гроунд", _ROLE)])
    assert proposal.items == []


def test_promotion_comes_only_from_repeated_direct_contact(db_session, tmp_path) -> None:
    _mail(db_session, f"{_PROMO} <uniquada-ground@example.com>")
    _mail(db_session, f"{_PROMO} <uniquada-ground@example.com>")
    obj = _text_object(db_session, f"{_PROMO} is written only in this document")
    revision = _sources(db_session, tmp_path).load(obj.id).source_revision
    item = _ground(db_session, tmp_path, obj.id, revision, [_row(_PROMO, _ROLE)]).items[0]
    assert item.person_resolution.state == "promotion_candidates"
    assert len(item.person_resolution.promotion_candidates) == 1
    candidate = item.person_resolution.promotion_candidates[0]
    assert candidate.display_name == _PROMO
    assert candidate.direct_hit_count == 2
    assert candidate.provider
    dumped = json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
    assert "uniquada-ground@example.com" not in dumped
    assert "canonical_value" not in dumped


def test_document_name_alone_is_not_a_promotion(db_session, tmp_path) -> None:
    obj = _text_object(db_session, "Только Документ Гроунд")
    revision = _sources(db_session, tmp_path).load(obj.id).source_revision
    proposal = _ground(
        db_session, tmp_path, obj.id, revision, [_row("Только Документ Гроунд", _ROLE)]
    )
    assert proposal.items == []


def test_promotion_bridge_is_exact_display_only(db_session, tmp_path) -> None:
    _mail(db_session, f"{_PROMO} <uniquada-exact@example.com>")
    _mail(db_session, f"{_PROMO} <uniquada-exact@example.com>")
    obj, revision = _image(db_session, tmp_path)
    exact = _ground(
        db_session, tmp_path, obj.id, revision, [_row(f"  {_PROMO.lower()}  ", _ROLE)]
    ).items[0]
    near = _ground(
        db_session,
        tmp_path,
        obj.id,
        revision,
        [_row(f"{_PROMO} extra", _ROLE), _row(_PROMO.split()[0], _ROLE)],
    )
    assert exact.person_resolution.state == "promotion_candidates"
    assert exact.person_name == _PROMO.lower()
    assert near.items == []


def test_two_promotion_identities_are_not_auto_chosen(db_session, tmp_path) -> None:
    addresses = [f"ada-ground-{index}@example.com" for index in range(4)]
    for address in addresses:
        _mail(db_session, f"{_PROMO} <{address}>")
        _mail(db_session, f"{_PROMO} <{address}>")
    obj, revision = _image(db_session, tmp_path)
    item = _ground(db_session, tmp_path, obj.id, revision, [_row(_PROMO, _ROLE)]).items[0]
    keys = sorted(promotion_candidate_key(normalize_email(f"{_PROMO} <{address}>")) for address in addresses)
    found = [candidate.candidate_key for candidate in item.person_resolution.promotion_candidates]
    assert item.person_resolution.person_id is None
    assert found == keys[:3]


def test_suppressed_and_owned_promotions_are_absent(db_session, tmp_path) -> None:
    owned = normalize_email(f"{_PROMO} <owned-ground@example.com>")
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("REL1DB Уже Есть")
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).attach(person.id, owned)
    _mail(db_session, f"{_PROMO} <owned-ground@example.com>")
    _mail(db_session, f"{_PROMO} <owned-ground@example.com>")
    suppressed = normalize_email("REL1DB Скрытый <hidden-ground@example.com>")
    _mail(db_session, "REL1DB Скрытый <hidden-ground@example.com>")
    _mail(db_session, "REL1DB Скрытый <hidden-ground@example.com>")
    PersonPromotionService(db_session, BOOTSTRAP_USER_ID).suppress(suppressed)
    obj, revision = _image(db_session, tmp_path)
    states = _ground(
        db_session,
        tmp_path,
        obj.id,
        revision,
        [_row(_PROMO, _ROLE), _row("REL1DB Скрытый", _ROLE)],
    )
    assert len(states.items) == 1
    owned_row = states.items[0]
    assert owned_row.person_resolution.state == "resolved"
    assert owned_row.person_resolution.person_id == person.id
    assert owned_row.person_resolution.promotion_candidates == []


def test_exact_role_is_reused_including_case_and_space(db_session, tmp_path) -> None:
    _known_person(db_session, _NAME)
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Роль Гроунд")
    assigned = PersonRoleService(db_session, BOOTSTRAP_USER_ID).assign(person.id, _ROLE)
    obj, revision = _image(db_session, tmp_path)
    item = _ground(
        db_session, tmp_path, obj.id, revision, [_row(_NAME, f"  {_ROLE.upper()}  ")]
    ).items[0]
    assert item.role_resolution.state == "reuse_existing"
    assert item.role_resolution.role_term_id == assigned.role_term_id
    assert item.role_resolution.display_text == _ROLE
    assert item.role_resolution.suggestions == []
    assert item.role == _ROLE.upper()


def test_semantic_near_role_stays_new_and_caps_suggestions(db_session, tmp_path) -> None:
    _known_person(db_session, _NAME)
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Подсказки Гроунд")
    roles = PersonRoleService(db_session, BOOTSTRAP_USER_ID)
    roles.assign(person.id, _NEAR)
    for index in range(5):
        roles.assign(person.id, f"я {_ROLE} {index}", context=f"ctx {index}")
    obj, revision = _image(db_session, tmp_path)
    item = _ground(db_session, tmp_path, obj.id, revision, [_row(_NAME, _ROLE)]).items[0]
    assert item.role_resolution.state == "propose_new"
    assert item.role_resolution.role_term_id is None
    assert item.role_resolution.display_text == _ROLE
    assert item.role_resolution.suggestions[0] == _NEAR
    assert len(item.role_resolution.suggestions) == 5
    assert f"я {_ROLE} 4" not in item.role_resolution.suggestions
    assert item.role_resolution.display_text not in item.role_resolution.suggestions


def test_input_order_and_query_discipline(db_session, tmp_path, monkeypatch) -> None:
    calls = {"resolve": 0, "promotion": 0, "exact": 0, "suggest": 0}

    def _resolve(self, query: str):
        calls["resolve"] += 1
        return _original_resolve(self, query)

    def _eligible(self):
        calls["promotion"] += 1
        return _original_eligible(self)

    def _exact(session, user_id, keys):
        calls["exact"] += 1
        return _original_exact(session, user_id, keys)

    def _suggest(session, user_id, key):
        calls["suggest"] += 1
        return _original_suggest(session, user_id, key)

    _original_resolve = PersonAssistantService.resolve
    _original_eligible = PersonPromotionService.eligible_role_import_participants
    _original_exact = _exact_terms
    _original_suggest = _suggestion_texts
    monkeypatch.setattr(PersonAssistantService, "resolve", _resolve)
    monkeypatch.setattr(PersonPromotionService, "eligible_role_import_participants", _eligible)
    monkeypatch.setattr(
        "app.services.person_role_import_grounding_service._exact_terms", _exact
    )
    monkeypatch.setattr(
        "app.services.person_role_import_grounding_service._suggestion_texts", _suggest
    )
    obj, revision = _image(db_session, tmp_path)
    rows = [
        _row("Первый Гроунд", "новая роль гроунд а"),
        _row("Первый Гроунд", "новая роль гроунд б"),
        _row("Второй Гроунд", "новая роль гроунд а"),
    ]
    proposal = _ground(db_session, tmp_path, obj.id, revision, rows)
    assert proposal.items == []
    assert calls == {"resolve": 2, "promotion": 1, "exact": 1, "suggest": 2}


def test_grounding_revision_tracks_facts(db_session, tmp_path) -> None:
    obj, revision = _image(db_session, tmp_path)
    rows = [_row(_NAME, _ROLE)]
    first = _ground(db_session, tmp_path, obj.id, revision, rows)
    second = _ground(db_session, tmp_path, obj.id, revision, rows)
    assert first.grounding_revision == second.grounding_revision
    person = _known_person(db_session, _NAME)
    resolved = _ground(db_session, tmp_path, obj.id, revision, rows)
    assert resolved.grounding_revision != first.grounding_revision
    PersonRoleService(db_session, BOOTSTRAP_USER_ID).assign(person.id, _ROLE)
    reused = _ground(db_session, tmp_path, obj.id, revision, rows)
    assert reused.grounding_revision != resolved.grounding_revision
    changed_row = _ground(db_session, tmp_path, obj.id, revision, [_row(_NAME, _ROLE, context="иной")])
    assert changed_row.grounding_revision != reused.grounding_revision


def test_endpoint_does_not_write_or_call_a_model(db_session, tmp_path, monkeypatch) -> None:
    def _forbid(*_args, **_kwargs):
        raise AssertionError("provider was constructed")

    monkeypatch.setattr(
        "app.llm.openai_role_import_provider.OpenAIRoleImportExtractionProvider.for_user",
        _forbid,
    )
    obj, revision = _image(db_session, tmp_path)
    before = _counts(db_session)
    _ground(db_session, tmp_path, obj.id, revision, [_row(_NAME, _ROLE)])
    assert _counts(db_session) == before


def test_cross_user_and_hidden_sources_fail_closed(db_session, tmp_path, nornickel_user_id) -> None:
    foreign = Object(
        user_id=nornickel_user_id,
        kind="document",
        title="foreign",
        body="secret",
        origin="user",
        state="confirmed",
        metadata_={},
    )
    hidden = _text_object(db_session, "hidden body")
    hidden.state = REJECTED_STATE
    db_session.add(foreign)
    db_session.flush()
    with pytest.raises(NotFoundError):
        _ground(db_session, tmp_path, foreign.id, "abc", [_row(_NAME, _ROLE)])
    with pytest.raises(NotFoundError):
        _ground(db_session, tmp_path, hidden.id, "abc", [_row(_NAME, _ROLE)])


def test_items_truncated_is_required_and_changes_grounding_revision(db_session, tmp_path) -> None:
    obj, revision = _image(db_session, tmp_path)
    payload = {
        "source_object_id": obj.id,
        "source_revision": revision,
        "items": [_row(_NAME, _ROLE)],
    }
    with pytest.raises(ModelValidationError):
        RoleImportGroundRequest.model_validate(payload)
    rows = [_row(f"REL1DB Строка {index}", _ROLE) for index in range(32)]
    complete = _ground(db_session, tmp_path, obj.id, revision, rows, items_truncated=False)
    truncated = _ground(db_session, tmp_path, obj.id, revision, rows, items_truncated=True)
    assert complete.items == []
    assert truncated.items == []
    assert complete.items_truncated is False
    assert truncated.items_truncated is True
    assert complete.grounding_revision != truncated.grounding_revision
    assert complete.source_kind == "image"
    assert complete.source_truncated is False
    long_text = "я" * (ROLE_IMPORT_MAX_SOURCE_TEXT_CHARS + 1)
    text = _text_object(db_session, long_text)
    text_revision = _sources(db_session, tmp_path).load(text.id).source_revision
    derived = _ground(db_session, tmp_path, text.id, text_revision, [_row(_NAME, _ROLE)])
    assert derived.source_kind == "text"
    assert derived.source_truncated is True
    assert derived.items_truncated is False


def test_zero_rows_skip_promotion_scan(db_session, tmp_path, monkeypatch) -> None:
    calls = {"promotion": 0}
    original = PersonPromotionService.eligible_role_import_participants

    def _eligible(self):
        calls["promotion"] += 1
        return original(self)

    monkeypatch.setattr(PersonPromotionService, "eligible_role_import_participants", _eligible)
    obj, revision = _image(db_session, tmp_path)
    proposal = _service(db_session, tmp_path).ground(
        RoleImportGroundRequest(
            source_object_id=obj.id,
            source_revision=revision,
            items_truncated=False,
            items=[],
        )
    )
    assert proposal.items == []
    assert calls["promotion"] == 0
    assert role_term_identity(_ROLE)[0] == _ROLE


def test_http_source_conflict_detail(auth_client, db_session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "resource_upload_root", str(tmp_path / "uploads"))
    obj, _revision = _image(db_session, tmp_path)
    response = auth_client.post(
        "/people/role-import/ground",
        json={
            "source_object_id": str(obj.id),
            "source_revision": "stale",
            "items_truncated": False,
            "items": [_row(_NAME, _ROLE)],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "role_import_source_changed"


def _known_person(db_session, title: str):
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(title)
    address = f"known-{person.id.hex[:12]}@example.com"
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).attach(
        person.id, normalize_email(f"{title} <{address}>")
    )
    _mail(db_session, f"{title} <{address}>")
    return person


def test_resolved_person_without_communication_is_omitted(db_session, tmp_path) -> None:
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    obj, revision = _image(db_session, tmp_path)
    proposal = _ground(db_session, tmp_path, obj.id, revision, [_row(_NAME, _ROLE)])
    assert proposal.items == []


def test_ambiguous_keeps_only_communication_backed_candidates(db_session, tmp_path) -> None:
    backed = _known_person(db_session, _AMBIGUOUS)
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_AMBIGUOUS)
    obj, revision = _image(db_session, tmp_path)
    item = _ground(db_session, tmp_path, obj.id, revision, [_row(_AMBIGUOUS, _ROLE)]).items[0]
    assert item.person_resolution.state == "ambiguous"
    assert item.person_resolution.person_id is None
    assert [candidate.person_id for candidate in item.person_resolution.candidates] == [backed.id]


def test_filtered_ambiguous_people_do_not_fall_through_to_promotion(db_session, tmp_path) -> None:
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_PROMO)
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_PROMO)
    _mail(db_session, f"{_PROMO} <promo-only-ground@example.com>")
    _mail(db_session, f"{_PROMO} <promo-only-ground@example.com>")
    obj, revision = _image(db_session, tmp_path)
    proposal = _ground(db_session, tmp_path, obj.id, revision, [_row(_PROMO, _ROLE)])
    assert proposal.items == []


def test_filtered_rows_keep_original_indexes(db_session, tmp_path) -> None:
    _known_person(db_session, _NAME)
    obj, revision = _image(db_session, tmp_path)
    proposal = _ground(
        db_session,
        tmp_path,
        obj.id,
        revision,
        [_row("Никого Нет Гроунд", _ROLE), _row(_NAME, _ROLE), _row("Ещё Никого", _NEAR)],
    )
    assert [item.row_index for item in proposal.items] == [1]
    assert proposal.items[0].role_resolution.state == "propose_new"


def test_truncated_zero_count_stays_omitted(db_session, tmp_path, monkeypatch) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)

    def _count(self, person_ids, **_kwargs):
        return {person_id: 0 for person_id in person_ids}, True

    monkeypatch.setattr(PersonAssistantService, "count_attributable_communications", _count)
    obj, revision = _image(db_session, tmp_path)
    proposal = _ground(db_session, tmp_path, obj.id, revision, [_row(_NAME, _ROLE)])
    assert proposal.items == []
    assert person.id


def _ground(
    db_session,
    tmp_path: Path,
    object_id,
    revision: str,
    items: list[dict],
    *,
    items_truncated: bool = False,
):
    return _service(db_session, tmp_path).ground(
        RoleImportGroundRequest(
            source_object_id=object_id,
            source_revision=revision,
            items_truncated=items_truncated,
            items=[RoleImportGroundInputItem.model_validate(item) for item in items],
        )
    )


def _service(db_session, tmp_path: Path) -> PersonRoleImportGroundingService:
    return PersonRoleImportGroundingService(
        db_session, BOOTSTRAP_USER_ID, tmp_path / "uploads"
    )


def _sources(db_session, tmp_path: Path) -> PersonRoleImportSourceService:
    return PersonRoleImportSourceService(db_session, BOOTSTRAP_USER_ID, tmp_path / "uploads")


def _image(db_session, tmp_path: Path):
    result = _register_raster(db_session, tmp_path / "uploads", "shot.png", PNG, ingest=False)
    obj = db_session.get(Object, result.object_id)
    revision = hashlib.sha256(PNG).hexdigest()
    return obj, revision


def _row(name: str, role: str, *, context: str | None = None) -> dict:
    return {
        "person_name": name,
        "role": role,
        "context": context,
        "evidence_text": "цитата",
        "source_locator": None,
    }


def _mail(db_session, sender: str) -> None:
    db_session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="email",
            provider="yandex_mail",
            title="note",
            origin="source",
            state="observed",
            occurred_at=datetime.now(UTC),
            metadata_={"folder": "inbox", "sender": sender, "to": "me@example.com"},
        )
    )
    db_session.flush()


def _counts(db_session) -> dict[str, int]:
    tables = (
        Object,
        Edge,
        PersonIdentity,
        PersonIdentityEvidence,
        PersonPromotionFeedback,
        PersonRoleTerm,
        PersonRoleAssignment,
        PendingActionPlan,
        Notification,
        AITrace,
        AITraceEvent,
        User,
    )
    return {
        table.__tablename__: db_session.scalar(select(func.count()).select_from(table))
        for table in tables
    }
