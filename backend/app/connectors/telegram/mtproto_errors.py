class TelegramMtprotoError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class TelegramMtprotoConfigurationError(TelegramMtprotoError):
    pass


class TelegramMtprotoChallengeNotFoundError(TelegramMtprotoError):
    pass


class TelegramMtprotoChallengeExpiredError(TelegramMtprotoError):
    pass


class TelegramMtprotoInvalidPhoneError(TelegramMtprotoError):
    pass


class TelegramMtprotoInvalidCodeError(TelegramMtprotoError):
    pass


class TelegramMtprotoInvalidPasswordError(TelegramMtprotoError):
    pass


class TelegramMtprotoIdentityConflictError(TelegramMtprotoError):
    pass


class TelegramMtprotoAccountNotConnectedError(TelegramMtprotoError):
    pass


class TelegramMtprotoAuthorizationInvalidError(TelegramMtprotoError):
    pass


class TelegramMtprotoGroupUnavailableError(TelegramMtprotoError):
    pass


class TelegramMtprotoGroupNotSelectedError(TelegramMtprotoError):
    pass


class TelegramMtprotoFolderConfigurationError(TelegramMtprotoError):
    pass


class TelegramMtprotoScopeUnavailableError(TelegramMtprotoError):
    pass


class TelegramMtprotoProviderReferenceInvalidError(TelegramMtprotoError):
    pass


class TelegramMtprotoProviderUnavailableError(TelegramMtprotoError):
    def __init__(self, message: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
