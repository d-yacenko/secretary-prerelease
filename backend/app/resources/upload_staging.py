import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.resources.constants import ALLOWED_UPLOAD_SUFFIXES, MAX_UPLOAD_BYTES, UPLOAD_CHUNK_BYTES
from app.services.errors import ValidationError


@dataclass(frozen=True)
class StagedUpload:
    path: Path
    content_hash: str
    original_filename: str
    size: int


def sanitize_upload_filename(filename: str | None) -> str:
    raw = Path(filename or "upload.txt").name
    safe = re.sub(r"[^\w.\-]+", "_", raw).strip("._")
    return safe[:200] if safe else "upload.txt"


async def stage_upload_file(upload, temp_dir: Path) -> StagedUpload:
    original_filename = sanitize_upload_filename(
        upload.filename if hasattr(upload, "filename") else None
    )
    suffix = Path(original_filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise ValidationError(f"unsupported upload format: {suffix or '(none)'}")

    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"staging-{uuid.uuid4().hex}{suffix}"

    digest = hashlib.sha256()
    total = 0
    try:
        with temp_path.open("wb") as handle:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise ValidationError("upload exceeds size limit")
                digest.update(chunk)
                handle.write(chunk)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    if total == 0:
        temp_path.unlink(missing_ok=True)
        raise ValidationError("upload is empty")

    return StagedUpload(
        path=temp_path,
        content_hash=digest.hexdigest(),
        original_filename=original_filename,
        size=total,
    )
