"""ZIP bomb guards for OOXML mechanical extraction."""

import zipfile

from app.content_extraction.constants import (
    MAX_OOXML_COMPRESSION_RATIO,
    MAX_OOXML_UNCOMPRESSED_BYTES,
    MAX_OOXML_ZIP_ENTRIES,
)


class UnsafeZipError(Exception):
    pass


def validate_zip_archive(archive: zipfile.ZipFile) -> None:
    entries = archive.infolist()
    if len(entries) > MAX_OOXML_ZIP_ENTRIES:
        raise UnsafeZipError("zip entry count exceeds limit")
    total_uncompressed = 0
    for info in entries:
        if info.is_dir():
            continue
        uncompressed = info.file_size
        compressed = max(info.compress_size, 1)
        if uncompressed / compressed > MAX_OOXML_COMPRESSION_RATIO:
            raise UnsafeZipError("zip compression ratio exceeds limit")
        total_uncompressed += uncompressed
        if total_uncompressed > MAX_OOXML_UNCOMPRESSED_BYTES:
            raise UnsafeZipError("zip uncompressed size exceeds limit")
