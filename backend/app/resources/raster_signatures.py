"""Magic-byte checks for the four role-import raster formats."""

from pathlib import Path

_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_RIFF = b"RIFF"
_WEBP = b"WEBP"


def raster_signature_matches(suffix: str, path: Path) -> bool:
    header = path.read_bytes()[:16]
    return header_matches_suffix(suffix, header)


def header_matches_suffix(suffix: str, header: bytes) -> bool:
    normalized = suffix.lower()
    if normalized == ".png":
        return header.startswith(_PNG)
    if normalized in {".jpg", ".jpeg"}:
        return header.startswith(_JPEG)
    if normalized == ".webp":
        return len(header) >= 12 and header.startswith(_RIFF) and header[8:12] == _WEBP
    return False


def mime_type_for_suffix(suffix: str) -> str:
    normalized = suffix.lower()
    if normalized == ".png":
        return "image/png"
    if normalized in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if normalized == ".webp":
        return "image/webp"
    raise ValueError(f"unsupported raster suffix: {suffix}")
