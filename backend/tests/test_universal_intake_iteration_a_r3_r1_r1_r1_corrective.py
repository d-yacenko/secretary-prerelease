"""Universal Intake Iteration A-R3-R1-R1-R1: extraction baseline + race-safe failures."""

import socket
import uuid
from unittest.mock import patch

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.content_extraction.bounded_download import DownloadTooLargeError
from app.content_extraction.constants import EXTRACTION_VERSION
from app.content_extraction.extract_service import ExplicitResourceContentExtractor
from app.content_extraction.extraction_baseline import WEB_REVALIDATION_GENERATION_METADATA_KEY
from app.content_extraction.mechanical_extractors import extract_from_path as real_extract
from app.content_extraction.metadata_keys import (
    CONTENT_EXTRACTION_STATUS,
    MECHANICAL_REPRESENTATION_KINDS,
)
from app.db.engine import engine
from app.db.models import Job, Object, Representation
from app.jobs.constants import JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT
from app.resources.constants import MAX_WEB_FETCH_BYTES
from app.resources.web_fetch import WebFetchResult
from app.services.web_explicit_link_intake_service import WebExplicitLinkIntakeService
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_universal_intake_iteration_a_r3_r1_corrective import (
    _REAL_HTTPX_CLIENT,
    ARXIV_STYLE_URL,
    _large_pdf_bytes,
)


def _patch_addr(mock_resolve) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]


def _pdf_handler(body: bytes, **headers):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(len(body)),
                **headers,
            },
        )

    return handler


def _txt_handler(body: bytes, **headers):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "text/plain",
                "Content-Length": str(len(body)),
                **headers,
            },
        )

    return handler


def _mechanical_rep_count(db_session, object_id) -> int:
    return int(
        db_session.scalar(
            select(func.count())
            .select_from(Representation)
            .where(
                Representation.object_id == object_id,
                Representation.kind.in_(MECHANICAL_REPRESENTATION_KINDS),
            )
        )
        or 0
    )


def _latest_extract_job(db_session, object_id):
    return db_session.scalars(
        select(Job)
        .where(
            Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
            Job.payload["object_id"].as_string() == str(object_id),
        )
        .order_by(Job.created_at.desc())
    ).first()


