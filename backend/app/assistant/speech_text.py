"""Strip presentation-only Markdown so TTS reads semantic text, not markup."""

from __future__ import annotations

import re

_FENCE_RE = re.compile(r"```(?:[\w.+-]+)?\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_BOLD_RE = re.compile(r"(\*\*|__)(.*?)\1")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^>\s?", re.MULTILINE)
_LIST_RE = re.compile(r"^(\s*)(?:[-*+]|\d+\.)\s+", re.MULTILINE)
_HR_RE = re.compile(r"^\s*([-*_]\s*){3,}\s*$", re.MULTILINE)
_EXTRA_STARS_RE = re.compile(r"[*_`#]+")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def prepare_speech_text(text: str) -> str:
    prepared = text.replace("\r\n", "\n").replace("\r", "\n")
    prepared = _FENCE_RE.sub(lambda match: match.group(1).strip(), prepared)
    prepared = _IMAGE_RE.sub(lambda match: match.group(1).strip(), prepared)
    prepared = _LINK_RE.sub(lambda match: match.group(1).strip(), prepared)
    prepared = _INLINE_CODE_RE.sub(lambda match: match.group(1), prepared)
    prepared = _BOLD_RE.sub(lambda match: match.group(2), prepared)
    prepared = _ITALIC_RE.sub(lambda match: match.group(1) or match.group(2) or "", prepared)
    prepared = _HEADING_RE.sub("", prepared)
    prepared = _BLOCKQUOTE_RE.sub("", prepared)
    prepared = _LIST_RE.sub(r"\1", prepared)
    prepared = _HR_RE.sub("", prepared)
    prepared = _EXTRA_STARS_RE.sub("", prepared)
    prepared = _MULTI_SPACE_RE.sub(" ", prepared)
    prepared = _MULTI_NEWLINE_RE.sub("\n\n", prepared)
    return prepared.strip()
