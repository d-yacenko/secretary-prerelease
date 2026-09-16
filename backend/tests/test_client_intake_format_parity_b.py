"""Format Parity Pass B client-intake contract regressions."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db, get_embedding_service
from app.db.models import Object, Representation
from app.jobs.constants import JOB_TYPE_SUMMARIZE_RESOURCE
from app.llm.embedding_service import FakeEmbeddingService
from app.local.client_paths import compute_client_content_revision
from app.main import app
from app.services.client_intake_constants import (
    DATASET_FILE_SUFFIXES,
    DOCUMENT_FILE_SUFFIXES,
    LEGACY_METADATA_ONLY_SUFFIXES,
)
from app.services.client_representation_service import ClientRepresentationValidator


@pytest.fixture
def parity_client(db_session, auth_headers, tmp_path: Path):
    from tests.conftest import apply_embedding_service_overrides, AuthTestClient

    local_mirror = tmp_path / "local-mirror"
    local_mirror.mkdir()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(FakeEmbeddingService())
    with (
        patch("app.core.config.settings.local_files_root", str(local_mirror)),
        TestClient(app) as client,
    ):
        yield AuthTestClient(client, auth_headers)
    app.dependency_overrides.clear()


def _register_device(client, device_key: str = "desk-parity-b") -> None:
    resp = client.post(
        "/local/devices/register",
        json={"device_key": device_key, "display_name": "Parity B desktop"},
    )
    assert resp.status_code == 201


def _revision(source_path: str, size: int, modified_at: str) -> str:
    return compute_client_content_revision(source_path, size, modified_at, None)


def _intake(
    client,
    *,
    filename: str,
    representations: list[dict],
    metadata_only: bool = False,
    source_path: str | None = None,
):
    source_path = source_path or f"/home/user/{filename}"
    payload = {
        "device_key": "desk-parity-b",
        "source_path": source_path,
        "filename": filename,
        "size": 2048,
        "modified_at": "2026-01-01T10:00:00Z",
        "content_revision": _revision(source_path, 2048, "2026-01-01T10:00:00Z"),
        "representations": representations,
        "metadata_only": metadata_only,
    }
    return client.post("/local/files/client-intake", json=payload)


def _russian_txt_payload() -> list[dict]:
    text = "Привет, это обычный русский текст. " * 60
    assert len(text.encode("utf-8")) < 16 * 1024
    return [{"kind": "full", "text": text}]


@pytest.mark.parametrize(
    "suffix",
    sorted(DOCUMENT_FILE_SUFFIXES),
)
def test_document_like_full_chunk_accepted(parity_client, suffix: str) -> None:
    _register_device(parity_client)
    filename = f"sample{suffix}"
    full = _intake(
        parity_client,
        filename=filename,
        representations=[{"kind": "full", "text": "document body"}],
    )
    assert full.status_code == 201, full.text
    chunk = _intake(
        parity_client,
        filename=filename,
        source_path=f"/home/user/chunk{suffix}",
        representations=[
            {"kind": "chunk", "text": "part a", "part_index": 0, "metadata": {"source_chunk_index": 0}},
            {"kind": "chunk", "text": "part b", "part_index": 1, "metadata": {"source_chunk_index": 1}},
        ],
    )
    assert chunk.status_code == 201, chunk.text


@pytest.mark.parametrize(
    "suffix",
    sorted(DATASET_FILE_SUFFIXES),
)
def test_dataset_like_structural_and_chunk_accepted(parity_client, suffix: str) -> None:
    _register_device(parity_client)
    filename = f"data{suffix}"
    reps = [
        {"kind": "schema", "text": "schema\ncolumns: a:string"},
        {"kind": "sample", "text": "sample\na\n1", "metadata": {"row_count_in_sample": 1, "compact_preview": True}},
        {
            "kind": "statistics",
            "text": "rows: 1",
            "metadata": {
                "row_count": 1,
                "rows_sampled": 1,
                "column_count": 1,
                "stats_truncated": False,
            },
        },
        {"kind": "full", "text": "a\n1"},
        {"kind": "chunk", "text": "[row=1]\n1", "part_index": 0, "metadata": {"source_chunk_index": 0}},
        {"kind": "chunk", "text": "[row=2]\n2", "part_index": 1, "metadata": {"source_chunk_index": 1}},
    ]
    resp = _intake(parity_client, filename=filename, representations=reps)
    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize("suffix", sorted(LEGACY_METADATA_ONLY_SUFFIXES))
def test_legacy_suffix_rejects_representations(parity_client, suffix: str) -> None:
    _register_device(parity_client)
    resp = _intake(
        parity_client,
        filename=f"legacy{suffix}",
        representations=[{"kind": "full", "text": "legacy"}],
    )
    assert resp.status_code == 422


def test_russian_txt_intake_accepted(parity_client, db_session) -> None:
    _register_device(parity_client)
    reps = _russian_txt_payload()
    text = reps[0]["text"]
    resp = _intake(
        parity_client,
        filename="notes.txt",
        representations=reps,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["metadata_only"] is False
    assert body["representations_created"] >= 1
    obj = db_session.scalar(select(Object).where(Object.id == body["object_id"]))
    assert obj is not None
    assert obj.kind == "document"
    stored = db_session.scalars(
        select(Representation).where(Representation.object_id == body["object_id"])
    ).all()
    assert stored
    assert text in stored[0].text


def test_truncated_txt_metadata_accepted(parity_client) -> None:
    _register_device(parity_client)
    resp = _intake(
        parity_client,
        filename="large.txt",
        representations=[
            {
                "kind": "chunk",
                "text": "x" * 1000,
                "part_index": 0,
                "metadata": {"truncated": True, "source_chunk_index": 0},
            }
        ],
    )
    assert resp.status_code == 201, resp.text


def test_truncated_false_metadata_accepted(parity_client) -> None:
    _register_device(parity_client)
    resp = _intake(
        parity_client,
        filename="small.txt",
        representations=[
            {"kind": "full", "text": "ok", "metadata": {"truncated": False}},
        ],
    )
    assert resp.status_code == 201


def test_indexed_unknown_bin_requires_metadata_only(parity_client) -> None:
    _register_device(parity_client)
    resp = _intake(
        parity_client,
        filename="data.bin",
        source_path="/home/user/data.bin",
        representations=[],
        metadata_only=False,
    )
    assert resp.status_code == 422
    assert "metadata_only" in resp.json()["detail"].lower()


def test_unknown_metadata_key_rejected(parity_client) -> None:
    _register_device(parity_client)
    resp = _intake(
        parity_client,
        filename="notes.txt",
        representations=[
            {"kind": "full", "text": "ok", "metadata": {"columns": [{"name": "a"}]}},
        ],
    )
    assert resp.status_code == 422
    assert "columns" in resp.json()["detail"]


def test_dataset_duplicate_schema_rejected(parity_client) -> None:
    _register_device(parity_client)
    reps = [
        {"kind": "schema", "text": "schema a"},
        {"kind": "schema", "text": "schema b"},
        {"kind": "sample", "text": "sample"},
        {"kind": "statistics", "text": "stats"},
    ]
    resp = _intake(parity_client, filename="dup.csv", representations=reps)
    assert resp.status_code == 422


def test_dataset_duplicate_sample_rejected(parity_client) -> None:
    _register_device(parity_client)
    reps = [
        {"kind": "schema", "text": "schema"},
        {"kind": "sample", "text": "sample a"},
        {"kind": "sample", "text": "sample b"},
        {"kind": "statistics", "text": "stats"},
    ]
    resp = _intake(parity_client, filename="dup-sample.csv", representations=reps)
    assert resp.status_code == 422


def test_dataset_duplicate_full_rejected(parity_client) -> None:
    _register_device(parity_client)
    reps = [
        {"kind": "schema", "text": "schema"},
        {"kind": "sample", "text": "sample"},
        {"kind": "statistics", "text": "stats"},
        {"kind": "full", "text": "a"},
        {"kind": "full", "text": "b"},
    ]
    resp = _intake(parity_client, filename="dup-full.csv", representations=reps)
    assert resp.status_code == 422


def test_validator_normalizes_sampled_row_indices() -> None:
    validator = ClientRepresentationValidator()
    normalized = validator.validate_payload(
        "data.csv",
        [
            {
                "kind": "chunk",
                "text": "row",
                "metadata": {
                    "sampled_row_indices": [3, 1, 1, 2],
                    "dataset_row_count": 10,
                    "dataset_rows_represented": 3,
                    "dataset_sampling_mode": "distributed",
                    "dataset_sampling_truncated": True,
                },
            }
        ],
        metadata_only=False,
    )
    assert normalized[0]["metadata"]["sampled_row_indices"] == [1, 2, 3]


def test_txt_schema_kind_rejected(parity_client) -> None:
    _register_device(parity_client)
    resp = _intake(
        parity_client,
        filename="notes.txt",
        representations=[{"kind": "schema", "text": "columns: a"}],
    )
    assert resp.status_code == 422
