"""Universal Intake A final concurrency: final authority lock + revalidation generation."""

import uuid
from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.content_extraction.bounded_download import DownloadTooLargeError
from app.content_extraction.extract_service import ExplicitResourceContentExtractor
from app.content_extraction.extraction_baseline import (
    WEB_REVALIDATION_GENERATION_METADATA_KEY,
    derive_web_extraction_baseline,
)
from app.content_extraction.mechanical_extractors import extract_from_path as real_extract
from app.content_extraction.metadata_keys import (
    CONTENT_EXTRACTION_STATUS,
    MECHANICAL_REPRESENTATION_KINDS,
)
from app.db.engine import engine
from app.db.models import Job, Object, Representation
from app.jobs.constants import JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT
from app.resources.web_fetch import WebFetchResult
from app.services.correlation_constants import SEMANTIC_SUMMARY_REVISION_KEY
from app.services.retrieval_service import RetrievalService
from app.services.semantic_summary_service import SemanticSummaryService
from app.services.web_explicit_link_intake_service import WebExplicitLinkIntakeService
from app.users.bootstrap import BOOTSTRAP_USER_ID


def _txt_fetch(url: str, body: bytes, *, etag: str | None = None) -> WebFetchResult:
    return WebFetchResult(
        final_url=url,
        text="",
        title="race.txt",
        content_type="text/plain",
        content_hash=None,
        content_length=len(body),
        etag=etag,
        last_modified=None,
        is_direct_file=True,
        is_binary=True,
        detected_suffix=".txt",
        file_too_large=False,
    )


def _mechanical_rep_count(session: Session, object_id) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Representation)
            .where(
                Representation.object_id == object_id,
                Representation.kind.in_(MECHANICAL_REPRESENTATION_KINDS),
            )
        )
        or 0
    )


def _extract_jobs(session: Session, object_id):
    return session.scalars(
        select(Job).where(
            Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
            Job.payload["object_id"].as_string() == str(object_id),
        )
    ).all()


def _intake_e2_in_session_b(url: str, phase: dict) -> None:
    phase["supersede"] = True
    session_b = Session(engine)
    try:
        WebExplicitLinkIntakeService(session=session_b, user_id=BOOTSTRAP_USER_ID).intake_link(url)
        session_b.commit()
    finally:
        session_b.close()


def _extract_then_supersede(url: str, phase: dict, object_id, path):
    reps, meta = real_extract(object_id, path)
    if not phase.get("interleaved"):
        phase["interleaved"] = True
        _intake_e2_in_session_b(url, phase)
    return reps, meta


def test_no_validator_baseline_changes_with_generation() -> None:
    url = f"https://example.test/generation-baseline-{uuid.uuid4().hex}.txt"
    body = b"generation baseline\n"

    def intake_fetch(_requested_url: str) -> WebFetchResult:
        return _txt_fetch(url, body)

    with (
        patch(
            "app.services.web_explicit_link_intake_service.fetch_web_page",
            side_effect=intake_fetch,
        ),
        patch(
            "app.content_extraction.web_file_content.download_public_web_file",
            return_value=body,
        ),
    ):
        session = Session(engine)
        service = WebExplicitLinkIntakeService(session=session, user_id=BOOTSTRAP_USER_ID)
        first = service.intake_link(url)
        obj = session.get(Object, first.object_id)
        baseline_1 = derive_web_extraction_baseline(obj.metadata_)
        assert obj.metadata_.get(WEB_REVALIDATION_GENERATION_METADATA_KEY) == 1
        job = _extract_jobs(session, first.object_id)[0]
        session.commit()

        extractor = ExplicitResourceContentExtractor(session=session, user_id=BOOTSTRAP_USER_ID)
        extractor.run(
            first.object_id,
            expected_revision=job.payload.get("expected_content_revision"),
            extraction_version=job.payload.get("extraction_version"),
            expected_baseline=job.payload.get("extraction_baseline"),
        )
        session.commit()

        second = service.intake_link(url)
        obj = session.get(Object, first.object_id)
        baseline_2 = derive_web_extraction_baseline(obj.metadata_)
        assert second.content_jobs_enqueued == 1
        assert obj.metadata_.get(WEB_REVALIDATION_GENERATION_METADATA_KEY) == 2
        assert baseline_2 != baseline_1
        assert len(_extract_jobs(session, first.object_id)) == 2
        session.commit()
        session.close()


