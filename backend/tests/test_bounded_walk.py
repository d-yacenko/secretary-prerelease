from pathlib import Path
from unittest.mock import patch

import pytest

from app.local.constants import (
    MAX_SCAN_INSPECTION_ITEMS,
    MAX_SCAN_SUPPORTED_ITEMS,
    SUPPORTED_LOCAL_SUFFIXES,
)
from app.local.paths import LocalPathResolver
from app.services.job_queue_service import JobQueueService
from app.services.local_device_service import LocalDeviceService
from app.services.local_file_sync_service import (
    LocalFileSyncService,
    bounded_supported_walk,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture
def local_mirror(tmp_path: Path) -> Path:
    return tmp_path / "local-mirror"


def _walk(
    root_dir: Path,
    max_inspections: int = MAX_SCAN_INSPECTION_ITEMS,
    max_supported: int = MAX_SCAN_SUPPORTED_ITEMS,
) -> tuple[list[Path], bool]:
    result = bounded_supported_walk(
        root_dir,
        max_depth=8,
        max_supported=max_supported,
        max_inspections=max_inspections,
    )
    return result.paths, result.truncated


def test_bounded_walk_runs_without_pathlib_follow_symlinks_kwarg(tmp_path: Path) -> None:
    """Regression: Path.is_dir(follow_symlinks=...) is not valid on Python 3.12."""
    root_dir = tmp_path / "walk-root"
    root_dir.mkdir()
    (root_dir / "sample.txt").write_text("ok", encoding="utf-8")
    paths, truncated = _walk(root_dir)
    assert len(paths) == 1
    assert truncated is False


def test_exactly_max_supported_files_not_truncated(tmp_path: Path) -> None:
    root_dir = tmp_path / "exact-cap"
    root_dir.mkdir()
    cap = 3
    for index in range(cap):
        (root_dir / f"file-{index}.txt").write_text(f"text-{index}", encoding="utf-8")

    paths, truncated = _walk(root_dir, max_supported=cap)
    assert len(paths) == cap
    assert truncated is False


def test_max_supported_plus_one_is_truncated(tmp_path: Path) -> None:
    root_dir = tmp_path / "over-cap"
    root_dir.mkdir()
    cap = 3
    for index in range(cap + 1):
        (root_dir / f"file-{index}.txt").write_text(f"text-{index}", encoding="utf-8")

    paths, truncated = _walk(root_dir, max_supported=cap)
    assert len(paths) == cap
    assert truncated is True


def test_symlink_file_outside_root_not_registered(
    tmp_path: Path, db_session, local_mirror: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside-secret", encoding="utf-8")

    resolver = LocalPathResolver(local_mirror)
    device_service = LocalDeviceService(db_session, BOOTSTRAP_USER_ID, resolver)
    device_service.register_device("symlink-file", "Desktop")
    root = device_service.register_root("symlink-file", "docs")
    root_dir = resolver.resolve_root_path(BOOTSTRAP_USER_ID, "symlink-file", "docs")
    (root_dir / "link.txt").symlink_to(outside)

    paths, truncated = _walk(root_dir)
    assert paths == []
    assert truncated is False

    sync = LocalFileSyncService(
        db_session,
        BOOTSTRAP_USER_ID,
        resolver,
        JobQueueService(db_session),
        upload_root=tmp_path / "uploads",
    )
    result = sync.scan_root(root.root_id)
    assert result.objects_created == 0
    assert result.items_truncated is False


def test_symlink_directory_outside_root_not_traversed(tmp_path: Path) -> None:
    mirror = tmp_path / "mirror"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "hidden.txt").write_text("hidden", encoding="utf-8")

    resolver = LocalPathResolver(mirror)
    device_root = resolver.device_mirror_root(BOOTSTRAP_USER_ID, "symlink-dir")
    device_root.mkdir(parents=True)
    root_dir = device_root / "docs"
    root_dir.mkdir()
    (root_dir / "escape").symlink_to(outside_dir, target_is_directory=True)

    paths, truncated = _walk(root_dir)
    assert paths == []
    assert truncated is False


def test_inspection_cap_stops_large_directory(tmp_path: Path) -> None:
    root_dir = tmp_path / "big-dir"
    root_dir.mkdir()
    for index in range(12):
        (root_dir / f"entry-{index:02d}.bin").write_bytes(b"x")

    cap = 5
    paths, truncated = _walk(root_dir, max_inspections=cap)
    assert truncated is True
    assert len(paths) == 0


def test_zero_supported_with_excess_inspected_is_truncated(tmp_path: Path) -> None:
    root_dir = tmp_path / "unsupported-only"
    root_dir.mkdir()
    for index in range(10):
        (root_dir / f"file-{index}.bin").write_bytes(b"x")

    paths, truncated = _walk(root_dir, max_inspections=5)
    assert paths == []
    assert truncated is True


def test_supported_files_then_inspection_cap_is_truncated(tmp_path: Path) -> None:
    root_dir = tmp_path / "mixed"
    root_dir.mkdir()
    (root_dir / "first.txt").write_text("one", encoding="utf-8")
    for index in range(10):
        (root_dir / f"noise-{index}.bin").write_bytes(b"x")

    paths, truncated = _walk(root_dir, max_inspections=3)
    assert truncated is True
    assert len(paths) >= 1
    assert all(path.suffix.lower() in SUPPORTED_LOCAL_SUFFIXES for path in paths)


def test_scan_reports_truncated_when_inspection_cap_exhausted(
    tmp_path: Path, db_session, local_mirror: Path
) -> None:
    resolver = LocalPathResolver(local_mirror)
    device_service = LocalDeviceService(db_session, BOOTSTRAP_USER_ID, resolver)
    device_service.register_device("trunc-scan", "Desktop")
    root = device_service.register_root("trunc-scan", "bulk")
    root_dir = resolver.resolve_root_path(BOOTSTRAP_USER_ID, "trunc-scan", "bulk")
    (root_dir / "visible.txt").write_text("visible", encoding="utf-8")
    for index in range(10):
        (root_dir / f"extra-{index}.bin").write_bytes(b"x")

    sync = LocalFileSyncService(
        db_session,
        BOOTSTRAP_USER_ID,
        resolver,
        JobQueueService(db_session),
        upload_root=tmp_path / "uploads",
    )
    with patch(
        "app.services.local_file_sync_service.MAX_SCAN_INSPECTION_ITEMS",
        3,
    ):
        result = sync.scan_root(root.root_id)
    assert result.items_truncated is True
    assert result.objects_created == 1
