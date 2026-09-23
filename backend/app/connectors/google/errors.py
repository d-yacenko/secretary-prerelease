import re
from typing import Literal

import httpx

_OAUTH_ERROR_CODE = re.compile(r"^[A-Za-z0-9_]{1,64}$")

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


def sanitize_oauth_error_code(value: object) -> str | None:
    """Keep only a short provider OAuth error code. Never keep tokens or bodies."""
    if not isinstance(value, str) or not _OAUTH_ERROR_CODE.fullmatch(value):
        return None
    return value


class GoogleOAuthError(GoogleConnectorError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
        oauth_error: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.oauth_error = sanitize_oauth_error_code(oauth_error)
        super().__init__(message)


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
        if exc.retryable:
            return "transient", True, exc.retry_after_seconds
        return "authentication", False, None
    if isinstance(exc, GoogleApiError):
        if exc.retryable:
            return "transient", True, exc.retry_after_seconds
        if exc.status_code == 401 or exc.api_status == "UNAUTHENTICATED" or exc.reason == "authError":
            return "authentication", False, None
        if exc.api_status == "PERMISSION_DENIED" or exc.reason in {
            "insufficientPermissions",
            "accessNotConfigured",
            "forbidden",
            "domainPolicy",
        }:
            return "permission", False, None
        return "unknown", False, None
    if isinstance(exc, httpx.RequestError):
        return "transient", True, None
    return "unknown", False, None
