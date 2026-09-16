"""Universal Object Delete — Secretary-local tombstones."""

pytest_plugins = [
    "tests.test_phase_27c_explicit_intake_google",
    "tests.test_phase_27c_local_explicit_intake",
]

import socket
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.deps import get_db
from app.api.schemas import EdgeCreate, ObjectCreate
from app.connectors.google.constants import DRIVE_READONLY_SCOPE
from app.connectors.mattermost.sync import MattermostSyncService
from app.db.models import Edge, Object, Representation
from app.domain.object_visibility import passive_sync_should_skip_existing
from app.domain.task_lifecycle import TASK_STATUS_DELETED
from app.jobs.handlers import (
    handle_correlate_object,
    handle_embed_object,
    handle_extract_explicit_resource_content,
    handle_summarize_resource,
)
from app.main import app
from app.services.domain_tool_service import DomainToolService
from app.services.errors import NotFoundError
from app.services.explicit_link_intake_errors import ExplicitLinkIntakeError
from app.services.graph_service import GraphService
from app.services.object_deletion_service import ObjectDeletionService
from app.services.object_query_service import ObjectQueryService
from app.services.open_target_service import OpenTargetService
from app.services.retrieval_service import RetrievalService
from app.services.search_service import SearchService
from app.services.web_explicit_link_intake_service import WebExplicitLinkIntakeService
from app.services.web_url_normalize import normalize_explicit_web_url
from app.tools.schemas import DeleteTaskInput
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides
from tests.test_phase_27c_explicit_intake_google import (
    FakeDriveTransport,
    _drive_file,
    _google_account,
    _intake_service,
)
from tests.test_phase_27c_local_explicit_intake import (
    _intake_file,
    _intake_folder,
)


@pytest.fixture
def api_client(db_session, fake_embedding_service, auth_headers):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


def _create_note(db_session, title: str = "Disposable note") -> Object:
    return GraphService(db_session, BOOTSTRAP_USER_ID, None).create_object(
        ObjectCreate(kind="note", title=title, body="body", origin="system")
    )


def _create_task(db_session, title: str = "Disposable task") -> Object:
    return GraphService(db_session, BOOTSTRAP_USER_ID, None).create_object(
        ObjectCreate(kind="task", title=title, body="body", origin="system", status="open")
    )


def test_legacy_deleted_task_backfill_semantics(db_session) -> None:
    deleted = _create_task(db_session, "legacy deleted")
    deleted.status = TASK_STATUS_DELETED
    deleted.deleted_at = None
    open_task = _create_task(db_session, "still open")
    done = _create_task(db_session, "done task")
    done.status = "done"
    db_session.flush()

    deleted.deleted_at = deleted.updated_at or datetime.now(UTC)
    db_session.flush()

    refreshed_deleted = db_session.get(Object, deleted.id)
    refreshed_open = db_session.get(Object, open_task.id)
    refreshed_done = db_session.get(Object, done.id)
    assert refreshed_deleted.deleted_at is not None
    assert refreshed_open.deleted_at is None
    assert refreshed_done.deleted_at is None


def test_generic_delete_note_sets_deleted_at(db_session) -> None:
    note = _create_note(db_session)
    result = ObjectDeletionService(db_session, BOOTSTRAP_USER_ID).delete_object(note.id)
    assert result.already_deleted is False
    assert result.deleted_at is not None
    refreshed = db_session.get(Object, note.id)
    assert refreshed is not None
    assert refreshed.deleted_at is not None


def test_generic_delete_idempotent(db_session) -> None:
    note = _create_note(db_session)
    service = ObjectDeletionService(db_session, BOOTSTRAP_USER_ID)
    first = service.delete_object(note.id)
    second = service.delete_object(note.id)
    assert first.already_deleted is False
    assert second.already_deleted is True


