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
    ) -> None:
        self.operation = operation
        self.status_code = status_code
        self.reason = reason
        self.api_status = api_status
        self.retryable = retryable
        super().__init__(message)
