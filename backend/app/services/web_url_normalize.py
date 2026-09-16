"""Deterministic normalization for generic public web URL identity."""

from urllib.parse import quote, unquote, urlparse, urlunparse


def normalize_explicit_web_url(url: str) -> str:
    """Normalize scheme/host/path for stable Object.external_id and canonical_uri."""
    raw = url.strip()
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("web url hostname missing")

    port = parsed.port
    default_port = 80 if scheme == "http" else 443
    netloc = host
    if port is not None and port != default_port:
        netloc = f"{host}:{port}"

    path = unquote(parsed.path or "/")
    if not path.startswith("/"):
        path = f"/{path}"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    query = parsed.query
    return urlunparse((scheme, netloc, quote(path, safe="/%"), "", query, ""))
