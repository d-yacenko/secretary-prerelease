"""Universal Intake & Format Parity — Iteration A tests."""

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.db.models import Job, Object, Representation
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
from app.main import app
from app.resources.constants import PROVIDER_WEB
from app.resources.web_fetch import WebFetchResult
from app.services.capture_service import CaptureService
from app.services.context_service import ContextService
from app.services.explicit_link_provider import detect_intake_provider
from app.services.recent_source_service import RecentSourceService
from app.services.retrieval_service import RetrievalService
from app.services.web_explicit_link_intake_service import WebExplicitLinkIntakeService
from app.users.bootstrap import BOOTSTRAP_USER_ID

MARKER_NOTE = "uni_intake_note_marker_xyz"
MARKER_WEB = "uni_intake_web_marker_xyz"
TEST_URL = "https://example.org/uni-intake-test-page"


def _web_fetch_html(marker: str, title: str = "Test Page") -> WebFetchResult:
    text = f"{title} {marker}"
    return WebFetchResult(
        title=title,
        text=text,
        final_url=TEST_URL,
        content_type="text/html",
        is_binary=False,
        content_hash=f"hash-{marker}",
    )


def test_detect_intake_provider_google_and_yandex_and_web() -> None:
    assert detect_intake_provider("https://drive.google.com/file/d/abc/view") == "google_drive"
    assert detect_intake_provider("https://disk.yandex.ru/d/abc") == "yandex_disk"
    assert detect_intake_provider("https://example.org/article") == PROVIDER_WEB


def test_capture_note_creates_confirmed_note(auth_client, db_session) -> None:
    response = auth_client.post(
        "/capture/note",
        json={"text": f"Note body {MARKER_NOTE}", "title": "My note"},
    )
    assert response.status_code == 201
    note_id = response.json()["note_id"]
    obj = db_session.get(Object, uuid.UUID(note_id))
    assert obj is not None
    assert obj.kind == "note"
    assert obj.origin == "user"
    assert obj.state == "confirmed"
    assert obj.status is None
    assert obj.provider is None
    assert obj.title == "My note"
    assert MARKER_NOTE in obj.body


def test_capture_note_derives_title(auth_client, db_session) -> None:
    response = auth_client.post("/capture/note", json={"text": f"First line {MARKER_NOTE}"})
    assert response.status_code == 201
    obj = db_session.get(Object, uuid.UUID(response.json()["note_id"]))
    assert obj.title.startswith("First line")


def test_capture_note_blank_rejected(auth_client) -> None:
    response = auth_client.post("/capture/note", json={"text": "   "})
    assert response.status_code == 422


def test_capture_note_enqueue_embed_once(auth_client, db_session) -> None:
    response = auth_client.post("/capture/note", json={"text": f"embed {uuid.uuid4().hex}"})
    note_id = response.json()["note_id"]
    jobs = db_session.scalars(
        __import__("sqlalchemy", fromlist=["select"]).select(Job).where(
            Job.user_id == BOOTSTRAP_USER_ID,
            Job.type == JOB_TYPE_EMBED_OBJECT,
        )
    ).all()
    matching = [j for j in jobs if j.payload.get("object_id") == note_id]
    assert len(matching) == 1


