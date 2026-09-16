"""Universal Intake Iteration A-R3: direct web file handoff."""

import socket
import uuid
from unittest.mock import patch

import httpx
from sqlalchemy import func, select

from app.content_extraction.constants import EXTRACTION_VERSION
from app.content_extraction.extract_service import ExplicitResourceContentExtractor
from app.db.models import Job, Object
from app.jobs.constants import JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT
from app.resources.constants import MAX_WEB_FETCH_BYTES, PROVIDER_WEB
from app.resources.web_fetch import fetch_web_page
from app.services.context_service import ContextService
from app.services.retrieval_service import RetrievalService
from app.services.web_explicit_link_intake_service import WebExplicitLinkIntakeService
from app.services.web_url_normalize import normalize_explicit_web_url
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.fixtures.phase_29a_fixtures import _minimal_pdf_bytes

ARXIV_STYLE_URL = "https://example.test/pdf/1506.04214"
_REAL_HTTPX_CLIENT = httpx.Client


def _large_pdf_bytes(marker: str, target_size: int) -> bytes:
    pdf = _minimal_pdf_bytes(marker)
    if len(pdf) >= target_size:
        return pdf
    padding = b"\n% padding\n" + (b"0" * (target_size - len(pdf) - 12))
    return pdf + padding


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_large_pdf_without_extension_classifies_as_direct_file(mock_resolve) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    body = _large_pdf_bytes("arxiv_marker_seed", MAX_WEB_FETCH_BYTES + 512 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(len(body)),
            },
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        result = fetch_web_page(ARXIV_STYLE_URL)

    assert result.is_direct_file
    assert result.detected_suffix == ".pdf"
    assert result.file_too_large is False
    assert result.content_length == len(body)
    assert len(body) > MAX_WEB_FETCH_BYTES


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_large_pdf_intake_creates_web_file_pending(mock_resolve, db_session) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    marker = f"arxiv_r3_{uuid.uuid4().hex}"
    body = _large_pdf_bytes(marker, MAX_WEB_FETCH_BYTES + 512 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(len(body)),
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
        result = service.intake_link(ARXIV_STYLE_URL)

    obj = db_session.get(Object, result.object_id)
    assert obj.provider == PROVIDER_WEB
    assert obj.kind == "file"
    assert obj.origin == "explicit"
    assert obj.metadata_["content_extraction_status"] == "pending"
    assert obj.metadata_["detected_suffix"] == ".pdf"
    jobs = db_session.scalars(
        select(Job).where(
            Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
            Job.payload["object_id"].as_string() == str(obj.id),
        )
    ).all()
    assert jobs


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_large_pdf_worker_extracts_and_retrieves_late_marker(mock_resolve, db_session) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    marker = f"latepdf{uuid.uuid4().hex}"
    body = _large_pdf_bytes(marker, MAX_WEB_FETCH_BYTES + 256 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(len(body)),
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
        result = service.intake_link(ARXIV_STYLE_URL)
        db_session.commit()

        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        obj = db_session.get(Object, result.object_id)
        extractor.run(
            obj.id,
            expected_revision=obj.metadata_.get("content_revision"),
            extraction_version="phase29a-v2",
        )
        db_session.commit()

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(marker, limit=5, time_scope="all")
    assert result.object_id in [h.object_id for h in hits.hits]

    ctx = ContextService(db_session, BOOTSTRAP_USER_ID, embedding_service=None).build_context(
        object_id=result.object_id,
        query=marker,
        max_chars=8000,
    )
    joined = "\n".join(item.content for item in ctx.items)
    assert marker in joined


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_large_pdf_intake_idempotent_same_object(mock_resolve, db_session) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    body = _large_pdf_bytes("idempotent_pdf", MAX_WEB_FETCH_BYTES + 128 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(len(body)),
                "ETag": '"stable-etag"',
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
        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        obj = db_session.get(Object, first.object_id)
        extractor.run(
            obj.id,
            expected_revision=obj.metadata_.get("content_revision"),
            extraction_version=EXTRACTION_VERSION,
        )
        db_session.commit()
        second = service.intake_link(ARXIV_STYLE_URL)

    assert second.object_id == first.object_id
    assert second.status == "unchanged"
    normalized = normalize_explicit_web_url(ARXIV_STYLE_URL)
    count = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.provider == PROVIDER_WEB,
            Object.external_id == normalized,
        )
    )
    assert count == 1


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_web_page_html_regression_under_fetch_cap(mock_resolve) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    html = "<html><title>Page</title><body>hello web page</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=html.encode(), headers={"Content-Type": "text/html"})

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        result = fetch_web_page("https://example.org/article")

    assert not result.is_direct_file
    assert "hello web page" in result.text


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_existing_web_page_upgrades_to_file_on_pdf_reintake(mock_resolve, db_session) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    body = _large_pdf_bytes("upgrade_marker", MAX_WEB_FETCH_BYTES + 64 * 1024)
    url = f"https://example.test/upgrade-{uuid.uuid4().hex}.pdf"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(len(body)),
            },
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        prior = Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="web_page",
            title="old web page",
            origin="explicit",
            state="observed",
            provider=PROVIDER_WEB,
            external_id=normalize_explicit_web_url(url),
            canonical_uri=url,
            metadata_={"content_extraction_status": "metadata_only"},
        )
        db_session.add(prior)
        db_session.commit()

        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        result = service.intake_link(url)

    refreshed = db_session.get(Object, prior.id)
    assert result.object_id == prior.id
    assert refreshed.kind == "file"
    assert refreshed.metadata_["content_extraction_status"] == "pending"
