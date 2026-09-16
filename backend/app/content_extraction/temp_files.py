"""Secure ephemeral files for cloud content extraction."""

import os
import tempfile
from pathlib import Path
from typing import Self


class SecureTempFile:
    def __init__(self, suffix: str) -> None:
        self._suffix = suffix
        self._path: Path | None = None

    @property
    def path(self) -> Path:
        if self._path is None:
            raise RuntimeError("temp file not created")
        return self._path

    def write(self, data: bytes) -> Path:
        fd, name = tempfile.mkstemp(prefix="sec-extract-", suffix=self._suffix)
        os.close(fd)
        self._path = Path(name)
        try:
            os.chmod(name, 0o600)
        except OSError:
            pass
        self._path.write_bytes(data)
        return self._path

    def cleanup(self) -> None:
        if self._path is None:
            return
        try:
            self._path.unlink(missing_ok=True)
        finally:
            self._path = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.cleanup()
