"""Read-only strong identity evidence from communication Object metadata.

Extractors do not create People and do not write the source mapping.
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


def extract_person_identity_evidence(source: Object) -> tuple[NormalizedPersonIdentity, ...]:
    metadata = source.metadata_ if isinstance(source.metadata_, Mapping) else {}
    if source.provider in {"gmail", "yandex_mail"} and source.kind == "email":
        identities = _email_evidence(metadata)
    elif source.provider == "mattermost" and source.kind == "chat_message":
        identities = _mattermost_evidence(metadata)
    elif source.provider == "teams" and source.kind == "chat_message":
        identities = _teams_evidence(metadata)
    elif source.provider == "telegram" and source.kind == "chat_message":
        identities = _telegram_evidence(metadata)
    else:
        identities = []
    found: list[NormalizedPersonIdentity] = []
    seen: set[tuple[str, str, str, str]] = set()
    for identity in identities:
        key = (identity.provider, identity.identity_type, identity.realm, identity.canonical_value)
        if key in seen:
            continue
        seen.add(key)
        found.append(identity)
    return tuple(found)


def _email_evidence(metadata: Mapping[str, Any]) -> list[NormalizedPersonIdentity]:
    results: list[NormalizedPersonIdentity] = []
    for key in _EMAIL_KEYS:
        results.extend(_emails_from_value(metadata.get(key)))
    headers = metadata.get("headers")
    if isinstance(headers, Mapping):
        for key in _HEADER_EMAIL_KEYS:
            results.extend(_emails_from_value(headers.get(key)))
    return results


def _emails_from_value(raw: object) -> list[NormalizedPersonIdentity]:
    if isinstance(raw, list):
        values = raw
    else:
        values = [raw]
    results: list[NormalizedPersonIdentity] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        display = _envelope_display(value)
        try:
            results.append(normalize_email(value, display_value=display))
        except PersonIdentityInputError:
            continue
    return results


def _envelope_display(value: str) -> str | None:
    if "<" not in value:
        return None
    name = value.split("<", 1)[0].strip().strip('"')
    return name or None


def _mattermost_evidence(metadata: Mapping[str, Any]) -> list[NormalizedPersonIdentity]:
    server_url = metadata.get("server_url")
    if not isinstance(server_url, str) or not server_url.strip():
        return []
    display = _text(metadata.get("author_display_name"))
    results: list[NormalizedPersonIdentity] = []
    user_id = metadata.get("author_user_id")
    if isinstance(user_id, str) and user_id.strip():
        try:
            results.append(
                normalize_mattermost_user_id(server_url, user_id, display_value=display)
            )
        except PersonIdentityInputError:
            pass
    username = metadata.get("author_username")
    if isinstance(username, str) and username.strip():
        try:
            results.append(
                normalize_mattermost_username(server_url, username, display_value=display)
            )
        except PersonIdentityInputError:
            pass
    return results


def _teams_evidence(metadata: Mapping[str, Any]) -> list[NormalizedPersonIdentity]:
    if metadata.get("sender_kind") != "user":
        return []
    tenant_id = metadata.get("tenant_id")
    sender_id = metadata.get("sender_id")
    if not isinstance(tenant_id, str) or not isinstance(sender_id, str):
        return []
    try:
        return [
            normalize_teams_user_id(
                tenant_id,
                sender_id,
                display_value=_text(metadata.get("sender_display_name")),
            )
        ]
    except PersonIdentityInputError:
        return []


def _telegram_evidence(metadata: Mapping[str, Any]) -> list[NormalizedPersonIdentity]:
    if metadata.get("transport") != "mtproto":
        return []
    account_id = metadata.get("account_id")
    if not isinstance(account_id, str) or "sender_peer_id" not in metadata:
        return []
    try:
        return [normalize_telegram_user_id(account_id, metadata.get("sender_peer_id"))]
    except PersonIdentityInputError:
        return []


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
