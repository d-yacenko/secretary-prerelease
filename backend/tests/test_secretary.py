from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.api.schemas import ContextBuildResult, ContextItem, EdgeCreate, ObjectCreate, ObjectUpdate
from app.llm.fake_secretary_provider import FakeSecretaryProvider
from app.llm.secretary_provider import SecretaryAnalysisError
from app.services.graph_service import GraphService
from app.services.provenance import AGENT_ORIGIN, PROPOSED_STATE
from app.services.secretary_service import SecretaryService
from app.users.bootstrap import BOOTSTRAP_USER_ID

FIXED_REFERENCE = datetime(2026, 8, 28, 10, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
EMAIL_TEXT = (
    "Let's meet tomorrow at 13:30. Please send the updated forecast before the meeting."
)


def _email_context() -> ContextBuildResult:
    email_id = UUID("00000000-0000-4000-8000-000000000001")
    return ContextBuildResult(
        items=[
            ContextItem(
                object_id=email_id,
                kind="email",
                title="Inbound email",
                content=EMAIL_TEXT,
                origin="source",
                state="observed",
                why_included="target object",
            )
        ],
        total_chars=len(EMAIL_TEXT),
        truncated=False,
    )


def test_secretary_fixture_identifies_meeting_and_task() -> None:
    service = SecretaryService(FakeSecretaryProvider())
    result = service.analyze(
        trigger="analyze inbound email",
        context=_email_context(),
        reference_datetime=FIXED_REFERENCE,
        timezone="Europe/Amsterdam",
    )

    assert result.success
    assert result.analysis is not None
    assert result.analysis.summary
    proposal_types = {proposal.type for proposal in result.analysis.proposals}
    assert "meeting" in proposal_types
    assert "task" in proposal_types

    meeting = next(p for p in result.analysis.proposals if p.type == "meeting")
    task = next(p for p in result.analysis.proposals if p.type == "task")

    assert meeting.start_at is not None
    assert meeting.start_at.hour == 13
    assert meeting.start_at.minute == 30
    assert meeting.start_at.day == 29
    assert meeting.confidence == 0.84
    assert meeting.evidence_item_indices == [0]

    assert task.due_at is not None
    assert task.confidence == 0.79
    assert task.evidence_item_indices == [0]
    assert task.due_at <= meeting.start_at


def test_secretary_rejects_negative_evidence_index() -> None:
    from app.llm.secretary_models import SecretaryAnalysis, SecretaryProposal

    analysis = SecretaryAnalysis(
        proposals=[
            SecretaryProposal(
                type="task",
                title="Bad evidence",
                confidence=0.5,
                evidence_item_indices=[-1],
            )
        ]
    )
    service = SecretaryService(_InvalidEvidenceProvider(analysis))
    result = service.analyze(
        trigger="x",
        context=_email_context(),
        reference_datetime=FIXED_REFERENCE,
    )
    assert not result.success
    assert "evidence" in (result.error or "").lower()


def test_secretary_rejects_out_of_range_evidence_index() -> None:
    from app.llm.secretary_models import SecretaryAnalysis, SecretaryProposal

    analysis = SecretaryAnalysis(
        proposals=[
            SecretaryProposal(
                type="task",
                title="Bad evidence",
                confidence=0.5,
                evidence_item_indices=[99],
            )
        ]
    )
    service = SecretaryService(_InvalidEvidenceProvider(analysis))
    result = service.analyze(trigger="x", context=_email_context(), reference_datetime=FIXED_REFERENCE)
    assert not result.success


def test_secretary_deduplicates_evidence_indices() -> None:
    from app.llm.secretary_models import SecretaryAnalysis, SecretaryProposal

    analysis = SecretaryAnalysis(
        proposals=[
            SecretaryProposal(
                type="note",
                title="Dup evidence",
                confidence=0.6,
                evidence_item_indices=[0, 0, 0],
            )
        ]
    )
    service = SecretaryService(_InvalidEvidenceProvider(analysis))
    result = service.analyze(trigger="x", context=_email_context(), reference_datetime=FIXED_REFERENCE)
    assert result.success
    assert result.analysis.proposals[0].evidence_item_indices == [0]


def test_create_secretary_provider_without_api_key_fails() -> None:
    from app.core.config import settings
    from app.llm.secretary_provider import SecretaryConfigurationError
    from app.services.secretary_service import create_secretary_provider

    original = settings.openai_api_key
    settings.openai_api_key = ""
    try:
        with pytest.raises(SecretaryConfigurationError):
            create_secretary_provider()
    finally:
        settings.openai_api_key = original


class _InvalidEvidenceProvider:
    def __init__(self, analysis):
        self._analysis = analysis

    def analyze(self, trigger, context, reference_datetime, timezone, instructions):
        return self._analysis


def test_secretary_failure_returns_controlled_result() -> None:
    class FailingProvider:
        def analyze(self, trigger, context, reference_datetime, timezone, instructions):
            raise SecretaryAnalysisError("provider unavailable")

    result = SecretaryService(FailingProvider()).analyze(
        trigger="x",
        context=_email_context(),
        reference_datetime=FIXED_REFERENCE,
    )
    assert not result.success
    assert result.analysis is None
    assert result.error == "provider unavailable"


def test_invalid_origin_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        ObjectCreate(kind="task", title="Bad", origin="test")


def test_invalid_state_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        ObjectCreate(kind="task", title="Bad", origin="user", state="active")


def test_confidence_outside_range_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        ObjectCreate(
            kind="event",
            title="Bad confidence",
            origin=AGENT_ORIGIN,
            confidence=1.2,
        )


def test_edge_state_transition_to_confirmed(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = graph.create_object(ObjectCreate(kind="task", title="Source", origin="user"))
    target = graph.create_object(
        ObjectCreate(
            kind="event",
            title="Meeting",
            origin=AGENT_ORIGIN,
            confidence=0.82,
        )
    )
    edge = graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type="related_to",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.82,
        )
    )

    updated = graph.set_edge_state(edge.id, "confirmed")
    assert updated.state == "confirmed"
    assert updated.origin == AGENT_ORIGIN
    assert updated.confidence == 0.82
    assert updated.source_id == source.id
    assert updated.target_id == target.id
    assert updated.type == "related_to"


def test_edge_state_transition_to_rejected(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = graph.create_object(ObjectCreate(kind="task", title="Source", origin="user"))
    target = graph.create_object(
        ObjectCreate(
            kind="event",
            title="Meeting",
            origin=AGENT_ORIGIN,
            confidence=0.55,
        )
    )
    edge = graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type="related_to",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.55,
        )
    )

    updated = graph.set_edge_state(edge.id, "rejected")
    assert updated.state == "rejected"
    assert updated.origin == AGENT_ORIGIN
    assert updated.confidence == 0.55


def test_patch_null_state_returns_validation_error(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    graph.create_object(ObjectCreate(kind="task", title="Task", origin="user"))
    with pytest.raises(PydanticValidationError):
        ObjectUpdate(state=None)


def test_origin_immutable_on_update(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    event = graph.create_object(
        ObjectCreate(
            kind="event",
            title="Meeting",
            origin=AGENT_ORIGIN,
            confidence=0.82,
        )
    )
    updated = graph.update_object(event.id, ObjectUpdate(state="confirmed"))
    assert updated.origin == AGENT_ORIGIN
    assert updated.state == "confirmed"
    assert updated.confidence == 0.82
