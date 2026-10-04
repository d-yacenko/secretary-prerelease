"""Exact multi-token name mentions for role import. Not an identity."""

from __future__ import annotations

import hashlib
import re

MIN_ROLE_IMPORT_NAME_MENTION_OBJECTS = 2
_KEY_PREFIX = "role-import-name-mention\n"


def mention_display_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def mention_candidate_key(display_name: str) -> str:
    """Opaque key for a name-only candidate. It contains no object id or identity."""
    return hashlib.sha256(f"{_KEY_PREFIX}{mention_display_key(display_name)}".encode()).hexdigest()


def mention_pattern(display_name: str) -> re.Pattern[str] | None:
    """Exact phrase with flexible internal whitespace and Unicode token boundaries.

    A single token is not mention evidence. A hit inside a longer token is not a hit.
    """
    tokens = mention_display_key(display_name).split(" ")
    if len(tokens) < 2:
        return None
    body = r"\s+".join(re.escape(token) for token in tokens)
    return re.compile(rf"(?<!\w){body}(?!\w)")


def text_mentions_name(pattern: re.Pattern[str], value: str | None) -> bool:
    if not value:
        return False
    return pattern.search(mention_display_key(value)) is not None
