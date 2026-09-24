"""Deterministic display-name comparison for Person candidates.

Equality of a normalized name proposes a candidate. It is not an identity key.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def name_tokens(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(token.casefold() for token in _TOKEN_RE.findall(value) if len(token) >= 3)


def names_match(left: str | None, right: str | None) -> bool:
    left_tokens = name_tokens(left)
    right_tokens = name_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    return left_tokens == right_tokens or left_tokens < right_tokens or right_tokens < left_tokens
