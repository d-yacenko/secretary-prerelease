from urllib.parse import urlparse

from app.connectors.google.constants import GOOGLE_DRIVE_PROVIDER
from app.connectors.google.drive_url_parser import GOOGLE_DRIVE_URL_HOSTS
from app.connectors.yandex.constants import YANDEX_DISK_PROVIDER
from app.connectors.yandex.disk_url_parser import YANDEX_DISK_ALLOWED_HOSTS
from app.resources.constants import PROVIDER_WEB
from app.services.explicit_link_intake_errors import ExplicitLinkIntakeError


def detect_intake_provider(url: str) -> str:
    raw = url.strip()
    if not raw:
        raise ExplicitLinkIntakeError("invalid link url")

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ExplicitLinkIntakeError("unsupported link url")
    if parsed.username or parsed.password:
        raise ExplicitLinkIntakeError("unsupported link url")

    host = (parsed.hostname or "").lower()
    if host in GOOGLE_DRIVE_URL_HOSTS:
        return GOOGLE_DRIVE_PROVIDER
    if host in YANDEX_DISK_ALLOWED_HOSTS:
        return YANDEX_DISK_PROVIDER
    return PROVIDER_WEB
