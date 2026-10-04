"""Role-import exact-name mention fallback. It never invents an identity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.models import (
    AITrace,
    Object,
    PersonIdentity,
    PersonIdentityEvidence,
    PersonRoleAssignment,
)
from app.domain.person_identity import normalize_email
from app.domain.person_promotion import promotion_candidate_key
from app.domain.role_import_mentions import mention_candidate_key
from app.services.action_plan_service import ActionPlanService
from app.services.errors import ValidationError
from app.services.person_identity_service import PersonIdentityService
from app.services.person_role_import_mention_service import (
    PersonRoleImportMentionEvidenceService,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_rel1d_role_import_batch import (
    _approve,
    _fact_counts,
    _input,
    _proposal,
    _service,
)
from tests.test_rel1d_role_import_grounding import _ground, _image, _known_person
from tests.test_rel1d_role_import_source import _text_object

_NAME = "Шабаршина HG15 Тест"
_ROLE = "hg15рольа"
_ROLE_B = "hg15рольб"
_OTHER = "Петрова HG15 Другая"


def test_two_distinct_objects_make_one_mention_candidate(db_session, tmp_path) -> None:
    _mention(db_session, body=f"письмо про {_NAME}")
    _mention(db_session, body=f"ещё раз {_NAME} в другом письме")
    item = _item(db_session, tmp_path, _NAME)
    candidate = item.person_resolution.promotion_candidates[0]
    assert item.person_resolution.state == "promotion_candidates"
    assert len(item.person_resolution.promotion_candidates) == 1
    assert candidate.evidence_kind == "name_mentions"
    assert candidate.display_name == _NAME
    assert candidate.direct_hit_count == 2
    assert candidate.communication_object_count == 2
    assert candidate.candidate_key == mention_candidate_key(_NAME)
    assert candidate.sources == []
    dumped = candidate.model_dump(mode="json")
    assert "identity" not in dumped
    assert "@" not in str(dumped)


def test_repeated_mentions_in_one_object_are_not_enough(db_session, tmp_path) -> None:
    _mention(db_session, body=f"{_NAME}. {_NAME}. {_NAME}.")
    assert _ground_items(db_session, tmp_path, _NAME) == []


def test_substring_and_partial_names_are_not_mentions(db_session, tmp_path) -> None:
    _mention(db_session, body="Шабаршина HG15 рядом")
    _mention(db_session, body="Шабаршина HG15 Тестовна")
    assert _ground_items(db_session, tmp_path, _NAME) == []


def test_single_token_name_is_not_mention_backed(db_session, tmp_path) -> None:
    _mention(db_session, title="HG15solo")
    _mention(db_session, body="HG15solo")
    assert _ground_items(db_session, tmp_path, "HG15solo") == []


def test_case_and_internal_whitespace_match(db_session, tmp_path) -> None:
    _mention(db_session, body="шабаршина    hg15     тест")
    _mention(db_session, title="ШАБАРШИНА HG15 ТЕСТ")
    candidate = _item(db_session, tmp_path, "  шабаршина   hg15   тест ").person_resolution.promotion_candidates[0]
    assert candidate.evidence_kind == "name_mentions"
    assert candidate.communication_object_count == 2
    assert candidate.candidate_key == mention_candidate_key("шабаршина hg15 тест")


def test_title_body_and_subject_each_count(db_session, tmp_path) -> None:
    _mention(db_session, title=_NAME)
    _mention(db_session, body=_NAME)
    _mention(db_session, subject=_NAME)
    candidate = _item(db_session, tmp_path, _NAME).person_resolution.promotion_candidates[0]
    assert candidate.communication_object_count == 3


def test_identity_participant_supersedes_mention_fallback(db_session, tmp_path) -> None:
    _mention(db_session, body=_NAME)
    _mention(db_session, body=_NAME)
    sender = f"{_NAME} <hg15-identity@example.com>"
    _mention(db_session, sender=sender)
    candidate = _item(db_session, tmp_path, _NAME).person_resolution.promotion_candidates[0]
    assert candidate.evidence_kind == "identity_participant"
    assert candidate.candidate_key == promotion_candidate_key(normalize_email(sender))
    assert candidate.candidate_key != mention_candidate_key(_NAME)


def test_source_only_name_stays_omitted(db_session, tmp_path) -> None:
    source = _text_object(db_session, _NAME)
    from app.services.person_role_import_source_service import PersonRoleImportSourceService

    revision = PersonRoleImportSourceService(
        db_session, BOOTSTRAP_USER_ID, tmp_path / "uploads"
    ).load(source.id).source_revision
    proposal = _ground(db_session, tmp_path, source.id, revision, [_row(_NAME)])
    assert proposal.items == []


def test_mention_scan_runs_once_for_the_batch(db_session, tmp_path, monkeypatch) -> None:
    _mention(db_session, body=_NAME)
    _mention(db_session, body=_NAME)
    _mention(db_session, body=_OTHER)
    _mention(db_session, body=_OTHER)
    calls = {"n": 0}
    original = PersonRoleImportMentionEvidenceService.evidence_for

    def _counted(self, names):
        calls["n"] += 1
        return original(self, names)

    monkeypatch.setattr(PersonRoleImportMentionEvidenceService, "evidence_for", _counted)
    obj, revision = _image(db_session, tmp_path)
    proposal = _ground(
        db_session,
        tmp_path,
        obj.id,
        revision,
        [_row(_NAME), _row(_NAME, _ROLE_B), _row(_OTHER)],
    )
    assert calls["n"] == 1
    assert len(proposal.items) == 3


def test_execute_scans_two_mention_names_once(db_session, tmp_path, monkeypatch) -> None:
    _mention(db_session, body=_NAME)
    _mention(db_session, body=_NAME)
    _mention(db_session, body=_OTHER)
    _mention(db_session, body=_OTHER)
    calls: list[list[str]] = []
    original = PersonRoleImportMentionEvidenceService.evidence_for

    def _spy(self, names):
        calls.append(list(names))
        return original(self, names)

    monkeypatch.setattr(PersonRoleImportMentionEvidenceService, "evidence_for", _spy)
    plan, _key = _plan(db_session, tmp_path, [_row(_NAME), _row(_OTHER, _ROLE_B)], [0, 1])
    calls.clear()
    output = _approve(db_session, plan.id).result["actions"][0]["output"]
    assert calls == [[_NAME, _OTHER]]
    assert output["people_created"] == 2
    assert {row["person_id"] for row in output["rows"]} == {
        output["rows"][0]["person_id"],
        output["rows"][1]["person_id"],
    }
    assert output["rows"][0]["person_id"] != output["rows"][1]["person_id"]
    for row in output["rows"]:
        assert _identity_count(db_session, row["person_id"]) == 0
        assert _evidence_count(db_session, row["person_id"]) == 0


def test_execute_without_mention_rows_does_not_scan(db_session, tmp_path, monkeypatch) -> None:
    name = "HG151 Известный Человек"
    person = _known_person(db_session, name)
    calls: list[list[str]] = []
    original = PersonRoleImportMentionEvidenceService.evidence_for

    def _spy(self, names):
        calls.append(list(names))
        return original(self, names)

    monkeypatch.setattr(PersonRoleImportMentionEvidenceService, "evidence_for", _spy)
    source, revision, proposal = _proposal(db_session, tmp_path, [_row(name)])
    assert proposal.items[0].person_resolution.state == "resolved"
    plan = _service(db_session, tmp_path).prepare_plan(
        _input(
            source.id,
            revision,
            proposal.grounding_revision,
            [_row(name)],
            [{"row_index": 0, "person_id": str(person.id)}],
        )
    )
    calls.clear()
    view = _approve(db_session, plan.id)
    assert view.status == "executed"
    assert calls == []


def test_prepare_needs_an_explicit_candidate_and_writes_no_person(db_session, tmp_path) -> None:
    _mention(db_session, body=_NAME)
    _mention(db_session, body=_NAME)
    before = _fact_counts(db_session)
    source, revision, proposal = _proposal(db_session, tmp_path, [_row(_NAME)])
    assert _fact_counts(db_session)["people"] == before["people"]
    key = proposal.items[0].person_resolution.promotion_candidates[0].candidate_key
    with pytest.raises(ValidationError, match="not grounded"):
        _service(db_session, tmp_path).prepare(
            _input(source.id, revision, proposal.grounding_revision, [_row(_NAME)], [
                {"row_index": 0, "promotion_candidate_key": "a" * 64}
            ])
        )
    plan = _service(db_session, tmp_path).prepare_plan(
        _input(source.id, revision, proposal.grounding_revision, [_row(_NAME)], [
            {"row_index": 0, "promotion_candidate_key": key}
        ])
    )
    stored = plan
    assert stored.status == "pending"
    assert _fact_counts(db_session)["people"] == before["people"]
    assert _fact_counts(db_session)["identities"] == before["identities"]


def test_approve_creates_person_and_role_without_identity(db_session, tmp_path) -> None:
    _mention(db_session, body=_NAME)
    _mention(db_session, body=_NAME)
    traces = _traces(db_session)
    plan, key = _plan(db_session, tmp_path, [_row(_NAME)], [0])
    view = _approve(db_session, plan.id)
    output = view.result["actions"][0]["output"]
    assert view.status == "executed"
    assert output["people_created"] == 1
    person_id = output["rows"][0]["person_id"]
    person = db_session.get(Object, person_id)
    assert person.title == _NAME
    assert _identity_count(db_session, person.id) == 0
    assert _evidence_count(db_session, person.id) == 0
    assert len(_assignments(db_session, person.id)) == 1
    assert key == mention_candidate_key(_NAME)
    assert _traces(db_session) == traces


def test_reject_writes_nothing(db_session, tmp_path) -> None:
    _mention(db_session, body=_NAME)
    _mention(db_session, body=_NAME)
    before = _fact_counts(db_session)
    plan, _key = _plan(db_session, tmp_path, [_row(_NAME)], [0])
    view = ActionPlanService(db_session, BOOTSTRAP_USER_ID).reject(plan.id)
    assert view.status == "rejected"
    assert _fact_counts(db_session)["people"] == before["people"]
    assert _fact_counts(db_session)["assignments"] == before["assignments"]
    assert _fact_counts(db_session)["identities"] == before["identities"]


def test_lost_mention_evidence_fails_closed(db_session, tmp_path) -> None:
    first = _mention(db_session, body=_NAME)
    _mention(db_session, body=_NAME)
    before = _fact_counts(db_session)
    plan, _key = _plan(db_session, tmp_path, [_row(_NAME)], [0])
    db_session.delete(first)
    db_session.flush()
    view = _approve(db_session, plan.id)
    assert view.status == "failed"
    assert "role_import_grounding_changed" in view.failure
    assert _fact_counts(db_session)["people"] == before["people"]


def test_stronger_identity_before_approve_fails_closed(db_session, tmp_path) -> None:
    _mention(db_session, body=_NAME)
    _mention(db_session, body=_NAME)
    before = _fact_counts(db_session)
    plan, _key = _plan(db_session, tmp_path, [_row(_NAME)], [0])
    _mention(db_session, sender=f"{_NAME} <hg15-later@example.com>")
    view = _approve(db_session, plan.id)
    assert view.status == "failed"
    assert "role_import_grounding_changed" in view.failure
    assert _fact_counts(db_session)["people"] == before["people"]
    assert _fact_counts(db_session)["identities"] == before["identities"]


def test_new_exact_person_before_approve_fails_closed(db_session, tmp_path) -> None:
    _mention(db_session, body=_NAME)
    _mention(db_session, body=_NAME)
    before = _fact_counts(db_session)
    plan, _key = _plan(db_session, tmp_path, [_row(_NAME)], [0])
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    view = _approve(db_session, plan.id)
    assert view.status == "failed"
    assert "role_import_grounding_changed" in view.failure
    assert _fact_counts(db_session)["people"] == before["people"] + 1
    assert _fact_counts(db_session)["identities"] == before["identities"]


def test_two_rows_reuse_one_name_only_person(db_session, tmp_path) -> None:
    _mention(db_session, body=_NAME)
    _mention(db_session, body=_NAME)
    plan, _key = _plan(db_session, tmp_path, [_row(_NAME), _row(_NAME, _ROLE_B)], [0, 1])
    output = _approve(db_session, plan.id).result["actions"][0]["output"]
    assert output["people_created"] == 1
    assert output["assignments_changed"] == 2
    person_id = output["rows"][0]["person_id"]
    assert output["rows"][1]["person_id"] == person_id
    assert _identity_count(db_session, person_id) == 0
    assert len(_assignments(db_session, person_id)) == 2


def test_later_row_failure_rolls_back_the_name_only_person(db_session, tmp_path, monkeypatch) -> None:
    _mention(db_session, body=_NAME)
    _mention(db_session, body=_NAME)
    _mention(db_session, body=_OTHER)
    _mention(db_session, body=_OTHER)
    before = _fact_counts(db_session)
    plan, _key = _plan(
        db_session,
        tmp_path,
        [_row(_NAME), _row(_OTHER, _ROLE_B)],
        [0, 1],
    )
    real = PersonIdentityService.create_person

    def _second(self, title: str):
        if title == _OTHER:
            raise ValidationError("stop")
        return real(self, title)

    monkeypatch.setattr(PersonIdentityService, "create_person", _second)
    view = _approve(db_session, plan.id)
    assert view.status == "failed"
    assert _fact_counts(db_session)["people"] == before["people"]
    assert _fact_counts(db_session)["assignments"] == before["assignments"]
    assert _fact_counts(db_session)["identities"] == before["identities"]


def test_resolved_exact_title_can_use_mention_evidence(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    _mention(db_session, body=_NAME)
    _mention(db_session, title=_NAME)
    item = _item(db_session, tmp_path, _NAME)
    assert item.person_resolution.state == "resolved"
    assert item.person_resolution.person_id == person.id
    assert item.person_resolution.promotion_candidates == []


def test_ambiguous_exact_titles_stay_ambiguous_on_mentions(db_session, tmp_path) -> None:
    first = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    second = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    _mention(db_session, subject=_NAME)
    _mention(db_session, subject=_NAME)
    item = _item(db_session, tmp_path, _NAME)
    assert item.person_resolution.state == "ambiguous"
    assert item.person_resolution.person_id is None
    assert {candidate.person_id for candidate in item.person_resolution.candidates} == {
        first.id,
        second.id,
    }


def test_different_title_variant_is_not_blessed_by_mentions(db_session, tmp_path) -> None:
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("Ольга HG15Вариант")
    _mention(db_session, body="Оля HG15Вариант")
    _mention(db_session, body="Оля HG15Вариант")
    assert _ground_items(db_session, tmp_path, "Оля HG15Вариант") == []


def test_one_mention_inside_a_truncated_scan_fails_closed(db_session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.person_role_import_mention_service.MAX_PERSON_SCAN_ROWS",
        1,
    )
    _mention(db_session, body=_NAME, when=datetime.now(UTC))
    _mention(db_session, body=_NAME, when=datetime.now(UTC) - timedelta(days=1))
    assert _ground_items(db_session, tmp_path, _NAME) == []


def test_mention_card_uses_name_mentions_mode(db_session, tmp_path) -> None:
    _mention(db_session, body=_NAME)
    _mention(db_session, body=_NAME)
    plan, _key = _plan(db_session, tmp_path, [_row(_NAME)], [0])
    from app.db.models import PendingActionPlan

    stored = db_session.get(PendingActionPlan, plan.id)
    row = stored.actions[0]["arguments"]["selected_rows"][0]
    assert row["evidence_kind"] == "name_mentions"
    assert row["promotion_candidate_key"] == mention_candidate_key(_NAME)
    assert "body" not in row
    presentation = stored.actions[0]["presentation"]["rows"][0]
    assert presentation["target_mode"] == "name_mentions"
    assert presentation["target_display"] == _NAME
    assert "candidate_key" not in presentation
    assert plan.actions[0]["arguments"] == {}


def _item(db_session, tmp_path, name: str):
    return _ground_items(db_session, tmp_path, name)[0]


def _ground_items(db_session, tmp_path, name: str):
    obj, revision = _image(db_session, tmp_path)
    return _ground(db_session, tmp_path, obj.id, revision, [_row(name)]).items


def _plan(db_session, tmp_path, items, indexes):
    source, revision, proposal = _proposal(db_session, tmp_path, items)
    selections = []
    for index in indexes:
        key = proposal.items[index].person_resolution.promotion_candidates[0].candidate_key
        selections.append({"row_index": index, "promotion_candidate_key": key})
    plan = _service(db_session, tmp_path).prepare_plan(
        _input(source.id, revision, proposal.grounding_revision, items, selections)
    )
    return plan, selections[0]["promotion_candidate_key"]


def _row(name: str, role: str = _ROLE) -> dict:
    return {
        "person_name": name,
        "role": role,
        "context": None,
        "evidence_text": "цитата",
        "source_locator": None,
    }


def _mention(
    db_session,
    *,
    title: str = "note",
    body: str = "",
    subject: str | None = None,
    sender: str | None = None,
    when: datetime | None = None,
) -> Object:
    metadata = {"folder": "inbox", "to": "me@example.com"}
    if subject is not None:
        metadata["subject"] = subject
    if sender is not None:
        metadata["sender"] = sender
    row = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        provider="gmail",
        title=title,
        body=body,
        origin="source",
        state="observed",
        occurred_at=when or datetime.now(UTC),
        metadata_=metadata,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _identity_count(db_session, person_id) -> int:
    return int(
        db_session.scalar(
            select(func.count()).select_from(PersonIdentity).where(
                PersonIdentity.person_object_id == person_id
            )
        )
        or 0
    )


def _evidence_count(db_session, person_id) -> int:
    return int(
        db_session.scalar(
            select(func.count()).select_from(PersonIdentityEvidence).where(
                PersonIdentityEvidence.person_object_id == person_id
            )
        )
        or 0
    )


def _assignments(db_session, person_id) -> list[PersonRoleAssignment]:
    return list(
        db_session.scalars(
            select(PersonRoleAssignment).where(PersonRoleAssignment.person_object_id == person_id)
        )
    )


def _traces(db_session) -> int:
    return int(db_session.scalar(select(func.count()).select_from(AITrace)) or 0)