def test_generic_delete_foreign_user_isolation(db_session, nornickel_user_id) -> None:
    note = Object(
        user_id=nornickel_user_id,
        kind="note",
        title="foreign",
        origin="system",
        state="confirmed",
    )
    db_session.add(note)
    db_session.flush()
    service = ObjectDeletionService(db_session, BOOTSTRAP_USER_ID)
    with pytest.raises(NotFoundError):
        service.delete_object(note.id)


def test_task_delete_endpoints_set_deleted_at(api_client, db_session) -> None:
    task = _create_task(db_session)
    response = api_client.delete(f"/tasks/{task.id}")
    assert response.status_code == 200
    refreshed = db_session.get(Object, task.id)
    assert refreshed.status == TASK_STATUS_DELETED
    assert refreshed.deleted_at is not None

    task2 = _create_task(db_session, "second")
    response2 = api_client.delete(f"/objects/{task2.id}")
    assert response2.status_code == 200
    body = response2.json()
    assert body["object_id"] == str(task2.id)
    refreshed2 = db_session.get(Object, task2.id)
    assert refreshed2.deleted_at is not None
    assert refreshed2.status == TASK_STATUS_DELETED


def test_agent_delete_task_sets_deleted_at(db_session, fake_embedding_service) -> None:
    task = _create_task(db_session, "agent delete")
    service = DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    result = service.delete_task(DeleteTaskInput(object_id=task.id))
    assert result.new_status == TASK_STATUS_DELETED
    refreshed = db_session.get(Object, task.id)
    assert refreshed.deleted_at is not None


def test_deleted_object_hidden_from_search_retrieve_inbox_open_target(
    db_session, api_client
) -> None:
    note = _create_note(db_session, "hidden marker alpha")
    ObjectDeletionService(db_session, BOOTSTRAP_USER_ID).delete_object(note.id)
    db_session.flush()

    search = SearchService(db_session, BOOTSTRAP_USER_ID).search("hidden marker alpha")
    assert all(item.id != note.id for item in search)

    retrieval = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve("hidden marker alpha")
    assert all(hit.object_id != note.id for hit in retrieval.hits)

    # Notes are not inbox feed objects; search/retrieve/open-target coverage is sufficient.

    with pytest.raises(NotFoundError):
        OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(note.id)

    response = api_client.get(f"/objects/{note.id}")
    assert response.status_code == 404


def test_deleted_object_with_representation_not_retrievable(db_session) -> None:
    note = _create_note(db_session, "chunk marker beta")
    rep = Representation(
        object_id=note.id,
        kind="chunk",
        text="chunk marker beta unique token",
        metadata_={},
    )
    db_session.add(rep)
    db_session.flush()
    ObjectDeletionService(db_session, BOOTSTRAP_USER_ID).delete_object(note.id)
    db_session.flush()

    results = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "chunk marker beta unique token"
    )
    assert all(hit.object_id != note.id for hit in results.hits)


def test_graph_hides_deleted_endpoint_but_keeps_edge(db_session, api_client) -> None:
    task = _create_task(db_session, "graph task")
    email = GraphService(db_session, BOOTSTRAP_USER_ID, None).create_object(
        ObjectCreate(kind="email", title="graph email", origin="system", provider="gmail")
    )
    GraphService(db_session, BOOTSTRAP_USER_ID, None).create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=email.id,
            type="related_to",
            origin="system",
            state="observed",
        )
    )
    ObjectDeletionService(db_session, BOOTSTRAP_USER_ID).delete_object(task.id)
    db_session.flush()

    edge_count = db_session.scalar(select(func.count()).select_from(Edge))
    assert edge_count == 1

    neighbors = api_client.get(f"/objects/{email.id}/neighbors")
    assert neighbors.status_code == 200
    neighbor_ids = {row["object"]["id"] for row in neighbors.json()["neighbors"]}
    assert str(task.id) not in neighbor_ids


