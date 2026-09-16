"""Documented Yandex Disk public-download host trust policy (PHASE 29A-R1-R1)."""

# Exact hostnames returned by Yandex Disk public download API (href targets).
YANDEX_DOWNLOAD_HOST_EXACT = frozenset(
    {
        "downloader.disk.yandex.ru",
        "downloader.disk.yandex.com",
        "cloud-api.yandex.net",
        "storage.yandex.net",
    }
)

# Suffixes for Yandex-operated download/CDN hosts (dynamic shard subdomains).
YANDEX_DOWNLOAD_HOST_SUFFIXES = (
    ".disk.yandex.ru",
    ".disk.yandex.com",
    ".storage.yandex.net",
    ".yandexcloud.net",
)


def is_yandex_download_host_allowed(host: str) -> bool:
    normalized = host.lower().strip()
    if not normalized:
        return False
    if normalized in YANDEX_DOWNLOAD_HOST_EXACT:
        return True
    return any(normalized.endswith(suffix) for suffix in YANDEX_DOWNLOAD_HOST_SUFFIXES)
