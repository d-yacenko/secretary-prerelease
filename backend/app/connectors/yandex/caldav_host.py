"""Trusted Yandex Calendar CalDAV host validation."""

import ipaddress
from urllib.parse import urlparse

from app.connectors.yandex.constants import DEFAULT_CALDAV_HOST
from app.connectors.yandex.errors import YandexConfigurationError

TRUSTED_CALDAV_HOSTS = frozenset({DEFAULT_CALDAV_HOST})


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast:
        return True
    if ip.is_reserved or ip.is_unspecified:
        return True
    return bool(hasattr(ip, "is_global") and not ip.is_global)


def _hostname_literal_blocked(hostname: str) -> bool:
    lowered = hostname.lower().rstrip(".")
    if lowered in {"localhost", "0.0.0.0"} or lowered.endswith(".local"):
        return True
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return _ip_is_blocked(hostname)


def _extract_hostname(caldav_host: str) -> str:
    raw = caldav_host.strip()
    if not raw:
        raise YandexConfigurationError("yandex calendar caldav host is required")
    if raw.lower().startswith("http://"):
        raise YandexConfigurationError("yandex calendar caldav host must use https")
    if raw.lower().startswith("https://"):
        parsed = urlparse(raw)
        if parsed.scheme != "https":
            raise YandexConfigurationError("yandex calendar caldav host must use https")
        hostname = parsed.hostname
        if not hostname:
            raise YandexConfigurationError("yandex calendar caldav host is invalid")
        return hostname
    host_part = raw.split("/", 1)[0].rstrip("/")
    if not host_part:
        raise YandexConfigurationError("yandex calendar caldav host is invalid")
    return host_part


def validate_trusted_caldav_host(caldav_host: str) -> str:
    hostname = _extract_hostname(caldav_host)
    if _hostname_literal_blocked(hostname):
        raise YandexConfigurationError("yandex calendar caldav host is not allowed")
    normalized = hostname.lower().rstrip(".")
    if normalized not in TRUSTED_CALDAV_HOSTS:
        raise YandexConfigurationError("yandex calendar caldav host is not allowed")
    if normalized == DEFAULT_CALDAV_HOST:
        return DEFAULT_CALDAV_HOST
    return normalized


def trusted_caldav_base_url(caldav_host: str) -> str:
    hostname = validate_trusted_caldav_host(caldav_host)
    return f"https://{hostname}"
