from pathlib import Path
from uuid import UUID

from app.local.errors import LocalAccessError, LocalPathError


def validate_object_upload_path(
    upload_root: Path,
    user_id: UUID,
    object_id: UUID,
    raw_path: str,
) -> Path:
    if not raw_path:
        raise LocalPathError("upload_path must not be empty")
    path = Path(raw_path)
    if not path.is_absolute():
        raise LocalPathError("upload_path must be absolute")
    resolved = path.resolve()
    allowed_root = (upload_root / str(user_id) / str(object_id)).resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError:
        raise LocalAccessError("upload_path escapes object upload tree") from None
    if not resolved.is_file():
        raise LocalPathError("upload file not found")
    return resolved
