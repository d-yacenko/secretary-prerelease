from typing import Literal

YandexSyncFailureKind = Literal[
    "transient",
    "authentication",
    "permission",
    "unknown",
]


class YandexConnectorError(Exception):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        failure_kind: YandexSyncFailureKind = "unknown",
    ) -> None:
        self.message = message
        self.retryable = retryable
        self.failure_kind = failure_kind
        super().__init__(message)


class YandexConfigurationError(YandexConnectorError):
    pass


class YandexImapError(YandexConnectorError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        failure_kind: YandexSyncFailureKind = "unknown",
    ) -> None:
        super().__init__(
            message,
            retryable=retryable,
            failure_kind=failure_kind,
        )


class YandexSmtpError(YandexConnectorError):
    pass


class YandexCalDavError(YandexConnectorError):
    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        path: str | None = None,
        status_code: int | None = None,
        category: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.operation = operation
        self.path = path
        self.status_code = status_code
        self.category = category
        failure_kind: YandexSyncFailureKind = {
            "auth": "authentication",
            "permission": "permission",
            "rate_limit": "transient",
            "server": "transient",
            "network": "transient",
        }.get(category or "", "unknown")
        super().__init__(
            message,
            retryable=retryable,
            failure_kind=failure_kind,
        )


class YandexCalDavStaleSyncTokenError(YandexCalDavError):
    pass


class YandexDiskApiError(YandexConnectorError):
    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        status_code: int | None = None,
        reason: str | None = None,
    ) -> None:
        self.operation = operation
        self.status_code = status_code
        self.reason = reason
        super().__init__(message)


def classify_yandex_sync_failure(
    exc: BaseException,
) -> tuple[YandexSyncFailureKind, bool]:
    """Return safe source-sync metadata while preserving legacy retry behavior."""
    if isinstance(exc, YandexConfigurationError):
        return "unknown", False
    if isinstance(exc, YandexConnectorError):
        return exc.failure_kind, exc.retryable
    if isinstance(exc, (TimeoutError, OSError)):
        return "transient", True
    return "unknown", True
