"""Universal Intake Iteration A-R3-R1: bounded probe + idempotency closure."""

import socket
import uuid
from collections.abc import Iterator
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import func, select

from app.content_extraction.constants import MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES
from app.content_extraction.extract_service import ExplicitResourceContentExtractor
from app.db.models import Job, Object, Representation
from app.jobs.constants import JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT
from app.resources.constants import MAX_WEB_FETCH_BYTES
from app.resources.web_fetch import WEB_CLASSIFY_PREFIX_BYTES as CLASSIFY_BYTES
from app.resources.web_fetch import WebFetchError, fetch_web_page
from app.services.retrieval_service import RetrievalService
from app.services.web_explicit_link_intake_service import WebExplicitLinkIntakeService
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.fixtures.phase_29a_fixtures import _minimal_pdf_bytes

_REAL_HTTPX_CLIENT = httpx.Client
ARXIV_STYLE_URL = "https://example.test/pdf/1506.04214"


class _ByteStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes], *, trap_after_chunks: int | None = None) -> None:
        self._chunks = chunks
        self._trap_after_chunks = trap_after_chunks
        self.bytes_consumed = 0
        self.chunk_reads = 0

    def __iter__(self) -> Iterator[bytes]:
        for index, chunk in enumerate(self._chunks):
            if self._trap_after_chunks is not None and index >= self._trap_after_chunks:
                raise AssertionError("stream over-read detected")
            self.chunk_reads += 1
            self.bytes_consumed += len(chunk)
            yield chunk


class _PoisonStream(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        raise AssertionError("body must not be consumed for declared too_large file")


def _patch_web_client(handler) -> object:
    transport = httpx.MockTransport(handler)
    return patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    )


