"""Stored communication participants that can back a role-import Person candidate.

This scan is role-import only. It does not change generic direct-contact promotion.
A participant qualifies only with a non-empty display name and an exact attachable
identity already stored on the communication. Body text, subjects, and channel
titles are not identities.
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

_EMAIL_KEYS = ("sender", "from", "reply_to")
_HEADER_EMAIL_KEYS = ("from", "reply-to", "sender")


def participant_identities(
    source: Object,
    *,
    self_identity_keys: set[tuple[str, str, str, str]],
) -> tuple[NormalizedPersonIdentity, ...]:
    metadata = source.metadata_ if isinstance(source.metadata_, Mapping) else {}
    if source.provider in {"gmail", "yandex_mail"} and source.kind == "email":
        identities = _email_participants(metadata)
    elif source.provider == "mattermost" and source.kind == "chat_message":
        identities = _mattermost_participant(metadata)
    elif source.provider == "teams" and source.kind == "chat_message":
        identities = _teams_participant(metadata)
    elif source.provider == "telegram" and source.kind == "chat_message":
        identities = _telegram_participant(metadata)
    else:
        identities = []
    found: list[NormalizedPersonIdentity] = []
    seen: set[tuple[str, str, str, str]] = set()
    for identity in identities:
        if not _display(identity.display_value):
            continue
        key = (identity.provider, identity.identity_type, identity.realm, identity.canonical_value)
        if key in seen or key in self_identity_keys:
            continue
        seen.add(key)
        found.append(identity)
    return tuple(found)


def _email_participants(metadata: Mapping[str, Any]) -> list[NormalizedPersonIdentity]:
    values: list[str] = []
    for key in _EMAIL_KEYS:
        values.extend(_email_parts(metadata.get(key)))
    recipients = metadata.get("recipients")
    if recipients is None:
        recipients = metadata.get("to")
    values.extend(_email_parts(recipients))
    values.extend(_email_parts(metadata.get("cc")))
    headers = metadata.get("headers")
    if isinstance(headers, Mapping):
        for key in _HEADER_EMAIL_KEYS:
            values.extend(_email_parts(headers.get(key)))
    results: list[NormalizedPersonIdentity] = []
    for value in values:
        display = _envelope_display(value)
        if display is None:
            continue
        try:
            results.append(normalize_email(value, display_value=display))
        except PersonIdentityInputError:
            continue
    results.extend(_structured_email_participants(metadata.get("to_participants")))
    results.extend(_structured_email_participants(metadata.get("cc_participants")))
    return results


def _structured_email_participants(items: object) -> list[NormalizedPersonIdentity]:
    if not isinstance(items, list):
        return []
    results: list[NormalizedPersonIdentity] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        address = item.get("address")
        display_name = item.get("display_name")
        if not isinstance(address, str) or not isinstance(display_name, str):
            continue
        display = " ".join(display_name.split())
        if not address.strip() or not display:
            continue
        try:
            results.append(normalize_email(address, display_value=display))
        except PersonIdentityInputError:
            continue
    return results


def _email_parts(value: object) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _envelope_display(value: str) -> str | None:
    if "<" not in value:
        return None
    name = value.split("<", 1)[0].strip().strip('"')
    return name or None


def _mattermost_participant(metadata: Mapping[str, Any]) -> list[NormalizedPersonIdentity]:
    server_url = metadata.get("server_url")
    if not isinstance(server_url, str) or not server_url.strip():
        return []
    display = _text(metadata.get("author_display_name"))
    if display is None:
        return []
    author = _text(metadata.get("author_user_id"))
    if author is not None:
        try:
            return [normalize_mattermost_user_id(server_url, author, display_value=display)]
        except PersonIdentityInputError:
            return []
    username = _text(metadata.get("author_username"))
    if username is None:
        return []
    try:
        return [normalize_mattermost_username(server_url, username, display_value=display)]
    except PersonIdentityInputError:
        return []


def _teams_participant(metadata: Mapping[str, Any]) -> list[NormalizedPersonIdentity]:
    if metadata.get("sender_kind") != "user":
        return []
    display = _text(metadata.get("sender_display_name"))
    tenant_id = metadata.get("tenant_id")
    sender_id = metadata.get("sender_id")
    if display is None or not isinstance(tenant_id, str) or not isinstance(sender_id, str):
        return []
    try:
        return [normalize_teams_user_id(tenant_id, sender_id, display_value=display)]
    except PersonIdentityInputError:
        return []


def _telegram_participant(metadata: Mapping[str, Any]) -> list[NormalizedPersonIdentity]:
    if metadata.get("transport") != "mtproto":
        return []
    account_id = metadata.get("account_id")
    if not isinstance(account_id, str) or not account_id.strip():
        return []
    if metadata.get("direction") == "outbound":
        if metadata.get("peer_kind") != "private":
            return []
        return _telegram_user(
            account_id,
            metadata.get("peer_id"),
            _text(metadata.get("peer_title")) or _text(metadata.get("peer_display_name")),
        )
    return _telegram_user(
        account_id,
        metadata.get("sender_peer_id"),
        _text(metadata.get("sender_display_name")),
    )


def _telegram_user(
    account_id: str,
    raw_id: object,
    display: str | None,
) -> list[NormalizedPersonIdentity]:
    if display is None:
        return []
    try:
        return [normalize_telegram_user_id(account_id, raw_id, display_value=display)]
    except PersonIdentityInputError:
        return []


def _display(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
