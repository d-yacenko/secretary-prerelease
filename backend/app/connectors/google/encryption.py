from cryptography.fernet import Fernet, InvalidToken

from app.connectors.google.errors import GoogleConfigurationError


class CredentialEncryption:
    def __init__(self, key: str) -> None:
        if not key:
            raise GoogleConfigurationError("credential encryption key is not configured")
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except ValueError:
            raise GoogleConfigurationError("credential encryption key is invalid") from None

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            raise GoogleConfigurationError("stored credential could not be decrypted") from None