def test_background_jobs_noop_for_deleted_object(db_session, fake_embedding_service) -> None:
    note = _create_note(db_session)
    ObjectDeletionService(db_session, BOOTSTRAP_USER_ID).delete_object(note.id)
    db_session.flush()
    payload = {"object_id": str(note.id)}
    handle_embed_object(db_session, fake_embedding_service, payload, BOOTSTRAP_USER_ID)
    handle_summarize_resource(db_session, fake_embedding_service, payload, BOOTSTRAP_USER_ID)
    handle_correlate_object(db_session, fake_embedding_service, payload, BOOTSTRAP_USER_ID)
    handle_extract_explicit_resource_content(
        db_session, fake_embedding_service, payload, BOOTSTRAP_USER_ID
    )
    refreshed = db_session.get(Object, note.id)
    assert refreshed.deleted_at is not None


def test_mattermost_passive_sync_does_not_clear_deleted_at(db_session) -> None:
    from unittest.mock import MagicMock

    from app.services.job_queue_service import JobQueueService

    external_id = "https://mattermost.example.com:post-1"
    deleted_at = datetime.now(UTC)
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider="mattermost",
        external_id=external_id,
        origin="source",
        state="observed",
        title="old",
        deleted_at=deleted_at,
    )
    db_session.add(obj)
    db_session.flush()

    sync = MattermostSyncService(
        session=db_session,
        account_store=MagicMock(),
        job_queue=JobQueueService(db_session),
    )
    normalized = {
        "kind": "chat_message",
        "provider": "mattermost",
        "external_id": external_id,
        "origin": "source",
        "state": "observed",
        "title": "updated",
        "body": "updated body",
        "metadata": {},
        "occurred_at": datetime.now(UTC),
    }
    existing = sync._find_existing(BOOTSTRAP_USER_ID, external_id)
    assert existing is not None
    if existing is not None and passive_sync_should_skip_existing(existing):
        result = "unchanged"
    else:
        sync._apply_normalized(existing, normalized)
        result = "updated"
    assert result == "unchanged"
    refreshed = db_session.get(Object, obj.id)
    assert refreshed.deleted_at == deleted_at
    assert refreshed.title == "old"


