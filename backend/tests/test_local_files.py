import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db
from app.db.models import Job, Object, Representation, User
from app.jobs.constants import JOB_TYPE_INGEST_LOCAL_FILE, JOB_TYPE_SUMMARIZE_RESOURCE
from app.jobs.handlers import handle_ingest_local_file
from app.local.constants import (
    CHEAP_HASH_MAX_BYTES,
    POLICY_INDEX_TEXT,
    POLICY_METADATA_ONLY,
    POLICY_UPLOAD_COPY,
    PROVIDER_LOCAL_DEVICE,
)
from app.local.paths import LocalPathResolver
from app.main import app
from app.resources.constants import (
    CONTENT_INGESTED_REVISION_KEY,
    REVISION_METADATA_KEYS,
)
from app.services.dataset_tool_service import DatasetToolService
from app.services.job_queue_service import JobQueueService
from app.services.local_device_service import LocalDeviceService
from app.services.local_file_sync_service import (
    LocalFileReport,
    LocalFileSyncService,
    _revision_signature,
    copy_local_file_to_upload,
)
from app.services.representation_service import KIND_SAMPLE, KIND_SCHEMA, KIND_STATISTICS
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture
def local_mirror(tmp_path: Path) -> Path:
    return tmp_path / "local-mirror"


@pytest.fixture
def local_client(db_session, local_mirror: Path, auth_headers):
    from tests.conftest import AuthTestClient

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with (
        patch("app.core.config.settings.local_files_root", str(local_mirror)),
        TestClient(app) as client,
    ):
        yield AuthTestClient(client, auth_headers)
    app.dependency_overrides.clear()


def _device_service(db_session, local_mirror: Path) -> LocalDeviceService:
    return LocalDeviceService(
        db_session,
        BOOTSTRAP_USER_ID,
        LocalPathResolver(local_mirror),
    )


def _sync_service(db_session, local_mirror: Path, upload_root: Path) -> LocalFileSyncService:
    return LocalFileSyncService(
        db_session,
        BOOTSTRAP_USER_ID,
        LocalPathResolver(local_mirror),
        JobQueueService(db_session),
        upload_root=upload_root,
    )


def _mtime_iso(path: Path) -> str:
    stat = path.stat()
    return datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()


def test_register_device_and_root(local_mirror: Path, db_session) -> None:
    service = _device_service(db_session, local_mirror)
    device = service.register_device("laptop-1", "Work laptop")
    assert device.created
    root = service.register_root("laptop-1", "projects/alpha", default_policy=POLICY_METADATA_ONLY)
    assert root.created
    assert root.root_path == "projects/alpha"
    resolved = LocalPathResolver(local_mirror).resolve_root_path(
        BOOTSTRAP_USER_ID, "laptop-1", "projects/alpha"
    )
    assert resolved.is_dir()


def test_scan_registers_local_files_and_skips_unchanged_rescan(
    local_mirror: Path, db_session, tmp_path: Path
) -> None:
    upload_root = tmp_path / "uploads"
    device_service = _device_service(db_session, local_mirror)
    device_service.register_device("desk-1", "Desktop")
    root = device_service.register_root(
        "desk-1",
        "docs",
        default_policy=POLICY_INDEX_TEXT,
    )
    root_dir = LocalPathResolver(local_mirror).resolve_root_path(
        BOOTSTRAP_USER_ID, "desk-1", "docs"
    )
    note = root_dir / "notes.txt"
    note.write_text("local desktop notes content", encoding="utf-8")

    sync = _sync_service(db_session, local_mirror, upload_root)
    first = sync.scan_root(root.root_id)
    assert first.objects_created == 1
    assert first.ingest_jobs_enqueued == 1

    obj = db_session.scalar(
        select(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.provider == PROVIDER_LOCAL_DEVICE,
            Object.kind != "folder",
        )
    )
    assert obj is not None
    assert obj.canonical_uri.startswith("personal://device/desk-1/file/")
    assert obj.metadata_["local_relative_path"] == "notes.txt"

    second = sync.scan_root(root.root_id)
    assert second.objects_unchanged == 1
    assert second.ingest_jobs_enqueued == 0


