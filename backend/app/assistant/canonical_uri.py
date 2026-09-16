from urllib.parse import urlparse, urlunparse

_LOCAL_PATH_PREFIXES = (
    "/home/",
    "/var/",
    "/tmp/",
    "/usr/",
    "/etc/",
    "/opt/",
    "/root/",
    "/private/",
    "\\\\",
)

_UNSAFE_SCHEMES = frozenset({"file", "ftp"})


def sanitize_canonical_uri_for_assistant(uri: str | None) -> str | None:
    """Return a conservative Assistant-safe canonical URI or omit it."""
    try:
        return _sanitize_canonical_uri(uri)
    except Exception:  # noqa: BLE001
        return None


def _sanitize_canonical_uri(uri: str | None) -> str | None:
    if uri is None:
        return None
    trimmed = uri.strip()
    if not trimmed:
        return None

    lowered = trimmed.lower()
    if lowered.startswith(("file:", "file://")):
        return None
    if trimmed.startswith(_LOCAL_PATH_PREFIXES):
        return None
    if len(trimmed) > 1 and trimmed[1] == ":" and trimmed[0].isalpha():
        return None

    parsed = urlparse(trimmed)
    if not parsed.scheme:
        if trimmed.startswith("/") or "\\" in trimmed:
            return None
        return None

    if parsed.scheme in _UNSAFE_SCHEMES:
        return None

    if parsed.scheme not in {"http", "https"}:
        return None

    host = parsed.hostname
    if not host:
        return None

    try:
        port = parsed.port
    except ValueError:
        return None
    if port is not None and not (0 <= port <= 65535):
        return None

    netloc = host
    if port is not None:
        netloc = f"{host}:{port}"

    # Assistant-facing URIs omit query and fragment entirely.
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, "", ""))
