import hashlib
import re

from app.local.errors import LocalPathError

_DEVICE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_device_key(device_key: str) -> str:
    key = device_key.strip()
    if not key:
        raise LocalPathError("device_key must not be empty")
    if key.startswith(("/", "\\")):
        raise LocalPathError("device_key must not be an absolute path")
    if "/" in key or "\\" in key:
        raise LocalPathError("device_key must not contain path separators")
    if key in {".", ".."}:
        raise LocalPathError("device_key must not be a relative path segment")
    if "../" in key or key.startswith(".."):
        raise LocalPathError("device_key must not contain parent path segments")
    if not _DEVICE_KEY_PATTERN.match(key):
        raise LocalPathError("device_key contains invalid characters")
    return key


def device_filesystem_name(device_key: str) -> str:
    validated = validate_device_key(device_key)
    digest = hashlib.sha256(validated.encode("utf-8")).hexdigest()[:16]
    safe_prefix = re.sub(r"[^A-Za-z0-9._-]", "_", validated)[:32]
    return f"{safe_prefix}_{digest}"