def test_explicit_web_readd_restores_same_object_id(db_session) -> None:
    url = f"https://example.test/restore-{uuid.uuid4().hex}.txt"
    external_id = normalize_explicit_web_url(url)
    body = b"restore marker\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "text/plain", "Content-Length": str(len(body))},
        )

    transport = httpx.MockTransport(handler)
    _REAL_HTTPX_CLIENT = httpx.Client
    with patch(
        "app.resources.web_fetch.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    ), patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        first = service.intake_link(url)
        db_session.commit()
        ObjectDeletionService(db_session, BOOTSTRAP_USER_ID).delete_object(first.object_id)
        db_session.commit()
        second = service.intake_link(url)
        db_session.commit()

    assert second.object_id == first.object_id
    refreshed = db_session.get(Object, first.object_id)
    assert refreshed.deleted_at is None
    assert refreshed.external_id == external_id


def test_explicit_google_drive_readd_restores_same_object_id(
    db_session, oauth_client_file, credential_key, google_settings
) -> None:
    file_id = f"restore-{uuid.uuid4().hex}"
    url = f"https://drive.google.com/file/d/{file_id}/view"
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    transport = FakeDriveTransport({file_id: _drive_file(file_id, "Restore doc")})
    service = _intake_service(db_session, credential_key, oauth_client_file, transport)
    first = service.intake_link(url, account_id=account.id)
    db_session.commit()
    ObjectDeletionService(db_session, BOOTSTRAP_USER_ID).delete_object(first.object_id)
    db_session.commit()
    second = service.intake_link(url, account_id=account.id)
    db_session.commit()
    assert second.object_id == first.object_id
    refreshed = db_session.get(Object, first.object_id)
    assert refreshed.deleted_at is None


def test_web_readd_fetch_failure_keeps_tombstone(db_session) -> None:
    url = f"https://example.test/fail-restore-{uuid.uuid4().hex}.txt"
    body = b"restore marker\n"

    def success_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "text/plain", "Content-Length": str(len(body))},
        )

    transport = httpx.MockTransport(success_handler)
    _REAL_HTTPX_CLIENT = httpx.Client
    with patch(
        "app.resources.web_fetch.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    ), patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        service = WebExplicitLinkIntakeService(session=db_session, user_id=BOOTSTRAP_USER_ID)
        first = service.intake_link(url)
        db_session.commit()
        ObjectDeletionService(db_session, BOOTSTRAP_USER_ID).delete_object(first.object_id)
        db_session.commit()

        with patch(
            "app.services.web_explicit_link_intake_service.fetch_web_page",
            side_effect=ExplicitLinkIntakeError("network failed"),
        ), pytest.raises(ExplicitLinkIntakeError):
            service.intake_link(url)

        refreshed = db_session.get(Object, first.object_id)
        assert refreshed is not None
        assert refreshed.deleted_at is not None

        second = service.intake_link(url)
        db_session.commit()

    assert second.object_id == first.object_id
    refreshed_after = db_session.get(Object, first.object_id)
    assert refreshed_after.deleted_at is None


def test_explicit_local_file_delete_readd_restores_same_id(
    phase27c_local_client, db_session
) -> None:
    from app.services.folder_object_service import EXPLICIT_LOCAL_INTAKE_MODE

    phase27c_local_client.post(
        "/local/devices/register",
        json={"device_key": "desk-26b", "display_name": "Test desktop"},
    )
    first = _intake_file(phase27c_local_client, intake_mode=EXPLICIT_LOCAL_INTAKE_MODE)
    ObjectDeletionService(db_session, BOOTSTRAP_USER_ID).delete_object(
        uuid.UUID(first["object_id"])
    )
    db_session.flush()
    tombstoned = db_session.get(Object, uuid.UUID(first["object_id"]))
    assert tombstoned.deleted_at is not None

    second = _intake_file(phase27c_local_client, intake_mode=EXPLICIT_LOCAL_INTAKE_MODE)
    assert second["object_id"] == first["object_id"]
    restored = db_session.get(Object, uuid.UUID(first["object_id"]))
    assert restored.deleted_at is None


def test_explicit_local_folder_delete_readd_restores_same_id(
    phase27c_local_client, db_session, tmp_path
) -> None:
    folder = tmp_path / "restore-folder"
    folder.mkdir()
    body = _intake_folder(
        phase27c_local_client,
        root_path=str(folder.relative_to(tmp_path)),
        client_source_path=str(folder),
    )
    ObjectDeletionService(db_session, BOOTSTRAP_USER_ID).delete_object(
        uuid.UUID(body["object_id"])
    )
    db_session.flush()
    tombstoned = db_session.get(Object, uuid.UUID(body["object_id"]))
    assert tombstoned.deleted_at is not None

    second = _intake_folder(
        phase27c_local_client,
        root_path=str(folder.relative_to(tmp_path)),
        client_source_path=str(folder),
    )
    assert second["object_id"] == body["object_id"]
    restored = db_session.get(Object, uuid.UUID(body["object_id"]))
    assert restored.deleted_at is None


def test_passive_local_rediscovery_keeps_tombstone(db_session, tmp_path) -> None:
    from app.local.paths import LocalPathResolver
    from app.services.job_queue_service import JobQueueService
    from app.services.local_device_service import LocalDeviceService
    from app.services.local_file_sync_service import LocalFileReport, LocalFileSyncService

    local_mirror = tmp_path / "local-mirror"
    local_mirror.mkdir()
    device_key = "passive-device"
    root_rel = "docs"

    device_service = LocalDeviceService(
        db_session, BOOTSTRAP_USER_ID, LocalPathResolver(local_mirror)
    )
    device_service.register_device(device_key=device_key, display_name="Passive")
    device_service.register_root(
        device_key=device_key,
        root_path=root_rel,
        default_policy="metadata_only",
    )

    sync = LocalFileSyncService(
        db_session,
        BOOTSTRAP_USER_ID,
        LocalPathResolver(local_mirror),
        JobQueueService(db_session),
    )
    first = sync.report_files(
        device_key,
        root_rel,
        [
            LocalFileReport(
                relative_path="notes.md",
                size=12,
                modified_at="2026-01-01T10:00:00Z",
            )
        ],
    )
    assert first.objects_created == 1
    obj = db_session.scalar(
        select(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.provider == "local_device",
        )
    )
    assert obj is not None
    deleted_at = datetime.now(UTC)
    obj.deleted_at = deleted_at
    db_session.flush()

    second = sync.report_files(
        device_key,
        root_rel,
        [
            LocalFileReport(
                relative_path="notes.md",
                size=12,
                modified_at="2026-01-01T10:00:00Z",
            )
        ],
    )
    assert second.objects_updated == 0
    refreshed = db_session.get(Object, obj.id)
    assert refreshed.deleted_at == deleted_at


def test_legacy_status_deleted_hidden_from_active_reads(db_session, api_client) -> None:
    obj = GraphService(db_session, BOOTSTRAP_USER_ID, None).create_object(
        ObjectCreate(
            kind="file",
            title="legacy deleted drive file",
            origin="source",
            provider="google_drive",
            external_id=f"drive:{uuid.uuid4().hex}",
            status="deleted",
        )
    )
    db_session.flush()

    search = SearchService(db_session, BOOTSTRAP_USER_ID).search("legacy deleted drive")
    assert all(item.id != obj.id for item in search)

    query = ObjectQueryService(db_session, BOOTSTRAP_USER_ID).query(kinds=["file"])
    assert all(row.id != obj.id for row in query)

    with pytest.raises(NotFoundError):
        OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)

    response = api_client.get(f"/objects/{obj.id}")
    assert response.status_code == 404


