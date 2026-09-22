"""Project current-user participation from normalized Object metadata.

Output is factual provider-neutral roles only. No relationship/dependency
inference. No fuzzy name matching. No body keyword scans.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any

from app.connectors.teams.id_token import try_canonical_microsoft_guid
from app.db.models import Object
from app.personal_relevance.models import (
    PERSONAL_RELEVANCE_MAX_ATTENDEES,
    PERSONAL_RELEVANCE_MAX_EMAIL_ADDRESSES,
    PERSONAL_RELEVANCE_MAX_MENTIONS,
    PERSONAL_RELEVANCE_MAX_PARTICIPATION_ROLES,
    USER_PARTICIPATION_ROLES,
)

_EMAIL_PROVIDERS = frozenset({"gmail", "yandex_mail"})
_CALENDAR_PROVIDERS = frozenset({"google_calendar", "yandex_calendar"})
_INTERNAL_AUTHOR_KINDS = frozenset({"task", "note"})


@dataclass(frozen=True)
class ParticipationIdentity:
    emails: frozenset[str]
    mattermost_user_ids: frozenset[str]
    mattermost_usernames: frozenset[str]
    has_google_account: bool
    has_yandex_calendar_account: bool
    telegram_user_ids: frozenset[str] = frozenset()
    teams_user_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ParticipationEvidence:
    roles: tuple[str, ...]
    truncated: bool = False


def extract_email_address(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    _, addr = parseaddr(stripped)
    candidate = (addr or "").strip()
    if not candidate and "@" in stripped and "<" not in stripped:
        candidate = stripped
    candidate = candidate.strip().strip("<>").strip()
    if "@" not in candidate or any(ch.isspace() for ch in candidate):
        return None
    local, _, domain = candidate.partition("@")
    if not local or not domain or "." not in domain:
        return None
    return candidate.casefold()


def current_user_participation(
    obj: Object,
    identity: ParticipationIdentity,
) -> ParticipationEvidence:
    roles: set[str] = set()
    truncated = False
    metadata = obj.metadata_ if isinstance(obj.metadata_, dict) else {}
    provider = obj.provider

    if obj.origin == "user" and obj.kind in _INTERNAL_AUTHOR_KINDS:
        roles.add("author")

    if provider in _EMAIL_PROVIDERS:
        sender = extract_email_address(metadata.get("sender"))
        if sender is not None and sender in identity.emails:
            roles.add("sender")
        recipients, recipients_truncated = bounded_string_items(
            metadata.get("recipients"), PERSONAL_RELEVANCE_MAX_EMAIL_ADDRESSES
        )
        truncated = truncated or recipients_truncated
        for recipient in recipients:
            email = extract_email_address(recipient)
            if email is not None and email in identity.emails:
                roles.add("direct_recipient")
                break
        copied, cc_truncated = bounded_string_items(
            metadata.get("cc"), PERSONAL_RELEVANCE_MAX_EMAIL_ADDRESSES
        )
        truncated = truncated or cc_truncated
        for item in copied:
            email = extract_email_address(item)
            if email is not None and email in identity.emails:
                roles.add("copied_recipient")
                break

    if provider in _CALENDAR_PROVIDERS:
        organizer = extract_email_address(metadata.get("organizer"))
        if organizer is not None and organizer in identity.emails:
            roles.add("organizer")
        if _truthy_flag(metadata.get("organizer_self")) and _calendar_self_trusted(
            provider, identity
        ):
            roles.add("organizer")
        attendees, attendees_truncated = bounded_attendee_entries(
            metadata.get("attendees"), PERSONAL_RELEVANCE_MAX_ATTENDEES
        )
        truncated = truncated or attendees_truncated or _truthy_flag(
            metadata.get("attendees_truncated")
        )
        for attendee in attendees:
            email = extract_email_address(attendee.get("email"))
            self_flag = _truthy_flag(attendee.get("self"))
            if (email is not None and email in identity.emails) or (
                self_flag and _calendar_self_trusted(provider, identity)
            ):
                roles.add("attendee")
            if self_flag and _truthy_flag(attendee.get("organizer")) and _calendar_self_trusted(
                provider, identity
            ):
                roles.add("organizer")

    if provider == "mattermost":
        author_user_id = _scalar_str(metadata.get("author_user_id"))
        if author_user_id and author_user_id in identity.mattermost_user_ids:
            roles.add("author")
        author_username = _scalar_str(metadata.get("author_username"))
        if author_username and author_username.casefold() in identity.mattermost_usernames:
            roles.add("author")
        mentions, mentions_truncated = bounded_string_items(
            metadata.get("mentioned_user_ids"), PERSONAL_RELEVANCE_MAX_MENTIONS
        )
        truncated = truncated or mentions_truncated or _truthy_flag(
            metadata.get("mentioned_user_ids_truncated")
        )
        for mention in mentions:
            if mention in identity.mattermost_user_ids:
                roles.add("mentioned")
                break
        mention_names, names_truncated = bounded_string_items(
            metadata.get("mentioned_usernames"), PERSONAL_RELEVANCE_MAX_MENTIONS
        )
        truncated = truncated or names_truncated
        for mention in mention_names:
            if mention.casefold() in identity.mattermost_usernames:
                roles.add("mentioned")
                break

    if provider == "telegram":
        business_user_id = _scalar_str(metadata.get("business_user_id"))
        sender_id = _scalar_str(metadata.get("from_user_id"))
        direction = _scalar_str(metadata.get("direction"))
        if metadata.get("transport") == "mtproto":
            sender_id = _id_token(metadata.get("sender_peer_id"))
            peer_kind = _scalar_str(metadata.get("peer_kind"))
            if identity.telegram_user_ids:
                if sender_id in identity.telegram_user_ids and direction == "outbound":
                    roles.add("sender")
                elif (
                    direction == "inbound"
                    and peer_kind == "private"
                    and sender_id is not None
                    and sender_id not in identity.telegram_user_ids
                ):
                    roles.add("direct_recipient")
        elif business_user_id in identity.telegram_user_ids:
            if sender_id == business_user_id and direction == "outbound":
                roles.add("sender")
            elif sender_id and sender_id != business_user_id and direction == "inbound":
                roles.add("direct_recipient")

    if provider == "teams":
        teams_user_id = _scalar_str(metadata.get("teams_user_id"))
        sender_id = _scalar_str(metadata.get("sender_id"))
        direction = _scalar_str(metadata.get("direction"))
        canonical_self_id = try_canonical_microsoft_guid(teams_user_id)
        connected_teams_ids = {
            try_canonical_microsoft_guid(item) for item in identity.teams_user_ids
        }
        if canonical_self_id is not None and canonical_self_id in connected_teams_ids:
            canonical_sender_id = try_canonical_microsoft_guid(sender_id)
            if canonical_sender_id == canonical_self_id and direction == "outbound":
                roles.add("sender")
            elif (
                sender_id
                and canonical_sender_id != canonical_self_id
                and direction == "inbound"
            ):
                roles.add("direct_recipient")

    ordered = [role for role in USER_PARTICIPATION_ROLES if role in roles]
    if len(ordered) > PERSONAL_RELEVANCE_MAX_PARTICIPATION_ROLES:
        truncated = True
        ordered = ordered[:PERSONAL_RELEVANCE_MAX_PARTICIPATION_ROLES]
    return ParticipationEvidence(roles=tuple(ordered), truncated=truncated)


def _calendar_self_trusted(provider: str | None, identity: ParticipationIdentity) -> bool:
    if provider == "google_calendar":
        return identity.has_google_account
    if provider == "yandex_calendar":
        return identity.has_yandex_calendar_account
    return False


def bounded_string_items(value: object, keep_limit: int) -> tuple[list[str], bool]:
    if isinstance(value, str):
        return [value], False
    return _collect_bounded_prefix(
        value,
        keep_limit=keep_limit,
        inspect_limit=keep_limit + 1,
        parse=_string_entry,
    )


def bounded_attendee_entries(
    value: object, keep_limit: int
) -> tuple[list[dict[str, Any]], bool]:
    return _collect_bounded_prefix(
        value,
        keep_limit=keep_limit,
        inspect_limit=keep_limit + 1,
        parse=_attendee_entry,
    )


def _string_entry(item: object) -> str | None:
    return item if isinstance(item, str) else None


def _attendee_entry(item: object) -> dict[str, Any] | None:
    if isinstance(item, dict):
        return item
    if isinstance(item, str):
        return {"email": item}
    return None


def _collect_bounded_prefix(
    value: object,
    *,
    keep_limit: int,
    inspect_limit: int,
    parse,
) -> tuple[list, bool]:
    iterator = _collection_iter(value)
    if iterator is None:
        return [], False
    kept: list = []
    truncated = False
    for raw_seen, item in enumerate(iterator, start=1):
        if len(kept) >= keep_limit:
            truncated = True
            break
        parsed = parse(item)
        if parsed is not None:
            kept.append(parsed)
        if raw_seen >= inspect_limit:
            truncated = True
            break
    return kept, truncated


def _collection_iter(value: object):
    if value is None or isinstance(value, (str, bytes, bytearray, dict)):
        return None
    try:
        return iter(value)
    except TypeError:
        return None


def _scalar_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _id_token(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    return _scalar_str(value)


def _truthy_flag(value: object) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "1", "yes"}
    return False