def _large_pdf_bytes(marker: str, target_size: int) -> bytes:
    pdf = _minimal_pdf_bytes(marker)
    if len(pdf) >= target_size:
        return pdf
    padding = b"\n% padding\n" + (b"0" * (target_size - len(pdf) - 12))
    return pdf + padding


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_direct_file_probe_stops_before_tail(mock_resolve) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    prefix = _minimal_pdf_bytes("probe_stop")
    while len(prefix) < CLASSIFY_BYTES:
        prefix += b"\n"
    prefix = prefix[:CLASSIFY_BYTES]
    tail = b"X" * (MAX_WEB_FETCH_BYTES + 1024)
    stream = _ByteStream([prefix, tail], trap_after_chunks=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/octet-stream"},
            stream=stream,
        )

    with _patch_web_client(handler):
        result = fetch_web_page(ARXIV_STYLE_URL)

    assert result.is_direct_file
    assert stream.bytes_consumed <= CLASSIFY_BYTES
    assert stream.chunk_reads == 1


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_unsupported_binary_probe_stops_before_tail(mock_resolve) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    prefix = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
    while len(prefix) < CLASSIFY_BYTES:
        prefix += b"\x00"
    prefix = prefix[:CLASSIFY_BYTES]
    tail = b"Y" * (MAX_WEB_FETCH_BYTES + 1024)
    stream = _ByteStream([prefix, tail], trap_after_chunks=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "image/png"},
            stream=stream,
        )

    with _patch_web_client(handler):
        result = fetch_web_page("https://example.test/photo.png")

    assert result.is_binary
    assert not result.is_direct_file
    assert stream.bytes_consumed <= CLASSIFY_BYTES
    assert stream.chunk_reads == 1


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_declared_over_20mib_pdf_does_not_read_body(mock_resolve, db_session) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    declared = MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES + 1024

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(declared),
            },
            stream=_PoisonStream(),
        )

    with _patch_web_client(handler):
        fetched = fetch_web_page("https://example.test/big.pdf")
        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        result = service.intake_link("https://example.test/big.pdf")

    assert fetched.is_direct_file
    assert fetched.file_too_large is True
    obj = db_session.get(Object, result.object_id)
    assert obj.metadata_["content_extraction_status"] == "too_large"
    jobs = db_session.scalars(
        select(Job).where(
            Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
            Job.payload["object_id"].as_string() == str(obj.id),
        )
    ).all()
    assert jobs == []


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_html_uses_single_iterator_and_enforces_cap(mock_resolve) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    chunk_size = 64 * 1024
    chunks = [b"<html><body>" + (b"x" * (chunk_size - 13)) + b"</body></html>"]
    chunks.append(b"z" * (MAX_WEB_FETCH_BYTES + 1))
    stream = _ByteStream(chunks)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            stream=stream,
        )

    with _patch_web_client(handler), pytest.raises(WebFetchError, match="web fetch exceeded size limit"):
        fetch_web_page("https://example.test/page.html")

    assert stream.bytes_consumed > MAX_WEB_FETCH_BYTES


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_ready_reintake_same_etag_stays_ready(mock_resolve, db_session) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    marker = f"ready_idem_{uuid.uuid4().hex}"
    body = _large_pdf_bytes(marker, MAX_WEB_FETCH_BYTES + 128 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(len(body)),
                "ETag": '"ready-stable-etag"',
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
            extraction_version="phase29a-v2",
        )
        db_session.commit()

        rep_count_before = db_session.scalar(
            select(func.count()).select_from(Representation).where(
                Representation.object_id == first.object_id
            )
        )
        meta_before = dict(db_session.get(Object, first.object_id).metadata_ or {})
        assert meta_before["content_extraction_status"] == "ready"

        jobs_before = db_session.scalars(
            select(Job).where(
                Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
                Job.payload["object_id"].as_string() == str(first.object_id),
            )
        ).all()

        second = service.intake_link(ARXIV_STYLE_URL)
        db_session.commit()

    rep_count_after = db_session.scalar(
        select(func.count()).select_from(Representation).where(
            Representation.object_id == first.object_id
        )
    )
    jobs_after = db_session.scalars(
        select(Job).where(
            Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
            Job.payload["object_id"].as_string() == str(first.object_id),
        )
    ).all()

    refreshed = db_session.get(Object, first.object_id)
    assert second.object_id == first.object_id
    assert second.status == "unchanged"
    assert refreshed.metadata_["content_extraction_status"] == "ready"
    assert rep_count_after == rep_count_before
    assert len(jobs_after) == len(jobs_before)


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_no_validator_same_length_reextracts_changed_content(mock_resolve, db_session) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    url = "https://example.test/no-validator.txt"
    marker_a = f"markerA_{uuid.uuid4().hex}"
    marker_b = f"markerB_{uuid.uuid4().hex}"
    body_a = f"{marker_a}\nline two\n".encode()
    body_b = f"{marker_b}\nline two\n".encode()
    assert len(body_a) == len(body_b)
    call = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call["n"] += 1
        body = body_a if call["n"] == 1 else body_b
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "text/plain",
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
        first = service.intake_link(url)
        db_session.commit()
        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        obj = db_session.get(Object, first.object_id)
        extractor.run(
            obj.id,
            expected_revision=obj.metadata_.get("content_revision"),
            extraction_version="phase29a-v2",
        )
        db_session.commit()

        second = service.intake_link(url)
        db_session.commit()
        obj = db_session.get(Object, second.object_id)
        extractor.run(
            obj.id,
            expected_revision=obj.metadata_.get("content_revision"),
            extraction_version="phase29a-v2",
        )
        db_session.commit()

    assert second.object_id == first.object_id
    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(marker_b, limit=5, time_scope="all")
    assert first.object_id in [h.object_id for h in hits.hits]
    stale_hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(marker_a, limit=5, time_scope="all")
    assert first.object_id not in [h.object_id for h in stale_hits.hits]


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_unknown_length_over_20mib_worker_sets_too_large(mock_resolve, db_session) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    body = _large_pdf_bytes("worker_too_large", MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES + 512 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "application/pdf"},
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        result = service.intake_link("https://example.test/unknown-length.pdf")
        db_session.commit()
        extractor = ExplicitResourceContentExtractor(session=db_session, user_id=BOOTSTRAP_USER_ID)
        obj = db_session.get(Object, result.object_id)
        extractor.run(
            obj.id,
            expected_revision=obj.metadata_.get("content_revision"),
            extraction_version="phase29a-v2",
        )
        db_session.commit()

    obj = db_session.get(Object, result.object_id)
    assert obj.metadata_["content_extraction_status"] == "too_large"


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_text_csv_classifies_as_direct_file(mock_resolve, db_session) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    csv_body = b"name,value\nalpha,1\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=csv_body,
            headers={"Content-Type": "text/csv"},
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        fetched = fetch_web_page("https://example.test/data")
        result = WebExplicitLinkIntakeService(
            session=db_session, user_id=BOOTSTRAP_USER_ID
        ).intake_link("https://example.test/data")

    assert fetched.is_direct_file
    assert fetched.detected_suffix == ".csv"
    obj = db_session.get(Object, result.object_id)
    assert obj.kind == "file"


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_txt_url_plain_classifies_as_direct_file(mock_resolve, db_session) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    text_body = b"hello txt file\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=text_body,
            headers={"Content-Type": "text/plain"},
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        fetched = fetch_web_page("https://example.test/readme.txt")
        result = WebExplicitLinkIntakeService(
            session=db_session, user_id=BOOTSTRAP_USER_ID
        ).intake_link("https://example.test/readme.txt")

    assert fetched.is_direct_file
    assert fetched.detected_suffix == ".txt"
    obj = db_session.get(Object, result.object_id)
    assert obj.kind == "file"


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_md_url_markdown_classifies_as_direct_file(mock_resolve, db_session) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    md_body = b"# Title\n\nbody\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=md_body,
            headers={"Content-Type": "text/markdown"},
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        fetched = fetch_web_page("https://example.test/notes.md")
        result = WebExplicitLinkIntakeService(
            session=db_session, user_id=BOOTSTRAP_USER_ID
        ).intake_link("https://example.test/notes.md")

    assert fetched.is_direct_file
    assert fetched.detected_suffix == ".md"
    obj = db_session.get(Object, result.object_id)
    assert obj.kind == "file"
