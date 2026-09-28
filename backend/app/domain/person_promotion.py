"""Direct exact-identity eligibility for assisted Person promotion.

A qualifying row is not a Person. Display-name similarity is not authority.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.db.models import Object
from app.domain.person_identity import (
    MATTERMOST_USER_ID,
    NormalizedPersonIdentity,
    PersonIdentityInputError,
    normalize_email,
)
from app.domain.person_identity_evidence import extract_person_identity_evidence
from app.domain.person_salience import _email_audience, _email_direction

MIN_DIRECT_HITS = 2
MAX_DIRECT_HITS = 8
MAX_PROMOTION_CANDIDATES = 5
MAX_SOURCE_PREVIEWS = 3
REPEATED_DIRECT_CONTACT = "repeated_direct_contact"


def direct_promotion_identity(source: Object) -> NormalizedPersonIdentity | None:
    """Return the one exact remote identity when the row is a direct inbound contact."""
    metadata = source.metadata_ if isinstance(source.metadata_, Mapping) else {}
    if source.kind == "email" and source.provider in {"gmail", "yandex_mail"}:
        return _direct_email(source.provider, metadata)
    if source.kind == "chat_message" and source.provider == "mattermost":
        return _direct_chat(source, _mattermost_direct(metadata))
    if source.kind == "chat_message" and source.provider == "teams":
        return _direct_chat(source, _teams_direct(metadata))
    if source.kind == "chat_message" and source.provider == "telegram":
        return _direct_chat(source, _telegram_direct(metadata))
    return None


def _direct_email(provider: str, metadata: Mapping) -> NormalizedPersonIdentity | None:
    if _email_direction(provider, dict(metadata)) != "inbound":
        return None
    if len(_email_audience(dict(metadata))) != 1:
        return None
    raw = metadata.get("sender") or metadata.get("from")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return normalize_email(raw)
    except PersonIdentityInputError:
        return None


def _mattermost_direct(metadata: Mapping) -> bool:
    return str(metadata.get("channel_type") or "").upper() == "D"


def _teams_direct(metadata: Mapping) -> bool:
    return (
        metadata.get("sender_kind") == "user"
        and metadata.get("direction") == "inbound"
        and metadata.get("chat_type") == "oneOnOne"
    )


def _telegram_direct(metadata: Mapping) -> bool:
    if metadata.get("transport") != "mtproto":
        return False
    if metadata.get("peer_kind") != "private":
        return False
    return metadata.get("direction") != "outbound"


def _direct_chat(source: Object, direct: bool) -> NormalizedPersonIdentity | None:
    if not direct:
        return None
    identities = extract_person_identity_evidence(source)
    if source.provider == "mattermost":
        preferred = [item for item in identities if item.identity_type == MATTERMOST_USER_ID]
        identities = tuple(preferred or identities[:1])
    if len(identities) != 1:
        return None
    identity = identities[0]
    if source.provider != "telegram" or identity.display_value:
        return identity
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    display = _text(metadata.get("sender_display_name")) or _text(metadata.get("peer_title"))
    if display is None:
        return identity
    return NormalizedPersonIdentity(
        identity_type=identity.identity_type,
        provider=identity.provider,
        realm=identity.realm,
        canonical_value=identity.canonical_value,
        display_value=display[:120],
    )


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