def test_large_csv_local_file_produces_schema_and_sample(
    local_mirror: Path, db_session, tmp_path: Path
) -> None:
    upload_root = tmp_path / "uploads"
    device_service = _device_service(db_session, local_mirror)
    device_service.register_device("desk-2", "Desktop")
    root = device_service.register_root(
        "desk-2",
        "data",
        default_policy=POLICY_INDEX_TEXT,
    )
    root_dir = LocalPathResolver(local_mirror).resolve_root_path(
        BOOTSTRAP_USER_ID, "desk-2", "data"
    )
    csv_path = root_dir / "metrics.csv"
    rows = ["id,value"] + [f"{index},{index * 10}" for index in range(80)]
    csv_path.write_text("\n".join(rows), encoding="utf-8")

    sync = _sync_service(db_session, local_mirror, upload_root)
    result = sync.scan_root(root.root_id)
    assert result.objects_created == 1
    assert result.ingest_jobs_enqueued == 1

    job = db_session.scalar(
        select(Job).where(Job.type == JOB_TYPE_INGEST_LOCAL_FILE)
    )
    assert job is not None

    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch.object(
        db_session, "close", lambda: None
    ), patch(
        "app.core.config.settings.local_files_root", str(local_mirror)
    ):
        handle_ingest_local_file(
            db_session,
            None,
            job.payload,
            BOOTSTRAP_USER_ID,
        )

    obj = db_session.scalar(select(Object).where(Object.kind == "dataset"))
    assert obj is not None
    reps = db_session.scalars(
        select(Representation).where(Representation.object_id == obj.id)
    ).all()
    kinds = {rep.kind for rep in reps}
    assert KIND_SCHEMA in kinds
    assert KIND_SAMPLE in kinds
    assert KIND_STATISTICS in kinds
    assert obj.canonical_uri.startswith("personal://device/desk-2/file/")


def test_dataset_tools_query_columns(local_mirror: Path, db_session, tmp_path: Path) -> None:
    upload_root = tmp_path / "uploads"
    device_service = _device_service(db_session, local_mirror)
    device_service.register_device("desk-3", "Desktop")
    device_service.register_root("desk-3", "tables", default_policy=POLICY_METADATA_ONLY)
    root_dir = LocalPathResolver(local_mirror).resolve_root_path(
        BOOTSTRAP_USER_ID, "desk-3", "tables"
    )
    parquet_path = root_dir / "metrics.parquet"
    pq.write_table(pa.table({"name": ["a", "b", "c"], "value": [1, 2, 3]}), parquet_path)

    sync = _sync_service(db_session, local_mirror, upload_root)
    sync.report_files(
        "desk-3",
        "tables",
        [
            LocalFileReport(
                relative_path="metrics.parquet",
                size=parquet_path.stat().st_size,
                modified_at=_mtime_iso(parquet_path),
            )
        ],
    )
    obj = db_session.scalar(select(Object).where(Object.kind == "dataset"))
    assert obj is not None

    tools = DatasetToolService(
        db_session,
        BOOTSTRAP_USER_ID,
        LocalPathResolver(local_mirror),
        upload_root=upload_root,
    )
    schema = tools.get_schema(obj.id)
    assert "name" in schema["schema_text"]
    sample = tools.get_sample(obj.id, limit=2)
    assert sample["row_count_in_sample"] == 2
    stats = tools.get_basic_stats(obj.id)
    assert "rows:" in stats["statistics_text"]
    query = tools.query_columns(obj.id, ["name", "value"], limit=2)
    assert len(query["rows"]) == 2


