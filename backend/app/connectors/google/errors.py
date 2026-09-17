from typing import Literal

import httpx

GoogleSyncFailureKind = Literal[
    "transient",
    "authentication",
    "permission",
    "unknown",
]


class GoogleConnectorError(Exception):
    retryable: bool = False

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class GoogleConfigurationError(GoogleConnectorError):
    pass


class GoogleOAuthError(GoogleConnectorError):
    pass


class GoogleApiError(GoogleConnectorError):
    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        status_code: int | None = None,
        reason: str | None = None,
        api_status: str | None = None,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.operation = operation
        self.status_code = status_code
        self.reason = reason
        self.api_status = api_status
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


def classify_google_sync_failure(
    exc: BaseException,
) -> tuple[GoogleSyncFailureKind, bool, int | None]:
    """Classify Google source-sync failures conservatively."""
    if isinstance(exc, GoogleOAuthError):
        return "authentication", False, None
    if isinstance(exc, GoogleApiError):
        if exc.retryable:
            return "transient", True, exc.retry_after_seconds
        if exc.status_code == 401 or exc.api_status == "UNAUTHENTICATED" or exc.reason == "authError":
            return "authentication", False, None
        if exc.reason in {"insufficientPermissions", "accessNotConfigured", "forbidden", "domainPolicy"}:
            return "permission", False, None
        return "unknown", False, None
    if isinstance(exc, httpx.RequestError):
        return "transient", True, None
    return "unknown", False, None
