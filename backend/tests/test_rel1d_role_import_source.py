import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.api.schemas import ResourceRegisterRequest
from app.db.models import Object, Representation
from app.resources.constants import PROVIDER_UPLOAD
from app.services.errors import NotFoundError, ValidationError
from app.services.job_queue_service import JobQueueService
from app.services.person_role_import_source_service import (
    ROLE_IMPORT_MAX_SOURCE_TEXT_CHARS,
    PersonRoleImportSourceService,
)
from app.services.provenance import REJECTED_STATE
from app.services.representation_service import KIND_CHUNK, KIND_FULL
from app.services.resource_registration_service import ResourceRegistrationService
from app.users.bootstrap import BOOTSTRAP_USER_ID

PNG = b"\x89PNG\r\n\x1a\nunique-png"
JPEG = b"\xff\xd8\xffunique-jpeg"
WEBP = b"RIFF\x18\x00\x00\x00WEBPunique-webp"


def _service(db_session, upload_root: Path) -> ResourceRegistrationService:
    upload_root.mkdir(parents=True, exist_ok=True)
    return ResourceRegistrationService(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        job_queue=JobQueueService(db_session),
        upload_root=upload_root,
    )


def _sources(db_session, upload_root: Path, user_id=BOOTSTRAP_USER_ID) -> PersonRoleImportSourceService:
    return PersonRoleImportSourceService(db_session, user_id, upload_root)


def _staged(path: Path, data: bytes, filename: str):
    from app.resources.upload_staging import StagedUpload

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return StagedUpload(
        path=path,
        content_hash=hashlib.sha256(data).hexdigest(),
        original_filename=filename,
        size=len(data),
    )


def _register_raster(db_session, upload_root: Path, filename: str, data: bytes, *, ingest: bool):
    staged = _staged(upload_root / "staging" / filename, data, filename)
    return _service(db_session, upload_root).register(
        ResourceRegisterRequest(kind="file", title=filename, ingest_content=ingest),
        staged_upload=staged,
    )


class _FakeUpload:
    def __init__(self, data: bytes, filename: str) -> None:
        self._data = data
        self.filename = filename
        self._done = False

    async def read(self, size: int = -1) -> bytes:
        if self._done:
            return b""
        self._done = True
        return self._data


def _stage(tmp_path: Path, data: bytes, filename: str):
    from app.resources.upload_staging import stage_upload_file

    return asyncio.run(stage_upload_file(_FakeUpload(data, filename), tmp_path / "stage"))


@pytest.mark.parametrize(
    ("filename", "data"),
    [("shot.png", PNG), ("shot.jpg", JPEG), ("shot.jpeg", JPEG), ("shot.webp", WEBP)],
)
def test_raster_formats_register_without_ingest(db_session, tmp_path, filename, data) -> None:
    result = _register_raster(db_session, tmp_path / "uploads", filename, data, ingest=False)
    obj = db_session.get(Object, result.object_id)
    assert obj.provider == PROVIDER_UPLOAD
    assert result.representations_created == 0
    stored = Path(obj.metadata_["upload_path"])
    assert stored.is_file()
    assert str(BOOTSTRAP_USER_ID) in stored.parts
    assert str(obj.id) in stored.parts
    assert stored.read_bytes() == data
    loaded = _sources(db_session, tmp_path / "uploads").load(obj.id)
    assert loaded.source_kind == "image"
    assert loaded.source_revision == hashlib.sha256(data).hexdigest()
    assert loaded.image_bytes == data


def test_renamed_arbitrary_bytes_are_rejected(tmp_path) -> None:
    with pytest.raises(ValidationError, match="do not match the image format"):
        _stage(tmp_path, b"not-an-image", "renamed.png")


@pytest.mark.parametrize("filename", ["icon.svg", "anim.gif", "scan.bmp", "photo.heic"])
def test_unsupported_rasters_are_rejected(tmp_path, filename) -> None:
    with pytest.raises(ValidationError, match="unsupported upload format"):
        _stage(tmp_path, PNG, filename)


