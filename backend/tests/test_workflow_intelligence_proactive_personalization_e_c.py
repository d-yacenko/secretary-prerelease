"""Workflow Intelligence Pass E-C — Proactive personalization via E-B evidence."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.ai_audit.constants import EVENT_TRACE_STARTED
from app.api.schemas import ObjectCreate
from app.db.engine import engine
from app.db.models import (
    AITrace,
    AITraceEvent,
    Edge,
    GoogleAccount,
    Job,
    Notification,
    Object,
    User,
    UserIdentityProfile,
    UserSemanticContext,
    UserSettings,
)
from app.jobs.constants import JOB_STATUS_PENDING, JOB_TYPE_PROACTIVE_REVIEW
from app.personal_relevance.models import PERSONAL_RELEVANCE_EVIDENCE_VERSION
from app.proactive.constants import (
    PROACTIVE_PERSONAL_RELEVANCE_EVENT,
    PROACTIVE_READ_TOOL_NAMES,
    PROACTIVE_SEED_OBJECT_LIMIT,
    STALE_FENCE_STALE,
    STALE_FENCE_UNCHANGED,
)
from app.proactive.decision import ProactiveDecision
from app.proactive.instructions import PROACTIVE_SYSTEM_INSTRUCTIONS
from app.services.graph_service import GraphService
from app.services.label_service import LabelService
from app.services.personal_relevance_evidence_service import PersonalRelevanceEvidenceService
from app.services.personal_semantic_context_service import PersonalSemanticContextService
from app.services.proactive_review_service import (
    ProactiveReviewService,
    personal_relevance_evidence_is_stale,
    snapshot_covers_seed_ids,
)
from app.services.user_identity_context_service import UserIdentityProfileService
from app.services.user_serialization_gate import lock_user_serialization_row
from app.tools.registry import PROACTIVE_TOOL_DEFINITIONS
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_proactive_secretary_c import (
    ScriptedProactiveProvider,
    _count_jobs,
    _enable,
    _insight_answer,
    _install_provider,
    _none_answer,
    _noop_trace,
    _notifications,
    _proactive_payload,
    _source_email,
    _task_answer,
    _utcnow,
)
from tests.test_workflow_intelligence_personal_relevance_e_b import _identity

SECRET_BODY = "SECRET_BODY_TEXT_XYZ_DO_NOT_SEED"
SECRET_TOKEN = "SECRET_OAUTH_TOKEN_DO_NOT_SEED"
SECRET_SEMANTIC = "SECRET_SEMANTIC_CONTEXT_DO_NOT_AUDIT"


@pytest.fixture
def silent_trace(monkeypatch):
    monkeypatch.setattr(
        "app.services.proactive_review_service.ai_trace_session",
        _noop_trace,
    )


class _SessionProxy:
    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(self._session, name)


def _spy_snapshots(monkeypatch) -> list[list]:
    calls: list[list] = []
    original = PersonalRelevanceEvidenceService.build_snapshot

    def wrapped(self, user_id, object_ids):
        calls.append(list(object_ids))
        return original(self, user_id, object_ids)

    monkeypatch.setattr(PersonalRelevanceEvidenceService, "build_snapshot", wrapped)
    return calls


def _seed_json(provider: ScriptedProactiveProvider) -> dict:
    return json.loads(provider.last_ui_context)


def _labeled_source(session: Session) -> tuple[Object, Object]:
    source = _source_email(session, title="Labeled mail")
    labels = LabelService(session, BOOTSTRAP_USER_ID)
    created = labels.create_label("Context", description="Helps interpretation")
    labels.assign_label(source.id, created.label.id)
    return source, created.label


def test_alembic_head_includes_0034() -> None:
    versions = sorted(
        path.name
        for path in (Path(__file__).resolve().parents[1] / "alembic" / "versions").glob("*.py")
        if path.name[0].isdigit()
    )
    assert any(name.startswith("0034") for name in versions)


@pytest.mark.parametrize(
    ("relationship", "dependency"),
    [
        ("responsible", "waiting_on_user"),
        ("participant", "none"),
        ("observer", "none"),
        ("related", "unknown"),
        ("unknown", "unknown"),
    ],
)
def test_personal_relevance_enums_parse(relationship, dependency) -> None:
    payload = json.loads(_insight_answer(uuid.uuid4(), personal_relevance={
        "relationship": relationship,
        "dependency": dependency,
    }))
    parsed = ProactiveDecision.model_validate(payload)
    assert parsed.personal_relevance.relationship.value == relationship
    assert parsed.personal_relevance.dependency.value == dependency


def test_invalid_enums_and_notify_without_judgment_fail_closed() -> None:
    source_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        ProactiveDecision.model_validate(
            json.loads(_insight_answer(source_id, personal_relevance={
                "relationship": "owner",
                "dependency": "none",
            }))
        )
    with pytest.raises(ValidationError):
        ProactiveDecision.model_validate(
            json.loads(_insight_answer(source_id, personal_relevance={
                "relationship": "responsible",
                "dependency": "blocked",
            }))
        )
    raw = json.loads(_insight_answer(source_id))
    del raw["personal_relevance"]
    with pytest.raises(ValidationError):
        ProactiveDecision.model_validate(raw)
    with pytest.raises(ValidationError):
        ProactiveDecision.model_validate(
            json.loads(_insight_answer(source_id, extra={"chain_of_thought": "secret reasoning"}))
        )


def test_none_may_omit_personal_relevance() -> None:
    parsed = ProactiveDecision.model_validate({"decision": "none", "notification": None})
    assert parsed.personal_relevance is None


def test_snapshot_once_before_llm_for_seed_ids(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    calls = _spy_snapshots(monkeypatch)
    first = _source_email(db_session, title="One")
    second = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(kind="email", title="Two", origin="source", body=SECRET_BODY)
    )
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 1
    assert len(calls) == 1
    assert len(calls[0]) <= PROACTIVE_SEED_OBJECT_LIMIT
    assert {first.id, second.id} <= set(calls[0])
    payload = _seed_json(provider)
    assert list(payload.keys()).count("user_context") == 1
    assert payload["user_context_signature"]
    assert payload["evidence_version"] == PERSONAL_RELEVANCE_EVIDENCE_VERSION
    seed_ids = {item["id"] for item in payload["seed_objects"]}
    assert str(first.id) in seed_ids
    assert str(second.id) in seed_ids
    user_ctx = json.dumps(payload["user_context"])
    assert all("user_context" not in item for item in payload["seed_objects"])
    assert SECRET_BODY not in json.dumps(payload)
    assert all("body" not in item for item in payload["seed_objects"])
    for item in payload["seed_objects"]:
        assert "user_participation_roles" in item
        assert "participation_truncated" in item
        assert "assigned_labels" in item
        assert "labels_truncated" in item
        assert "object_evidence_signature" in item
        assert "object_id" in item
    assert user_ctx.count("truncated") >= 1


def test_seed_context_has_no_secrets_and_keeps_truncation(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    _identity(db_session, BOOTSTRAP_USER_ID)
    PersonalSemanticContextService.build(db_session).upsert_context(
        BOOTSTRAP_USER_ID, SECRET_SEMANTIC
    )
    db_session.add(
        GoogleAccount(
            user_id=BOOTSTRAP_USER_ID,
            email="google@example.com",
            scopes=["gmail"],
            access_token_encrypted=SECRET_TOKEN,
            refresh_token_encrypted="SECRET_REFRESH",
        )
    )
    source, _label = _labeled_source(db_session)
    for index in range(9):
        extra = LabelService(db_session, BOOTSTRAP_USER_ID).create_label(f"Extra {index}")
        LabelService(db_session, BOOTSTRAP_USER_ID).assign_label(source.id, extra.label.id)
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    payload = _seed_json(provider)
    dumped = json.dumps(payload)
    assert SECRET_TOKEN not in dumped
    assert "SECRET_REFRESH" not in dumped
    assert SECRET_SEMANTIC in dumped
    assert payload["user_context"]["truncated"] in (True, False)
    match = next(item for item in payload["seed_objects"] if item["id"] == str(source.id))
    assert match["labels_truncated"] is True
    assert "truncated" in payload["user_context"]


def test_source_must_be_initial_seed_related_may_be_tool_seen(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    seed = _source_email(db_session, title="Seed")
    unseen = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(kind="email", title="Old thread", origin="source")
    )
    unseen.updated_at = _utcnow() - timedelta(days=30)
    db_session.flush()
    provider = _install_provider(
        monkeypatch,
        ScriptedProactiveProvider(
            _insight_answer(unseen.id),
            tool_calls=[("get_object", {"object_id": str(unseen.id)})],
        ),
    )
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 1
    assert _notifications(db_session) == []

    _install_provider(
        monkeypatch,
        ScriptedProactiveProvider(
            _insight_answer(seed.id, related_id=unseen.id),
            tool_calls=[("get_object", {"object_id": str(unseen.id)})],
        ),
    )
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    notes = _notifications(db_session)
    assert len(notes) == 1
    assert notes[0].source_object_id == seed.id
    assert notes[0].related_object_id == unseen.id


def test_allowlist_unchanged_and_no_mutating_tools() -> None:
    assert PROACTIVE_READ_TOOL_NAMES == (
        "retrieve",
        "query_objects",
        "get_object",
        "get_context",
        "list_neighbors",
        "list_notifications",
    )
    names = [item["name"] for item in PROACTIVE_TOOL_DEFINITIONS]
    assert names == list(PROACTIVE_READ_TOOL_NAMES)
    for forbidden in (
        "create_task",
        "send_email",
        "assign_label",
        "create_label",
        "update_task",
        "create_calendar_event",
    ):
        assert forbidden not in names
    assert "personal_relevance" not in names
    assert "copied_recipient does NOT mean observer" in PROACTIVE_SYSTEM_INSTRUCTIONS or (
        "copied_recipient" in PROACTIVE_SYSTEM_INSTRUCTIONS
        and "not a deterministic" in PROACTIVE_SYSTEM_INSTRUCTIONS
    )


def test_malformed_json_fails_closed(db_session, monkeypatch, silent_trace) -> None:
    _enable(db_session)
    _source_email(db_session)
    _install_provider(monkeypatch, ScriptedProactiveProvider("{not-json"))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert _notifications(db_session) == []
    assert _count_jobs(db_session, status=JOB_STATUS_PENDING) == 1


def test_notify_without_personal_relevance_fails_closed(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    source = _source_email(db_session)
    raw = json.loads(_insight_answer(source.id))
    del raw["personal_relevance"]
    _install_provider(monkeypatch, ScriptedProactiveProvider(json.dumps(raw)))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert _notifications(db_session) == []


def test_task_source_cannot_emit_task_proposal(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    task = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="task",
            title="Already a task",
            origin="user",
            status="open",
            due_at=_utcnow() + timedelta(hours=12),
        )
    )
    _install_provider(monkeypatch, ScriptedProactiveProvider(_task_answer(task.id)))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(
        {"window_start": (_utcnow() - timedelta(minutes=5)).isoformat()}
    )
    assert _notifications(db_session) == []
    assert db_session.scalar(select(func.count()).select_from(Object).where(Object.kind == "task")) == 1


def _run_stale(db_session, monkeypatch, source: Object, after_tools) -> ScriptedProactiveProvider:
    provider = _install_provider(
        monkeypatch,
        ScriptedProactiveProvider(_insight_answer(source.id), after_tools=after_tools),
    )
    before = len(_notifications(db_session))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 1
    assert len(_notifications(db_session)) == before
    assert _count_jobs(db_session, status=JOB_STATUS_PENDING) >= 1
    return provider


def test_stale_semantic_context_discards_notification(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    source = _source_email(db_session)
    PersonalSemanticContextService.build(db_session).upsert_context(
        BOOTSTRAP_USER_ID, "before"
    )

    def mutate():
        PersonalSemanticContextService.build(db_session).upsert_context(
            BOOTSTRAP_USER_ID, "after change"
        )
        db_session.flush()

    calls = _spy_snapshots(monkeypatch)
    _run_stale(db_session, monkeypatch, source, mutate)
    assert len(calls) == 2


def test_stale_identity_discards_notification(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    _identity(db_session, BOOTSTRAP_USER_ID, email="alice@example.com")
    source = _source_email(db_session)

    def mutate():
        UserIdentityProfileService.build(db_session).upsert_profile(
            BOOTSTRAP_USER_ID,
            "Имя: Bob Changed\nEmail:\n- bob@example.com\n",
        )
        db_session.flush()

    _run_stale(db_session, monkeypatch, source, mutate)


def test_stale_connected_account_discards_notification(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    account = GoogleAccount(
        user_id=BOOTSTRAP_USER_ID,
        email="before@example.com",
        scopes=["gmail"],
    )
    db_session.add(account)
    db_session.flush()
    source = _source_email(db_session)

    def mutate():
        account.email = "after@example.com"
        db_session.flush()

    _run_stale(db_session, monkeypatch, source, mutate)


def test_stale_label_assignment_discards_notification(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    source, _label = _labeled_source(db_session)

    def mutate():
        extra = LabelService(db_session, BOOTSTRAP_USER_ID).create_label("New assignment")
        LabelService(db_session, BOOTSTRAP_USER_ID).assign_label(source.id, extra.label.id)
        db_session.flush()

    _run_stale(db_session, monkeypatch, source, mutate)


def test_stale_label_description_discards_notification(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    source, label = _labeled_source(db_session)

    def mutate():
        LabelService(db_session, BOOTSTRAP_USER_ID).update_label(
            label.id,
            description="Updated description",
            description_set=True,
        )
        db_session.flush()

    _run_stale(db_session, monkeypatch, source, mutate)


def test_stale_participation_or_freshness_discards_notification(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    _identity(db_session, BOOTSTRAP_USER_ID, email="alice@example.com")
    source = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="email",
            title="Direct",
            origin="source",
            provider="gmail",
            metadata={
                "sender": "boss@example.com",
                "recipients": ["alice@example.com"],
            },
        )
    )

    def mutate():
        source.metadata_ = {
            "sender": "boss@example.com",
            "recipients": ["other@example.com"],
        }
        flag_modified(source, "metadata_")
        source.updated_at = datetime.now(UTC)
        db_session.flush()

    _run_stale(db_session, monkeypatch, source, mutate)


def test_unchanged_evidence_creates_one_notification(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    source = _source_email(db_session)
    calls = _spy_snapshots(monkeypatch)
    provider = _install_provider(
        monkeypatch, ScriptedProactiveProvider(_insight_answer(source.id))
    )
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 1
    assert len(calls) == 2
    notes = _notifications(db_session)
    assert len(notes) == 1
    assert notes[0].source_object_id == source.id
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert len(_notifications(db_session)) == 1


def test_audit_metadata_is_bounded(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.ai_audit.context.SessionLocal",
        lambda: _SessionProxy(db_session),
    )
    _enable(db_session)
    PersonalSemanticContextService.build(db_session).upsert_context(
        BOOTSTRAP_USER_ID, SECRET_SEMANTIC
    )
    source = _source_email(db_session)
    _install_provider(monkeypatch, ScriptedProactiveProvider(_insight_answer(source.id)))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    events = list(
        db_session.scalars(
            select(AITraceEvent).where(
                AITraceEvent.event_type == PROACTIVE_PERSONAL_RELEVANCE_EVENT
            )
        )
    )
    assert events
    meta = events[-1].metadata_
    dumped = json.dumps(meta)
    assert SECRET_SEMANTIC not in dumped
    assert "chain_of_thought" not in dumped
    assert meta["evidence_version"] == PERSONAL_RELEVANCE_EVIDENCE_VERSION
    assert meta["seed_count"] >= 1
    assert meta["user_context_signature"]
    assert meta["source_object_evidence_signature"]
    assert meta["relationship"] == "responsible"
    assert meta["dependency"] == "waiting_on_user"
    assert meta["stale_fence"] == STALE_FENCE_UNCHANGED
    assert meta["decision"] == "notify"
    assert meta["notification_kind"] == "insight"
    assert "user_context_truncated" in meta
    assert EVENT_TRACE_STARTED


def test_stale_fence_audit_is_none(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.ai_audit.context.SessionLocal",
        lambda: _SessionProxy(db_session),
    )
    _enable(db_session)
    source = _source_email(db_session)
    PersonalSemanticContextService.build(db_session).upsert_context(
        BOOTSTRAP_USER_ID, "before"
    )

    def mutate():
        PersonalSemanticContextService.build(db_session).upsert_context(
            BOOTSTRAP_USER_ID, "after"
        )
        db_session.flush()

    _install_provider(
        monkeypatch,
        ScriptedProactiveProvider(_insight_answer(source.id), after_tools=mutate),
    )
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    events = list(
        db_session.scalars(
            select(AITraceEvent).where(
                AITraceEvent.event_type == PROACTIVE_PERSONAL_RELEVANCE_EVENT
            )
        )
    )
    assert events[-1].metadata_["stale_fence"] == STALE_FENCE_STALE
    assert events[-1].metadata_["decision"] == "none"
    assert _notifications(db_session) == []


def test_disabled_proactive_makes_zero_llm_and_snapshot_calls(
    db_session, monkeypatch, silent_trace
) -> None:
    calls = _spy_snapshots(monkeypatch)
    _source_email(db_session)
    provider = _install_provider(
        monkeypatch, ScriptedProactiveProvider(_insight_answer(uuid.uuid4()))
    )
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 0
    assert calls == []
    settings = db_session.get(UserSettings, BOOTSTRAP_USER_ID)
    assert settings is None or settings.proactive_enabled is False
    assert settings is None or settings.auto_label_enabled is False


def test_instructions_do_not_hardcode_taxonomy_parser() -> None:
    assert "Роль ·" not in PROACTIVE_SYSTEM_INSTRUCTIONS
    assert "Сфера ·" not in PROACTIVE_SYSTEM_INSTRUCTIONS
    assert "Проект ·" not in PROACTIVE_SYSTEM_INSTRUCTIONS
    backend = Path(__file__).resolve().parents[1] / "app"
    for path in (
        backend / "services/proactive_review_service.py",
        backend / "proactive/decision.py",
    ):
        text = path.read_text(encoding="utf-8")
        assert "PersonalRelevanceClassifier" not in text
        assert "assess_personal_relevance" not in text


def test_no_second_job_type() -> None:
    from app.jobs.constants import JOB_TYPE_AUTO_LABEL_OBJECT

    assert JOB_TYPE_PROACTIVE_REVIEW != JOB_TYPE_AUTO_LABEL_OBJECT


def test_incomplete_snapshot_skips_llm(db_session, monkeypatch, silent_trace) -> None:
    _enable(db_session)
    source = _source_email(db_session)
    original = PersonalRelevanceEvidenceService.build_snapshot

    def incomplete(self, user_id, object_ids):
        snap = original(self, user_id, object_ids)
        if not snap.objects:
            return snap
        dropped = snap.objects[0]
        objects = snap.objects[1:]
        signatures = {
            key: value
            for key, value in snap.object_evidence_signatures.items()
            if key != str(dropped.object_id)
        }
        return replace(snap, objects=objects, object_evidence_signatures=signatures)

    monkeypatch.setattr(PersonalRelevanceEvidenceService, "build_snapshot", incomplete)
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_insight_answer(source.id)))
    before_jobs = _count_jobs(db_session, status=JOB_STATUS_PENDING)
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 0
    assert _notifications(db_session) == []
    assert _count_jobs(db_session, status=JOB_STATUS_PENDING) == before_jobs + 1


def test_stale_equality_treats_added_or_removed_seed_as_stale(db_session) -> None:
    first = _source_email(db_session, title="A")
    second = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(kind="email", title="B", origin="source")
    )
    service = PersonalRelevanceEvidenceService.build(db_session)
    both = service.build_snapshot(BOOTSTRAP_USER_ID, [first.id, second.id])
    one = service.build_snapshot(BOOTSTRAP_USER_ID, [first.id])
    assert snapshot_covers_seed_ids(both, [first.id, second.id])
    assert not snapshot_covers_seed_ids(one, [first.id, second.id])
    assert personal_relevance_evidence_is_stale(both, one, [first.id, second.id])
    extra = dict(one.object_evidence_signatures)
    extra[str(second.id)] = "not-a-real-signature"
    mutated = replace(one, object_evidence_signatures=extra, truncated_objects=False)
    assert personal_relevance_evidence_is_stale(one, mutated, [first.id])


@contextmanager
def _isolated_proactive_user():
    user_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(User(id=user_id, display_name=f"proactive-e-c-r1-{user_id}"))
        session.add(
            UserSettings(
                user_id=user_id,
                proactive_enabled=True,
                proactive_interval_minutes=60,
            )
        )
        session.commit()
    try:
        yield user_id
    finally:
        with Session(engine) as session:
            session.execute(delete(Notification).where(Notification.user_id == user_id))
            session.execute(
                delete(AITraceEvent).where(
                    AITraceEvent.trace_id.in_(select(AITrace.id).where(AITrace.user_id == user_id))
                )
            )
            session.execute(delete(AITrace).where(AITrace.user_id == user_id))
            session.execute(delete(Job).where(Job.user_id == user_id))
            session.execute(delete(Edge).where(Edge.user_id == user_id))
            session.execute(delete(Object).where(Object.user_id == user_id))
            session.execute(delete(GoogleAccount).where(GoogleAccount.user_id == user_id))
            session.execute(delete(UserSemanticContext).where(UserSemanticContext.user_id == user_id))
            session.execute(delete(UserIdentityProfile).where(UserIdentityProfile.user_id == user_id))
            session.execute(delete(UserSettings).where(UserSettings.user_id == user_id))
            session.execute(delete(User).where(User.id == user_id))
            session.commit()


def _run_isolated_review(monkeypatch, user_id, source_id, **hooks) -> None:
    _install_provider(monkeypatch, ScriptedProactiveProvider(_insight_answer(source_id)))
    monkeypatch.setattr(
        "app.services.proactive_review_service.ai_trace_session",
        _noop_trace,
    )
    with Session(engine) as worker:
        ProactiveReviewService(worker, user_id, **hooks).run(_proactive_payload())
        worker.commit()


def test_separate_session_semantic_writer_before_authority_discards(monkeypatch) -> None:
    with _isolated_proactive_user() as user_id:
        with Session(engine) as session:
            source = _source_email(session, user_id)
            source_id = source.id
            PersonalSemanticContextService.build(session).upsert_context(user_id, "before")
            session.commit()

        def after_llm() -> None:
            with Session(engine) as other:
                PersonalSemanticContextService.build(other).upsert_context(user_id, "after")
                other.commit()

        _run_isolated_review(monkeypatch, user_id, source_id, after_llm=after_llm)
        with Session(engine) as session:
            assert list(session.scalars(select(Notification).where(Notification.user_id == user_id))) == []


def test_separate_session_label_writer_before_authority_discards(monkeypatch) -> None:
    with _isolated_proactive_user() as user_id:
        with Session(engine) as session:
            source = _source_email(session, user_id)
            source_id = source.id
            created = LabelService(session, user_id).create_label("Race")
            session.commit()
            label_id = created.label.id

        def after_llm() -> None:
            with Session(engine) as other:
                LabelService(other, user_id).assign_label(source_id, label_id)
                other.commit()

        _run_isolated_review(monkeypatch, user_id, source_id, after_llm=after_llm)
        with Session(engine) as session:
            assert list(session.scalars(select(Notification).where(Notification.user_id == user_id))) == []


def test_separate_session_object_freshness_writer_before_authority_discards(
    monkeypatch,
) -> None:
    with _isolated_proactive_user() as user_id:
        with Session(engine) as session:
            source = _source_email(session, user_id)
            source_id = source.id
            session.commit()

        def after_llm() -> None:
            with Session(engine) as other:
                obj = other.get(Object, source_id)
                assert obj is not None
                obj.title = "changed-after-model"
                obj.updated_at = datetime.now(UTC)
                other.commit()

        _run_isolated_review(monkeypatch, user_id, source_id, after_llm=after_llm)
        with Session(engine) as session:
            assert list(session.scalars(select(Notification).where(Notification.user_id == user_id))) == []


def test_separate_session_connected_account_writer_before_authority_discards(
    monkeypatch,
) -> None:
    with _isolated_proactive_user() as user_id:
        with Session(engine) as session:
            source = _source_email(session, user_id)
            source_id = source.id
            session.add(
                GoogleAccount(user_id=user_id, email="before@example.com", scopes=["gmail"])
            )
            session.commit()

        def after_llm() -> None:
            with Session(engine) as other:
                account = other.scalar(
                    select(GoogleAccount).where(GoogleAccount.user_id == user_id)
                )
                assert account is not None
                account.email = "after@example.com"
                other.commit()

        _run_isolated_review(monkeypatch, user_id, source_id, after_llm=after_llm)
        with Session(engine) as session:
            assert list(session.scalars(select(Notification).where(Notification.user_id == user_id))) == []


def test_authority_blocks_user_gate_until_notification_flush(monkeypatch) -> None:
    with _isolated_proactive_user() as user_id:
        with Session(engine) as session:
            source = _source_email(session, user_id)
            source_id = source.id
            session.commit()

        def after_authority() -> None:
            with Session(engine) as other:
                other.execute(text("SET LOCAL lock_timeout = '100ms'"))
                with pytest.raises(OperationalError):
                    lock_user_serialization_row(other, user_id)

        _run_isolated_review(
            monkeypatch, user_id, source_id, after_authority=after_authority
        )
        with Session(engine) as session:
            notes = list(session.scalars(select(Notification).where(Notification.user_id == user_id)))
            assert len(notes) == 1
            assert notes[0].source_object_id == source_id
