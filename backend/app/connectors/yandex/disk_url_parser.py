import re
from urllib.parse import urlparse

from app.services.explicit_link_intake_errors import ExplicitLinkIntakeError

YANDEX_DISK_ALLOWED_HOSTS = frozenset(
    {
        "disk.yandex.ru",
        "disk.yandex.com",
        "disk.360.yandex.ru",
        "disk.360.yandex.com",
        "yadi.sk",
    }
)

_SHARE_PATH_RE = re.compile(r"^/(d|i)/([^/?#]+)")


def _parse_share_url(url: str) -> str:
    raw = url.strip()
    if not raw:
        raise ExplicitLinkIntakeError("invalid link url")

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ExplicitLinkIntakeError("unsupported link url")
    if parsed.username or parsed.password:
        raise ExplicitLinkIntakeError("unsupported link url")

    host = (parsed.hostname or "").lower()
    if host not in YANDEX_DISK_ALLOWED_HOSTS:
        raise ExplicitLinkIntakeError("unsupported link url")

    path = parsed.path or ""
    if path.startswith("/client/") or "/client/" in path:
        raise ExplicitLinkIntakeError("yandex disk private link unsupported")

    match = _SHARE_PATH_RE.match(path)
    if not match:
        raise ExplicitLinkIntakeError("unsupported link url")

    share_key = match.group(2).strip()
    if not share_key:
        raise ExplicitLinkIntakeError("invalid link url")

    normalized = f"{parsed.scheme}://{host}{path}"
    if parsed.query:
        normalized += f"?{parsed.query}"
    return normalized


def parse_yandex_disk_share_url(url: str) -> str:
    return _parse_share_url(url)


def is_valid_yandex_disk_share_url(url: str) -> bool:
    try:
        _parse_share_url(url)
        return True
    except ExplicitLinkIntakeError:
        return False