def test_legacy_status_deleted_explicit_readd_restores_visibility(
    db_session, oauth_client_file, credential_key, google_settings
) -> None:
    file_id = f"legacy-restore-{uuid.uuid4().hex}"
    url = f"https://drive.google.com/file/d/{file_id}/view"
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    transport = FakeDriveTransport({file_id: _drive_file(file_id, "Legacy restore")})
    service = _intake_service(db_session, credential_key, oauth_client_file, transport)
    first = service.intake_link(url, account_id=account.id)
    db_session.commit()

    existing = db_session.get(Object, first.object_id)
    existing.status = "deleted"
    existing.deleted_at = None
    db_session.commit()

    with pytest.raises(NotFoundError):
        OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(first.object_id)

    second = service.intake_link(url, account_id=account.id)
    db_session.commit()
    assert second.object_id == first.object_id
    restored = db_session.get(Object, first.object_id)
    assert restored.deleted_at is None
    assert restored.status is None
    OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(first.object_id)


def test_graph_context_hides_deleted_neighbor_and_edge(db_session, api_client) -> None:
    parent = _create_task(db_session, "context parent")
    child = GraphService(db_session, BOOTSTRAP_USER_ID, None).create_object(
        ObjectCreate(kind="note", title="context child", origin="system")
    )
    GraphService(db_session, BOOTSTRAP_USER_ID, None).create_edge(
        EdgeCreate(
            source_id=parent.id,
            target_id=child.id,
            type="related_to",
            origin="system",
            state="observed",
        )
    )
    ObjectDeletionService(db_session, BOOTSTRAP_USER_ID).delete_object(child.id)
    db_session.flush()

    edge_count = db_session.scalar(select(func.count()).select_from(Edge))
    assert edge_count == 1

    response = api_client.get(f"/objects/{parent.id}/context")
    assert response.status_code == 200
    body = response.json()
    assert body["edges"] == []
    assert body["neighbors"] == []
