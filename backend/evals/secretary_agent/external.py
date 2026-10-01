"""Eval-only fake transports for F2. They never open a live provider."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from cryptography.fernet import Fernet
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.connectors.mattermost.transport import FakeMattermostTransport
from app.core.config import settings
from app.services.domain_tool_service import DomainToolService
from app.services.email_external_action_service import EmailExternalActionService
from evals.secretary_agent.safety import assert_dry_run_transports

CHAT_SERVER = "https://chat.example.com"


class FakeGmailTransport:
    def __init__(self) -> None:
        self.send_calls: list[dict[str, Any]] = []

    def send_message(
        self,
        access_token: str,
        user_id: str,
        raw: str,
        thread_id: str | None = None,
    ) -> dict[str, str]:
        self.send_calls.append(
            {
                "access_token": access_token,
                "user_id": user_id,
                "raw": raw,
                "thread_id": thread_id,
            }
        )
        message_id = f"gmail-{len(self.send_calls)}"
        return {"id": message_id, "threadId": thread_id or "thread"}


@dataclass
class ExternalBundle:
    kind: str
    gmail: FakeGmailTransport | None = None
    mattermost: FakeMattermostTransport | None = None
    session_factories: list[Any] = field(default_factory=list)

    @property
    def transports(self) -> tuple[object, ...]:
        transport = self.gmail if self.kind == "email" else self.mattermost
        return (transport,)


@contextmanager
def external_settings() -> Iterator[None]:
    previous_key = settings.secretary_credential_key
    previous_urls = settings.mattermost_allowed_base_urls
    settings.secretary_credential_key = Fernet.generate_key().decode()
    settings.mattermost_allowed_base_urls = CHAT_SERVER
    try:
        yield
    finally:
        settings.secretary_credential_key = previous_key
        settings.mattermost_allowed_base_urls = previous_urls


@contextmanager
def inject_fake_tools(bundle: ExternalBundle, connection: Connection) -> Iterator[None]:
    """Make ActionPlanService construct a fake-bound DomainToolService."""
    assert_dry_run_transports(bundle.transports)
    factory = _local_sessions(connection)
    original_init = DomainToolService.__init__
    original_token = EmailExternalActionService._valid_access_token

    def patched(self: DomainToolService, *args: Any, **kwargs: Any) -> None:
        if bundle.kind == "email":
            kwargs.setdefault("gmail_transport", bundle.gmail)
            kwargs.setdefault("gmail_token_session_factory", factory)
        else:
            kwargs.setdefault("mattermost_transport", bundle.mattermost)
        kwargs.setdefault("attempt_session_factory", factory)
        bundle.session_factories.append(kwargs.get("attempt_session_factory"))
        original_init(self, *args, **kwargs)

    def local_token(self: EmailExternalActionService, account_id: Any) -> str:
        del self, account_id
        return "eval-access-token"

    DomainToolService.__init__ = patched  # type: ignore[method-assign]
    if bundle.kind == "email":
        EmailExternalActionService._valid_access_token = local_token  # type: ignore[method-assign]
    try:
        yield
    finally:
        DomainToolService.__init__ = original_init  # type: ignore[method-assign]
        EmailExternalActionService._valid_access_token = original_token  # type: ignore[method-assign]


def _local_sessions(connection: Connection):
    def factory() -> Session:
        return Session(bind=connection, join_transaction_mode="create_savepoint")

    return factory
