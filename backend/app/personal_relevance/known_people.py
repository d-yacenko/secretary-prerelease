"""Exact known-Person positions on a source object.

Positions are factual source roles only. This module does not match names,
rank People, or read the database.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.db.models import Object
from app.domain.person_identity import (
    NormalizedPersonIdentity,
    PersonIdentityInputError,
    normalize_email,
    normalize_mattermost_user_id,
    normalize_mattermost_username,
    normalize_teams_user_id,
    normalize_telegram_user_id,
)
from app.personal_relevance.models import (
    KNOWN_PERSON_SOURCE_ROLES,
    PERSONAL_RELEVANCE_MAX_ATTENDEES,
    PERSONAL_RELEVANCE_MAX_EMAIL_ADDRESSES,
    PERSONAL_RELEVANCE_MAX_MENTIONS,
)
from app.services.user_participation_evidence_service import (
    bounded_attendee_entries,
    bounded_string_items,
)

_EMAIL_PROVIDERS = frozenset({"gmail", "yandex_mail"})
_CALENDAR_PROVIDERS = frozenset({"google_calendar", "yandex_calendar"})


def extract_known_person_positions(
    obj: Object,
) -> tuple[tuple[tuple[NormalizedPersonIdentity, tuple[str, ...]], ...], bool]:
    metadata = obj.metadata_ if isinstance(obj.metadata_, Mapping) else {}
    roles_by_key: dict[tuple[str, str, str, str], set[str]] = {}
    identities: dict[tuple[str, str, str, str], NormalizedPersonIdentity] = {}
    truncated = False
    provider = obj.provider

    if provider in _EMAIL_PROVIDERS and obj.kind == "email":
        truncated = _collect_emails(metadata, roles_by_key, identities) or truncated
    elif provider in _CALENDAR_PROVIDERS and obj.kind == "event":
        truncated = _collect_calendar(metadata, roles_by_key, identities) or truncated
    elif provider == "mattermost" and obj.kind == "chat_message":
        truncated = _collect_mattermost(metadata, roles_by_key, identities) or truncated
    elif provider == "telegram" and obj.kind == "chat_message":
        _collect_telegram(metadata, roles_by_key, identities)
    elif provider == "teams" and obj.kind == "chat_message":
        _collect_teams(metadata, roles_by_key, identities)

    ordered = tuple((identities[key], _ordered_roles(roles_by_key[key])) for key in identities)
    return ordered, truncated


def _collect_emails(
    metadata: Mapping[str, Any],
    roles_by_key: dict,
    identities: dict,
) -> bool:
    truncated = False
    for key in ("sender", "from"):
        _add_email(metadata.get(key), "sender", roles_by_key, identities)
    headers = metadata.get("headers")
    if isinstance(headers, Mapping):
        for key in ("from", "sender"):
            _add_email(headers.get(key), "sender", roles_by_key, identities)
    for field, role in (
        ("recipients", "recipient"),
        ("to", "recipient"),
        ("cc", "copied_recipient"),
    ):
        values, field_truncated = bounded_string_items(
            metadata.get(field), PERSONAL_RELEVANCE_MAX_EMAIL_ADDRESSES
        )
        truncated = truncated or field_truncated
        for value in values:
            _add_email(value, role, roles_by_key, identities)
    return truncated


def _collect_calendar(
    metadata: Mapping[str, Any],
    roles_by_key: dict,
    identities: dict,
) -> bool:
    _add_email(metadata.get("organizer"), "organizer", roles_by_key, identities)
    attendees, truncated = bounded_attendee_entries(
        metadata.get("attendees"), PERSONAL_RELEVANCE_MAX_ATTENDEES
    )
    truncated = truncated or _truthy(metadata.get("attendees_truncated"))
    for attendee in attendees:
        _add_email(attendee.get("email"), "attendee", roles_by_key, identities)
    return truncated


def _collect_mattermost(
    metadata: Mapping[str, Any],
    roles_by_key: dict,
    identities: dict,
) -> bool:
    server_url = metadata.get("server_url")
    if not isinstance(server_url, str) or not server_url.strip():
        return False
    truncated = False
    _add_mattermost_id(
        server_url, metadata.get("author_user_id"), "author", roles_by_key, identities
    )
    _add_mattermost_username(
        server_url, metadata.get("author_username"), "author", roles_by_key, identities
    )
    mention_ids, ids_truncated = bounded_string_items(
        metadata.get("mentioned_user_ids"), PERSONAL_RELEVANCE_MAX_MENTIONS
    )
    truncated = truncated or ids_truncated or _truthy(metadata.get("mentioned_user_ids_truncated"))
    for mention in mention_ids:
        _add_mattermost_id(server_url, mention, "mentioned", roles_by_key, identities)
    mention_names, names_truncated = bounded_string_items(
        metadata.get("mentioned_usernames"), PERSONAL_RELEVANCE_MAX_MENTIONS
    )
    truncated = truncated or names_truncated
    for mention in mention_names:
        _add_mattermost_username(server_url, mention, "mentioned", roles_by_key, identities)
    return truncated


def _collect_telegram(metadata: Mapping[str, Any], roles_by_key: dict, identities: dict) -> None:
    if metadata.get("transport") != "mtproto":
        return
    account_id = metadata.get("account_id")
    if not isinstance(account_id, str) or not account_id.strip():
        return
    direction = metadata.get("direction")
    if direction == "inbound":
        _add_telegram(
            account_id, metadata.get("sender_peer_id"), "sender", roles_by_key, identities
        )
    if direction == "outbound" and metadata.get("peer_kind") == "private":
        _add_telegram(
            account_id, metadata.get("peer_id"), "conversation_peer", roles_by_key, identities
        )


def _collect_teams(metadata: Mapping[str, Any], roles_by_key: dict, identities: dict) -> None:
    if metadata.get("sender_kind") != "user" or metadata.get("direction") != "inbound":
        return
    tenant_id = metadata.get("tenant_id")
    sender_id = metadata.get("sender_id")
    if not isinstance(tenant_id, str) or not isinstance(sender_id, str):
        return
    try:
        identity = normalize_teams_user_id(tenant_id, sender_id)
    except PersonIdentityInputError:
        return
    _remember(identity, "sender", roles_by_key, identities)


def _add_email(raw: object, role: str, roles_by_key: dict, identities: dict) -> None:
    if not isinstance(raw, str) or not raw.strip():
        return
    try:
        identity = normalize_email(raw)
    except PersonIdentityInputError:
        return
    _remember(identity, role, roles_by_key, identities)


def _add_mattermost_id(
    server_url: str, raw: object, role: str, roles_by_key: dict, identities: dict
) -> None:
    if not isinstance(raw, str) or not raw.strip():
        return
    try:
        identity = normalize_mattermost_user_id(server_url, raw)
    except PersonIdentityInputError:
        return
    _remember(identity, role, roles_by_key, identities)


def _add_mattermost_username(
    server_url: str, raw: object, role: str, roles_by_key: dict, identities: dict
) -> None:
    if not isinstance(raw, str) or not raw.strip():
        return
    try:
        identity = normalize_mattermost_username(server_url, raw)
    except PersonIdentityInputError:
        return
    _remember(identity, role, roles_by_key, identities)


def _add_telegram(
    account_id: str, raw: object, role: str, roles_by_key: dict, identities: dict
) -> None:
    try:
        identity = normalize_telegram_user_id(account_id, raw)
    except PersonIdentityInputError:
        return
    _remember(identity, role, roles_by_key, identities)


def _remember(
    identity: NormalizedPersonIdentity,
    role: str,
    roles_by_key: dict,
    identities: dict,
) -> None:
    key = (identity.provider, identity.identity_type, identity.realm, identity.canonical_value)
    identities.setdefault(key, identity)
    roles_by_key.setdefault(key, set()).add(role)


def _ordered_roles(roles: set[str]) -> tuple[str, ...]:
    return tuple(role for role in KNOWN_PERSON_SOURCE_ROLES if role in roles)


def _truthy(value: object) -> bool:
    return value is True or value == "true"
