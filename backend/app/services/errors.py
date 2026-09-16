import uuid


class NotFoundError(Exception):
    def __init__(self, resource: str, entity_id: uuid.UUID) -> None:
        self.resource = resource
        self.entity_id = entity_id
        super().__init__(f"{resource} {entity_id} not found")


class ConflictError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ValidationError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