def test_raster_ingest_content_true_is_rejected(db_session, tmp_path) -> None:
    before = db_session.scalar(select(func.count()).select_from(Object))
    with pytest.raises(ValidationError, match="ingest_content=false"):
        _register_raster(db_session, tmp_path / "uploads", "shot.png", PNG, ingest=True)
    after = db_session.scalar(select(func.count()).select_from(Object))
    assert before == after


def test_text_upload_still_indexes(db_session, tmp_path) -> None:
    data = b"plain text source"
    staged = _staged(tmp_path / "uploads" / "staging" / "note.txt", data, "note.txt")
    result = _service(db_session, tmp_path / "uploads").register(
        ResourceRegisterRequest(kind="file", title="note.txt", ingest_content=True),
        staged_upload=staged,
    )
    rows = db_session.scalars(
        select(Representation).where(Representation.object_id == result.object_id)
    ).all()
    assert rows
    assert any(row.text and "plain text source" in row.text for row in rows)


def test_hash_mismatch_is_rejected(db_session, tmp_path) -> None:
    upload_root = tmp_path / "uploads"
    result = _register_raster(db_session, upload_root, "shot.png", PNG, ingest=False)
    obj = db_session.get(Object, result.object_id)
    metadata = dict(obj.metadata_)
    metadata["content_hash"] = "0" * 64
    obj.metadata_ = metadata
    db_session.flush()
    with pytest.raises(ValidationError, match="failed content check"):
        _sources(db_session, upload_root).load(obj.id)


def test_cross_user_hidden_and_rejected_fail_closed(db_session, tmp_path) -> None:
    upload_root = tmp_path / "uploads"
    result = _register_raster(db_session, upload_root, "shot.png", PNG, ingest=False)
    other_id = uuid4()
    from app.db.models import User

    db_session.add(User(id=other_id, display_name="Other"))
    db_session.flush()
    with pytest.raises(NotFoundError):
        _sources(db_session, upload_root, other_id).load(result.object_id)

    obj = db_session.get(Object, result.object_id)
    obj.deleted_at = datetime.now(UTC)
    db_session.flush()
    with pytest.raises(NotFoundError):
        _sources(db_session, upload_root).load(obj.id)

    obj.deleted_at = None
    obj.state = REJECTED_STATE
    db_session.flush()
    with pytest.raises(NotFoundError):
        _sources(db_session, upload_root).load(obj.id)


def test_forged_upload_path_is_rejected(db_session, tmp_path) -> None:
    upload_root = tmp_path / "uploads"
    result = _register_raster(db_session, upload_root, "shot.png", PNG, ingest=False)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"OUTSIDE-SECRET")
    obj = db_session.get(Object, result.object_id)
    metadata = dict(obj.metadata_)
    metadata["upload_path"] = str(outside)
    obj.metadata_ = metadata
    db_session.flush()
    with pytest.raises(ValidationError, match="not available") as caught:
        _sources(db_session, upload_root).load(obj.id)
    assert "OUTSIDE-SECRET" not in str(caught.value)
    assert str(outside) not in str(caught.value)


def test_missing_upload_file_is_rejected(db_session, tmp_path) -> None:
    upload_root = tmp_path / "uploads"
    result = _register_raster(db_session, upload_root, "shot.png", PNG, ingest=False)
    obj = db_session.get(Object, result.object_id)
    Path(obj.metadata_["upload_path"]).unlink()
    with pytest.raises(ValidationError, match="not available") as caught:
        _sources(db_session, upload_root).load(obj.id)
    assert "upload_path" not in str(caught.value)


def test_suffix_magic_mismatch_is_rejected(db_session, tmp_path) -> None:
    upload_root = tmp_path / "uploads"
    result = _register_raster(db_session, upload_root, "shot.png", PNG, ingest=False)
    obj = db_session.get(Object, result.object_id)
    stored = Path(obj.metadata_["upload_path"])
    stored.write_bytes(JPEG)
    metadata = dict(obj.metadata_)
    metadata["content_hash"] = hashlib.sha256(JPEG).hexdigest()
    obj.metadata_ = metadata
    db_session.flush()
    with pytest.raises(ValidationError, match="failed content check"):
        _sources(db_session, upload_root).load(obj.id)