def test_user_b_cannot_scan_or_read_other_user_root(
    local_mirror: Path, db_session, tmp_path: Path
) -> None:
    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="User B"))
    db_session.flush()

    service_a = _device_service(db_session, local_mirror)
    service_a.register_device("shared-device", "Shared")
    root = service_a.register_root("shared-device", "private", default_policy=POLICY_METADATA_ONLY)

    service_b = LocalDeviceService(db_session, user_b_id, LocalPathResolver(local_mirror))
    from app.services.errors import NotFoundError

    with pytest.raises(NotFoundError):
        service_b.get_root_for_user(root.root_id)

    sync_b = LocalFileSyncService(
        db_session,
        user_b_id,
        LocalPathResolver(local_mirror),
        JobQueueService(db_session),
        upload_root=tmp_path / "uploads-b",
    )
    with pytest.raises(NotFoundError):
        sync_b.scan_root(root.root_id)


def test_worker_rejects_other_user_local_ingest_job(db_session, local_mirror: Path) -> None:
    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="User B"))
    db_session.flush()

    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="document",
        title="secret.txt",
        origin="user",
        state="confirmed",
        provider=PROVIDER_LOCAL_DEVICE,
        external_id="device-a:docs/secret.txt",
        metadata_={
            "device_key": "device-a",
            "local_root_path": "docs",
            "local_relative_path": "secret.txt",
        },
    )
    db_session.add(obj)
    db_session.flush()

    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch.object(
        db_session, "close", lambda: None
    ), pytest.raises(ValueError, match="ownership mismatch"):
        handle_ingest_local_file(
            db_session,
            None,
            {
                "object_id": str(obj.id),
                "expected_revision": "rev",
                "expected_policy": POLICY_INDEX_TEXT,
            },
            user_b_id,
        )


def test_local_api_register_and_scan(local_client: TestClient, local_mirror: Path) -> None:
    device_resp = local_client.post(
        "/local/devices/register",
        json={"device_key": "api-device", "display_name": "API device"},
    )
    assert device_resp.status_code == 201

    root_resp = local_client.post(
        "/local/roots/register",
        json={
            "device_key": "api-device",
            "root_path": "workspace",
            "default_policy": POLICY_METADATA_ONLY,
        },
    )
    assert root_resp.status_code == 201
    root_id = root_resp.json()["root_id"]

    root_dir = LocalPathResolver(local_mirror).resolve_root_path(
        BOOTSTRAP_USER_ID, "api-device", "workspace"
    )
    (root_dir / "readme.md").write_text("# hello", encoding="utf-8")

    scan_resp = local_client.post(f"/local/roots/{root_id}/scan")
    assert scan_resp.status_code == 200
    body = scan_resp.json()
    assert body["objects_created"] == 1
    assert body["ingest_jobs_enqueued"] == 0


def test_same_device_different_roots_create_distinct_objects(
    local_mirror: Path, db_session, tmp_path: Path
) -> None:
    upload_root = tmp_path / "uploads"
    device_service = _device_service(db_session, local_mirror)
    device_service.register_device("desk-4", "Desktop")
    root_a = device_service.register_root("desk-4", "root-a", default_policy=POLICY_METADATA_ONLY)
    root_b = device_service.register_root("desk-4", "root-b", default_policy=POLICY_METADATA_ONLY)

    dir_a = LocalPathResolver(local_mirror).resolve_root_path(BOOTSTRAP_USER_ID, "desk-4", "root-a")
    dir_b = LocalPathResolver(local_mirror).resolve_root_path(BOOTSTRAP_USER_ID, "desk-4", "root-b")
    (dir_a / "readme.md").write_text("root a", encoding="utf-8")
    (dir_b / "readme.md").write_text("root b", encoding="utf-8")

    sync = _sync_service(db_session, local_mirror, upload_root)
    sync.scan_root(root_a.root_id)
    sync.scan_root(root_b.root_id)

    objs = db_session.scalars(select(Object).where(Object.provider == PROVIDER_LOCAL_DEVICE)).all()
    file_objs = [obj for obj in objs if obj.kind != "folder"]
    assert len(file_objs) == 2
    external_ids = {obj.external_id for obj in file_objs}
    assert external_ids == {"desk-4:root-a/readme.md", "desk-4:root-b/readme.md"}


