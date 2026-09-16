"""Universal Intake Iteration A-R1 corrective regressions."""

import socket
import uuid
from datetime import timedelta
from unittest.mock import patch

import httpx
from sqlalchemy import func, select

from app.db.models import Job, Object, Representation
from app.llm.embedding_service import FakeEmbeddingService
from app.resources.constants import PROVIDER_WEB
from app.resources.web_fetch import WebFetchResult, fetch_web_page
from app.services.capture_service import CaptureService
from app.services.context_service import ContextService
from app.services.correlation_constants import (
    SEMANTIC_SUMMARY_METADATA_KEY,
    SEMANTIC_SUMMARY_REVISION_KEY,
)
from app.services.domain_tool_service import DomainToolService
from app.services.job_queue_service import utcnow
from app.services.recent_source_service import (
    RecentSourceService,
)
from app.services.representation_service import KIND_SUMMARY
from app.services.retrieval_service import RetrievalService
from app.services.web_explicit_link_intake_service import WebExplicitLinkIntakeService
from app.services.web_url_normalize import normalize_explicit_web_url
from app.tools.registry import ASSISTANT_TOOL_DEFINITIONS
from app.tools.schemas import QueryObjectsInput
from app.users.bootstrap import BOOTSTRAP_USER_ID

URL_REDIRECT_START = "https://example.org/uni-intake-redirect-start"
URL_FINAL_B = "https://example.org/uni-intake-final-b"
URL_FINAL_C = "https://example.org/uni-intake-final-c"
LONG_PAGE_URL = "https://example.org/uni-intake-long-page"


def _web_result(
    *,
    text: str,
    final_url: str,
    content_hash: str,
    title: str = "Test Page",
) -> WebFetchResult:
    return WebFetchResult(
        title=title,
        text=text,
        final_url=final_url,
        content_type="text/html",
        is_binary=False,
        content_hash=content_hash,
    )


@patch("app.services.web_explicit_link_intake_service.fetch_web_page")
def test_redirect_idempotency_same_requested_url(mock_fetch, db_session) -> None:
    mock_fetch.return_value = _web_result(
        text="redirect body marker_b",
        final_url=URL_FINAL_B,
        content_hash="hash-b",
    )
    service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
    first = service.intake_link(URL_REDIRECT_START)
    db_session.commit()
    obj = db_session.get(Object, first.object_id)
    assert obj.external_id == normalize_explicit_web_url(URL_REDIRECT_START)
    assert obj.canonical_uri == URL_FINAL_B

    second = service.intake_link(URL_REDIRECT_START)
    assert second.object_id == first.object_id
    assert second.status == "unchanged"

    normalized = normalize_explicit_web_url(URL_REDIRECT_START)
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


@patch("app.services.web_explicit_link_intake_service.fetch_web_page")
def test_redirect_destination_change_updates_canonical_uri(mock_fetch, db_session) -> None:
    mock_fetch.return_value = _web_result(
        text="first destination body",
        final_url=URL_FINAL_B,
        content_hash="hash-dest-b",
    )
    service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
    first = service.intake_link(URL_REDIRECT_START)
    db_session.commit()

    mock_fetch.return_value = _web_result(
        text="second destination body changed",
        final_url=URL_FINAL_C,
        content_hash="hash-dest-c",
    )
    second = service.intake_link(URL_REDIRECT_START)
    assert second.object_id == first.object_id
    assert second.status == "updated"

    obj = db_session.get(Object, first.object_id)
    assert obj.canonical_uri == URL_FINAL_C
    assert obj.external_id == normalize_explicit_web_url(URL_REDIRECT_START)
    assert obj.metadata_["final_url"] == URL_FINAL_C


@patch("app.services.web_explicit_link_intake_service.fetch_web_page")
def test_long_page_marker_after_8k_is_retrievable(mock_fetch, db_session) -> None:
    marker = f"latemarker{uuid.uuid4().hex}"
    position = 9000
    text = ("a" * position) + f" {marker} " + ("b" * 15000)
    mock_fetch.return_value = _web_result(
        text=text,
        final_url=LONG_PAGE_URL,
        content_hash=f"hash-{marker}",
    )
    service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
    result = service.intake_link(LONG_PAGE_URL)
    db_session.commit()

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        marker, limit=5, time_scope="all"
    )
    assert result.object_id in [h.object_id for h in hits.hits]


