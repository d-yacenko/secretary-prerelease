class TeamsConnectorError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class TeamsConfigurationError(TeamsConnectorError):
    pass


class TeamsOAuthError(TeamsConnectorError):
    pass


class TeamsReconnectRequiredError(TeamsOAuthError):
    """Authorization was revoked; Graph writes and token refresh must stop."""


class TeamsIdentityConflictError(TeamsOAuthError):
    """The Microsoft identity is already bound to another Secretary user."""


class TeamsIdentitySwitchError(TeamsOAuthError):
    """A different Microsoft identity is already connected for this user."""


class TeamsRateLimitedError(TeamsConnectorError):
    """HTTP 429; caller must schedule retry and must not advance watermarks."""

    def __init__(self, message: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class TeamsSecurityError(TeamsConnectorError):
    pass


class TeamsSyncError(TeamsConnectorError):
    """Visible sync failure; correctness state must not advance."""


class TeamsSubscriptionNotFoundError(TeamsConnectorError):
    """The remote Graph subscription no longer exists."""


class TeamsWriteDefiniteError(TeamsConnectorError):
    """Provider rejected a write; delivery did not occur."""


class TeamsWriteUncertainError(TeamsConnectorError):
    """Write may have been delivered; do not retry blindly."""
