"""Exact lexical identity for emergent Person role terms and contexts."""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+", re.UNICODE)
ROLE_TEXT_MAX = 120
CONTEXT_TEXT_MAX = 200


class PersonRoleTextError(ValueError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def collapse_role_text(value: str | None) -> str:
    if value is None:
        return ""
    return _WHITESPACE.sub(" ", value.strip())


def role_term_identity(value: str | None) -> tuple[str, str]:
    display = collapse_role_text(value)
    if not display:
        raise PersonRoleTextError("role text is empty")
    if len(display) > ROLE_TEXT_MAX:
        raise PersonRoleTextError("role text is too long")
    return display, display.casefold()


def role_context_identity(value: str | None) -> tuple[str | None, str]:
    display = collapse_role_text(value)
    if not display:
        return None, ""
    if len(display) > CONTEXT_TEXT_MAX:
        raise PersonRoleTextError("context text is too long")
    return display, display.casefold()


def role_search_key(value: str | None) -> str | None:
    """Return a lexical search key, or None when the query is empty or not a role term."""
    display = collapse_role_text(value)
    if not display or len(display) > ROLE_TEXT_MAX:
        return None
    return display.casefold()
