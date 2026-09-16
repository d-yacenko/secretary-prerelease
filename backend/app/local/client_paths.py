"""Client-reported source path helpers."""

import hashlib


def normalize_client_source_path(source_path: str) -> str:
    text = source_path.replace("\\", "/").strip()
    while "//" in text:
        text = text.replace("//", "/")
    return text


def build_client_source_external_id(device_key: str, source_path: str) -> str:
    normalized = normalize_client_source_path(source_path)
    return f"{device_key}:client-source:{normalized}"


def cheap_content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_client_content_revision(
    client_source_locator: str,
    size: int,
    modified_at: str,
    content_hash: str | None = None,
) -> str:
    """Deterministic revision from canonical client source locator and file facts."""
    normalized_locator = normalize_client_source_path(client_source_locator)
    parts = {
        "modified_at": modified_at,
        "size": size,
        "source_path": normalized_locator,
    }
    if content_hash:
        parts["content_hash"] = content_hash
    payload = "|".join(f"{key}={parts[key]}" for key in sorted(parts))
    return cheap_content_hash(payload.encode("utf-8"))
