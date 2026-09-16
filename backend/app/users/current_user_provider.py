from contextvars import ContextVar
from uuid import UUID

from sqlalchemy.orm import Session

from app.auth.errors import AuthenticationError
from app.auth.token_service import AuthTokenService
from app.core.current_user import CurrentUserContext

_auth_bearer_token: ContextVar[str | None] = ContextVar("auth_bearer_token", default=None)


def set_request_bearer_token(token: str | None) -> object:
    return _auth_bearer_token.set(token)


def reset_request_bearer_token(reset_token: object) -> None:
    _auth_bearer_token.reset(reset_token)


def resolve_current_user(session: Session) -> CurrentUserContext:
    plaintext = _auth_bearer_token.get()
    if not plaintext:
        raise AuthenticationError("authentication required")
    user_id = AuthTokenService(session).authenticate(plaintext)
    if user_id is None:
        raise AuthenticationError("invalid or expired token")
    return CurrentUserContext(user_id=user_id)


def resolve_current_user_id(session: Session) -> UUID:
    return resolve_current_user(session).user_id
