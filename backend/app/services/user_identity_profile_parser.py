from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.user_identity_constants import (
    MAX_ALIAS_ITEMS,
    MAX_FULL_NAME_CHARS,
    MAX_IDENTITY_LIST_ITEM_CHARS,
    MAX_IDENTITY_LIST_ITEMS,
    MAX_PREFERRED_NAME_CHARS,
)

_SECTION_ALIASES = {
    "имя": "full_name",
    "как ко мне обращаться": "preferred_name",
    "варианты имени": "aliases",
    "должности": "roles",
    "организации": "organizations",
    "email": "emails",
    "e-mail": "emails",
    "телефон": "phones",
    "telegram": "telegram",
    "другие идентификаторы": "other_identifiers",
}

_INLINE_SECTIONS = {"aliases"}
_LIST_SECTIONS = {
    "roles",
    "organizations",
    "emails",
    "phones",
    "telegram",
    "other_identifiers",
}
_SCALAR_SECTIONS = {"full_name", "preferred_name"}


@dataclass(frozen=True)
class ParsedIdentityProfile:
    full_name: str | None = None
    preferred_name: str | None = None
    aliases: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    telegram: list[str] = field(default_factory=list)
    other_identifiers: list[str] = field(default_factory=list)


def parse_profile_text(profile_text: str) -> ParsedIdentityProfile:
    normalized = profile_text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return ParsedIdentityProfile()

    scalars: dict[str, str | None] = {
        "full_name": None,
        "preferred_name": None,
    }
    lists: dict[str, list[str]] = {
        "aliases": [],
        "roles": [],
        "organizations": [],
        "emails": [],
        "phones": [],
        "telegram": [],
        "other_identifiers": [],
    }

    current_section: str | None = None
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            current_section = None
            continue

        header_match = re.match(r"^([^:]+):\s*(.*)$", line)
        if header_match is not None:
            header_key = header_match.group(1).strip().casefold()
            section = _SECTION_ALIASES.get(header_key)
            if section is not None:
                current_section = section
                remainder = header_match.group(2).strip()
                if section in _SCALAR_SECTIONS:
                    scalars[section] = _bound_scalar(section, remainder or None)
                elif section in _INLINE_SECTIONS:
                    lists[section].extend(_split_inline_items(remainder))
                elif remainder:
                    lists[section].append(_bound_list_item(remainder))
                continue

        if current_section is None:
            continue
        if current_section in _SCALAR_SECTIONS:
            existing = scalars[current_section]
            joined = f"{existing} {line}".strip() if existing else line
            scalars[current_section] = _bound_scalar(current_section, joined)
            continue
        item = line[2:].strip() if line.startswith("- ") else line.strip()
        if item:
            lists[current_section].append(_bound_list_item(item))

    return ParsedIdentityProfile(
        full_name=scalars["full_name"],
        preferred_name=scalars["preferred_name"],
        aliases=_bound_list("aliases", lists["aliases"]),
        roles=_bound_list("roles", lists["roles"]),
        organizations=_bound_list("organizations", lists["organizations"]),
        emails=_bound_list("emails", lists["emails"]),
        phones=_bound_list("phones", lists["phones"]),
        telegram=_bound_list("telegram", lists["telegram"]),
        other_identifiers=_bound_list("other_identifiers", lists["other_identifiers"]),
    )


def _split_inline_items(value: str) -> list[str]:
    if not value.strip():
        return []
    parts = [part.strip() for part in value.split(",")]
    return [_bound_list_item(part) for part in parts if part]


def _bound_scalar(section: str, value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    limit = MAX_FULL_NAME_CHARS if section == "full_name" else MAX_PREFERRED_NAME_CHARS
    return trimmed[:limit]


def _bound_list_item(value: str) -> str:
    return value.strip()[:MAX_IDENTITY_LIST_ITEM_CHARS]


def _bound_list(section: str, values: list[str]) -> list[str]:
    limit = MAX_ALIAS_ITEMS if section == "aliases" else MAX_IDENTITY_LIST_ITEMS
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized[:MAX_IDENTITY_LIST_ITEM_CHARS])
        if len(deduped) >= limit:
            break
    return deduped
