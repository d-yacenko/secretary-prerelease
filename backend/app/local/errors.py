class LocalFileError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class LocalPathError(LocalFileError):
    pass


class LocalAccessError(LocalFileError):
    pass
