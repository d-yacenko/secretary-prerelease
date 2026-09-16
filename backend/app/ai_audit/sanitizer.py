"""Sanitize AI audit payloads — never store secrets or raw credentials."""

import json
import re
from typing import Any

_SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|authorization|bearer|access[_-]?token|refresh[_-]?token|"
    r"secret|password|credential|encrypted)",
    re.IGNORECASE,
)

_SENSITIVE_SUBSTRINGS = (
    "sk-",
    "Bearer ",
    "authorization:",
)


def _looks_sensitive_key(key: str) -> bool:
    return bool(_SECRET_KEY_PATTERN.search(key))


def _looks_sensitive_value(value: str) -> bool:
    lowered = value.lower()
    return any(marker.lower() in lowered for marker in _SENSITIVE_SUBSTRINGS)


def sanitize_for_audit(value: Any, *, depth: int = 0) -> Any:
    if depth > 12:
        return "[truncated-depth]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if _looks_sensitive_value(value):
            return "[redacted]"
        if len(value) > 32000:
            return value[:32000] + "…"
        return value
    if isinstance(value, bytes):
        return {"byte_size": len(value)}
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if _looks_sensitive_key(key_str):
                sanitized[key_str] = "[redacted]"
            else:
                sanitized[key_str] = sanitize_for_audit(item, depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_for_audit(item, depth=depth + 1) for item in value[:200]]
    return sanitize_for_audit(str(value), depth=depth + 1)


def bounded_json_text(value: Any, max_chars: int = 32000) -> str:
    text = json.dumps(sanitize_for_audit(value), ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"
