"""Deterministic normalization for exact Person provider identities.

Display names are not strong keys. This module does not call a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from app.connectors.mattermost.errors import MattermostSecurityError
from app.connectors.mattermost.normalize import normalize_server_url

EMAIL_IDENTITY = "email"
MATTERMOST_USER_ID = "mattermost_user_id"
MATTERMOST_USERNAME = "mattermost_username"
TEAMS_USER_ID = "teams_user_id"
TELEGRAM_USER_ID = "telegram_user_id"

EMAIL_PROVIDER = "email"
MATTERMOST_PROVIDER = "mattermost"
TEAMS_PROVIDER = "teams"
TELEGRAM_MTPROTO_PROVIDER = "telegram_mtproto"

_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
_ANGLE_EMAIL_RE = re.compile(r"<([^<>]+)>")
_MATTERMOST_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_MAX_VALUE_CHARS = 320
_MAX_REALM_CHARS = 512
_MAX_DISPLAY_CHARS = 200


class PersonIdentityInputError(ValueError):
    """Malformed identity input. Fail closed."""


@dataclass(frozen=True)
class NormalizedPersonIdentity:
    identity_type: str
    provider: str
    realm: str
    canonical_value: str
    display_value: str | None = None


def normalize_email(raw: str, *, display_value: str | None = None) -> NormalizedPersonIdentity:
    extracted = _angle_or_plain(raw)
    canonical = extracted.casefold()
    if not _EMAIL_RE.fullmatch(canonical) or len(canonical) > _MAX_VALUE_CHARS:
        raise PersonIdentityInputError("email identity is malformed")
    display = display_value if display_value is not None else _envelope_name(raw)
    return NormalizedPersonIdentity(
        identity_type=EMAIL_IDENTITY,
        provider=EMAIL_PROVIDER,
        realm="",
        canonical_value=canonical,
        display_value=_bound_display(display),
    )


def normalize_mattermost_user_id(
    server_url: str,
    user_id: str,
    *,
    display_value: str | None = None,
) -> NormalizedPersonIdentity:
    realm = _mattermost_realm(server_url)
    canonical = str(user_id).strip()
    if not canonical or any(char.isspace() for char in canonical) or len(canonical) > _MAX_VALUE_CHARS:
        raise PersonIdentityInputError("mattermost user id is malformed")
    return NormalizedPersonIdentity(
        identity_type=MATTERMOST_USER_ID,
        provider=MATTERMOST_PROVIDER,
        realm=realm,
        canonical_value=canonical,
        display_value=_bound_display(display_value),
    )


def normalize_mattermost_username(
    server_url: str,
    username: str,
    *,
    display_value: str | None = None,
) -> NormalizedPersonIdentity:
    realm = _mattermost_realm(server_url)
    canonical = str(username).strip().casefold()
    if not _MATTERMOST_USERNAME_RE.fullmatch(canonical):
        raise PersonIdentityInputError("mattermost username is malformed")
    return NormalizedPersonIdentity(
        identity_type=MATTERMOST_USERNAME,
        provider=MATTERMOST_PROVIDER,
        realm=realm,
        canonical_value=canonical,
        display_value=_bound_display(display_value),
    )


def normalize_teams_user_id(
    tenant_id: str,
    sender_id: str,
    *,
    display_value: str | None = None,
) -> NormalizedPersonIdentity:
    realm = _microsoft_guid(tenant_id, "teams tenant id")
    canonical = _microsoft_guid(sender_id, "teams user id")
    return NormalizedPersonIdentity(
        identity_type=TEAMS_USER_ID,
        provider=TEAMS_PROVIDER,
        realm=realm,
        canonical_value=canonical,
        display_value=_bound_display(display_value),
    )


def normalize_telegram_user_id(
    account_realm: str,
    sender_peer_id: object,
    *,
    display_value: str | None = None,
) -> NormalizedPersonIdentity:
    realm = str(account_realm).strip()
    if not realm or any(char.isspace() for char in realm) or len(realm) > _MAX_REALM_CHARS:
        raise PersonIdentityInputError("telegram account realm is malformed")
    text = str(sender_peer_id).strip()
    if not text or text in {"+", "-"}:
        raise PersonIdentityInputError("telegram sender peer id is malformed")
    sign = ""
    digits = text
    if text[0] in "+-":
        if text[0] == "-":
            sign = "-"
        digits = text[1:]
    if not digits.isdigit():
        raise PersonIdentityInputError("telegram sender peer id is malformed")
    canonical = f"{sign}{int(digits)}"
    if canonical in {"", "-0"}:
        raise PersonIdentityInputError("telegram sender peer id is malformed")
    return NormalizedPersonIdentity(
        identity_type=TELEGRAM_USER_ID,
        provider=TELEGRAM_MTPROTO_PROVIDER,
        realm=realm,
        canonical_value=canonical,
        display_value=_bound_display(display_value),
    )


def _envelope_name(raw: str) -> str | None:
    text = str(raw or "")
    if "<" not in text:
        return None
    name = text.split("<", 1)[0].strip().strip('"')
    return name or None


def _angle_or_plain(raw: str) -> str:
    text = str(raw or "").strip()
    if not text or len(text) > _MAX_VALUE_CHARS + 80:
        raise PersonIdentityInputError("email identity is malformed")
    match = _ANGLE_EMAIL_RE.search(text)
    return (match.group(1) if match else text).strip()


def _mattermost_realm(server_url: str) -> str:
    try:
        realm = normalize_server_url(str(server_url))
    except MattermostSecurityError as exc:
        raise PersonIdentityInputError("mattermost server realm is malformed") from exc
    if len(realm) > _MAX_REALM_CHARS:
        raise PersonIdentityInputError("mattermost server realm is malformed")
    return realm


def _microsoft_guid(value: object, label: str) -> str:
    text = str(value or "").strip()
    try:
        return str(UUID(text))
    except ValueError as exc:
        raise PersonIdentityInputError(f"{label} is malformed") from exc


def _bound_display(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > _MAX_DISPLAY_CHARS:
        raise PersonIdentityInputError("display value is too long")
    return text
