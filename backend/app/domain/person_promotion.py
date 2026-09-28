"""Direct exact-identity eligibility for assisted Person promotion.

A qualifying row is not a Person. Display-name similarity is not authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from app.connectors.mattermost.errors import MattermostSecurityError
from app.connectors.mattermost.normalize import normalize_server_url
from app.db.models import MattermostAccount, Object
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
    if source.kind == "chat_message" and source.provider == "teams":
        return _direct_chat(source, _teams_direct(metadata))
    if source.kind == "chat_message" and source.provider == "telegram":
        return _direct_chat(source, _telegram_direct(metadata))
    return None


_AUTOMATED_LOCAL_COMPACT = frozenset(
    {
        "noreply",
        "donotreply",
        "mailerdaemon",
        "postmaster",
        "calendarnotification",
    }
)


def _direct_email(provider: str, metadata: Mapping) -> NormalizedPersonIdentity | None:
    if _email_direction(provider, dict(metadata)) != "inbound":
        return None
    if len(_email_audience(dict(metadata))) != 1:
        return None
    if _has_list_id(metadata):
        return None
    raw = metadata.get("sender") or metadata.get("from")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        identity = normalize_email(raw)
    except PersonIdentityInputError:
        return None
    if _automated_email_local_part(identity.canonical_value):
        return None
    return identity


def _has_list_id(metadata: Mapping) -> bool:
    headers = metadata.get("headers")
    if not isinstance(headers, Mapping):
        return False
    value = headers.get("list-id")
    return isinstance(value, str) and bool(value.strip())


def _automated_email_local_part(canonical: str) -> bool:
    local = canonical.split("@", 1)[0].casefold()
    compact = local.replace("-", "").replace("_", "").replace(".", "")
    return compact in _AUTOMATED_LOCAL_COMPACT


def mattermost_remote_identity(
    source: Object,
    account: MattermostAccount | None,
) -> NormalizedPersonIdentity | None:
    """Qualify a Mattermost DM only when stored account facts prove a remote author."""
    if source.provider != "mattermost" or source.kind != "chat_message":
        return None
    metadata = source.metadata_ if isinstance(source.metadata_, Mapping) else {}
    if metadata.get("channel_type") != "D":
        return None
    account_id = _uuid(metadata.get("account_id"))
    if account is None or account_id is None or account.id != account_id:
        return None
    if account.user_id != source.user_id:
        return None
    author = metadata.get("author_user_id")
    remote = account.remote_user_id
    if not isinstance(author, str) or not author.strip():
        return None
    if not isinstance(remote, str) or not remote.strip() or author.strip() == remote.strip():
        return None
    try:
        message_realm = normalize_server_url(str(metadata.get("server_url") or ""))
        account_realm = normalize_server_url(account.server_url)
    except MattermostSecurityError:
        return None
    if message_realm != account_realm:
        return None
    identities = [
        item
        for item in extract_person_identity_evidence(source)
        if item.identity_type == MATTERMOST_USER_ID and item.canonical_value == author.strip()
    ]
    if len(identities) != 1:
        return None
    return identities[0]


def _uuid(value: object) -> UUID | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


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
