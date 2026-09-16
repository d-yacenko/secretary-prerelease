class AuthenticationError(Exception):
    def __init__(self, message: str = "authentication required") -> None:
        self.message = message
        super().__init__(message)
