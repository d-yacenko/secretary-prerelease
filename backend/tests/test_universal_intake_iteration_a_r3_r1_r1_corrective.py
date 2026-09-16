"""Universal Intake Iteration A-R3-R1-R1: revision completeness + current-content safety."""

import hashlib
import socket
import uuid
from unittest.mock import patch

import httpx
from sqlalchemy import func, select

from app.content_extraction.constants import EXTRACTION_VERSION
from app.content_extraction.extract_service import ExplicitResourceContentExtractor
from app.content_extraction.extraction_baseline import (
    WEB_REVALIDATION_GENERATION_METADATA_KEY,
    derive_web_extraction_baseline,
)
from app.content_extraction.metadata_keys import CONTENT_EXTRACTION_STATUS
from app.db.models import Job, Object, Representation
from app.jobs.constants import JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT
from app.resources.constants import MAX_WEB_FETCH_BYTES
from app.resources.web_fetch import fetch_web_page
from app.services.correlation_constants import (
    SEMANTIC_SUMMARY_METADATA_KEY,
    SEMANTIC_SUMMARY_REVISION_KEY,
)
from app.services.retrieval_service import RetrievalService
from app.services.semantic_summary_service import SemanticSummaryService
from app.services.web_explicit_link_intake_service import WebExplicitLinkIntakeService
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_universal_intake_iteration_a_r3_r1_corrective import (
    _REAL_HTTPX_CLIENT,
    ARXIV_STYLE_URL,
    _large_pdf_bytes,
)

STALE_VERSION = "phase29a-v1"


def _patch_addr(mock_resolve) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]


