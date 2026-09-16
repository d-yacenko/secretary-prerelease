"""Explicit local re-intake authoritative refresh regressions."""

import uuid

import pytest
from sqlalchemy import func, select

from app.db.models import Job, Object, Representation
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT, JOB_TYPE_SUMMARIZE_RESOURCE
from app.local.constants import POLICY_METADATA_ONLY
from app.services.client_intake_constants import CLIENT_REPRESENTATION_KINDS
from app.services.folder_object_service import EXPLICIT_LOCAL_INTAKE_MODE
from app.services.object_deletion_service import ObjectDeletionService
from app.services.representation_generation import get_representation_generation
from app.users.bootstrap import BOOTSTRAP_USER_ID

from tests.test_phase_27c_local_explicit_intake import _intake_file

pytest_plugins = [
    "tests.test_phase_26b",
    "tests.test_phase_27c_local_explicit_intake",
]

OLD_EXPLICIT_MARKER = "OLD_EXPLICIT_MARKER"
NEW_EXPLICIT_MARKER = "NEW_EXPLICIT_MARKER"


def _register_explicit_client(client) -> None:
    client.post(
        "/local/devices/register",
        json={"device_key": "desk-26b", "display_name": "Test desktop"},
    )


def _mechanical_rep_texts(db_session, object_id: uuid.UUID) -> list[str]:
    reps = db_session.scalars(
        select(Representation).where(
            Representation.object_id == object_id,
            Representation.kind.in_(CLIENT_REPRESENTATION_KINDS),
        )
    ).all()
    return [rep.text or "" for rep in reps]


def _summarize_jobs_for_object(db_session, object_id: uuid.UUID) -> list[Job]:
    return [
        job
        for job in db_session.scalars(select(Job).where(Job.type == JOB_TYPE_SUMMARIZE_RESOURCE))
        if job.payload.get("object_id") == str(object_id)
    ]


def test_explicit_reintake_same_revision_replaces_representations(
    phase27c_local_client, db_session
) -> None:
    _register_explicit_client(phase27c_local_client)
    first = _intake_file(
        phase27c_local_client,
        intake_mode=EXPLICIT_LOCAL_INTAKE_MODE,
        representations=[{"kind": "full", "text": OLD_EXPLICIT_MARKER}],
    )
    object_id = uuid.UUID(first["object_id"])
    assert OLD_EXPLICIT_MARKER in _mechanical_rep_texts(db_session, object_id)
    before_generation = get_representation_generation(
        db_session.get(Object, object_id).metadata_
    )

    second = _intake_file(
        phase27c_local_client,
        intake_mode=EXPLICIT_LOCAL_INTAKE_MODE,
        representations=[{"kind": "full", "text": NEW_EXPLICIT_MARKER}],
    )

    assert second["object_id"] == first["object_id"]
    assert second["status"] == "updated"
    assert second["status"] != "unchanged"
    assert second["jobs_enqueued"] == 1
    texts = _mechanical_rep_texts(db_session, object_id)
    assert OLD_EXPLICIT_MARKER not in texts
    assert NEW_EXPLICIT_MARKER in texts
    assert len(_summarize_jobs_for_object(db_session, object_id)) >= 1
    after_generation = get_representation_generation(
        db_session.get(Object, object_id).metadata_
    )
    assert after_generation == before_generation + 1


def test_tombstoned_explicit_reintake_replaces_representations(
    phase27c_local_client, db_session
) -> None:
    _register_explicit_client(phase27c_local_client)
    first = _intake_file(
        phase27c_local_client,
        intake_mode=EXPLICIT_LOCAL_INTAKE_MODE,
        representations=[{"kind": "full", "text": OLD_EXPLICIT_MARKER}],
    )
    object_id = uuid.UUID(first["object_id"])
    ObjectDeletionService(db_session, BOOTSTRAP_USER_ID).delete_object(object_id)
    db_session.flush()
    tombstoned = db_session.get(Object, object_id)
    assert tombstoned is not None
    assert tombstoned.deleted_at is not None

    second = _intake_file(
        phase27c_local_client,
        intake_mode=EXPLICIT_LOCAL_INTAKE_MODE,
        representations=[{"kind": "full", "text": NEW_EXPLICIT_MARKER}],
    )

    assert second["object_id"] == first["object_id"]
    restored = db_session.get(Object, object_id)
    assert restored is not None
    assert restored.deleted_at is None
    texts = _mechanical_rep_texts(db_session, object_id)
    assert OLD_EXPLICIT_MARKER not in texts
    assert NEW_EXPLICIT_MARKER in texts
    assert second["jobs_enqueued"] == 1
    assert len(_summarize_jobs_for_object(db_session, object_id)) >= 1


def test_explicit_reintake_does_not_create_duplicate_object(
    phase27c_local_client, db_session
) -> None:
    _register_explicit_client(phase27c_local_client)
    first = _intake_file(phase27c_local_client, intake_mode=EXPLICIT_LOCAL_INTAKE_MODE)
    before_count = db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.provider == "local_device",
        )
    )
    second = _intake_file(phase27c_local_client, intake_mode=EXPLICIT_LOCAL_INTAKE_MODE)
    after_count = db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.provider == "local_device",
        )
    )

    assert second["object_id"] == first["object_id"]
    assert before_count == after_count


def test_passive_reintake_same_revision_stays_unchanged(
    phase26b_client, db_session
) -> None:
    from tests.test_phase_26b import _intake_payload, _register_device

    _register_device(phase26b_client)
    first = phase26b_client.post("/local/files/client-intake", json=_intake_payload())
    assert first.status_code == 201
    object_id = uuid.UUID(first.json()["object_id"])
    before_texts = _mechanical_rep_texts(db_session, object_id)
    before_jobs = len(_summarize_jobs_for_object(db_session, object_id))
    before_generation = get_representation_generation(
        db_session.get(Object, object_id).metadata_
    )

    second = phase26b_client.post("/local/files/client-intake", json=_intake_payload())
    assert second.status_code == 201
    body = second.json()
    assert body["status"] == "unchanged"
    assert body["jobs_enqueued"] == 0
    assert _mechanical_rep_texts(db_session, object_id) == before_texts
    assert len(_summarize_jobs_for_object(db_session, object_id)) == before_jobs
    assert get_representation_generation(db_session.get(Object, object_id).metadata_) == before_generation


def test_explicit_metadata_only_refresh_clears_stale_representations(
    phase27c_local_client, db_session
) -> None:
    _register_explicit_client(phase27c_local_client)
    indexed = _intake_file(
        phase27c_local_client,
        intake_mode=EXPLICIT_LOCAL_INTAKE_MODE,
        representations=[{"kind": "full", "text": "indexed searchable body"}],
    )
    object_id = uuid.UUID(indexed["object_id"])
    assert _mechanical_rep_texts(db_session, object_id)

    refreshed = _intake_file(
        phase27c_local_client,
        intake_mode=EXPLICIT_LOCAL_INTAKE_MODE,
        representations=[],
        metadata_only=True,
    )

    assert refreshed["object_id"] == indexed["object_id"]
    assert refreshed["status"] == "updated"
    assert refreshed["jobs_enqueued"] == 1
    obj = db_session.get(Object, object_id)
    assert obj is not None
    assert obj.metadata_["indexing_policy"] == POLICY_METADATA_ONLY
    assert obj.embedding is None
    assert "semantic_summary" not in (obj.metadata_ or {})
    assert _mechanical_rep_texts(db_session, object_id) == []
    embed_jobs = list(
        db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT))
    )
    assert any(job.payload.get("object_id") == str(object_id) for job in embed_jobs)
