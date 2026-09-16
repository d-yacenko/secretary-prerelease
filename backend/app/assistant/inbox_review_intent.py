"""Deterministic Inbox review vs inspect utterance contract.

Voice/typed complete enumeration of everything new is purpose=review.
Count/peek questions are purpose=inspect and never a completion receipt.
"""

from __future__ import annotations

import re

COMPLETE_INBOX_REVIEW_UTTERANCES: tuple[str, ...] = (
    "перечисли все новые сообщения",
    "назови все новые сообщения",
    "прочти все новые сообщения",
    "что нового — перечисли всё",
)

INSPECT_INBOX_REVIEW_UTTERANCES: tuple[str, ...] = (
    "сколько новых?",
    "сколько новых сообщений?",
    "покажи последние два",
    "есть что-нибудь новое?",
)

_PUNCT_RE = re.compile(r"[?!.,;:]+")
_DASH_RE = re.compile(r"[—–−-]+")
_REVIEW_VERB = r"(?:перечисли|назови|прочти|прочитай)"
_HARMLESS_FILLER = r"(?:мне|пожалуйста|давай|ну)"
_REVIEW_ALL_NEW_RE = re.compile(
    rf"{_REVIEW_VERB}(?: {_HARMLESS_FILLER})* все новые сообщения"
)
_WHAT_NEW_ENUMERATE_RE = re.compile(r"что нового перечисли все")
_COUNT_NEW_RE = re.compile(r"сколько(?: (?:у меня|сейчас))* новых сообщений")


def normalize_inbox_review_utterance(text: str) -> str:
    lowered = text.strip().lower().replace("ё", "е")
    lowered = _DASH_RE.sub(" ", lowered)
    lowered = _PUNCT_RE.sub(" ", lowered)
    return " ".join(lowered.split())


def inbox_review_purpose_for_utterance(text: str) -> str | None:
    """Return review/inspect for explicit contract phrases; otherwise None."""
    normalized = normalize_inbox_review_utterance(text)
    if not normalized:
        return None
    inspect_forms = tuple(
        normalize_inbox_review_utterance(phrase) for phrase in INSPECT_INBOX_REVIEW_UTTERANCES
    )
    if _requests_complete_review(normalized):
        return "review"
    if _COUNT_NEW_RE.search(normalized):
        return "inspect"
    if normalized in inspect_forms:
        return "inspect"
    if any(form and form in normalized for form in inspect_forms):
        return "inspect"
    return None


def _requests_complete_review(normalized: str) -> bool:
    return (
        _REVIEW_ALL_NEW_RE.search(normalized) is not None
        or _WHAT_NEW_ENUMERATE_RE.search(normalized) is not None
    )


def format_complete_review_utterance_list() -> str:
    quoted = ", ".join(f"«{phrase}»" for phrase in COMPLETE_INBOX_REVIEW_UTTERANCES)
    return quoted


def format_inspect_utterance_list() -> str:
    quoted = ", ".join(f"«{phrase}»" for phrase in INSPECT_INBOX_REVIEW_UTTERANCES)
    return quoted
