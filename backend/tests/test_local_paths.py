import uuid
from pathlib import Path

import pytest

from app.local.constants import MAX_TEXT_WINDOW_BYTES
from app.local.device_keys import validate_device_key
from app.local.errors import LocalPathError
from app.local.paths import LocalPathResolver
from app.users.bootstrap import BOOTSTRAP_USER_ID


def test_device_key_traversal_rejected() -> None:
    with pytest.raises(LocalPathError):
        validate_device_key("../other-user")
    with pytest.raises(LocalPathError):
        validate_device_key("/etc/passwd")
    with pytest.raises(LocalPathError):
        validate_device_key("foo/bar")
    with pytest.raises(LocalPathError):
        validate_device_key("foo\\bar")


def test_device_mirrors_are_user_scoped(tmp_path: Path) -> None:
    mirror = tmp_path / "mirror"
    user_b_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
    resolver = LocalPathResolver(mirror)
    root_a = resolver.device_mirror_root(BOOTSTRAP_USER_ID, "laptop")
    root_b = resolver.device_mirror_root(user_b_id, "laptop")
    assert root_a != root_b
    assert str(BOOTSTRAP_USER_ID) in str(root_a)
    assert "00000000-0000-0000-0000-000000000099" in str(root_b)


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    mirror = tmp_path / "mirror"
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    resolver = LocalPathResolver(mirror)
    device_root = resolver.device_mirror_root(BOOTSTRAP_USER_ID, "symlink-device")
    device_root.mkdir(parents=True)
    root_dir = device_root / "docs"
    root_dir.mkdir()
    link = root_dir / "escape.txt"
    link.symlink_to(outside)

    with pytest.raises(LocalPathError):
        resolver.resolve_file_path(
            BOOTSTRAP_USER_ID,
            "symlink-device",
            "docs",
            "escape.txt",
        )


def test_read_bounded_text_marks_large_file_sampled(tmp_path: Path) -> None:
    from app.local.bounded_io import read_bounded_text

    large = tmp_path / "huge.txt"
    large.write_bytes(b"x" * (MAX_TEXT_WINDOW_BYTES * 3))
    text, meta = read_bounded_text(large)
    assert meta["truncated"] is True
    assert meta["sampled"] is True
    assert meta["source_bytes"] > MAX_TEXT_WINDOW_BYTES
    assert len(text) <= 3 * MAX_TEXT_WINDOW_BYTES + 10