@patch("app.services.web_explicit_link_intake_service.fetch_web_page")
def test_long_page_marker_after_8k_visible_in_context(mock_fetch, db_session) -> None:
    marker = f"ctxlate{uuid.uuid4().hex}"
    position = 9000
    text = ("c" * position) + f" {marker} " + ("d" * 15000)
    mock_fetch.return_value = _web_result(
        text=text,
        final_url=LONG_PAGE_URL,
        content_hash=f"hash-ctx-{marker}",
    )
    service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
    result = service.intake_link(LONG_PAGE_URL)
    db_session.commit()

    ctx = ContextService(db_session, BOOTSTRAP_USER_ID, embedding_service=None).build_context(
        object_id=result.object_id,
        query=marker,
        max_chars=8000,
    )
    joined = "\n".join(i.content for i in ctx.items)
    assert marker in joined


@patch("app.services.web_explicit_link_intake_service.fetch_web_page")
def test_changed_content_invalidates_embedding_and_summary(mock_fetch, db_session) -> None:
    mock_fetch.return_value = _web_result(
        text="old revision body",
        final_url=LONG_PAGE_URL,
        content_hash="hash-old-rev",
    )
    service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
    first = service.intake_link(LONG_PAGE_URL)
    obj = db_session.get(Object, first.object_id)
    obj.embedding = [0.1, 0.2, 0.3]
    obj.metadata_ = {
        **(obj.metadata_ or {}),
        SEMANTIC_SUMMARY_METADATA_KEY: "Stale summary text.",
        SEMANTIC_SUMMARY_REVISION_KEY: "web:sha256:hash-old-rev",
    }
    db_session.add(
        Representation(
            object_id=obj.id,
            kind=KIND_SUMMARY,
            text="Stale summary text.",
            metadata_={},
        )
    )
    db_session.commit()

    mock_fetch.return_value = _web_result(
        text="new revision body unique_marker",
        final_url=LONG_PAGE_URL,
        content_hash="hash-new-rev",
    )
    second = service.intake_link(LONG_PAGE_URL)
    db_session.flush()

    refreshed = db_session.get(Object, second.object_id)
    assert refreshed.embedding is None
    assert refreshed.metadata_.get(SEMANTIC_SUMMARY_METADATA_KEY) is None
    assert refreshed.metadata_.get(SEMANTIC_SUMMARY_REVISION_KEY) is None

    reps = db_session.scalars(
        select(Representation).where(Representation.object_id == refreshed.id)
    ).all()
    assert not any(r.kind == KIND_SUMMARY for r in reps)
    joined = "\n".join(r.text for r in reps)
    assert "new revision body unique_marker" in joined
    assert "old revision body" not in joined


@patch("app.services.web_explicit_link_intake_service.fetch_web_page")
def test_same_revision_skips_invalidation_and_duplicate_jobs(mock_fetch, db_session) -> None:
    mock_fetch.return_value = _web_result(
        text="stable body",
        final_url=LONG_PAGE_URL,
        content_hash="hash-stable",
    )
    service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
    first = service.intake_link(LONG_PAGE_URL)
    obj = db_session.get(Object, first.object_id)
    obj.embedding = [0.5, 0.6]
    obj.metadata_ = {
        **(obj.metadata_ or {}),
        SEMANTIC_SUMMARY_METADATA_KEY: "Stable summary.",
        SEMANTIC_SUMMARY_REVISION_KEY: "web:sha256:hash-stable",
    }
    db_session.commit()

    jobs_before = db_session.scalars(select(Job)).all()
    second = service.intake_link(LONG_PAGE_URL)
    jobs_after = db_session.scalars(select(Job)).all()
    assert second.status == "unchanged"
    assert len(jobs_after) == len(jobs_before)

    refreshed = db_session.get(Object, first.object_id)
    assert refreshed.embedding == [0.5, 0.6]
    assert refreshed.metadata_.get(SEMANTIC_SUMMARY_METADATA_KEY) == "Stable summary."