def test_capture_note_user_isolation(db_session, issue_bearer) -> None:
    from app.db.models import User

    other_id = uuid.uuid4()
    db_session.add(User(id=other_id, display_name="Other"))
    db_session.flush()
    token = issue_bearer(other_id, label="note-iso")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        created = client.post(
            "/capture/note",
            json={"text": "isolated note"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 201
        note_id = created.json()["note_id"]
        obj = db_session.get(Object, uuid.UUID(note_id))
        assert obj.user_id == other_id
    finally:
        app.dependency_overrides.clear()


def test_note_retrieve_by_phrase(db_session) -> None:
    svc = CaptureService(db_session, BOOTSTRAP_USER_ID)
    marker = f"note_retrieve_{uuid.uuid4().hex}"
    note = svc.capture_note(f"Body with {marker}")
    db_session.commit()
    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(marker, limit=5, time_scope="all")
    assert note.note_id in [h.object_id for h in hits.hits]


def test_note_not_in_today_tasks(auth_client, db_session) -> None:
    auth_client.post("/capture/note", json={"text": f"today skip {uuid.uuid4().hex}"})
    today = auth_client.get("/today")
    assert today.status_code == 200
    tasks = today.json().get("tasks", [])
    assert all(t.get("kind") != "note" for t in tasks)


@patch("app.services.web_explicit_link_intake_service.fetch_web_page")
def test_web_intake_creates_web_page(mock_fetch, db_session) -> None:
    mock_fetch.return_value = _web_fetch_html(MARKER_WEB)
    service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
    result = service.intake_link(TEST_URL)
    obj = db_session.get(Object, result.object_id)
    assert obj.kind == "web_page"
    assert obj.provider == PROVIDER_WEB
    assert obj.origin == "explicit"
    assert obj.state == "observed"
    assert obj.canonical_uri == TEST_URL
    reps = db_session.scalars(
        __import__("sqlalchemy", fromlist=["select"]).select(Representation).where(
            Representation.object_id == obj.id
        )
    ).all()
    assert any(MARKER_WEB in r.text for r in reps)
    assert result.status == "created"


@patch("app.services.web_explicit_link_intake_service.fetch_web_page")
def test_web_intake_idempotent_same_content(mock_fetch, db_session) -> None:
    mock_fetch.return_value = _web_fetch_html(MARKER_WEB)
    service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
    first = service.intake_link(TEST_URL)
    db_session.commit()
    second = service.intake_link(TEST_URL)
    assert second.object_id == first.object_id
    assert second.status == "unchanged"
    assert second.content_jobs_enqueued == 0


@patch("app.services.web_explicit_link_intake_service.fetch_web_page")
def test_web_intake_changed_content_refreshes(mock_fetch, db_session) -> None:
    mock_fetch.return_value = _web_fetch_html("old_marker")
    service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
    first = service.intake_link(TEST_URL)
    db_session.commit()
    mock_fetch.return_value = _web_fetch_html("new_marker_unique")
    second = service.intake_link(TEST_URL)
    assert second.object_id == first.object_id
    assert second.status == "updated"
    reps = db_session.scalars(
        __import__("sqlalchemy", fromlist=["select"]).select(Representation).where(
            Representation.object_id == first.object_id
        )
    ).all()
    joined = "\n".join(r.text for r in reps)
    assert "new_marker_unique" in joined


@patch("app.services.web_explicit_link_intake_service.fetch_web_page")
def test_web_retrieve_and_context(mock_fetch, db_session) -> None:
    marker = f"web_ctx_{uuid.uuid4().hex}"
    mock_fetch.return_value = _web_fetch_html(marker)
    service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
    result = service.intake_link(TEST_URL)
    db_session.commit()
    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(marker, limit=5, time_scope="all")
    assert result.object_id in [h.object_id for h in hits.hits]
    ctx = ContextService(db_session, BOOTSTRAP_USER_ID, embedding_service=None).build_context(
        object_id=result.object_id,
        query=marker,
        max_chars=8000,
    )
    joined = "\n".join(i.content for i in ctx.items)
    assert marker in joined


@patch("app.services.web_explicit_link_intake_service.fetch_web_page")
def test_web_binary_metadata_only(mock_fetch, db_session) -> None:
    mock_fetch.return_value = WebFetchResult(
        title=None,
        text="",
        final_url=TEST_URL,
        content_type="application/pdf",
        is_binary=True,
        content_hash="pdfhash",
    )
    service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
    result = service.intake_link(TEST_URL)
    obj = db_session.get(Object, result.object_id)
    assert obj.metadata_["content_extraction_status"] == "metadata_only"
    reps = db_session.scalars(
        __import__("sqlalchemy", fromlist=["select"]).select(Representation).where(
            Representation.object_id == obj.id
        )
    ).all()
    assert reps == []


@patch("app.services.web_explicit_link_intake_service.fetch_web_page")
def test_intake_link_api_web(mock_fetch, auth_client) -> None:
    mock_fetch.return_value = _web_fetch_html(f"api_{uuid.uuid4().hex}")
    response = auth_client.post("/intake/link", json={"url": TEST_URL})
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == PROVIDER_WEB
    assert body["kind"] == "web_page"


def test_recent_inbox_includes_note_and_web_page(db_session) -> None:
    note = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="note",
        title="Inbox note",
        origin="user",
        state="confirmed",
        body="body",
    )
    web = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="web_page",
        title="Inbox web",
        origin="explicit",
        state="observed",
        provider=PROVIDER_WEB,
        external_id="https://example.org/inbox",
        canonical_uri="https://example.org/inbox",
    )
    task = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="task",
        title="Not in inbox",
        origin="user",
        state="confirmed",
        status="open",
    )
    db_session.add_all([note, web, task])
    db_session.flush()
    titles = {row.title for row in RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent()}
    assert "Inbox note" in titles
    assert "Inbox web" in titles
    assert "Not in inbox" not in titles
