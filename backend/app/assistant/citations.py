import re
from uuid import UUID

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_MARKDOWN_CITATION = re.compile(rf"\[([^\]]+)\]\(secretary://object/({_UUID})\)")
_BARE_CITATION = re.compile(rf"secretary://object/({_UUID})")
_MALFORMED_CITATION = re.compile(rf"secretary://object/(?!{_UUID}(?:\b|$))[^\s)]*")


def extract_cited_object_ids(answer: str) -> list[UUID]:
    found: list[UUID] = []
    seen: set[UUID] = set()
    for match in _BARE_CITATION.finditer(answer):
        object_id = UUID(match.group(1))
        if object_id in seen:
            continue
        seen.add(object_id)
        found.append(object_id)
    return found


def neutralize_unproven_citations(answer: str, allowed: set[UUID]) -> str:
    """Keep only secretary://object links whose ids were exposed this turn."""

    def markdown(match: re.Match[str]) -> str:
        object_id = UUID(match.group(2))
        if object_id in allowed:
            return match.group(0)
        return match.group(1)

    text = _MARKDOWN_CITATION.sub(markdown, answer)

    def bare(match: re.Match[str]) -> str:
        object_id = UUID(match.group(1))
        if object_id in allowed:
            return match.group(0)
        return "object"

    text = _BARE_CITATION.sub(bare, text)
    return _MALFORMED_CITATION.sub("object", text)