def test_mid_worker_etag_supersession_blocks_stale_persist() -> None:
    marker_a = f"etagA_{uuid.uuid4().hex}"
    marker_b = f"etagB_{uuid.uuid4().hex}"
    body_a = f"{marker_a}\n".encode()
    body_b = f"{marker_b}\n".encode()
    url = f"https://example.test/race-{uuid.uuid4().hex}.txt"
    phase = {"supersede": False, "j2": False, "interleaved": False}

    def intake_fetch(_requested_url: str) -> WebFetchResult:
        if phase["supersede"]:
            return _txt_fetch(url, body_b, etag='"e2"')
        return _txt_fetch(url, body_a, etag='"e1"')

    def worker_download(_requested_url: str, **_kwargs) -> bytes:
        return body_b if phase["j2"] else body_a

    def extract_then_supersede(object_id, path):
        return _extract_then_supersede(url, phase, object_id, path)

    with (
        patch(
            "app.services.web_explicit_link_intake_service.fetch_web_page",
            side_effect=intake_fetch,
        ),
        patch(
            "app.content_extraction.web_file_content.download_public_web_file",
            side_effect=worker_download,
        ),
        patch(
            "app.content_extraction.extract_service.extract_from_path",
            extract_then_supersede,
        ),
    ):
        session = Session(engine)
        service = WebExplicitLinkIntakeService(session=session, user_id=BOOTSTRAP_USER_ID)
        first = service.intake_link(url)
        session.commit()
        object_id = first.object_id
        job_e1 = next(
            job
            for job in _extract_jobs(session, object_id)
            if job.payload.get("expected_content_revision") == 'web:etag:"e1"'
        )

        extractor = ExplicitResourceContentExtractor(session=session, user_id=BOOTSTRAP_USER_ID)
        extractor.run(
            object_id,
            expected_revision=job_e1.payload.get("expected_content_revision"),
            extraction_version=job_e1.payload.get("extraction_version"),
            expected_baseline=job_e1.payload.get("extraction_baseline"),
        )
        session.commit()

        refreshed = session.get(Object, object_id)
        assert refreshed.metadata_["content_revision"] == 'web:etag:"e2"'
        assert refreshed.metadata_[CONTENT_EXTRACTION_STATUS] == "pending"
        assert _mechanical_rep_count(session, object_id) == 0
        job_e2 = next(
            job
            for job in _extract_jobs(session, object_id)
            if job.payload.get("expected_content_revision") == 'web:etag:"e2"'
        )

        phase["j2"] = True
        extractor.run(
            object_id,
            expected_revision=job_e2.payload.get("expected_content_revision"),
            extraction_version=job_e2.payload.get("extraction_version"),
            expected_baseline=job_e2.payload.get("extraction_baseline"),
        )
        session.commit()

        final = session.get(Object, object_id)
        assert final.metadata_["content_revision"] == 'web:etag:"e2"'
        assert final.metadata_[CONTENT_EXTRACTION_STATUS] == "ready"
        assert _mechanical_rep_count(session, object_id) > 0
        hits_b = RetrievalService(session, BOOTSTRAP_USER_ID).retrieve(
            marker_b, limit=5, time_scope="all"
        )
        hits_a = RetrievalService(session, BOOTSTRAP_USER_ID).retrieve(
            marker_a, limit=5, time_scope="all"
        )
        assert object_id in [hit.object_id for hit in hits_b.hits]
        assert object_id not in [hit.object_id for hit in hits_a.hits]
        session.close()


