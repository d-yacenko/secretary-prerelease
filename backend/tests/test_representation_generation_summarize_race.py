"""Representation generation summarize race regressions."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from app.db.models import Job, Object, Representation
from app.jobs.constants import JOB_STATUS_PENDING, JOB_TYPE_SUMMARIZE_RESOURCE
from app.llm.summarizer import FakeSummarizer
from app.services.client_intake_constants import CLIENT_REPRESENTATION_KINDS
from app.services.correlation_constants import SEMANTIC_SUMMARY_METADATA_KEY
from app.services.folder_object_service import EXPLICIT_LOCAL_INTAKE_MODE
from app.services.representation_generation import (
    REPRESENTATION_GENERATION_KEY,
    bump_representation_generation,
    get_representation_generation,
)
from app.services.representation_service import KIND_SUMMARY
from app.services.semantic_summary_service import SemanticSummaryService
from app.users.bootstrap import BOOTSTRAP_USER_ID

from tests.test_phase_27c_local_explicit_intake import _intake_file

pytest_plugins = [
    "tests.test_phase_26b",
    "tests.test_phase_27c_local_explicit_intake",
]

OLD_MARKER = "OLD_GENERATION_MARKER"
NEW_MARKER = "NEW_GENERATION_MARKER"


def _register_explicit_client(client) -> None:
    client.post(
        "/local/devices/register",
        json={"device_key": "desk-26b", "display_name": "Test desktop"},
    )


def _summarize_jobs_for_object(db_session, object_id: uuid.UUID) -> list[Job]:
    return [
        job
        for job in db_session.scalars(select(Job).where(Job.type == JOB_TYPE_SUMMARIZE_RESOURCE))
        if job.payload.get("object_id") == str(object_id)
    ]


def _pending_summarize_jobs(db_session, object_id: uuid.UUID) -> list[Job]:
    return [
        job
        for job in _summarize_jobs_for_object(db_session, object_id)
        if job.status in {JOB_STATUS_PENDING, "running"}
    ]


def _mechanical_texts(db_session, object_id: uuid.UUID) -> list[str]:
    reps = db_session.scalars(
        select(Representation).where(
            Representation.object_id == object_id,
            Representation.kind.in_(CLIENT_REPRESENTATION_KINDS),
        )
    ).all()
    return [rep.text or "" for rep in reps]


class _StaleBumpSummarizer:
    def __init__(self, session, object_id: uuid.UUID, replacement_text: str) -> None:
        self._session = session
        self._object_id = object_id
        self._replacement_text = replacement_text

    def summarize(self, text: str) -> str:
        obj = self._session.get(Object, self._object_id)
        assert obj is not None
        obj.metadata_ = bump_representation_generation(dict(obj.metadata_ or {}))
        self._session.execute(
            delete(Representation).where(Representation.object_id == self._object_id)
        )
        self._session.add(
            Representation(
                object_id=self._object_id,
                kind="full",
                text=self._replacement_text,
                metadata_={},
            )
        )
        self._session.flush()
        return f"stale-summary-from-{text[:32]}"


def test_pending_old_summarize_does_not_suppress_same_revision_refresh(
    phase27c_local_client, db_session
) -> None:
    _register_explicit_client(phase27c_local_client)
    first = _intake_file(
        phase27c_local_client,
        intake_mode=EXPLICIT_LOCAL_INTAKE_MODE,
        representations=[{"kind": "full", "text": OLD_MARKER}],
    )
    object_id = uuid.UUID(first["object_id"])
    obj = db_session.get(Object, object_id)
    assert obj is not None
    assert get_representation_generation(obj.metadata_) == 1
    pending_g1 = _pending_summarize_jobs(db_session, object_id)
    assert len(pending_g1) == 1
    assert pending_g1[0].payload["expected_representation_generation"] == 1

    second = _intake_file(
        phase27c_local_client,
        intake_mode=EXPLICIT_LOCAL_INTAKE_MODE,
        representations=[{"kind": "full", "text": NEW_MARKER}],
    )
    db_session.expire_all()
    obj = db_session.get(Object, object_id)
    assert obj is not None
    assert second["jobs_enqueued"] == 1
    assert get_representation_generation(obj.metadata_) == 2
    jobs = _summarize_jobs_for_object(db_session, object_id)
    generations = {job.payload["expected_representation_generation"] for job in jobs}
    assert generations == {1, 2}
    assert NEW_MARKER in _mechanical_texts(db_session, object_id)


def test_stale_g1_worker_cannot_persist_after_g2_refresh(db_session) -> None:
    object_id = uuid.uuid4()
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        title="race.txt",
        origin="source",
        state="observed",
        provider="local_device",
        external_id=f"race-{object_id}",
        metadata_={
            "content_revision": "rev-race",
            REPRESENTATION_GENERATION_KEY: 1,
        },
    )
    db_session.add(obj)
    db_session.flush()
    db_session.add(
        Representation(
            object_id=obj.id,
            kind="full",
            text=OLD_MARKER * 200,
            metadata_={},
        )
    )
    db_session.flush()

    summary = SemanticSummaryService(
        db_session,
        BOOTSTRAP_USER_ID,
        summarizer=_StaleBumpSummarizer(db_session, obj.id, NEW_MARKER),
    ).update_summary_for_object(
        obj.id,
        expected_revision="rev-race",
        expected_representation_generation=1,
    )
    db_session.flush()
    db_session.refresh(obj)

    assert summary is None
    assert SEMANTIC_SUMMARY_METADATA_KEY not in (obj.metadata_ or {})
    summary_reps = db_session.scalars(
        select(Representation).where(
            Representation.object_id == obj.id,
            Representation.kind == KIND_SUMMARY,
        )
    ).all()
    assert summary_reps == []
    assert get_representation_generation(obj.metadata_) == 2
    assert NEW_MARKER in _mechanical_texts(db_session, obj.id)


def test_g2_summarizes_current_representations(phase27c_local_client, db_session) -> None:
    _register_explicit_client(phase27c_local_client)
    first = _intake_file(
        phase27c_local_client,
        intake_mode=EXPLICIT_LOCAL_INTAKE_MODE,
        representations=[{"kind": "full", "text": OLD_MARKER}],
    )
    object_id = uuid.UUID(first["object_id"])
    _intake_file(
        phase27c_local_client,
        intake_mode=EXPLICIT_LOCAL_INTAKE_MODE,
        representations=[{"kind": "full", "text": NEW_MARKER}],
    )
    db_session.expire_all()
    obj = db_session.get(Object, object_id)
    assert obj is not None
    generation = get_representation_generation(obj.metadata_)
    summary = SemanticSummaryService(
        db_session,
        BOOTSTRAP_USER_ID,
        summarizer=FakeSummarizer(max_chars=4000),
    ).update_summary_for_object(
        object_id,
        expected_revision=obj.metadata_["content_revision"],
        expected_representation_generation=generation,
    )
    assert summary is not None
    assert NEW_MARKER in summary
    assert OLD_MARKER not in summary


def test_passive_unchanged_does_not_bump_generation_or_enqueue_summarize(
    phase26b_client, db_session
) -> None:
    from tests.test_phase_26b import _intake_payload, _register_device

    _register_device(phase26b_client)
    first = phase26b_client.post("/local/files/client-intake", json=_intake_payload())
    assert first.status_code == 201
    object_id = uuid.UUID(first.json()["object_id"])
    obj = db_session.get(Object, object_id)
    assert obj is not None
    before_generation = get_representation_generation(obj.metadata_)
    before_jobs = len(_summarize_jobs_for_object(db_session, object_id))

    second = phase26b_client.post("/local/files/client-intake", json=_intake_payload())
    assert second.status_code == 201
    body = second.json()
    assert body["status"] == "unchanged"
    assert body["jobs_enqueued"] == 0
    db_session.refresh(obj)
    assert get_representation_generation(obj.metadata_) == before_generation
    assert len(_summarize_jobs_for_object(db_session, object_id)) == before_jobs


def test_changed_revision_bumps_generation_and_summarize_job_matches(
    phase26b_client, db_session
) -> None:
    from tests.test_phase_26b import _intake_payload, _register_device

    _register_device(phase26b_client)
    payload = _intake_payload()
    first = phase26b_client.post("/local/files/client-intake", json=payload)
    assert first.status_code == 201
    object_id = uuid.UUID(first.json()["object_id"])
    obj = db_session.get(Object, object_id)
    assert obj is not None
    before_generation = get_representation_generation(obj.metadata_)

    payload = _intake_payload(
        modified_at="2026-09-06T12:00:00Z",
        representations=[{"kind": "full", "text": "updated passive body"}],
    )
    second = phase26b_client.post("/local/files/client-intake", json=payload)
    assert second.status_code == 201
    body = second.json()
    assert body["status"] == "updated"
    assert body["jobs_enqueued"] == 1
    db_session.refresh(obj)
    after_generation = get_representation_generation(obj.metadata_)
    assert after_generation == before_generation + 1
    matching_jobs = [
        job
        for job in _summarize_jobs_for_object(db_session, object_id)
        if job.payload.get("expected_representation_generation") == after_generation
    ]
    assert len(matching_jobs) == 1
    latest_job = matching_jobs[0]
    assert latest_job.payload["expected_representation_generation"] == after_generation
    assert latest_job.payload["expected_revision"] == obj.metadata_["content_revision"]

    summary = SemanticSummaryService(
        db_session,
        BOOTSTRAP_USER_ID,
        summarizer=FakeSummarizer(max_chars=4000),
    ).update_summary_for_object(
        object_id,
        expected_revision=obj.metadata_["content_revision"],
        expected_representation_generation=after_generation,
    )
    assert summary is not None


def test_update_summary_for_missing_object_raises_not_found(db_session) -> None:
    import pytest

    from app.services.errors import NotFoundError

    missing_id = uuid.uuid4()
    with pytest.raises(NotFoundError) as exc_info:
        SemanticSummaryService(db_session, BOOTSTRAP_USER_ID).update_summary_for_object(
            missing_id
        )
    assert exc_info.value.resource == "object"
    assert exc_info.value.entity_id == missing_id
