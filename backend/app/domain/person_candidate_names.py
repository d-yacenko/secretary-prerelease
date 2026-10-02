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


_GIVEN_NAME_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset(
        {
            "ольга",
            "ольги",
            "ольге",
            "ольгу",
            "ольгой",
            "оля",
            "оли",
            "оле",
            "олю",
            "олей",
        }
    ),
)


def ordered_name_tokens(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(token.casefold() for token in _TOKEN_RE.findall(value) if token)


def name_variant_match(query: str | None, candidate: str | None) -> bool:
    """True only for an explicit given-name family with the same surname.

    A two-token query whose given name and surname already equal the candidate
    is an exact name, not a variant.
    """
    left = ordered_name_tokens(query)
    right = ordered_name_tokens(candidate)
    if len(left) != 2 or len(right) != 2 or left[1] != right[1] or left[0] == right[0]:
        return False
    return any(left[0] in family and right[0] in family for family in _GIVEN_NAME_FAMILIES)
