"""Role-import evidence uses a 10_000-row window. Generic scans stay at 400."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import event, func, select

from app.db.models import AITrace, Object
from app.domain.person_assistant import (
    MAX_PERSON_SCAN_ROWS,
    MAX_ROLE_IMPORT_COMMUNICATION_SCAN_ROWS,
)
from app.domain.person_identity import normalize_email
from app.services.action_plan_service import ActionPlanService
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_identity_service import PersonIdentityService
from app.services.person_promotion_service import PersonPromotionService
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_rel1d_role_import_grounding import _ground, _image
from tests.test_rel1d_role_import_mentions import _mention, _plan, _row
from tests.test_rel1d_role_import_participants import _mail

_NAME = "HG2A Ирина Тест"
_ROLE = "hg2aроль"


def test_role_import_ceiling_is_independent_of_generic_400() -> None:
    assert MAX_PERSON_SCAN_ROWS == 400
    assert MAX_ROLE_IMPORT_COMMUNICATION_SCAN_ROWS == 10_000


def test_participant_outside_newest_400_is_visible_only_to_role_import(db_session, tmp_path) -> None:
    old = datetime.now(UTC) - timedelta(days=2)
    sender = f"{_NAME} <hg2a-old@example.com>"
    _mail(db_session, sender=sender, when=old)
    _mail(db_session, sender=sender, when=old)
    _newer(db_session, MAX_PERSON_SCAN_ROWS)
    promotion = PersonPromotionService(db_session, BOOTSTRAP_USER_ID)
    generic = {item.display_value for item in promotion.eligible_direct_contacts()}
    role_import = {item.display_value for item in promotion.eligible_role_import_participants()}
    assert _NAME not in generic
    assert _NAME in role_import
    item = _ground_name(db_session, tmp_path)
    assert item.person_resolution.promotion_candidates[0].evidence_kind == "identity_participant"


def test_two_mentions_outside_newest_400_qualify_and_one_does_not(db_session, tmp_path) -> None:
    old = datetime.now(UTC) - timedelta(days=2)
    _mention(db_session, body=_NAME, when=old)
    _mention(db_session, body=_NAME, when=old)
    _newer(db_session, MAX_PERSON_SCAN_ROWS)
    item = _ground_name(db_session, tmp_path)
    assert item.person_resolution.promotion_candidates[0].evidence_kind == "name_mentions"
    assert item.person_resolution.promotion_candidates[0].direct_hit_count == 2

    _mention(db_session, body="Другой HG2A Одиночный", when=old)
    _newer(db_session, MAX_PERSON_SCAN_ROWS)
    assert _ground_items(db_session, tmp_path, "Другой HG2A Одиночный") == []


def test_resolved_person_outside_newest_400_stays_actionable(db_session, tmp_path) -> None:
    person = _person_with_old_mail(db_session, _NAME)
    _newer(db_session, MAX_PERSON_SCAN_ROWS)
    assistant = PersonAssistantService(db_session, BOOTSTRAP_USER_ID)
    generic, truncated = assistant.count_attributable_communications([person.id])
    widened, widened_truncated = assistant.count_attributable_communications(
        [person.id],
        max_scan_rows=MAX_ROLE_IMPORT_COMMUNICATION_SCAN_ROWS,
    )
    assert generic[person.id] == 0
    assert truncated is True
    assert widened[person.id] == 1
    assert widened_truncated is False
    item = _ground_name(db_session, tmp_path)
    assert item.person_resolution.state == "resolved"
    assert item.person_resolution.person_id == person.id


def test_ambiguous_person_outside_newest_400_stays_ambiguous(db_session, tmp_path) -> None:
    backed = _person_with_old_mail(db_session, _NAME)
    other = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    _newer(db_session, MAX_PERSON_SCAN_ROWS)
    item = _ground_name(db_session, tmp_path)
    assert item.person_resolution.state == "ambiguous"
    assert [candidate.person_id for candidate in item.person_resolution.candidates] == [backed.id]
    assert other.id not in {candidate.person_id for candidate in item.person_resolution.candidates}


def test_identity_outside_newest_400_supersedes_mention_plan(db_session, tmp_path) -> None:
    mentioned = datetime.now(UTC) - timedelta(hours=1)
    _mention(db_session, body=_NAME, when=mentioned)
    _mention(db_session, body=_NAME, when=mentioned)
    plan, _key = _plan(db_session, tmp_path, [_row(_NAME, _ROLE)], [0])
    _mail(
        db_session,
        sender=f"{_NAME} <hg2a-later@example.com>",
        when=datetime.now(UTC) - timedelta(days=2),
    )
    _newer(db_session, MAX_PERSON_SCAN_ROWS - 2)
    before = _people(db_session)
    traces = _traces(db_session)
    view = ActionPlanService(db_session, BOOTSTRAP_USER_ID).approve(plan.id)
    assert view.status == "failed"
    assert "role_import_grounding_changed" in view.failure
    assert _people(db_session) == before
    assert _traces(db_session) == traces


def test_role_import_ceiling_reads_one_sentinel_and_fails_closed(db_session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.person_promotion_service.MAX_ROLE_IMPORT_COMMUNICATION_SCAN_ROWS",
        2,
    )
    monkeypatch.setattr(
        "app.services.person_role_import_mention_service.MAX_ROLE_IMPORT_COMMUNICATION_SCAN_ROWS",
        2,
    )
    limits: list[str] = []

    def _capture(_conn, _cursor, statement, parameters, _context, _executemany) -> None:
        folded = " ".join(statement.split())
        if "LIMIT" in folded.upper() and "objects" in folded.lower():
            limits.append(f"{folded[-180:]} :: {parameters!r}")

    old = datetime.now(UTC) - timedelta(days=2)
    _newer(db_session, 2)
    _mail(db_session, sender=f"{_NAME} <hg2a-beyond@example.com>", when=old)
    _mention(db_session, body=_NAME, when=old)
    _mention(db_session, body=_NAME, when=old)
    event.listen(db_session.bind, "before_cursor_execute", _capture)
    try:
        assert _NAME not in {
            item.display_value
            for item in PersonPromotionService(
                db_session, BOOTSTRAP_USER_ID
            ).eligible_role_import_participants()
        }
        assert _ground_items(db_session, tmp_path, _NAME) == []
        assert any(
            marker in item
            for item in limits
            for marker in (", 3)", ": 3,", ": 3}", "(3,)", "LIMIT 3")
        ), limits[:1]
    finally:
        event.remove(db_session.bind, "before_cursor_execute", _capture)


def _newer(db_session, count: int) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            Object(
                user_id=BOOTSTRAP_USER_ID,
                kind="email",
                provider="gmail",
                title="noise",
                origin="source",
                state="observed",
                occurred_at=now,
                metadata_={"sender": f"noise-{index}@example.com", "to": "me@example.com"},
            )
            for index in range(count)
        ]
    )
    db_session.flush()


def _person_with_old_mail(db_session, title: str):
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(title)
    address = f"hg2a-{person.id.hex[:8]}@example.com"
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).attach(
        person.id,
        normalize_email(f"{title} <{address}>"),
    )
    _mail(
        db_session,
        sender=f"{title} <{address}>",
        when=datetime.now(UTC) - timedelta(days=2),
    )
    return person


def _ground_name(db_session, tmp_path):
    items = _ground_items(db_session, tmp_path, _NAME)
    assert len(items) == 1
    return items[0]


def _ground_items(db_session, tmp_path, name: str):
    obj, revision = _image(db_session, tmp_path)
    return _ground(db_session, tmp_path, obj.id, revision, [_row(name, _ROLE)]).items


def _people(db_session) -> int:
    return int(
        db_session.scalar(
            select(func.count()).select_from(Object).where(Object.kind == "person")
        )
        or 0
    )


def _traces(db_session) -> int:
    return int(db_session.scalar(select(func.count()).select_from(AITrace)) or 0)