def test_no_validator_concurrent_reintake_converges() -> None:
    marker = f"concurrent_{uuid.uuid4().hex}"
    body = f"{marker}\nline two\n".encode()
    url = f"https://example.test/concurrent-no-val-{uuid.uuid4().hex}.txt"
    phase = {"supersede": False, "interleaved": False}

    def intake_fetch(_requested_url: str) -> WebFetchResult:
        return WebFetchResult(
            final_url=url,
            text="",
            title="t",
            content_type="text/plain",
            content_hash=None,
            content_length=len(body),
            etag=None,
            last_modified=None,
            is_direct_file=True,
            is_binary=True,
            detected_suffix=".txt",
            file_too_large=False,
        )

    def extract_then_supersede(object_id, path):
        reps, meta = real_extract(object_id, path)
        if not phase.get("interleaved"):
            phase["interleaved"] = True
            phase["supersede"] = True
            session_b = Session(engine)
            try:
                WebExplicitLinkIntakeService(
                    session=session_b, user_id=BOOTSTRAP_USER_ID
                ).intake_link(url)
                session_b.commit()
            finally:
                session_b.close()
        return reps, meta

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
            extract_then_supersede,
        ),
    ):
        session = Session(engine)
        service = WebExplicitLinkIntakeService(session=session, user_id=BOOTSTRAP_USER_ID)
        first = service.intake_link(url)
        session.commit()

        obj = session.get(Object, first.object_id)
        job = _latest_extract_job(session, obj.id)
        assert obj.metadata_.get(WEB_REVALIDATION_GENERATION_METADATA_KEY) == 1

        extractor = ExplicitResourceContentExtractor(session=session, user_id=BOOTSTRAP_USER_ID)
        extractor.run(
            obj.id,
            expected_revision=job.payload.get("expected_content_revision"),
            extraction_version=job.payload.get("extraction_version"),
            expected_baseline=job.payload.get("extraction_baseline"),
        )
        session.commit()

        refreshed = session.get(Object, first.object_id)
        assert refreshed.metadata_.get(WEB_REVALIDATION_GENERATION_METADATA_KEY) == 2
        jobs = session.scalars(
            select(Job).where(
                Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
                Job.payload["object_id"].as_string() == str(first.object_id),
            )
        ).all()
        assert len(jobs) == 2
        job_j2 = max(jobs, key=lambda job: job.created_at)
        assert job_j2.payload.get("extraction_baseline") != job.payload.get("extraction_baseline")
        assert refreshed.metadata_[CONTENT_EXTRACTION_STATUS] == "pending"
        assert _mechanical_rep_count(session, first.object_id) == 0

        extractor.run(
            obj.id,
            expected_revision=job_j2.payload.get("expected_content_revision"),
            extraction_version=job_j2.payload.get("extraction_version"),
            expected_baseline=job_j2.payload.get("extraction_baseline"),
        )
        session.commit()
        session.close()

    verify = Session(engine)
    final = verify.get(Object, first.object_id)
    assert final.metadata_[CONTENT_EXTRACTION_STATUS] == "ready"
    assert _mechanical_rep_count(verify, first.object_id) > 0
    verify.close()


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_same_etag_concurrent_reintake_does_not_abort_worker(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    body = _large_pdf_bytes("same_etag_concurrent", MAX_WEB_FETCH_BYTES + 32 * 1024)
    transport = httpx.MockTransport(_pdf_handler(body, ETag='"same-etag-concurrent"'))
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        first = service.intake_link(ARXIV_STYLE_URL)
        db_session.commit()

        obj = db_session.get(Object, first.object_id)
        real_download = ExplicitResourceContentExtractor._download_bytes
        job = _latest_extract_job(db_session, obj.id)

        def racing_download(self, obj_arg, metadata, plan):
            WebExplicitLinkIntakeService(
                session=self._session, user_id=self._user_id
            ).intake_link(ARXIV_STYLE_URL)
            self._session.flush()
            return real_download(self, obj_arg, metadata, plan)

        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        with patch.object(ExplicitResourceContentExtractor, "_download_bytes", racing_download):
            extractor.run(
                obj.id,
                expected_revision=job.payload.get("expected_content_revision"),
                extraction_version=job.payload.get("extraction_version"),
                expected_baseline=job.payload.get("extraction_baseline"),
            )
        db_session.commit()

    refreshed = db_session.get(Object, first.object_id)
    assert refreshed.metadata_[CONTENT_EXTRACTION_STATUS] == "ready"
    assert refreshed.metadata_["content_revision"] == 'web:etag:"same-etag-concurrent"'
    assert _mechanical_rep_count(db_session, first.object_id) > 0


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_etag_supersession_e1_to_e2_authoritative_successor(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    marker = f"supersede_{uuid.uuid4().hex}"
    body = _large_pdf_bytes(marker, MAX_WEB_FETCH_BYTES + 32 * 1024)
    call = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call["n"] += 1
        etag = '"etag-e1"' if call["n"] == 1 else '"etag-e2"'
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(len(body)),
                "ETag": etag,
            },
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        first = service.intake_link(ARXIV_STYLE_URL)
        db_session.commit()

        second = service.intake_link(ARXIV_STYLE_URL)
        db_session.commit()

        obj = db_session.get(Object, first.object_id)
        job_e1 = db_session.scalars(
            select(Job)
            .where(
                Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
                Job.payload["object_id"].as_string() == str(first.object_id),
                Job.payload["expected_content_revision"].as_string() == 'web:etag:"etag-e1"',
            )
        ).first()
        job_e2 = db_session.scalars(
            select(Job)
            .where(
                Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
                Job.payload["object_id"].as_string() == str(first.object_id),
                Job.payload["expected_content_revision"].as_string() == 'web:etag:"etag-e2"',
            )
        ).first()

        assert second.content_jobs_enqueued == 1
        assert job_e1 is not None
        assert job_e2 is not None
        assert job_e2.payload.get("extraction_baseline") != job_e1.payload.get(
            "extraction_baseline"
        )

        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        extractor.run(
            obj.id,
            expected_revision=job_e1.payload.get("expected_content_revision"),
            extraction_version=job_e1.payload.get("extraction_version"),
            expected_baseline=job_e1.payload.get("extraction_baseline"),
        )
        db_session.commit()

        refreshed = db_session.get(Object, obj.id)
        assert refreshed.metadata_["content_revision"] == 'web:etag:"etag-e2"'
        assert refreshed.metadata_[CONTENT_EXTRACTION_STATUS] == "pending"
        assert _mechanical_rep_count(db_session, obj.id) == 0

        extractor.run(
            obj.id,
            expected_revision=job_e2.payload.get("expected_content_revision"),
            extraction_version=job_e2.payload.get("extraction_version"),
            expected_baseline=job_e2.payload.get("extraction_baseline"),
        )
        db_session.commit()

    final = db_session.get(Object, first.object_id)
    assert final.metadata_["content_revision"] == 'web:etag:"etag-e2"'
    assert final.metadata_[CONTENT_EXTRACTION_STATUS] == "ready"
    assert _mechanical_rep_count(db_session, first.object_id) > 0


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_superseded_worker_failure_does_not_overwrite(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    marker = f"fail_supersede_{uuid.uuid4().hex}"
    body = _large_pdf_bytes(marker, MAX_WEB_FETCH_BYTES + 32 * 1024)
    url = f"https://example.test/fail-supersede-{uuid.uuid4().hex}.pdf"
    call = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call["n"] += 1
        etag = '"fail-e1"' if call["n"] == 1 else '"fail-e2"'
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(len(body)),
                "ETag": etag,
            },
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        first = service.intake_link(url)
        db_session.commit()

        service.intake_link(url)
        db_session.commit()

        obj = db_session.get(Object, first.object_id)
        job_e1 = db_session.scalars(
            select(Job)
            .where(
                Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
                Job.payload["object_id"].as_string() == str(first.object_id),
                Job.payload["expected_content_revision"].as_string() == 'web:etag:"fail-e1"',
            )
        ).first()

        def failing_download(self, obj_arg, metadata, plan):
            raise ValueError("simulated parser failure")

        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        with patch.object(ExplicitResourceContentExtractor, "_download_bytes", failing_download):
            extractor.run(
                obj.id,
                expected_revision=job_e1.payload.get("expected_content_revision"),
                extraction_version=job_e1.payload.get("extraction_version"),
                expected_baseline=job_e1.payload.get("extraction_baseline"),
            )
        db_session.commit()

    refreshed = db_session.get(Object, first.object_id)
    assert refreshed.metadata_["content_revision"] == 'web:etag:"fail-e2"'
    assert refreshed.metadata_[CONTENT_EXTRACTION_STATUS] == "pending"
    assert refreshed.metadata_.get("content_extraction_error") is None


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_superseded_worker_too_large_does_not_overwrite(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    marker = f"large_supersede_{uuid.uuid4().hex}"
    body = _large_pdf_bytes(marker, MAX_WEB_FETCH_BYTES + 32 * 1024)
    url = f"https://example.test/large-supersede-{uuid.uuid4().hex}.pdf"
    call = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call["n"] += 1
        etag = '"large-e1"' if call["n"] == 1 else '"large-e2"'
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(len(body)),
                "ETag": etag,
            },
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        first = service.intake_link(url)
        db_session.commit()

        service.intake_link(url)
        db_session.commit()

        obj = db_session.get(Object, first.object_id)
        job_e1 = db_session.scalars(
            select(Job)
            .where(
                Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
                Job.payload["object_id"].as_string() == str(first.object_id),
                Job.payload["expected_content_revision"].as_string() == 'web:etag:"large-e1"',
            )
        ).first()

        def too_large_download(self, obj_arg, metadata, plan):
            raise DownloadTooLargeError(1, 2)

        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        with patch.object(ExplicitResourceContentExtractor, "_download_bytes", too_large_download):
            extractor.run(
                obj.id,
                expected_revision=job_e1.payload.get("expected_content_revision"),
                extraction_version=job_e1.payload.get("extraction_version"),
                expected_baseline=job_e1.payload.get("extraction_baseline"),
            )
        db_session.commit()

    refreshed = db_session.get(Object, first.object_id)
    assert refreshed.metadata_["content_revision"] == 'web:etag:"large-e2"'
    assert refreshed.metadata_[CONTENT_EXTRACTION_STATUS] == "pending"
    assert refreshed.metadata_.get("content_extraction_error") is None


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_summary_only_is_not_mechanical_repairs(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    body = _large_pdf_bytes("summary_only", MAX_WEB_FETCH_BYTES + 32 * 1024)
    transport = httpx.MockTransport(_pdf_handler(body, ETag='"summary-only-etag"'))
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        first = service.intake_link(ARXIV_STYLE_URL)
        db_session.commit()
        obj = db_session.get(Object, first.object_id)
        meta = dict(obj.metadata_ or {})
        meta[CONTENT_EXTRACTION_STATUS] = "ready"
        meta["content_extraction_version"] = EXTRACTION_VERSION
        meta["content_revision"] = 'web:etag:"summary-only-etag"'
        meta["mechanical_representation_count"] = 1
        obj.metadata_ = meta
        db_session.add(
            Representation(
                object_id=obj.id,
                kind="summary",
                part_index=0,
                text="summary only",
                metadata_={},
            )
        )
        db_session.commit()

        second = service.intake_link(ARXIV_STYLE_URL)
        db_session.commit()

    assert second.content_jobs_enqueued == 1
    assert second.content_status == "pending"
    assert _mechanical_rep_count(db_session, first.object_id) == 0