def test_mid_worker_no_validator_revalidation_generation_supersedes() -> None:
    marker_a = f"novalA_{uuid.uuid4().hex}"
    marker_b = f"novalB_{uuid.uuid4().hex}"
    body_a = f"{marker_a}\nline two\n".encode()
    body_b = f"{marker_b}\nline two\n".encode()
    assert len(body_a) == len(body_b)
    url = f"https://example.test/race-{uuid.uuid4().hex}.txt"
    phase = {"supersede": False, "j2": False, "interleaved": False}

    def intake_fetch(_requested_url: str) -> WebFetchResult:
        current = body_b if phase["supersede"] else body_a
        return _txt_fetch(url, current)

    def worker_download(_requested_url: str, **_kwargs) -> bytes:
        return body_b if phase["j2"] else body_a

    def extract_then_supersede(object_id, path):
        return _extract_then_supersede(url, phase, object_id, path)

    with (
        patch(
            "app.services.web_explicit_link_intake_service.fetch_web_page",
            side_effect=intake_fetch,
        ),
        patch(
            "app.content_extraction.web_file_content.download_public_web_file",
            side_effect=worker_download,
        ),
        patch(
            "app.content_extraction.extract_service.extract_from_path",
            extract_then_supersede,
        ),
    ):
        session = Session(engine)
        service = WebExplicitLinkIntakeService(session=session, user_id=BOOTSTRAP_USER_ID)
        first = service.intake_link(url)
        session.commit()
        object_id = first.object_id
        obj = session.get(Object, object_id)
        assert obj.metadata_.get(WEB_REVALIDATION_GENERATION_METADATA_KEY) == 1
        job_j1 = _extract_jobs(session, object_id)[0]
        baseline_j1 = job_j1.payload.get("extraction_baseline")

        extractor = ExplicitResourceContentExtractor(session=session, user_id=BOOTSTRAP_USER_ID)
        extractor.run(
            object_id,
            expected_revision=job_j1.payload.get("expected_content_revision"),
            extraction_version=job_j1.payload.get("extraction_version"),
            expected_baseline=baseline_j1,
        )
        session.commit()

        refreshed = session.get(Object, object_id)
        assert refreshed.metadata_.get(WEB_REVALIDATION_GENERATION_METADATA_KEY) == 2
        jobs = _extract_jobs(session, object_id)
        assert len(jobs) == 2
        job_j2 = max(jobs, key=lambda job: job.created_at)
        assert job_j2.payload.get("extraction_baseline") != baseline_j1
        assert refreshed.metadata_[CONTENT_EXTRACTION_STATUS] == "pending"
        assert _mechanical_rep_count(session, object_id) == 0

        phase["j2"] = True
        extractor.run(
            object_id,
            expected_revision=job_j2.payload.get("expected_content_revision"),
            extraction_version=job_j2.payload.get("extraction_version"),
            expected_baseline=job_j2.payload.get("extraction_baseline"),
        )
        SemanticSummaryService(session, BOOTSTRAP_USER_ID).update_summary_for_object(object_id)
        session.commit()

        final = session.get(Object, object_id)
        assert final.metadata_[CONTENT_EXTRACTION_STATUS] == "ready"
        assert final.metadata_[SEMANTIC_SUMMARY_REVISION_KEY] == final.metadata_["content_revision"]
        hits_b = RetrievalService(session, BOOTSTRAP_USER_ID).retrieve(
            marker_b, limit=5, time_scope="all"
        )
        hits_a = RetrievalService(session, BOOTSTRAP_USER_ID).retrieve(
            marker_a, limit=5, time_scope="all"
        )
        assert object_id in [hit.object_id for hit in hits_b.hits]
        assert object_id not in [hit.object_id for hit in hits_a.hits]
        session.close()