def test_policy_change_to_index_text_enqueues_single_ingest(
    local_mirror: Path, db_session, tmp_path: Path
) -> None:
    upload_root = tmp_path / "uploads"
    device_service = _device_service(db_session, local_mirror)
    device_service.register_device("policy-device", "Desktop")
    device_service.register_root(
        "policy-device", "docs", default_policy=POLICY_METADATA_ONLY
    )
    root_dir = LocalPathResolver(local_mirror).resolve_root_path(
        BOOTSTRAP_USER_ID, "policy-device", "docs"
    )
    note = root_dir / "note.txt"
    note.write_text("policy change content", encoding="utf-8")
    mtime = _mtime_iso(note)

    sync = _sync_service(db_session, local_mirror, upload_root)
    first = sync.report_files(
        "policy-device",
        "docs",
        [
            LocalFileReport(
                relative_path="note.txt",
                size=note.stat().st_size,
                modified_at=mtime,
            )
        ],
    )
    assert first.ingest_jobs_enqueued == 0

    second = sync.report_files(
        "policy-device",
        "docs",
        [
            LocalFileReport(
                relative_path="note.txt",
                size=note.stat().st_size,
                modified_at=mtime,
                policy=POLICY_INDEX_TEXT,
            )
        ],
    )
    assert second.ingest_jobs_enqueued == 1

    jobs = db_session.scalars(
        select(Job).where(Job.type == JOB_TYPE_INGEST_LOCAL_FILE)
    ).all()
    assert len(jobs) == 1

    obj = db_session.scalar(
        select(Object).where(
            Object.provider == PROVIDER_LOCAL_DEVICE,
            Object.kind != "folder",
        )
    )
    assert obj is not None
    payload = jobs[0].payload
    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch.object(
        db_session, "close", lambda: None
    ), patch("app.core.config.settings.local_files_root", str(local_mirror)):
        handle_ingest_local_file(db_session, None, payload, BOOTSTRAP_USER_ID)
        handle_ingest_local_file(db_session, None, payload, BOOTSTRAP_USER_ID)

    summarize_jobs = db_session.scalars(
        select(Job).where(Job.type == JOB_TYPE_SUMMARIZE_RESOURCE)
    ).all()
    assert len(summarize_jobs) == 1


def test_large_csv_stats_are_bounded_and_marked_sampled(
    local_mirror: Path, db_session, tmp_path: Path
) -> None:
    from app.local.constants import MAX_CSV_STATS_SAMPLE_ROWS
    from app.services.representation_service import KIND_STATISTICS

    upload_root = tmp_path / "uploads"
    device_service = _device_service(db_session, local_mirror)
    device_service.register_device("big-csv", "Desktop")
    root = device_service.register_root("big-csv", "data", default_policy=POLICY_INDEX_TEXT)
    root_dir = LocalPathResolver(local_mirror).resolve_root_path(
        BOOTSTRAP_USER_ID, "big-csv", "data"
    )
    csv_path = root_dir / "big.csv"
    rows = ["id,value"] + [f"{i},{i}" for i in range(MAX_CSV_STATS_SAMPLE_ROWS + 500)]
    csv_path.write_text("\n".join(rows), encoding="utf-8")

    sync = _sync_service(db_session, local_mirror, upload_root)
    sync.scan_root(root.root_id)
    job = db_session.scalar(select(Job).where(Job.type == JOB_TYPE_INGEST_LOCAL_FILE))
    assert job is not None

    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch.object(
        db_session, "close", lambda: None
    ), patch("app.core.config.settings.local_files_root", str(local_mirror)):
        handle_ingest_local_file(db_session, None, job.payload, BOOTSTRAP_USER_ID)

    obj = db_session.scalar(select(Object).where(Object.kind == "dataset"))
    assert obj is not None
    stats = db_session.scalar(
        select(Representation).where(
            Representation.object_id == obj.id,
            Representation.kind == KIND_STATISTICS,
        )
    )
    assert stats is not None
    assert stats.metadata_["stats_truncated"] is True


