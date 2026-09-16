from collections.abc import Iterator
from contextlib import contextmanager

from app.auth.errors import AuthenticationError
from app.db.session import SessionLocal
from app.services.domain_tool_service import DomainToolService
from app.services.user_embedding_resolver import (
    EMBEDDING_PROVIDER_UNAVAILABLE,
    resolve_embedding_service_for_user,
)
from app.services.user_openai_credential_errors import UserOpenAICredentialConfigurationError
from app.users.current_user_provider import resolve_current_user


@contextmanager
def tool_session() -> Iterator[DomainToolService]:
    session = SessionLocal()
    try:
        try:
            current_user = resolve_current_user(session)
        except AuthenticationError as exc:
            raise RuntimeError(
                "MCP tools require Authorization: Bearer <token>; enable MCP only with authenticated access"
            ) from exc
        try:
            embedding_service = resolve_embedding_service_for_user(session, current_user.user_id)
        except UserOpenAICredentialConfigurationError as exc:
            raise RuntimeError(EMBEDDING_PROVIDER_UNAVAILABLE) from exc
        tools = DomainToolService(session, current_user.user_id, embedding_service)
        yield tools
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