def test_client_path_metadata_is_never_read(db_session, tmp_path) -> None:
    upload_root = tmp_path / "uploads"
    result = _register_raster(db_session, upload_root, "shot.png", PNG, ingest=False)
    secret = tmp_path / "client-secret.png"
    secret.write_bytes(b"CLIENT-SECRET-BYTES")
    missing = tmp_path / "missing-client.png"
    obj = db_session.get(Object, result.object_id)
    metadata = dict(obj.metadata_)
    metadata["client_absolute_path"] = str(missing)
    metadata["client_source_path"] = str(secret)
    metadata["local_path_metadata"] = {"path": str(secret)}
    obj.metadata_ = metadata
    db_session.flush()
    loaded = _sources(db_session, upload_root).load(obj.id)
    assert loaded.image_bytes == PNG
    assert b"CLIENT-SECRET-BYTES" not in loaded.image_bytes


def test_text_prefers_full_representation(db_session, tmp_path) -> None:
    obj = _text_object(db_session, "BODY ONLY")
    db_session.add(Representation(object_id=obj.id, kind=KIND_FULL, part_index=0, text="FULL TEXT"))
    db_session.add(Representation(object_id=obj.id, kind=KIND_CHUNK, part_index=0, text="CHUNK"))
    db_session.flush()
    loaded = _sources(db_session, tmp_path).load(obj.id)
    assert loaded.text == "FULL TEXT"
    assert loaded.source_kind == "text"


def test_chunks_are_ordered_and_bounded(db_session, tmp_path) -> None:
    obj = _text_object(db_session, None)
    db_session.add(Representation(object_id=obj.id, kind=KIND_CHUNK, part_index=2, text="c2"))
    db_session.add(Representation(object_id=obj.id, kind=KIND_CHUNK, part_index=0, text="c0"))
    db_session.add(Representation(object_id=obj.id, kind=KIND_CHUNK, part_index=1, text="c1"))
    db_session.flush()
    loaded = _sources(db_session, tmp_path).load(obj.id)
    assert loaded.text == "c0\nc1\nc2"
    assert loaded.source_truncated is False


def test_clipping_sets_source_truncated(db_session, tmp_path) -> None:
    body = "я" * (ROLE_IMPORT_MAX_SOURCE_TEXT_CHARS + 5)
    obj = _text_object(db_session, body)
    loaded = _sources(db_session, tmp_path).load(obj.id)
    assert loaded.source_truncated is True
    assert loaded.text == body[:ROLE_IMPORT_MAX_SOURCE_TEXT_CHARS]
    assert loaded.source_revision == hashlib.sha256(loaded.text.encode("utf-8")).hexdigest()


def test_revision_is_stable_and_changes_with_input(db_session, tmp_path) -> None:
    obj = _text_object(db_session, "Анна — директор")
    first = _sources(db_session, tmp_path).load(obj.id)
    second = _sources(db_session, tmp_path).load(obj.id)
    assert first.source_revision == second.source_revision
    obj.body = "Анна — секретарь"
    db_session.flush()
    changed = _sources(db_session, tmp_path).load(obj.id)
    assert changed.source_revision != first.source_revision


def test_text_source_does_not_fetch(db_session, tmp_path, monkeypatch) -> None:
    def _forbid(*_args, **_kwargs):
        raise AssertionError("source materialization attempted a fetch")

    monkeypatch.setattr("urllib.request.urlopen", _forbid)
    obj = _text_object(db_session, "stored body")
    obj.canonical_uri = "https://example.invalid/secret"
    db_session.flush()
    loaded = _sources(db_session, tmp_path).load(obj.id)
    assert loaded.text == "stored body"


def test_missing_stored_text_is_unsupported(db_session, tmp_path) -> None:
    obj = _text_object(db_session, None)
    with pytest.raises(ValidationError, match="no stored text"):
        _sources(db_session, tmp_path).load(obj.id)


def _text_object(db_session, body: str | None) -> Object:
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="document",
        title="notes",
        body=body,
        origin="user",
        state="confirmed",
        metadata_={},
    )
    db_session.add(obj)
    db_session.flush()
    return obj