def test_mid_worker_superseded_parser_failure_is_noop() -> None:
    body = b"parser failure race\n"
    url = f"https://example.test/race-{uuid.uuid4().hex}.txt"
    phase = {"supersede": False, "interleaved": False}

    def intake_fetch(_requested_url: str) -> WebFetchResult:
        if phase["supersede"]:
            return _txt_fetch(url, body, etag='"e2"')
        return _txt_fetch(url, body, etag='"e1"')

    def extract_then_supersede_and_fail(object_id, path):
        if not phase.get("interleaved"):
            phase["interleaved"] = True
            _intake_e2_in_session_b(url, phase)
        raise ValueError("simulated parser failure")

    with (
        patch(
            "app.services.web_explicit_link_intake_service.fetch_web_page",
            side_effect=intake_fetch,
        ),
        patch(
            "app.content_extraction.web_file_content.download_public_web_file",
            return_value=body,
        ),
        patch(
            "app.content_extraction.extract_service.extract_from_path",
            extract_then_supersede_and_fail,
        ),
    ):
        session = Session(engine)
        service = WebExplicitLinkIntakeService(session=session, user_id=BOOTSTRAP_USER_ID)
        first = service.intake_link(url)
        session.commit()
        object_id = first.object_id
        job_e1 = next(
            job
            for job in _extract_jobs(session, object_id)
            if job.payload.get("expected_content_revision") == 'web:etag:"e1"'
        )

        extractor = ExplicitResourceContentExtractor(session=session, user_id=BOOTSTRAP_USER_ID)
        extractor.run(
            object_id,
            expected_revision=job_e1.payload.get("expected_content_revision"),
            extraction_version=job_e1.payload.get("extraction_version"),
            expected_baseline=job_e1.payload.get("extraction_baseline"),
        )
        session.commit()

        refreshed = session.get(Object, object_id)
        assert refreshed.metadata_["content_revision"] == 'web:etag:"e2"'
        assert refreshed.metadata_[CONTENT_EXTRACTION_STATUS] == "pending"
        assert refreshed.metadata_.get("content_extraction_error") is None
        session.close()


def test_mid_worker_superseded_too_large_is_noop() -> None:
    body = b"too large race\n"
    url = f"https://example.test/race-{uuid.uuid4().hex}.txt"
    phase = {"supersede": False, "interleaved": False}

    def intake_fetch(_requested_url: str) -> WebFetchResult:
        if phase["supersede"]:
            return _txt_fetch(url, body, etag='"e2"')
        return _txt_fetch(url, body, etag='"e1"')

    def download_then_supersede_and_raise(_requested_url: str, **_kwargs) -> bytes:
        if not phase.get("interleaved"):
            phase["interleaved"] = True
            _intake_e2_in_session_b(url, phase)
        raise DownloadTooLargeError(1, 2)

    with (
        patch(
            "app.services.web_explicit_link_intake_service.fetch_web_page",
            side_effect=intake_fetch,
        ),
        patch(
            "app.content_extraction.web_file_content.download_public_web_file",
            side_effect=download_then_supersede_and_raise,
        ),
    ):
        session = Session(engine)
        service = WebExplicitLinkIntakeService(session=session, user_id=BOOTSTRAP_USER_ID)
        first = service.intake_link(url)
        session.commit()
        object_id = first.object_id
        job_e1 = next(
            job
            for job in _extract_jobs(session, object_id)
            if job.payload.get("expected_content_revision") == 'web:etag:"e1"'
        )

        extractor = ExplicitResourceContentExtractor(session=session, user_id=BOOTSTRAP_USER_ID)
        extractor.run(
            object_id,
            expected_revision=job_e1.payload.get("expected_content_revision"),
            extraction_version=job_e1.payload.get("extraction_version"),
            expected_baseline=job_e1.payload.get("extraction_baseline"),
        )
        session.commit()

        refreshed = session.get(Object, object_id)
        assert refreshed.metadata_["content_revision"] == 'web:etag:"e2"'
        assert refreshed.metadata_[CONTENT_EXTRACTION_STATUS] == "pending"
        assert refreshed.metadata_.get("content_extraction_error") is None
        session.close()
