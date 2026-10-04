"""One bounded scan for role-import exact-name mention evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Object
from app.domain.object_visibility import object_is_active
from app.domain.person_assistant import MAX_PERSON_SCAN_ROWS, PERSON_LOOKBACK_DAYS
from app.domain.role_import_mentions import (
    MIN_ROLE_IMPORT_NAME_MENTION_OBJECTS,
    mention_candidate_key,
    mention_pattern,
    text_mentions_name,
)
from app.domain.telegram_mtproto_ai import telegram_mtproto_ai_predicate
from app.services.provenance import REJECTED_STATE

_COMMUNICATION_KINDS = ("email", "chat_message")


@dataclass(frozen=True)
class NameMentionEvidence:
    display_name: str
    object_count: int
    latest_occurred_at: datetime | None
    provider_label: str
    candidate_key: str


class PersonRoleImportMentionEvidenceService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def evidence_for(self, names: list[str]) -> dict[str, NameMentionEvidence]:
        patterns = {}
        for name in names:
            if name in patterns:
                continue
            pattern = mention_pattern(name)
            if pattern is not None:
                patterns[name] = pattern
        if not patterns:
            return {}
        rows, _truncated = self._communication_rows()
        found: dict[str, NameMentionEvidence] = {}
        for name, pattern in patterns.items():
            object_ids: set[UUID] = set()
            latest: datetime | None = None
            providers: set[str] = set()
            for source in rows:
                if not _row_mentions(pattern, source):
                    continue
                object_ids.add(source.id)
                providers.add(source.provider or "")
                when = source.occurred_at or source.created_at
                if when is not None and (latest is None or when > latest):
                    latest = when
            if len(object_ids) < MIN_ROLE_IMPORT_NAME_MENTION_OBJECTS:
                continue
            found[name] = NameMentionEvidence(
                display_name=name,
                object_count=len(object_ids),
                latest_occurred_at=latest,
                provider_label=_provider_label(providers),
                candidate_key=mention_candidate_key(name),
            )
        return found

    def _communication_rows(self) -> tuple[list[Object], bool]:
        stamp = func.coalesce(Object.occurred_at, Object.created_at)
        cutoff = datetime.now(UTC) - timedelta(days=PERSON_LOOKBACK_DAYS)
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
        return rows[:MAX_PERSON_SCAN_ROWS], truncated


def _row_mentions(pattern, source: Object) -> bool:
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    subject = metadata.get("subject") if isinstance(metadata.get("subject"), str) else None
    return any(
        text_mentions_name(pattern, value)
        for value in (source.title, source.body, subject)
    )


def _provider_label(providers: set[str]) -> str:
    labels = sorted(item for item in providers if item)
    if len(labels) == 1:
        return labels[0]
    if not labels:
        return "communication"
    return "mixed"
