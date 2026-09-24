"""Derived Person salience from existing communication facts.

The score ranks how present a known Person is. It does not decide whether an
object is important, and it does not create People.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.connectors.mattermost.errors import MattermostSecurityError
from app.connectors.mattermost.normalize import normalize_server_url
from app.domain.person_identity import (
    EMAIL_IDENTITY,
    MATTERMOST_USER_ID,
    MATTERMOST_USERNAME,
    TEAMS_USER_ID,
    TELEGRAM_USER_ID,
)

FOCUS = "focus"
KNOWN = "known"
INCIDENTAL = "incidental"

WINDOW_DAYS = 90
MAX_SCAN_ROWS = 200
MAX_DIRECT_HITS = 8
MAX_PUBLIC_HITS = 8
MAX_COMMUNICATION_ROWS = MAX_SCAN_ROWS
MAX_GRAPH_EDGES = 20
MAX_RANKED_PEOPLE = 20
MAX_IDENTITY_ROWS = 500
MAX_ATTENTION_CANDIDATES = 20
MAX_TASK_CANDIDATES = 20
FREQUENCY_CAP = 8
PUBLIC_CAP = 8
DIRECTNESS_CAP = 48
RECIPROCITY_POINTS = 24
ROUTE_CHOICE_POINTS = 8
CONFIRMATION_POINTS = 20
TASK_CALENDAR_POINTS = 16
FOCUS_MIN = 40
KNOWN_MIN = 12
TASK_CALENDAR_KINDS = frozenset({"task", "event", "calendar_event"})
USER_ATTENTION_TYPES = frozenset({"user_route_choice", "user_confirmed"})

_YANDEX_SENT_FOLDERS = frozenset({"sent", "sent items", "sent messages", "отправленные"})
_YANDEX_SENT_SUFFIXES = ("/sent", "/sent items", "/отправленные")
_DIRECT_POINT = 8
_PUBLIC_POINT = 1
_RECENT_DAYS = 7
_MID_DAYS = 30


@dataclass(frozen=True)
class SalienceComponent:
    name: str
    value: int
    reason: str


@dataclass(frozen=True)
class PersonSalience:
    person_id: UUID | None
    score: int
    tier: str
    components: tuple[SalienceComponent, ...]
    eligible: bool
    truncated: bool
    window_days: int
    row_limit: int
    claims_object_importance: bool = False


@dataclass(frozen=True)
class InteractionHit:
    person_id: UUID
    exposure: str
    direction: str
    occurred_at: datetime


def decay_multiplier(occurred_at: datetime, now: datetime) -> int:
    age = now - occurred_at
    if age > timedelta(days=WINDOW_DAYS) or age < timedelta(0):
        return 0
    if age <= timedelta(days=_RECENT_DAYS):
        return 4
    if age <= timedelta(days=_MID_DAYS):
        return 2
    return 1


def score_person(
    person_id: UUID,
    hits: list[InteractionHit],
    *,
    now: datetime,
    route_choice: bool,
    confirmed: bool,
    task_calendar: bool,
    truncated: bool,
) -> PersonSalience:
    directness = 0
    public = 0
    direct_count = 0
    inbound = False
    outbound = False
    best_decay = 0
    for hit in hits:
        if hit.person_id != person_id:
            continue
        decay = decay_multiplier(hit.occurred_at, now)
        if decay == 0:
            continue
        if hit.exposure == "direct":
            direct_count += 1
            directness += _DIRECT_POINT * decay
            best_decay = max(best_decay, decay)
            if hit.direction == "outbound":
                outbound = True
            else:
                inbound = True
        else:
            public += _PUBLIC_POINT * decay
    directness = min(directness, DIRECTNESS_CAP)
    public = min(public, PUBLIC_CAP)
    frequency = min(direct_count, FREQUENCY_CAP) * 2
    reciprocity = RECIPROCITY_POINTS if inbound and outbound else 0
    recency = best_decay * 3
    attention = 0
    attention_reason = "no user attention"
    if confirmed:
        attention += CONFIRMATION_POINTS
        attention_reason = "explicit identity confirmation"
    if route_choice:
        attention += ROUTE_CHOICE_POINTS
        attention_reason = (
            "confirmation and route choice" if confirmed else "route choice"
        )
    task_value = TASK_CALENDAR_POINTS if task_calendar else 0
    components = (
        SalienceComponent("directness", directness, "direct 1:1 interaction"),
        SalienceComponent("reciprocity", reciprocity, "both directions in the window"),
        SalienceComponent("frequency", frequency, "capped direct interactions"),
        SalienceComponent("recency", recency, "decay bucket of the newest direct hit"),
        SalienceComponent("public_exposure", public, "capped group or channel exposure"),
        SalienceComponent("user_attention", attention, attention_reason),
        SalienceComponent(
            "task_calendar",
            task_value,
            "active task or calendar link" if task_calendar else "no task or calendar link",
        ),
    )
    total = min(100, sum(item.value for item in components))
    return PersonSalience(
        person_id=person_id,
        score=total,
        tier=_tier(total),
        components=components,
        eligible=True,
        truncated=truncated,
        window_days=WINDOW_DAYS,
        row_limit=MAX_SCAN_ROWS,
    )


def empty_salience(person_id: UUID | None, *, eligible: bool) -> PersonSalience:
    return PersonSalience(
        person_id=person_id,
        score=0,
        tier=INCIDENTAL,
        components=(),
        eligible=eligible,
        truncated=False,
        window_days=WINDOW_DAYS,
        row_limit=MAX_SCAN_ROWS,
    )


def communication_identity_keys(
    *,
    provider: str | None,
    metadata: dict,
) -> list[tuple[str, str, str]]:
    """Exact identity tuples a message may reference. Display names are omitted."""
    if provider in {"gmail", "yandex_mail"}:
        keys: list[tuple[str, str, str]] = []
        sender = _email_address(metadata.get("sender") or metadata.get("from"))
        if sender is not None:
            keys.append((EMAIL_IDENTITY, "", sender))
        for address in _email_audience(metadata):
            if (EMAIL_IDENTITY, "", address) not in keys:
                keys.append((EMAIL_IDENTITY, "", address))
        return keys
    if provider == "telegram" and metadata.get("transport") == "mtproto":
        realm = _text(metadata.get("account_id"))
        if realm is None:
            return []
        keys = []
        for value in (
            _positive_id(metadata.get("sender_peer_id")),
            _positive_id(metadata.get("peer_id")),
        ):
            if value is None:
                continue
            key = (TELEGRAM_USER_ID, realm, value)
            if key not in keys:
                keys.append(key)
        return keys
    if provider == "teams" and metadata.get("sender_kind") == "user":
        realm = _text(metadata.get("tenant_id"))
        sender = _text(metadata.get("sender_id"))
        if realm is None or sender is None:
            return []
        return [(TEAMS_USER_ID, realm.casefold(), sender.casefold())]
    if provider == "mattermost":
        raw_realm = _text(metadata.get("server_url"))
        if raw_realm is None:
            return []
        try:
            realm = normalize_server_url(raw_realm)
        except MattermostSecurityError:
            return []
        keys = []
        author_id = _text(metadata.get("author_user_id"))
        if author_id is not None:
            keys.append((MATTERMOST_USER_ID, realm, author_id))
        username = _text(metadata.get("author_username"))
        if username is not None:
            keys.append((MATTERMOST_USERNAME, realm, username.casefold()))
        return keys
    return []


def attribute_communication(
    *,
    provider: str | None,
    metadata: dict,
    occurred_at: datetime,
    identity_index: dict[tuple[str, str, str], UUID],
) -> list[InteractionHit]:
    if provider in {"gmail", "yandex_mail"}:
        return _email_hits(provider, metadata, occurred_at, identity_index)
    if provider == "telegram" and metadata.get("transport") == "mtproto":
        return _telegram_hits(metadata, occurred_at, identity_index)
    if provider == "teams":
        return _teams_hits(metadata, occurred_at, identity_index)
    if provider == "mattermost":
        return _mattermost_hits(metadata, occurred_at, identity_index)
    return []


def _tier(score: int) -> str:
    if score >= FOCUS_MIN:
        return FOCUS
    if score >= KNOWN_MIN:
        return KNOWN
    return INCIDENTAL


def _email_hits(
    provider: str,
    metadata: dict,
    occurred_at: datetime,
    identity_index: dict[tuple[str, str, str], UUID],
) -> list[InteractionHit]:
    direction = _email_direction(provider, metadata)
    if direction is None:
        return []
    audience = _email_audience(metadata)
    exposure = "direct" if len(audience) == 1 else "public"
    if direction == "inbound":
        sender = _email_address(metadata.get("sender") or metadata.get("from"))
        person_id = _lookup(identity_index, EMAIL_IDENTITY, "", sender)
        if person_id is None:
            return []
        return [InteractionHit(person_id, exposure, "inbound", occurred_at)]
    hits: list[InteractionHit] = []
    for address in audience:
        person_id = _lookup(identity_index, EMAIL_IDENTITY, "", address)
        if person_id is None:
            continue
        hits.append(InteractionHit(person_id, exposure, "outbound", occurred_at))
    return hits


def _email_direction(provider: str, metadata: dict) -> str | None:
    if provider == "gmail":
        labels = {
            str(label).upper()
            for label in metadata.get("labels") or []
            if isinstance(label, str)
        }
        sent = "SENT" in labels
        inbox = "INBOX" in labels or "UNREAD" in labels
        if sent == inbox:
            return None
        return "outbound" if sent else "inbound"
    if provider == "yandex_mail":
        folder = (_text(metadata.get("folder")) or "").casefold()
        if folder == "inbox" or folder.endswith("/inbox"):
            return "inbound"
        if folder in _YANDEX_SENT_FOLDERS or any(
            folder.endswith(suffix) for suffix in _YANDEX_SENT_SUFFIXES
        ):
            return "outbound"
    return None


def _telegram_hits(
    metadata: dict,
    occurred_at: datetime,
    identity_index: dict[tuple[str, str, str], UUID],
) -> list[InteractionHit]:
    realm = _text(metadata.get("account_id"))
    if realm is None:
        return []
    peer_kind = _text(metadata.get("peer_kind")) or ""
    direction = _text(metadata.get("direction")) or "inbound"
    sender = _positive_id(metadata.get("sender_peer_id"))
    peer = _positive_id(metadata.get("peer_id"))
    if peer_kind == "private":
        if direction == "outbound" and peer is not None:
            person_id = _lookup(identity_index, TELEGRAM_USER_ID, realm, peer)
            if person_id is not None:
                return [InteractionHit(person_id, "direct", "outbound", occurred_at)]
        if sender is not None:
            person_id = _lookup(identity_index, TELEGRAM_USER_ID, realm, sender)
            if person_id is not None:
                return [InteractionHit(person_id, "direct", "inbound", occurred_at)]
        return []
    if sender is None:
        return []
    person_id = _lookup(identity_index, TELEGRAM_USER_ID, realm, sender)
    if person_id is None:
        return []
    return [InteractionHit(person_id, "public", "inbound", occurred_at)]


def _teams_hits(
    metadata: dict,
    occurred_at: datetime,
    identity_index: dict[tuple[str, str, str], UUID],
) -> list[InteractionHit]:
    if metadata.get("sender_kind") != "user":
        return []
    realm = _text(metadata.get("tenant_id"))
    sender = _text(metadata.get("sender_id"))
    if realm is None or sender is None:
        return []
    person_id = _lookup(identity_index, TEAMS_USER_ID, realm.casefold(), sender.casefold())
    if person_id is None:
        return []
    if _text(metadata.get("direction")) != "inbound":
        return []
    exposure = "direct" if metadata.get("chat_type") == "oneOnOne" else "public"
    return [InteractionHit(person_id, exposure, "inbound", occurred_at)]


def _mattermost_hits(
    metadata: dict,
    occurred_at: datetime,
    identity_index: dict[tuple[str, str, str], UUID],
) -> list[InteractionHit]:
    raw_realm = _text(metadata.get("server_url"))
    if raw_realm is None:
        return []
    try:
        realm = normalize_server_url(raw_realm)
    except MattermostSecurityError:
        return []
    channel = (_text(metadata.get("channel_type")) or "").upper()
    exposure = "direct" if channel == "D" else "public"
    author_id = _text(metadata.get("author_user_id"))
    if author_id is not None:
        person_id = _lookup(identity_index, MATTERMOST_USER_ID, realm, author_id)
        if person_id is not None:
            return [InteractionHit(person_id, exposure, "inbound", occurred_at)]
    username = _text(metadata.get("author_username"))
    if username is None:
        return []
    person_id = _lookup(identity_index, MATTERMOST_USERNAME, realm, username.casefold())
    if person_id is None:
        return []
    return [InteractionHit(person_id, exposure, "inbound", occurred_at)]


def _lookup(
    identity_index: dict[tuple[str, str, str], UUID],
    identity_type: str,
    realm: str,
    value: str | None,
) -> UUID | None:
    if value is None:
        return None
    return identity_index.get((identity_type, realm, value))


def _email_address(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if "<" in text and ">" in text:
        text = text[text.rfind("<") + 1 : text.rfind(">")]
    text = text.strip().casefold()
    if "@" not in text:
        return None
    return text


def _email_audience(metadata: dict) -> list[str]:
    found = _email_addresses(metadata.get("recipients"))
    if not found:
        found = _email_addresses(metadata.get("to"))
    for address in _email_addresses(metadata.get("cc")):
        if address not in found:
            found.append(address)
    return found


def _email_addresses(value: object) -> list[str]:
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, list):
        parts = [item for item in value if isinstance(item, str)]
    else:
        return []
    found: list[str] = []
    for part in parts:
        address = _email_address(part)
        if address is not None and address not in found:
            found.append(address)
    return found


def _positive_id(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit() and int(value.strip()) > 0:
        return str(int(value.strip()))
    return None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