def test_malicious_upload_path_rejected_for_dataset_tools(
    db_session, tmp_path: Path, local_mirror: Path
) -> None:
    upload_root = tmp_path / "uploads"
    evil = tmp_path / "evil.csv"
    evil.write_text("a\n1", encoding="utf-8")

    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="dataset",
        title="evil",
        origin="user",
        state="confirmed",
        metadata_={"upload_path": str(evil)},
    )
    db_session.add(obj)
    db_session.flush()

    tools = DatasetToolService(
        db_session,
        BOOTSTRAP_USER_ID,
        LocalPathResolver(local_mirror),
        upload_root=upload_root,
    )
    from app.local.errors import LocalAccessError

    with pytest.raises(LocalAccessError):
        tools.get_schema(obj.id)


def test_large_upload_copy_streams_full_hash_and_updates_revision(
    local_mirror: Path, db_session, tmp_path: Path
) -> None:
    upload_root = tmp_path / "uploads"
    device_service = _device_service(db_session, local_mirror)
    device_service.register_device("upload-big", "Desktop")
    root = device_service.register_root(
        "upload-big", "files", default_policy=POLICY_UPLOAD_COPY
    )
    root_dir = LocalPathResolver(local_mirror).resolve_root_path(
        BOOTSTRAP_USER_ID, "upload-big", "files"
    )
    blob = root_dir / "blob.txt"
    revision_a = b"A" * (CHEAP_HASH_MAX_BYTES + 5000)
    blob.write_bytes(revision_a)

    sync = _sync_service(db_session, local_mirror, upload_root)
    first = sync.scan_root(root.root_id)
    assert first.objects_created == 1
    assert first.ingest_jobs_enqueued == 1

    job = db_session.scalar(select(Job).where(Job.type == JOB_TYPE_INGEST_LOCAL_FILE))
    assert job is not None

    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch.object(
        db_session, "close", lambda: None
    ), patch("app.core.config.settings.local_files_root", str(local_mirror)), patch(
        "app.core.config.settings.resource_upload_root", str(upload_root)
    ):
        handle_ingest_local_file(db_session, None, job.payload, BOOTSTRAP_USER_ID)

    obj = db_session.scalar(
        select(Object).where(
            Object.provider == PROVIDER_LOCAL_DEVICE,
            Object.kind != "folder",
        )
    )
    assert obj is not None
    revision_a_sig = obj.metadata_["content_revision"]
    upload_path = Path(obj.metadata_["upload_path"])
    assert upload_path.read_bytes() == revision_a
    assert obj.metadata_["content_hash"] == hashlib.sha256(revision_a).hexdigest()
    assert obj.metadata_[CONTENT_INGESTED_REVISION_KEY] == revision_a_sig

    revision_b = b"B" * (CHEAP_HASH_MAX_BYTES + 5000)
    blob.write_bytes(revision_b)
    second = sync.scan_root(root.root_id)
    assert second.objects_updated == 1
    assert second.ingest_jobs_enqueued == 1

    job_b = db_session.scalars(
        select(Job).where(Job.type == JOB_TYPE_INGEST_LOCAL_FILE)
    ).all()
    assert len(job_b) == 2
    payload_b = job_b[-1].payload

    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch.object(
        db_session, "close", lambda: None
    ), patch("app.core.config.settings.local_files_root", str(local_mirror)), patch(
        "app.core.config.settings.resource_upload_root", str(upload_root)
    ):
        handle_ingest_local_file(db_session, None, payload_b, BOOTSTRAP_USER_ID)

    db_session.refresh(obj)
    revision_b_sig = obj.metadata_["content_revision"]
    upload_path_b = Path(obj.metadata_["upload_path"])
    assert upload_path_b.read_bytes() == revision_b
    assert obj.metadata_["content_hash"] == hashlib.sha256(revision_b).hexdigest()
    assert obj.metadata_[CONTENT_INGESTED_REVISION_KEY] == revision_b_sig
    assert upload_path_b != upload_path or revision_a_sig != revision_b_sig

    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch.object(
        db_session, "close", lambda: None
    ), patch("app.core.config.settings.local_files_root", str(local_mirror)), patch(
        "app.core.config.settings.resource_upload_root", str(upload_root)
    ):
        handle_ingest_local_file(db_session, None, payload_b, BOOTSTRAP_USER_ID)

    db_session.refresh(obj)
    assert Path(obj.metadata_["upload_path"]).read_bytes() == revision_b


