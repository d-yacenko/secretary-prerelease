class UserOpenAICredentialConfigurationError(Exception):
    """Stored user OpenAI credential exists but cannot be used (encryption/decryption)."""

    def __init__(self, message: str = "user OpenAI credential is not available") -> None:
        self.message = message
        super().__init__(message)
