"""AH2-MR1 guards. They do not print secrets or open a database."""

from __future__ import annotations

import re
from typing import Any

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_SECRET_KEYS = re.compile(
    r"(api[_-]?key|password|secret|(?:^|_)token(?:_|$)|authorization|dsn|database_url|credential)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
_LIVE_TRANSPORTS = frozenset(
    {
        "GmailTransport",
        "SmtpTransport",
        "ImapTransport",
        "CalDavTransport",
        "MattermostTransport",
        "TeamsTransport",
        "TelegramMtprotoTransport",
    }
)


class EvalSafetyError(RuntimeError):
    pass


def assert_disposable_database(host: str, database: str) -> dict[str, str]:
    normalized = host.strip().lower()
    if normalized not in _LOCAL_HOSTS or "web-itx.duckdns.org" in normalized:
        raise EvalSafetyError("database host is not a local disposable target")
    if not database.strip():
        raise EvalSafetyError("database name is not classified as local/disposable")
    return {"host": normalized, "database": database.strip(), "local": "true"}


def assert_dry_run_transports(transports: tuple[object, ...]) -> None:
    for transport in transports:
        name = type(transport).__name__
        if name in _LIVE_TRANSPORTS or not name.startswith("Fake"):
            raise EvalSafetyError("scripted dry run cannot use a live transport")


def assert_no_secrets(payload: Any) -> None:
    if _secret_paths(payload) or _SECRET_VALUE.search(repr(payload)):
        raise EvalSafetyError("artifact contains secret fields")


def _secret_paths(payload: Any) -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _SECRET_KEYS.search(str(key)):
                found.append(str(key))
            found.extend(_secret_paths(value))
    elif isinstance(payload, list):
        for value in payload:
            found.extend(_secret_paths(value))
    return found