@patch("app.services.web_explicit_link_intake_service.fetch_web_page")
def test_pdf_without_content_type_becomes_pending_file(mock_fetch, db_session) -> None:
    mock_fetch.return_value = WebFetchResult(
        title=None,
        text="",
        final_url=LONG_PAGE_URL,
        content_type=None,
        is_binary=True,
        is_direct_file=True,
        detected_suffix=".pdf",
        content_length=4 * 1024 * 1024,
        content_hash="pdf-bytes",
    )
    service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
    result = service.intake_link(LONG_PAGE_URL)
    obj = db_session.get(Object, result.object_id)
    assert obj.kind == "file"
    assert obj.metadata_["content_extraction_status"] == "pending"
    reps = db_session.scalars(
        select(Representation).where(Representation.object_id == obj.id)
    ).all()
    assert reps == []


@patch("app.services.web_explicit_link_intake_service.fetch_web_page")
def test_pdf_mislabeled_text_plain_becomes_pending_file(mock_fetch, db_session) -> None:
    url = "https://example.org/mislabeled-pdf"
    mock_fetch.return_value = WebFetchResult(
        title=None,
        text="",
        final_url=url,
        content_type="text/plain",
        is_binary=True,
        is_direct_file=True,
        detected_suffix=".pdf",
        content_hash="pdf-mislabeled",
    )
    service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
    result = service.intake_link(url)
    obj = db_session.get(Object, result.object_id)
    assert obj.kind == "file"
    assert obj.metadata_["content_extraction_status"] == "pending"


def test_query_objects_returns_note_kind(db_session) -> None:
    note = CaptureService(db_session, BOOTSTRAP_USER_ID).capture_note(
        f"query note {uuid.uuid4().hex}"
    )
    db_session.flush()
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, FakeEmbeddingService())
    result = tools.query_objects(QueryObjectsInput(kinds=["note"], limit=20))
    assert any(row.object_id == note.note_id for row in result.objects)


def test_query_objects_returns_web_page_kind(db_session) -> None:
    web = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="web_page",
        title="Query web page",
        origin="explicit",
        state="observed",
        provider=PROVIDER_WEB,
        external_id=f"https://example.org/query-{uuid.uuid4().hex}",
        canonical_uri="https://example.org/query",
    )
    db_session.add(web)
    db_session.flush()
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, FakeEmbeddingService())
    result = tools.query_objects(QueryObjectsInput(kinds=["web_page"], limit=20))
    assert any(row.object_id == web.id for row in result.objects)


def test_notes_do_not_consume_provider_reserved_inbox_slots(db_session) -> None:
    now = utcnow()
    older = now - timedelta(hours=4)

    for index in range(12):
        note = Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="note",
            title=f"Recent note {index}",
            body=f"note body {index}",
            origin="user",
            state="confirmed",
        )
        note.created_at = now - timedelta(seconds=index)
        note.updated_at = now - timedelta(seconds=index)
        db_session.add(note)

    for index in range(3):
        gmail = Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="email",
            title=f"Gmail primary {index}",
            origin="source",
            state="observed",
            provider="gmail",
            external_id=f"gmail-{uuid.uuid4().hex}",
            metadata_={"labels": ["CATEGORY_PERSONAL"]},
        )
        gmail.created_at = older - timedelta(minutes=index)
        gmail.updated_at = older - timedelta(minutes=index)
        db_session.add(gmail)

    db_session.commit()
    titles = {row.title for row in RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent()}
    for index in range(3):
        assert f"Gmail primary {index}" in titles


def test_assistant_tool_count_unchanged() -> None:
    assert len(ASSISTANT_TOOL_DEFINITIONS) == len({d["name"] for d in ASSISTANT_TOOL_DEFINITIONS})


_REAL_HTTPX_CLIENT = httpx.Client


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_web_fetch_pdf_signature_without_content_type(mock_resolve) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4 fake pdf bytes")

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        result = fetch_web_page("http://example.com/doc.pdf")
    assert result.is_binary
    assert result.text == ""


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_web_fetch_pdf_mislabeled_text_plain_is_binary(mock_resolve) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"%PDF-1.4 fake",
            headers={"Content-Type": "text/plain"},
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        result = fetch_web_page("http://example.com/wrong-type.pdf")
    assert result.is_binary


@patch("app.resources.web_fetch.socket.getaddrinfo")
def test_web_fetch_text_plain_txt_url_classifies_as_direct_file(mock_resolve) -> None:
    mock_resolve.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"plain readable text content",
            headers={"Content-Type": "text/plain"},
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        result = fetch_web_page("http://example.com/readme.txt")
    assert result.is_direct_file
    assert result.detected_suffix == ".txt"