def test_stale_ingest_job_skips_representations_and_embed(
    local_mirror: Path, db_session, tmp_path: Path
) -> None:
    upload_root = tmp_path / "uploads"
    device_service = _device_service(db_session, local_mirror)
    device_service.register_device("stale-ingest", "Desktop")
    root = device_service.register_root(
        "stale-ingest", "docs", default_policy=POLICY_UPLOAD_COPY
    )
    root_dir = LocalPathResolver(local_mirror).resolve_root_path(
        BOOTSTRAP_USER_ID, "stale-ingest", "docs"
    )
    note = root_dir / "note.txt"
    note.write_text("revision A", encoding="utf-8")

    sync = _sync_service(db_session, local_mirror, upload_root)
    sync.scan_root(root.root_id)
    obj = db_session.scalar(
        select(Object).where(
            Object.provider == PROVIDER_LOCAL_DEVICE,
            Object.kind != "folder",
        )
    )
    assert obj is not None
    revision_a = obj.metadata_["content_revision"]
    payload = {
        "object_id": str(obj.id),
        "expected_revision": revision_a,
        "expected_policy": POLICY_UPLOAD_COPY,
    }

    note.write_text("revision B content", encoding="utf-8")
    meta_b = {
        key: obj.metadata_[key]
        for key in REVISION_METADATA_KEYS
        if key in obj.metadata_
    }
    meta_b["size"] = note.stat().st_size
    meta_b["modified_at"] = _mtime_iso(note)
    meta_b.pop("content_hash", None)
    revision_b = _revision_signature(meta_b)

    real_copy = copy_local_file_to_upload

    def copy_and_mutate_revision(*args, **kwargs):
        merged = dict(obj.metadata_ or {})
        merged["content_revision"] = revision_b
        obj.metadata_ = merged
        db_session.flush()
        return real_copy(*args, **kwargs)

    reps_before = len(
        db_session.scalars(
            select(Representation).where(Representation.object_id == obj.id)
        ).all()
    )

    object_id = obj.id

    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch.object(
        db_session, "close", lambda: None
    ), patch("app.core.config.settings.local_files_root", str(local_mirror)), patch(
        "app.core.config.settings.resource_upload_root", str(upload_root)
    ), patch(
        "app.jobs.handlers.copy_local_file_to_upload", copy_and_mutate_revision
    ):
        handle_ingest_local_file(db_session, None, payload, BOOTSTRAP_USER_ID)

    reps_after = len(
        db_session.scalars(
            select(Representation).where(Representation.object_id == object_id)
        ).all()
    )
    summarize_jobs = db_session.scalars(
        select(Job).where(Job.type == JOB_TYPE_SUMMARIZE_RESOURCE)
    ).all()

    obj = db_session.scalar(select(Object).where(Object.id == object_id))
    assert obj is not None
    assert reps_after == reps_before
    assert len(summarize_jobs) == 0
    assert obj.metadata_.get(CONTENT_INGESTED_REVISION_KEY) != revision_a
    assert obj.metadata_.get(CONTENT_INGESTED_REVISION_KEY) != revision_b