def _latest_extract_job(db_session, object_id):
    return db_session.scalars(
        select(Job)
        .where(
            Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
            Job.payload["object_id"].as_string() == str(object_id),
        )
        .order_by(Job.created_at.desc())
    ).first()


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


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_ready_same_etag_current_version_unchanged(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    body = _large_pdf_bytes("ready_current", MAX_WEB_FETCH_BYTES + 64 * 1024)
    transport = httpx.MockTransport(
        _pdf_handler(body, ETag='"stable-ready-etag"')
    )
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        first = service.intake_link(ARXIV_STYLE_URL)
        db_session.commit()
        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        obj = db_session.get(Object, first.object_id)
        extractor.run(
            obj.id,
            expected_revision=obj.metadata_.get("content_revision"),
            extraction_version=EXTRACTION_VERSION,
        )
        db_session.commit()
        jobs_before = db_session.scalars(
            select(Job).where(
                Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
                Job.payload["object_id"].as_string() == str(first.object_id),
            )
        ).all()
        second = service.intake_link(ARXIV_STYLE_URL)

    refreshed = db_session.get(Object, first.object_id)
    assert second.status == "unchanged"
    assert refreshed.metadata_[CONTENT_EXTRACTION_STATUS] == "ready"
    assert second.content_jobs_enqueued == 0
    assert len(jobs_before) == len(
        db_session.scalars(
            select(Job).where(
                Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
                Job.payload["object_id"].as_string() == str(first.object_id),
            )
        ).all()
    )


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_ready_same_etag_stale_extraction_version_reindexes(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    marker = f"stale_version_{uuid.uuid4().hex}"
    body = f"{marker}\nline two\n".encode()
    url = "https://example.test/stale-version.txt"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "text/plain",
                "Content-Length": str(len(body)),
                "ETag": '"stale-version-etag"',
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
        obj = db_session.get(Object, first.object_id)
        meta = dict(obj.metadata_ or {})
        meta[CONTENT_EXTRACTION_STATUS] = "ready"
        meta["content_extraction_version"] = STALE_VERSION
        meta["content_revision"] = 'web:etag:"stale-version-etag"'
        meta["etag"] = '"stale-version-etag"'
        meta["mechanical_representation_count"] = 1
        obj.metadata_ = meta
        db_session.add(
            Representation(
                object_id=obj.id,
                kind="chunk",
                part_index=0,
                text="stale version body",
                metadata_={},
            )
        )
        db_session.commit()

        second = service.intake_link(url)
        db_session.commit()

        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        obj = db_session.get(Object, first.object_id)
        extractor.run(
            first.object_id,
            expected_revision=obj.metadata_.get("content_revision"),
            extraction_version=EXTRACTION_VERSION,
        )
        db_session.commit()

    assert second.status == "updated"
    assert second.content_status == "pending"
    assert second.content_jobs_enqueued == 1
    jobs = db_session.scalars(
        select(Job).where(
            Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
            Job.payload["object_id"].as_string() == str(first.object_id),
        )
    ).all()
    assert len(jobs) == 1

    refreshed = db_session.get(Object, first.object_id)
    assert refreshed.metadata_[CONTENT_EXTRACTION_STATUS] == "ready"
    assert refreshed.metadata_["content_extraction_version"] == EXTRACTION_VERSION


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_ready_same_etag_missing_mechanical_reps_repairs(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    body = _large_pdf_bytes("missing_reps", MAX_WEB_FETCH_BYTES + 64 * 1024)
    transport = httpx.MockTransport(
        _pdf_handler(body, ETag='"missing-reps-etag"')
    )
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
        meta["content_revision"] = 'web:etag:"missing-reps-etag"'
        meta["mechanical_representation_count"] = 3
        obj.metadata_ = meta
        db_session.commit()

        second = service.intake_link(ARXIV_STYLE_URL)
        db_session.commit()

    assert second.content_jobs_enqueued == 1
    assert second.content_status == "pending"
    rep_count = db_session.scalar(
        select(func.count()).select_from(Representation).where(
            Representation.object_id == first.object_id
        )
    )
    assert rep_count == 0


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_no_validator_first_extraction_gets_sha256_revision(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    marker = f"sha_rev_{uuid.uuid4().hex}"
    body = f"{marker}\nline two\n".encode()
    url = "https://example.test/no-validator-sha.txt"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "text/plain", "Content-Length": str(len(body))},
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        result = service.intake_link(url)
        db_session.commit()
        obj = db_session.get(Object, result.object_id)
        assert obj.metadata_.get("content_revision") is None
        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        extractor.run(obj.id, expected_revision=None, extraction_version=EXTRACTION_VERSION)
        db_session.commit()

    refreshed = db_session.get(Object, result.object_id)
    expected = f"web:sha256:{hashlib.sha256(body).hexdigest()}"
    assert refreshed.metadata_["content_revision"] == expected
    assert refreshed.metadata_["content_hash"] == hashlib.sha256(body).hexdigest()


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_no_validator_summary_revision_is_current(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    marker = f"summary_{uuid.uuid4().hex}"
    body = f"{marker}\nline two\n".encode()
    url = "https://example.test/no-validator-summary.txt"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "text/plain", "Content-Length": str(len(body))},
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        result = service.intake_link(url)
        db_session.commit()
        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        obj = db_session.get(Object, result.object_id)
        extractor.run(obj.id, expected_revision=None, extraction_version=EXTRACTION_VERSION)
        db_session.commit()
        obj = db_session.get(Object, result.object_id)
        SemanticSummaryService(db_session, BOOTSTRAP_USER_ID).update_summary_for_object(obj.id)
        db_session.commit()

    refreshed = db_session.get(Object, result.object_id)
    revision = refreshed.metadata_["content_revision"]
    assert refreshed.metadata_[SEMANTIC_SUMMARY_REVISION_KEY] == revision
    assert refreshed.metadata_.get(SEMANTIC_SUMMARY_METADATA_KEY)


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_no_validator_reintake_hides_stale_content_before_worker(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    marker_a = f"hideA_{uuid.uuid4().hex}"
    marker_b = f"hideB_{uuid.uuid4().hex}"
    body_a = f"{marker_a}\nline two\n".encode()
    body_b = f"{marker_b}\nline two\n".encode()
    url = "https://example.test/hide-before-worker.txt"
    call = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call["n"] += 1
        body = body_a if call["n"] == 1 else body_b
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "text/plain", "Content-Length": str(len(body))},
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
        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        obj = db_session.get(Object, first.object_id)
        extractor.run(obj.id, expected_revision=None, extraction_version=EXTRACTION_VERSION)
        db_session.commit()
        SemanticSummaryService(db_session, BOOTSTRAP_USER_ID).update_summary_for_object(obj.id)
        db_session.commit()
        obj = db_session.get(Object, first.object_id)
        obj.embedding = [0.1, 0.2, 0.3]
        db_session.commit()

        second = service.intake_link(url)
        db_session.commit()

    refreshed = db_session.get(Object, first.object_id)
    assert second.content_status == "pending"
    assert refreshed.metadata_.get(SEMANTIC_SUMMARY_METADATA_KEY) is None
    assert refreshed.embedding is None
    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(marker_a, limit=5, time_scope="all")
    assert first.object_id not in [h.object_id for h in hits.hits]


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_no_validator_reintake_replaces_content_a_to_b(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    marker_a = f"replaceA_{uuid.uuid4().hex}"
    marker_b = f"replaceB_{uuid.uuid4().hex}"
    body_a = f"{marker_a}\nline two\n".encode()
    body_b = f"{marker_b}\nline two\n".encode()
    url = "https://example.test/replace-ab.txt"
    call = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call["n"] += 1
        body = body_a if call["n"] <= 2 else body_b
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "text/plain", "Content-Length": str(len(body))},
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
        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        obj = db_session.get(Object, first.object_id)
        extractor.run(obj.id, expected_revision=None, extraction_version=EXTRACTION_VERSION)
        db_session.commit()
        SemanticSummaryService(db_session, BOOTSTRAP_USER_ID).update_summary_for_object(obj.id)
        db_session.commit()

        second = service.intake_link(url)
        db_session.commit()
        obj = db_session.get(Object, second.object_id)
        extractor.run(obj.id, expected_revision=None, extraction_version=EXTRACTION_VERSION)
        db_session.commit()
        SemanticSummaryService(db_session, BOOTSTRAP_USER_ID).update_summary_for_object(obj.id)
        db_session.commit()

    assert second.object_id == first.object_id
    refreshed = db_session.get(Object, first.object_id)
    assert refreshed.metadata_[SEMANTIC_SUMMARY_REVISION_KEY] == refreshed.metadata_["content_revision"]
    hits_b = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(marker_b, limit=5, time_scope="all")
    assert first.object_id in [h.object_id for h in hits_b.hits]
    hits_a = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(marker_a, limit=5, time_scope="all")
    assert first.object_id not in [h.object_id for h in hits_a.hits]


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_no_validator_queue_dedupe(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    body = b"dedupe marker\n"
    url = f"https://example.test/dedupe-{uuid.uuid4().hex}.txt"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "text/plain", "Content-Length": str(len(body))},
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
        obj = db_session.get(Object, first.object_id)
        baseline_1 = derive_web_extraction_baseline(obj.metadata_)
        job_1 = db_session.scalars(
            select(Job).where(
                Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
                Job.payload["object_id"].as_string() == str(first.object_id),
            )
        ).first()
        second = service.intake_link(url)
        db_session.commit()

    jobs = db_session.scalars(
        select(Job).where(
            Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
            Job.payload["object_id"].as_string() == str(first.object_id),
        )
    ).all()
    refreshed = db_session.get(Object, first.object_id)
    assert second.object_id == first.object_id
    assert refreshed.metadata_.get(WEB_REVALIDATION_GENERATION_METADATA_KEY) == 2
    assert len(jobs) == 2
    assert jobs[0].payload.get("extraction_baseline") != jobs[1].payload.get("extraction_baseline")
    assert job_1 is not None
    assert baseline_1 != derive_web_extraction_baseline(refreshed.metadata_)


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_worker_survives_fetched_at_only_probe_during_download(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    marker = f"race_fetch_{uuid.uuid4().hex}"
    body = _large_pdf_bytes(marker, MAX_WEB_FETCH_BYTES + 32 * 1024)
    transport = httpx.MockTransport(_pdf_handler(body, ETag='"race-start"'))
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        result = service.intake_link(ARXIV_STYLE_URL)
        db_session.commit()

        obj = db_session.get(Object, result.object_id)
        real_download = ExplicitResourceContentExtractor._download_bytes
        job = _latest_extract_job(db_session, obj.id)
        start_revision = job.payload.get("expected_content_revision")
        start_baseline = job.payload.get("extraction_baseline")

        def racing_download(self, obj_arg, metadata, plan):
            raw = real_download(self, obj_arg, metadata, plan)
            fresh = self._session.get(Object, obj_arg.id)
            meta = dict(fresh.metadata_ or {})
            meta["fetched_at"] = "2026-09-04T10:00:00+00:00"
            fresh.metadata_ = meta
            self._session.flush()
            return raw

        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        with patch.object(ExplicitResourceContentExtractor, "_download_bytes", racing_download):
            extractor.run(
                obj.id,
                expected_revision=start_revision,
                extraction_version=EXTRACTION_VERSION,
                expected_baseline=start_baseline,
            )
        db_session.commit()

    refreshed = db_session.get(Object, obj.id)
    assert refreshed.metadata_[CONTENT_EXTRACTION_STATUS] == "ready"
    rep_count = db_session.scalar(
        select(func.count()).select_from(Representation).where(
            Representation.object_id == obj.id
        )
    )
    assert rep_count > 0


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_worker_race_guard_aborts_stale_result(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    marker = f"race_{uuid.uuid4().hex}"
    body = _large_pdf_bytes(marker, MAX_WEB_FETCH_BYTES + 32 * 1024)
    transport = httpx.MockTransport(_pdf_handler(body, ETag='"race-start"'))
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        result = service.intake_link(ARXIV_STYLE_URL)
        db_session.commit()

        obj = db_session.get(Object, result.object_id)
        real_download = ExplicitResourceContentExtractor._download_bytes
        job = _latest_extract_job(db_session, obj.id)
        start_revision = job.payload.get("expected_content_revision")
        start_baseline = job.payload.get("extraction_baseline")

        def racing_download(self, obj_arg, metadata, plan):
            raw = real_download(self, obj_arg, metadata, plan)
            fresh = self._session.get(Object, obj_arg.id)
            meta = dict(fresh.metadata_ or {})
            meta["etag"] = '"race-new"'
            meta["content_revision"] = 'web:etag:"race-new"'
            fresh.metadata_ = meta
            self._session.flush()
            return raw

        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        with patch.object(ExplicitResourceContentExtractor, "_download_bytes", racing_download):
            extractor.run(
                obj.id,
                expected_revision=start_revision,
                extraction_version=EXTRACTION_VERSION,
                expected_baseline=start_baseline,
            )
        db_session.commit()

    refreshed = db_session.get(Object, obj.id)
    assert refreshed.metadata_["content_revision"] == 'web:etag:"race-new"'
    rep_count = db_session.scalar(
        select(func.count()).select_from(Representation).where(
            Representation.object_id == obj.id
        )
    )
    assert rep_count == 0


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_pdf_url_with_text_html_stays_web_page(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    html = "<html><title>Paper</title><body>html paper body searchable</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=html.encode(),
            headers={"Content-Type": "text/html"},
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        fetched = fetch_web_page("https://example.org/paper.pdf")
        result = WebExplicitLinkIntakeService(
            session=db_session, user_id=BOOTSTRAP_USER_ID
        ).intake_link("https://example.org/paper.pdf")

    assert not fetched.is_direct_file
    assert "html paper body searchable" in fetched.text
    obj = db_session.get(Object, result.object_id)
    assert obj.kind == "web_page"


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_failed_same_etag_not_rewritten_to_pending(mock_resolve, db_session) -> None:
    _patch_addr(mock_resolve)
    body = _large_pdf_bytes("failed_state", MAX_WEB_FETCH_BYTES + 32 * 1024)
    transport = httpx.MockTransport(_pdf_handler(body, ETag='"failed-etag"'))
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
        meta[CONTENT_EXTRACTION_STATUS] = "failed"
        meta["content_revision"] = 'web:etag:"failed-etag"'
        obj.metadata_ = meta
        db_session.commit()
        second = service.intake_link(ARXIV_STYLE_URL)

    assert second.status == "unchanged"
    assert second.content_status == "failed"
    assert second.content_jobs_enqueued == 0
