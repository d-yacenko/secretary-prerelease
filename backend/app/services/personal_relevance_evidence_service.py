"""Read-only personal relevance evidence snapshot builder (Pass E-B).

Zero LLM calls. Zero writes, jobs, or notifications. Reusable later by Proactive E-C.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from types import SimpleNamespace
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Edge,
    GoogleAccount,
    MattermostAccount,
    Object,
    TeamsAccount,
    TelegramAccount,
    TelegramMtprotoAccount,
    UserSettings,
    YandexCalendarAccount,
    YandexMailAccount,
)
from app.domain.labels import EDGE_TYPE_LABELED_WITH, KIND_LABEL
from app.domain.object_visibility import object_is_active
from app.personal_relevance.models import (
    LABEL_EVIDENCE_FETCH_LIMIT,
    PERSONAL_RELEVANCE_EVIDENCE_VERSION,
    PERSONAL_RELEVANCE_MAX_IDENTITY_JSON_CHARS,
    PERSONAL_RELEVANCE_MAX_LABELS_PER_OBJECT,
    PERSONAL_RELEVANCE_MAX_OBJECTS,
    PERSONAL_RELEVANCE_MAX_SEMANTIC_CONTEXT_CHARS,
    PERSONAL_RELEVANCE_MAX_TITLE_CHARS,
    AssignedLabelEvidence,
    ObjectPersonalRelevanceEvidence,
    PersonalRelevanceEvidenceSnapshot,
    PersonalRelevanceUserContext,
    object_evidence_canonical_payload,
    user_context_canonical_payload,
)
from app.services.label_service import label_description
from app.services.personal_semantic_context_service import (
    load_personal_semantic_context,
    lock_identity_profile_row,
    lock_semantic_context_row,
)
from app.services.provenance import REJECTED_STATE
from app.services.user_identity_constants import (
    MAX_ALIAS_ITEMS,
    MAX_CONNECTED_ACCOUNT_IDENTIFIER_CHARS,
    MAX_CONNECTED_ACCOUNT_IDENTIFIERS,
    MAX_FULL_NAME_CHARS,
    MAX_IDENTITY_LIST_ITEM_CHARS,
    MAX_IDENTITY_LIST_ITEMS,
    MAX_PREFERRED_NAME_CHARS,
)
from app.services.user_identity_context_service import (
    UserIdentityContextService,
    UserIdentityRuntimeFacts,
    bound_runtime_identity_facts,
)
from app.services.user_participation_evidence_service import (
    ParticipationIdentity,
    current_user_participation,
    extract_email_address,
)
from app.services.user_serialization_gate import lock_user_serialization_row

_IDENTITY_FIELD_ORDER = (
    "full_name",
    "preferred_name",
    "aliases",
    "roles",
    "organizations",
    "emails",
    "phones",
    "telegram",
    "other_identifiers",
    "connected_account_identifiers",
)
_IDENTITY_SHRINK_ORDER = (
    "connected_account_identifiers",
    "other_identifiers",
    "aliases",
    "telegram",
    "phones",
    "organizations",
    "roles",
    "emails",
)


class PersonalRelevanceEvidenceService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._identity = UserIdentityContextService.build(session)

    @classmethod
    def build(cls, session: Session) -> PersonalRelevanceEvidenceService:
        return cls(session)

    def build_snapshot(
        self,
        user_id: UUID,
        object_ids: Sequence[UUID],
    ) -> PersonalRelevanceEvidenceSnapshot:
        user_context, identity = self._load_user_context(user_id)
        user_context_signature = _sha256_canonical(user_context_canonical_payload(user_context))

        requested = _dedupe_ids(object_ids)
        truncated_objects = len(requested) > PERSONAL_RELEVANCE_MAX_OBJECTS
        bounded_ids = requested[:PERSONAL_RELEVANCE_MAX_OBJECTS]
        owned = self._load_owned_objects(user_id, bounded_ids)
        labels_by_object = self._load_assigned_labels(user_id, [obj.id for obj in owned])

        object_records: list[ObjectPersonalRelevanceEvidence] = []
        signatures: dict[str, str] = {}
        for obj in owned:
            labels, labels_truncated = labels_by_object.get(obj.id, ((), False))
            participation = current_user_participation(obj, identity)
            title = obj.title or ""
            record = ObjectPersonalRelevanceEvidence(
                object_id=obj.id,
                kind=obj.kind,
                provider=obj.provider,
                origin=obj.origin,
                state=obj.state,
                status=obj.status,
                title=title[:PERSONAL_RELEVANCE_MAX_TITLE_CHARS],
                updated_at=obj.updated_at,
                due_at=obj.due_at,
                start_at=obj.start_at,
                occurred_at=obj.occurred_at,
                user_participation_roles=participation.roles,
                assigned_labels=labels,
                labels_truncated=labels_truncated,
                participation_truncated=participation.truncated,
            )
            object_records.append(record)
            signatures[str(obj.id)] = object_evidence_signature(
                record, user_context_signature
            )

        return PersonalRelevanceEvidenceSnapshot(
            version=PERSONAL_RELEVANCE_EVIDENCE_VERSION,
            user_context=user_context,
            objects=tuple(object_records),
            user_context_signature=user_context_signature,
            truncated_objects=truncated_objects,
            object_evidence_signatures=signatures,
        )

    def _load_user_context(
        self, user_id: UUID
    ) -> tuple[PersonalRelevanceUserContext, ParticipationIdentity]:
        raw_facts = self._identity.get_runtime_facts(user_id)
        bounded = bound_runtime_identity_facts(raw_facts)
        semantic = load_personal_semantic_context(self._session, user_id, lock_rows=False)
        semantic_text = semantic.context_text or ""
        truncated = _identity_was_truncated(raw_facts, bounded)
        if len(semantic_text) > PERSONAL_RELEVANCE_MAX_SEMANTIC_CONTEXT_CHARS:
            truncated = True
        semantic_text = semantic_text[:PERSONAL_RELEVANCE_MAX_SEMANTIC_CONTEXT_CHARS]

        (
            google_emails,
            yandex_mail_emails,
            yandex_calendar_emails,
            mm_ids,
            mm_usernames,
            telegram_ids,
            teams_ids,
        ) = (
            self._connected_match_tokens(user_id)
        )
        emails = frozenset(
            email
            for email in (
                *(extract_email_address(item) for item in bounded.emails),
                *google_emails,
                *yandex_mail_emails,
                *yandex_calendar_emails,
            )
            if email
        )
        identity = ParticipationIdentity(
            emails=emails,
            mattermost_user_ids=mm_ids,
            mattermost_usernames=mm_usernames,
            has_google_account=bool(google_emails),
            has_yandex_calendar_account=bool(yandex_calendar_emails),
            telegram_user_ids=telegram_ids,
            teams_user_ids=teams_ids,
        )
        connected = list(bounded.connected_account_identifiers)
        seen_connected = {item.casefold() for item in connected}
        for remote_id in sorted(mm_ids):
            token = f"mattermost:user_id:{remote_id}"[:MAX_CONNECTED_ACCOUNT_IDENTIFIER_CHARS]
            key = token.casefold()
            if key in seen_connected:
                continue
            if len(connected) >= MAX_CONNECTED_ACCOUNT_IDENTIFIERS:
                truncated = True
                break
            connected.append(token)
            seen_connected.add(key)
        for telegram_id in sorted(telegram_ids):
            token = f"telegram:user_id:{telegram_id}"[:MAX_CONNECTED_ACCOUNT_IDENTIFIER_CHARS]
            key = token.casefold()
            if key in seen_connected:
                continue
            if len(connected) >= MAX_CONNECTED_ACCOUNT_IDENTIFIERS:
                truncated = True
                break
            connected.append(token)
            seen_connected.add(key)
        for teams_id in sorted(teams_ids):
            token = f"teams:user_id:{teams_id}"[:MAX_CONNECTED_ACCOUNT_IDENTIFIER_CHARS]
            key = token.casefold()
            if key in seen_connected:
                continue
            if len(connected) >= MAX_CONNECTED_ACCOUNT_IDENTIFIERS:
                truncated = True
                break
            connected.append(token)
            seen_connected.add(key)

        projection = {
            "full_name": bounded.full_name,
            "preferred_name": bounded.preferred_name,
            "aliases": list(bounded.aliases),
            "roles": list(bounded.roles),
            "organizations": list(bounded.organizations),
            "emails": list(bounded.emails),
            "phones": list(bounded.phones),
            "telegram": list(bounded.telegram),
            "other_identifiers": list(bounded.other_identifiers),
            "connected_account_identifiers": connected,
        }
        projection, budget_truncated = fit_identity_json_budget(projection)
        truncated = truncated or budget_truncated

        user_context = PersonalRelevanceUserContext(
            full_name=projection["full_name"],
            preferred_name=projection["preferred_name"],
            aliases=tuple(projection["aliases"]),
            roles=tuple(projection["roles"]),
            organizations=tuple(projection["organizations"]),
            emails=tuple(projection["emails"]),
            phones=tuple(projection["phones"]),
            telegram=tuple(projection["telegram"]),
            other_identifiers=tuple(projection["other_identifiers"]),
            connected_account_identifiers=tuple(projection["connected_account_identifiers"]),
            semantic_context=semantic_text,
            truncated=truncated,
        )
        return user_context, identity

    def _connected_match_tokens(
        self, user_id: UUID
    ) -> tuple[
        frozenset[str],
        frozenset[str],
        frozenset[str],
        frozenset[str],
        frozenset[str],
        frozenset[str],
        frozenset[str],
    ]:
        google_emails = _emails_from_query(
            self._session.scalars(select(GoogleAccount.email).where(GoogleAccount.user_id == user_id))
        )
        yandex_mail_emails = _emails_from_query(
            self._session.scalars(
                select(YandexMailAccount.email).where(YandexMailAccount.user_id == user_id)
            )
        )
        yandex_calendar_emails = _emails_from_query(
            self._session.scalars(
                select(YandexCalendarAccount.email).where(YandexCalendarAccount.user_id == user_id)
            )
        )
        mm_ids: set[str] = set()
        mm_usernames: set[str] = set()
        for account in self._session.scalars(
            select(MattermostAccount).where(MattermostAccount.user_id == user_id)
        ):
            if account.remote_user_id:
                mm_ids.add(account.remote_user_id)
            if account.username:
                mm_usernames.add(account.username.casefold())
        telegram_ids = {
            str(account.telegram_user_id)
            for account in self._session.scalars(
                select(TelegramAccount).where(TelegramAccount.user_id == user_id)
            )
        }
        telegram_ids.update(
            str(account.telegram_user_id)
            for account in self._session.scalars(
                select(TelegramMtprotoAccount).where(TelegramMtprotoAccount.user_id == user_id)
            )
        )
        teams_ids = {
            account.microsoft_user_id
            for account in self._session.scalars(
                select(TeamsAccount).where(TeamsAccount.user_id == user_id)
            )
            if account.microsoft_user_id
        }
        return (
            google_emails,
            yandex_mail_emails,
            yandex_calendar_emails,
            frozenset(mm_ids),
            frozenset(mm_usernames),
            frozenset(telegram_ids),
            frozenset(teams_ids),
        )

    def _load_owned_objects(self, user_id: UUID, object_ids: list[UUID]) -> list[Object]:
        if not object_ids:
            return []
        rows = list(
            self._session.scalars(
                select(Object).where(
                    Object.user_id == user_id,
                    Object.id.in_(object_ids),
                    Object.state != REJECTED_STATE,
                    object_is_active(),
                )
            )
        )
        by_id = {item.id: item for item in rows}
        return [by_id[item_id] for item_id in object_ids if item_id in by_id]

    def _load_assigned_labels(
        self,
        user_id: UUID,
        object_ids: list[UUID],
    ) -> dict[UUID, tuple[tuple[AssignedLabelEvidence, ...], bool]]:
        result: dict[UUID, tuple[tuple[AssignedLabelEvidence, ...], bool]] = {
            object_id: ((), False) for object_id in object_ids
        }
        grouped: dict[UUID, list[tuple[int, AssignedLabelEvidence]]] = {}
        for row in fetch_bounded_label_assignment_rows(self._session, user_id, object_ids):
            evidence = AssignedLabelEvidence(
                label_id=row.label_id,
                title=row.title,
                description=label_description(SimpleNamespace(body=row.body)),
                assignment_origin=row.assignment_origin,
                assignment_confidence=row.assignment_confidence,
            )
            grouped.setdefault(row.source_id, []).append((row.rn, evidence))
        for source_id, ranked in grouped.items():
            ranked.sort(key=lambda item: item[0])
            truncated = len(ranked) > PERSONAL_RELEVANCE_MAX_LABELS_PER_OBJECT
            kept = [item[1] for item in ranked[:PERSONAL_RELEVANCE_MAX_LABELS_PER_OBJECT]]
            result[source_id] = (tuple(kept), truncated)
        return result


class _LabelAssignmentRow(NamedTuple):
    source_id: UUID
    rn: int
    label_id: UUID
    title: str
    body: str | None
    assignment_origin: str
    assignment_confidence: float | None


def fetch_bounded_label_assignment_rows(
    session: Session,
    user_id: UUID,
    object_ids: list[UUID],
) -> list[_LabelAssignmentRow]:
    if not object_ids:
        return []
    ranked = (
        select(
            Edge.source_id.label("source_id"),
            Edge.origin.label("assignment_origin"),
            Edge.confidence.label("assignment_confidence"),
            Object.id.label("label_id"),
            Object.title.label("title"),
            Object.body.label("body"),
            func.row_number()
            .over(
                partition_by=Edge.source_id,
                order_by=(
                    Object.metadata_["label_key"].as_string().asc(),
                    Object.id.asc(),
                ),
            )
            .label("rn"),
        )
        .select_from(Edge)
        .join(Object, Edge.target_id == Object.id)
        .where(
            Edge.user_id == user_id,
            Edge.source_id.in_(object_ids),
            Edge.type == EDGE_TYPE_LABELED_WITH,
            Edge.state != REJECTED_STATE,
            Object.user_id == user_id,
            Object.kind == KIND_LABEL,
            Object.state != REJECTED_STATE,
            object_is_active(Object),
        )
        .subquery()
    )
    rows = session.execute(
        select(ranked).where(ranked.c.rn <= LABEL_EVIDENCE_FETCH_LIMIT)
    ).all()
    return [
        _LabelAssignmentRow(
            source_id=row.source_id,
            rn=int(row.rn),
            label_id=row.label_id,
            title=row.title,
            body=row.body,
            assignment_origin=row.assignment_origin,
            assignment_confidence=row.assignment_confidence,
        )
        for row in rows
    ]


def object_evidence_signature(
    record: ObjectPersonalRelevanceEvidence,
    user_context_signature: str,
) -> str:
    return _sha256_canonical(
        object_evidence_canonical_payload(record, user_context_signature)
    )


def fit_identity_json_budget(projection: dict) -> tuple[dict, bool]:
    fitted = {key: projection[key] for key in _IDENTITY_FIELD_ORDER}
    truncated = False
    while _canonical_len(fitted) > PERSONAL_RELEVANCE_MAX_IDENTITY_JSON_CHARS:
        dropped = False
        for key in _IDENTITY_SHRINK_ORDER:
            items = fitted[key]
            if isinstance(items, list) and items:
                fitted = {**fitted, key: items[:-1]}
                truncated = True
                dropped = True
                break
        if not dropped:
            break
    return fitted, truncated


def _dedupe_ids(object_ids: Sequence[UUID]) -> list[UUID]:
    seen: set[UUID] = set()
    ordered: list[UUID] = []
    for item in sorted(object_ids, key=lambda value: value.bytes):
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _identity_was_truncated(
    raw: UserIdentityRuntimeFacts,
    bounded: UserIdentityRuntimeFacts,
) -> bool:
    if _scalar_truncated(raw.full_name, bounded.full_name, MAX_FULL_NAME_CHARS):
        return True
    if _scalar_truncated(
        raw.preferred_name, bounded.preferred_name, MAX_PREFERRED_NAME_CHARS
    ):
        return True
    pairs = (
        (raw.aliases, bounded.aliases, MAX_ALIAS_ITEMS, MAX_IDENTITY_LIST_ITEM_CHARS),
        (raw.roles, bounded.roles, MAX_IDENTITY_LIST_ITEMS, MAX_IDENTITY_LIST_ITEM_CHARS),
        (
            raw.organizations,
            bounded.organizations,
            MAX_IDENTITY_LIST_ITEMS,
            MAX_IDENTITY_LIST_ITEM_CHARS,
        ),
        (raw.emails, bounded.emails, MAX_IDENTITY_LIST_ITEMS, MAX_IDENTITY_LIST_ITEM_CHARS),
        (raw.phones, bounded.phones, MAX_IDENTITY_LIST_ITEMS, MAX_IDENTITY_LIST_ITEM_CHARS),
        (raw.telegram, bounded.telegram, MAX_IDENTITY_LIST_ITEMS, MAX_IDENTITY_LIST_ITEM_CHARS),
        (
            raw.other_identifiers,
            bounded.other_identifiers,
            MAX_IDENTITY_LIST_ITEMS,
            MAX_IDENTITY_LIST_ITEM_CHARS,
        ),
        (
            raw.connected_account_identifiers,
            bounded.connected_account_identifiers,
            MAX_CONNECTED_ACCOUNT_IDENTIFIERS,
            MAX_CONNECTED_ACCOUNT_IDENTIFIER_CHARS,
        ),
    )
    return any(_list_truncated(raw_list, bounded_list, max_items, max_chars) for raw_list, bounded_list, max_items, max_chars in pairs)


def _scalar_truncated(raw: str | None, bounded: str | None, limit: int) -> bool:
    if raw is None:
        return False
    stripped = raw.strip()
    if not stripped:
        return False
    return bounded != stripped[:limit] or len(stripped) > limit


def _list_truncated(
    raw_values: list[str],
    bounded: list[str],
    max_items: int,
    max_item_chars: int,
) -> bool:
    seen: set[str] = set()
    kept = 0
    for value in raw_values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        if kept >= max_items:
            return True
        if len(normalized) > max_item_chars:
            return True
        kept += 1
    return kept != len(bounded)


def _emails_from_query(values) -> frozenset[str]:
    emails: set[str] = set()
    for value in values:
        email = extract_email_address(value)
        if email:
            emails.add(email)
    return frozenset(emails)


def _canonical_len(value: object) -> int:
    return len(_canonical_json(value))


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_canonical(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _lock_account_rows(session: Session, model, user_id: UUID) -> None:
    list(
        session.scalars(
            select(model)
            .where(model.user_id == user_id)
            .order_by(model.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def acquire_personal_relevance_authority(
    session: Session,
    user_id: UUID,
    seed_ids: Sequence[UUID],
) -> UserSettings | None:
    """Lock E-B signature inputs. Order matches auto-label: User, settings, semantic, identity, then objects.

    Connected-account rows are locked after identity and before seed objects.
    """
    user = lock_user_serialization_row(session, user_id)
    if user is None:
        return None
    settings = session.scalar(
        select(UserSettings)
        .where(UserSettings.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    lock_semantic_context_row(session, user_id)
    lock_identity_profile_row(session, user_id)
    _lock_account_rows(session, GoogleAccount, user_id)
    _lock_account_rows(session, YandexMailAccount, user_id)
    _lock_account_rows(session, YandexCalendarAccount, user_id)
    _lock_account_rows(session, MattermostAccount, user_id)
    for object_id in sorted(seed_ids, key=lambda item: item.bytes):
        session.scalar(
            select(Object)
            .where(Object.id == object_id, Object.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return settings
