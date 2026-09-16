"""SSRF-safe bounded streaming downloads for provider-controlled URLs."""

import ipaddress
from collections.abc import Callable, Iterator
from urllib.parse import urlparse

import httpx

from app.content_extraction.bounded_download import (
    DownloadTooLargeError,
    read_bounded_response_body,
)
from app.content_extraction.yandex_download_policy import is_yandex_download_host_allowed

MAX_REDIRECT_HOPS = 5

REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})

HostResolver = Callable[[str], list[str]]


class UnsafeDownloadUrlError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _default_host_resolver(host: str) -> list[str]:
    import socket

    addresses: list[str] = []
    for family, _, _, _, sockaddr in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        ip = sockaddr[0]
        if ":" in ip and ip.startswith("[") and ip.endswith("]"):
            ip = ip[1:-1]
        addresses.append(ip)
    if not addresses:
        raise UnsafeDownloadUrlError("host_resolution_failed")
    return addresses


def _reject_private_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
    ):
        raise UnsafeDownloadUrlError("private_destination_forbidden")


def _reject_private_host_literal(host: str) -> None:
    try:
        if host.startswith("[") and host.endswith("]"):
            addr = ipaddress.ip_address(host[1:-1])
        else:
            addr = ipaddress.ip_address(host)
    except ValueError:
        return
    _reject_private_address(addr)


def validate_download_url(
    url: str,
    *,
    resolver: HostResolver | None = None,
) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise UnsafeDownloadUrlError("non_https_url")
    if not parsed.hostname:
        raise UnsafeDownloadUrlError("missing_hostname")
    if parsed.username or parsed.password:
        raise UnsafeDownloadUrlError("url_userinfo_forbidden")

    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost"):
        raise UnsafeDownloadUrlError("localhost_forbidden")

    _reject_private_host_literal(host)

    if not is_yandex_download_host_allowed(host):
        raise UnsafeDownloadUrlError("untrusted_download_host")

    resolve = resolver or _default_host_resolver
    for ip_str in resolve(host):
        try:
            _reject_private_address(ipaddress.ip_address(ip_str))
        except ValueError:
            raise UnsafeDownloadUrlError("invalid_resolved_address") from None


def validate_https_download_url(url: str) -> None:
    """Backward-compatible alias; prefer validate_download_url with resolver."""
    validate_download_url(url)


def _check_declared_content_length(headers: httpx.Headers, max_bytes: int) -> None:
    content_length = headers.get("Content-Length")
    if content_length is None:
        return
    try:
        declared = int(content_length)
    except ValueError:
        return
    if declared > max_bytes:
        raise DownloadTooLargeError(declared, max_bytes)


def bounded_get_safe_redirects(
    http: httpx.Client,
    url: str,
    *,
    max_bytes: int,
    max_hops: int = MAX_REDIRECT_HOPS,
    resolver: HostResolver | None = None,
) -> bytes:
    validate_download_url(url, resolver=resolver)
    current = url
    seen: set[str] = set()
    for _ in range(max_hops + 1):
        if current in seen:
            raise UnsafeDownloadUrlError("redirect_loop")
        seen.add(current)
        with http.stream("GET", current, follow_redirects=False) as response:
            if response.status_code in REDIRECT_STATUS_CODES:
                location = response.headers.get("Location")
                if not location:
                    raise UnsafeDownloadUrlError("redirect_missing_location")
                current = str(httpx.URL(current).join(location))
                validate_download_url(current, resolver=resolver)
                continue
            if response.status_code >= 400:
                response.raise_for_status()
            _check_declared_content_length(response.headers, max_bytes)
            return read_bounded_response_body(response, max_bytes)
    raise UnsafeDownloadUrlError("redirect_hop_limit")


class IterableByteStream(httpx.SyncByteStream):
    """Test helper: stream fixed chunks without preloading the full body."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        return iter(self._chunks)
