"""Bounds for Assistant-facing Person resolution.

Salience orders ambiguous candidates. It does not choose one of them.
"""

from __future__ import annotations

from app.domain.person_identity import (
    EMAIL_IDENTITY,
    EMAIL_PROVIDER,
    MATTERMOST_PROVIDER,
    MATTERMOST_USER_ID,
    MATTERMOST_USERNAME,
    TEAMS_PROVIDER,
    TEAMS_USER_ID,
    TELEGRAM_MTPROTO_PROVIDER,
    TELEGRAM_USER_ID,
    NormalizedPersonIdentity,
    PersonIdentityInputError,
    normalize_email,
    normalize_mattermost_user_id,
    normalize_mattermost_username,
    normalize_teams_user_id,
    normalize_telegram_user_id,
)

MAX_PERSON_CANDIDATES = 5
MAX_PERSON_ROUTES = 8
MAX_IDENTITIES_PER_PERSON = 8
MAX_PERSON_MESSAGES = 10
PERSON_LOOKBACK_DAYS = 90
PERSON_SCAN_CHUNK = 40
MAX_PERSON_SCAN = PERSON_SCAN_CHUNK
MAX_PERSON_SCAN_ROWS = PERSON_SCAN_CHUNK * 10

RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"
NONE = "none"


def parse_feedback_identity(
    identity_type: str,
    provider: str,
    realm: str,
    canonical_value: str,
) -> NormalizedPersonIdentity:
    """Normalize a model-supplied identity tuple. Malformed input fails closed."""
    if identity_type == EMAIL_IDENTITY and provider == EMAIL_PROVIDER:
        return normalize_email(canonical_value)
    if provider == MATTERMOST_PROVIDER and identity_type == MATTERMOST_USER_ID:
        return normalize_mattermost_user_id(realm, canonical_value)
    if provider == MATTERMOST_PROVIDER and identity_type == MATTERMOST_USERNAME:
        return normalize_mattermost_username(realm, canonical_value)
    if provider == TEAMS_PROVIDER and identity_type == TEAMS_USER_ID:
        return normalize_teams_user_id(realm, canonical_value)
    if provider == TELEGRAM_MTPROTO_PROVIDER and identity_type == TELEGRAM_USER_ID:
        return normalize_telegram_user_id(realm, canonical_value)
    raise PersonIdentityInputError("identity tuple is not a supported exact identity")


def feedback_identity_key(identity: NormalizedPersonIdentity) -> tuple[str, str, str, str]:
    return (identity.identity_type, identity.provider, identity.realm, identity.canonical_value)
