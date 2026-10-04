"""Assisted promotion from stored direct contacts to an explicit Person.

Reads do not create People. Approval creates one Person and one exact identity.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    GoogleAccount,
    MattermostAccount,
    Object,
    PersonIdentity,
    PersonIdentityEvidence,
    PersonPromotionFeedback,
    TeamsAccount,
    TelegramMtprotoAccount,
    YandexMailAccount,
)
from app.domain.object_visibility import object_is_active
from app.domain.person_assistant import (
    MAX_PERSON_SCAN_ROWS,
    PERSON_LOOKBACK_DAYS,
    parse_feedback_identity,
)
from app.domain.person_identity import (
    NormalizedPersonIdentity,
    PersonIdentityInputError,
    normalize_email,
    normalize_mattermost_user_id,
    normalize_mattermost_username,
    normalize_teams_user_id,
    normalize_telegram_user_id,
)
from app.domain.person_promotion import (
    MAX_DIRECT_HITS,
    MAX_PROMOTION_CANDIDATES,
    MAX_SOURCE_PREVIEWS,
    MIN_DIRECT_HITS,
    REPEATED_DIRECT_CONTACT,
    direct_promotion_identity,
    mattermost_remote_identity,
)
from app.domain.role_import_participants import participant_identities
from app.domain.telegram_mtproto_ai import telegram_mtproto_ai_predicate
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_identity_service import PERSON_KIND, PersonIdentityService
from app.services.provenance import REJECTED_STATE, USER_ORIGIN

_COMMUNICATION_KINDS = ("email", "chat_message")
_SUPPRESSION = "suppression"
_ACTIVE = "active"
_RETRACTED = "retracted"
_PROMOTION_EXPLANATION = "explicit promotion of an unresolved direct contact"


@dataclass(frozen=True)
class PromotionCandidate:
    identity: NormalizedPersonIdentity
    display_value: str
    direct_hit_count: int
    latest_occurred_at: datetime | None
    sources: tuple[Object, ...]


@dataclass
class _Hit:
    identity: NormalizedPersonIdentity
    display_value: str
    count: int
    latest: datetime | None
    sources: list[Object]


class PersonPromotionService:
    def __init__(self, session: Session, user_id: UUID, *, now: datetime | None = None) -> None:
        self._session = session
        self._user_id = user_id
        self._now = now or datetime.now(UTC)
        self._people = PersonIdentityService(session, user_id)
        self._evidence = PersonEvidenceService(session, user_id)

    def overview(
        self, *, include_quarantined_telegram: bool = False
    ) -> tuple[list[dict], bool, list[dict]]:
        hits, truncated = self._hits(include_quarantined_telegram=include_quarantined_telegram)
        owned = self._owned_keys()
        suppressed = {self._key(row): row for row in self._active_feedback()}
        ranked = [
            self._candidate(item)
            for item in hits.values()
            if item.count >= MIN_DIRECT_HITS
            and self._key(item.identity) not in owned
            and self._key(item.identity) not in suppressed
        ]
        ranked.sort(key=self._rank)
        visible = ranked[:MAX_PROMOTION_CANDIDATES]
        return (
            [self._candidate_payload(item) for item in visible],
            truncated,
            [self._suppression_payload(row) for row in suppressed.values()],
        )

    def eligible_direct_contacts(self) -> list[PromotionCandidate]:
        """One read-only scan of identities that overview would be allowed to show."""
        hits, _truncated = self._hits(include_quarantined_telegram=False)
        owned = self._owned_keys()
        suppressed = {self._key(row) for row in self._active_feedback()}
        return [
            self._candidate(item)
            for item in hits.values()
            if item.count >= MIN_DIRECT_HITS
            and self._key(item.identity) not in owned
            and self._key(item.identity) not in suppressed
        ]

    def eligible_role_import_participants(self) -> list[PromotionCandidate]:
        """Role-import scan: one stored participant hit is enough.

        Generic ``eligible_direct_contacts`` and ``MIN_DIRECT_HITS`` are not used.
        """
        hits, _truncated = self._participant_hits()
        owned = self._owned_keys()
        suppressed = {self._key(row) for row in self._active_feedback()}
        return [
            self._candidate(item)
            for item in hits.values()
            if item.count >= 1
            and self._key(item.identity) not in owned
            and self._key(item.identity) not in suppressed
        ]

    def suppress(
        self, identity: NormalizedPersonIdentity, *, display_value: str | None = None
    ) -> PersonPromotionFeedback:
        existing = self._active_for(identity)
        if existing is not None:
            return existing
        if not display_value or display_value == identity.canonical_value:
            hits, _truncated = self._hits(include_quarantined_telegram=True)
            item = hits.get(self._key(identity))
            if item is not None:
                display_value = item.display_value
        label = _label(display_value or identity.display_value, identity.canonical_value)
        row = PersonPromotionFeedback(
            user_id=self._user_id,
            provider=identity.provider,
            identity_type=identity.identity_type,
            realm=identity.realm,
            canonical_value=identity.canonical_value,
            display_value=label,
            feedback_kind=_SUPPRESSION,
            state=_ACTIVE,
            origin=USER_ORIGIN,
            provenance_key=_provenance(identity),
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            found = self._active_for(identity)
            if found is None:
                raise
            return found
        return row

    def retract(self, identity: NormalizedPersonIdentity) -> PersonPromotionFeedback:
        row = self._active_for(identity)
        if row is None:
            raise NotFoundError("person_promotion_feedback", identity.canonical_value)
        row.state = _RETRACTED
        row.retracted_at = datetime.now(UTC)
        row.updated_at = row.retracted_at
        self._session.flush()
        return row

    def approve(self, identity: NormalizedPersonIdentity) -> Object:
        owner = self._people.resolve(identity)
        if owner is not None:
            if self._promotion_confirmation(owner.id, identity) is not None:
                return owner
            raise ConflictError("person identity is already bound")
        if self._confirmation_people(identity):
            raise ConflictError("person identity is already bound")
        hit = self._eligible_hit(identity)
        if hit is None:
            raise ValidationError("promotion candidate is not exposed")
        label = hit.display_value
        frozen = replace(
            identity,
            display_value=None if label == identity.canonical_value else label,
        )
        try:
            with self._session.begin_nested():
                person = self._people.create_person(label)
                attached = self._people.attach(person.id, frozen)
                evidence = self._evidence.record_confirmation(
                    person.id,
                    identity,
                    _provenance(identity),
                    explanation=_PROMOTION_EXPLANATION,
                )
                if evidence.person_identity_id is None:
                    evidence.person_identity_id = attached.id
                    self._session.flush()
                return person
        except ConflictError:
            owner = self._people.resolve(identity)
            if owner is not None and self._promotion_confirmation(owner.id, identity) is not None:
                return owner
            raise ConflictError("person identity is already bound") from None

    def approve_role_import_participant(
        self, identity: NormalizedPersonIdentity, *, display_name: str
    ) -> Object:
        """Create one Person for a role-import participant identity.

        Revalidates the role-import scan. A bound identity is a conflict and is
        not attached to a differently named Person.
        """
        owner = self._people.resolve(identity)
        if owner is not None or self._confirmation_people(identity):
            raise ConflictError("person identity is already bound")
        hit = self._participant_hit(identity, display_name)
        if hit is None:
            raise ValidationError("role import participant is no longer eligible")
        label = hit.display_value
        frozen = replace(
            identity,
            display_value=None if label == identity.canonical_value else label,
        )
        try:
            with self._session.begin_nested():
                person = self._people.create_person(label)
                attached = self._people.attach(person.id, frozen)
                evidence = self._evidence.record_confirmation(
                    person.id,
                    identity,
                    _provenance(identity),
                    explanation=_PROMOTION_EXPLANATION,
                )
                if evidence.person_identity_id is None:
                    evidence.person_identity_id = attached.id
                    self._session.flush()
                return person
        except ConflictError:
            raise ConflictError("person identity is already bound") from None

    def _eligible_hit(self, identity: NormalizedPersonIdentity) -> _Hit | None:
        if self._key(identity) in self._owned_keys() or self._active_for(identity) is not None:
            return None
        hits, _truncated = self._hits(include_quarantined_telegram=True)
        item = hits.get(self._key(identity))
        if item is None or item.count < MIN_DIRECT_HITS:
            return None
        return item

    def _hits(
        self, *, include_quarantined_telegram: bool
    ) -> tuple[dict[tuple[str, str, str, str], _Hit], bool]:
        stamp = func.coalesce(Object.occurred_at, Object.created_at)
        cutoff = self._now - timedelta(days=PERSON_LOOKBACK_DAYS)
        rows = list(
            self._session.scalars(
                select(Object)
                .where(
                    Object.user_id == self._user_id,
                    Object.kind.in_(_COMMUNICATION_KINDS),
                    Object.state != REJECTED_STATE,
                    object_is_active(),
                    stamp >= cutoff,
                )
                .order_by(stamp.desc(), Object.id)
                .limit(MAX_PERSON_SCAN_ROWS + 1)
            )
        )
        truncated = len(rows) > MAX_PERSON_SCAN_ROWS
        accounts = self._mattermost_accounts()
        found: dict[tuple[str, str, str, str], _Hit] = {}
        for source in rows[:MAX_PERSON_SCAN_ROWS]:
            if source.provider == "telegram" and not include_quarantined_telegram:
                continue
            if source.provider == "mattermost":
                account_id = _mattermost_account_id(source)
                identity = mattermost_remote_identity(
                    source, accounts.get(account_id) if account_id else None
                )
            else:
                identity = direct_promotion_identity(source)
            if identity is None:
                continue
            key = self._key(identity)
            when = source.occurred_at or source.created_at
            current = found.get(key)
            if current is None:
                found[key] = _Hit(
                    identity,
                    _label(identity.display_value, identity.canonical_value),
                    1,
                    when,
                    [source],
                )
                continue
            current.count += 1
            if len(current.sources) < MAX_SOURCE_PREVIEWS:
                current.sources.append(source)
            if current.display_value == identity.canonical_value and identity.display_value:
                current.display_value = _label(identity.display_value, identity.canonical_value)
        return found, truncated

    def _participant_hits(self) -> tuple[dict[tuple[str, str, str, str], _Hit], bool]:
        stamp = func.coalesce(Object.occurred_at, Object.created_at)
        cutoff = self._now - timedelta(days=PERSON_LOOKBACK_DAYS)
        rows = list(
            self._session.scalars(
                select(Object)
                .where(
                    Object.user_id == self._user_id,
                    Object.kind.in_(_COMMUNICATION_KINDS),
                    Object.state != REJECTED_STATE,
                    object_is_active(),
                    stamp >= cutoff,
                    telegram_mtproto_ai_predicate(),
                )
                .order_by(stamp.desc(), Object.id)
                .limit(MAX_PERSON_SCAN_ROWS + 1)
            )
        )
        truncated = len(rows) > MAX_PERSON_SCAN_ROWS
        self_keys = self._self_identity_keys()
        found: dict[tuple[str, str, str, str], _Hit] = {}
        displays: dict[tuple[str, str, str, str], str] = {}
        for source in rows[:MAX_PERSON_SCAN_ROWS]:
            for identity in participant_identities(source, self_identity_keys=self_keys):
                key = self._key(identity)
                display_key = _participant_display_key(identity.display_value or "")
                if not display_key:
                    continue
                when = source.occurred_at or source.created_at
                current = found.get(key)
                if current is None:
                    found[key] = _Hit(identity, identity.display_value or "", 1, when, [source])
                    displays[key] = display_key
                    continue
                if displays[key] != display_key:
                    continue
                current.count += 1
                if when is not None and (current.latest is None or when > current.latest):
                    current.latest = when
                if len(current.sources) < MAX_SOURCE_PREVIEWS:
                    current.sources.append(source)
        return found, truncated

    def _participant_hit(
        self, identity: NormalizedPersonIdentity, display_name: str
    ) -> _Hit | None:
        if self._key(identity) in self._owned_keys() or self._active_for(identity) is not None:
            return None
        hits, _truncated = self._participant_hits()
        item = hits.get(self._key(identity))
        if item is None or item.count < 1:
            return None
        if _participant_display_key(item.display_value) != _participant_display_key(display_name):
            return None
        return item

    def _self_identity_keys(self) -> set[tuple[str, str, str, str]]:
        """Exact account identities of this Secretary user, scoped by provider and realm."""
        keys: set[tuple[str, str, str, str]] = set()
        emails = list(
            self._session.scalars(
                select(GoogleAccount.email).where(GoogleAccount.user_id == self._user_id)
            )
        )
        emails.extend(
            self._session.scalars(
                select(YandexMailAccount.email).where(YandexMailAccount.user_id == self._user_id)
            )
        )
        for email in emails:
            try:
                keys.add(self._key(normalize_email(email)))
            except PersonIdentityInputError:
                continue
        for account in self._session.scalars(
            select(TeamsAccount).where(TeamsAccount.user_id == self._user_id)
        ):
            try:
                keys.add(
                    self._key(
                        normalize_teams_user_id(account.tenant_id, account.microsoft_user_id)
                    )
                )
            except PersonIdentityInputError:
                continue
        for account in self._mattermost_accounts().values():
            try:
                keys.add(
                    self._key(
                        normalize_mattermost_user_id(account.server_url, account.remote_user_id)
                    )
                )
            except PersonIdentityInputError:
                pass
            try:
                keys.add(
                    self._key(normalize_mattermost_username(account.server_url, account.username))
                )
            except PersonIdentityInputError:
                pass
        for account in self._session.scalars(
            select(TelegramMtprotoAccount).where(TelegramMtprotoAccount.user_id == self._user_id)
        ):
            try:
                keys.add(
                    self._key(
                        normalize_telegram_user_id(str(account.id), account.telegram_user_id)
                    )
                )
            except PersonIdentityInputError:
                continue
        return keys

    def _mattermost_accounts(self) -> dict[UUID, MattermostAccount]:
        rows = self._session.scalars(
            select(MattermostAccount).where(MattermostAccount.user_id == self._user_id)
        )
        return {row.id: row for row in rows}

    def _owned_keys(self) -> set[tuple[str, str, str, str]]:
        rows = self._session.scalars(
            select(PersonIdentity)
            .join(Object, Object.id == PersonIdentity.person_object_id)
            .where(
                PersonIdentity.user_id == self._user_id,
                PersonIdentity.state != REJECTED_STATE,
                Object.user_id == self._user_id,
                Object.kind == PERSON_KIND,
                Object.state != REJECTED_STATE,
                object_is_active(),
            )
        )
        return {(row.provider, row.identity_type, row.realm, row.canonical_value) for row in rows}

    def _active_feedback(self) -> list[PersonPromotionFeedback]:
        return list(
            self._session.scalars(
                select(PersonPromotionFeedback)
                .where(
                    PersonPromotionFeedback.user_id == self._user_id,
                    PersonPromotionFeedback.state == _ACTIVE,
                    PersonPromotionFeedback.feedback_kind == _SUPPRESSION,
                )
                .order_by(
                    PersonPromotionFeedback.provider,
                    PersonPromotionFeedback.identity_type,
                    PersonPromotionFeedback.realm,
                    PersonPromotionFeedback.canonical_value,
                )
            )
        )

    def _active_for(self, identity: NormalizedPersonIdentity) -> PersonPromotionFeedback | None:
        return self._session.scalar(
            select(PersonPromotionFeedback).where(
                PersonPromotionFeedback.user_id == self._user_id,
                PersonPromotionFeedback.state == _ACTIVE,
                PersonPromotionFeedback.provider == identity.provider,
                PersonPromotionFeedback.identity_type == identity.identity_type,
                PersonPromotionFeedback.realm == identity.realm,
                PersonPromotionFeedback.canonical_value == identity.canonical_value,
            )
        )

    def _promotion_confirmation(
        self, person_id: UUID, identity: NormalizedPersonIdentity
    ) -> PersonIdentityEvidence | None:
        return self._session.scalar(
            select(PersonIdentityEvidence).where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.person_object_id == person_id,
                PersonIdentityEvidence.state == _ACTIVE,
                PersonIdentityEvidence.evidence_type == "user_confirmed",
                PersonIdentityEvidence.provenance_key == _provenance(identity),
                PersonIdentityEvidence.provider == identity.provider,
                PersonIdentityEvidence.identity_type == identity.identity_type,
                PersonIdentityEvidence.realm == identity.realm,
                PersonIdentityEvidence.canonical_value == identity.canonical_value,
            )
        )

    def _confirmation_people(self, identity: NormalizedPersonIdentity) -> list[UUID]:
        return list(
            self._session.scalars(
                select(PersonIdentityEvidence.person_object_id).where(
                    PersonIdentityEvidence.user_id == self._user_id,
                    PersonIdentityEvidence.state == _ACTIVE,
                    PersonIdentityEvidence.evidence_type == "user_confirmed",
                    PersonIdentityEvidence.provider == identity.provider,
                    PersonIdentityEvidence.identity_type == identity.identity_type,
                    PersonIdentityEvidence.realm == identity.realm,
                    PersonIdentityEvidence.canonical_value == identity.canonical_value,
                )
            )
        )

    def _candidate(self, item: _Hit) -> PromotionCandidate:
        return PromotionCandidate(
            identity=item.identity,
            display_value=item.display_value,
            direct_hit_count=min(item.count, MAX_DIRECT_HITS),
            latest_occurred_at=item.latest,
            sources=tuple(item.sources[:MAX_SOURCE_PREVIEWS]),
        )

    def _rank(self, item: PromotionCandidate) -> tuple:
        latest = item.latest_occurred_at or datetime.min.replace(tzinfo=UTC)
        identity = item.identity
        return (
            -item.direct_hit_count,
            -latest.timestamp(),
            identity.provider,
            identity.identity_type,
            identity.realm,
            identity.canonical_value,
        )

    def _candidate_payload(self, item: PromotionCandidate) -> dict:
        identity = item.identity
        return {
            "provider": identity.provider,
            "identity_type": identity.identity_type,
            "realm": identity.realm,
            "canonical_value": identity.canonical_value,
            "display_value": item.display_value,
            "direct_hit_count": item.direct_hit_count,
            "latest_occurred_at": item.latest_occurred_at,
            "reasons": [REPEATED_DIRECT_CONTACT],
            "sources": [_preview(source) for source in item.sources],
        }

    def _suppression_payload(self, row: PersonPromotionFeedback) -> dict:
        return {
            "provider": row.provider,
            "identity_type": row.identity_type,
            "realm": row.realm,
            "canonical_value": row.canonical_value,
            "display_value": row.display_value or row.canonical_value,
        }

    @staticmethod
    def _key(
        identity: NormalizedPersonIdentity | PersonPromotionFeedback,
    ) -> tuple[str, str, str, str]:
        return (identity.provider, identity.identity_type, identity.realm, identity.canonical_value)


def _participant_display_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def parse_promotion_identity(
    identity_type: str,
    provider: str,
    realm: str,
    canonical_value: str,
) -> NormalizedPersonIdentity:
    try:
        return parse_feedback_identity(identity_type, provider, realm, canonical_value)
    except PersonIdentityInputError as exc:
        raise ValidationError("identity tuple is malformed") from exc


def _provenance(identity: NormalizedPersonIdentity) -> str:
    raw = (
        f"{identity.provider}|{identity.identity_type}|{identity.realm}|{identity.canonical_value}"
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"graph_ui:promotion:{digest}"


def _mattermost_account_id(source: Object) -> UUID | None:
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    raw = metadata.get("account_id")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def _label(display: str | None, canonical: str) -> str:
    text = (display or "").strip() or canonical.strip()
    return text[:200]


def _preview(source: Object) -> dict:
    return {
        "object_id": source.id,
        "kind": source.kind,
        "provider": source.provider,
        "title": source.title,
        "occurred_at": source.occurred_at,
    }
