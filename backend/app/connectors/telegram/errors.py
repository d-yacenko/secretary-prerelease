class TelegramConnectorError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class TelegramConfigurationError(TelegramConnectorError):
    pass


class TelegramSecurityError(TelegramConnectorError):
    pass


class TelegramWriteDefiniteError(TelegramConnectorError):
    """Provider rejected a write; delivery did not occur."""


class TelegramWriteUncertainError(TelegramConnectorError):
    """Write may have been delivered; do not retry blindly."""
