"""Read-only grounding of a role-import proposal. Nothing is stored."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PersonRoleTerm
from app.domain.person_promotion import promotion_candidate_key
from app.domain.person_role_text import PersonRoleTextError, role_term_identity
from app.services.errors import ValidationError
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_promotion_service import PersonPromotionService, PromotionCandidate
from app.services.person_role_import_extraction_service import (
    _CONTEXT_MAX,
    _EVIDENCE_MAX,
    _LOCATOR_MAX,
    _NAME_MAX,
    _ROLE_MAX,
    RoleImportItem,
)
from app.services.person_role_import_source_service import PersonRoleImportSourceService
from app.tools.schemas import ResolvePersonOutput

MAX_GROUND_ITEMS = 32
MAX_PROMOTION_MATCHES = 3
MAX_ROLE_SUGGESTIONS = 5
SOURCE_CHANGED = "role_import_source_changed"


class RoleImportGroundInputItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_name: str = Field(min_length=1, max_length=_NAME_MAX)
    role: str = Field(min_length=1, max_length=_ROLE_MAX)
    context: str | None = Field(default=None, max_length=_CONTEXT_MAX)
    evidence_text: str = Field(min_length=1, max_length=_EVIDENCE_MAX)
    source_locator: str | None = Field(default=None, max_length=_LOCATOR_MAX)


class RoleImportGroundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_object_id: UUID
    source_revision: str = Field(min_length=1)
    items_truncated: bool
    items: list[RoleImportGroundInputItem] = Field(max_length=MAX_GROUND_ITEMS)


class RoleImportPersonCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    person_id: UUID
    title: str
    reasons: list[str]


class RoleImportPromotionSource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    object_id: UUID
    provider: str | None = None
    title: str | None = None
    occurred_at: datetime | None = None


class RoleImportPromotionCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    candidate_key: str
    display_name: str
    provider: str
    direct_hit_count: int
    latest_occurred_at: datetime | None = None
    sources: list[RoleImportPromotionSource]


class RoleImportPersonResolution(BaseModel):
    model_config = ConfigDict(extra="ignore")

    state: Literal["resolved", "ambiguous", "promotion_candidates", "unresolved"]
    person_id: UUID | None = None
    title: str | None = None
    reasons: list[str] = []
    candidates: list[RoleImportPersonCandidate] = []
    promotion_candidates: list[RoleImportPromotionCandidate] = []


class RoleImportRoleResolution(BaseModel):
    model_config = ConfigDict(extra="ignore")

    state: Literal["reuse_existing", "propose_new"]
    role_term_id: UUID | None = None
    display_text: str
    suggestions: list[str] = []


class RoleImportGroundedItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    row_index: int
    person_name: str
    role: str
    context: str | None = None
    evidence_text: str
    source_locator: str | None = None
    person_resolution: RoleImportPersonResolution
    role_resolution: RoleImportRoleResolution


class RoleImportGroundedProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_object_id: UUID
    source_revision: str
    source_kind: Literal["image", "text"]
    source_truncated: bool
    items_truncated: bool
    grounding_revision: str
    items: list[RoleImportGroundedItem]


class PersonRoleImportGroundingService:
    def __init__(self, session: Session, user_id: UUID, upload_root: Path) -> None:
        self._session = session
        self._user_id = user_id
        self._sources = PersonRoleImportSourceService(session, user_id, upload_root)
        self._people = PersonAssistantService(session, user_id)
        self._promotion = PersonPromotionService(session, user_id)

    def ground(self, request: RoleImportGroundRequest) -> RoleImportGroundedProposal:
        source = self._sources.load(request.source_object_id)
        if source.source_revision != request.source_revision:
            raise ValidationError(SOURCE_CHANGED)
        rows = [_strict_item(item) for item in request.items]
        people = _memoized_people(self._people, rows)
        promotions = self._promotion.eligible_direct_contacts() if rows else []
        roles = _role_resolutions(self._session, self._user_id, rows)
        items = [
            RoleImportGroundedItem(
                row_index=index,
                person_name=row.person_name,
                role=row.role,
                context=row.context,
                evidence_text=row.evidence_text,
                source_locator=row.source_locator,
                person_resolution=_person_resolution(
                    row.person_name, people[row.person_name], promotions
                ),
                role_resolution=roles[index],
            )
            for index, row in enumerate(rows)
        ]
        proposal = RoleImportGroundedProposal(
            source_object_id=source.object_id,
            source_revision=source.source_revision,
            source_kind=source.source_kind,  # type: ignore[arg-type]
            source_truncated=source.source_truncated,
            items_truncated=request.items_truncated,
            grounding_revision="",
            items=items,
        )
        proposal.grounding_revision = _grounding_revision(proposal)
        return proposal


def _memoized_people(
    people: PersonAssistantService, rows: list[RoleImportItem]
) -> dict[str, ResolvePersonOutput]:
    found: dict[str, ResolvePersonOutput] = {}
    for row in rows:
        if row.person_name not in found:
            found[row.person_name] = people.resolve(row.person_name)
    return found


def _person_resolution(
    person_name: str,
    resolved: ResolvePersonOutput,
    promotions: list[PromotionCandidate],
) -> RoleImportPersonResolution:
    if resolved.state == "resolved" and resolved.person_id is not None:
        chosen = next(
            (item for item in resolved.candidates if item.person_id == resolved.person_id),
            None,
        )
        return RoleImportPersonResolution(
            state="resolved",
            person_id=resolved.person_id,
            title=None if chosen is None else chosen.title,
            reasons=[] if chosen is None else list(chosen.reasons),
        )
    if resolved.state == "ambiguous":
        ordered = sorted(
            resolved.candidates,
            key=lambda item: (item.title.casefold(), str(item.person_id)),
        )
        return RoleImportPersonResolution(
            state="ambiguous",
            candidates=[
                RoleImportPersonCandidate(
                    person_id=item.person_id,
                    title=item.title,
                    reasons=list(item.reasons),
                )
                for item in ordered
            ],
        )
    matches = _promotion_matches(person_name, promotions)
    if matches:
        return RoleImportPersonResolution(state="promotion_candidates", promotion_candidates=matches)
    return RoleImportPersonResolution(state="unresolved")


def _promotion_matches(
    name: str, promotions: list[PromotionCandidate]
) -> list[RoleImportPromotionCandidate]:
    if not name:
        return []
    wanted = _display_key(name)
    matched = [item for item in promotions if _display_key(item.display_value) == wanted]
    matched.sort(key=lambda item: promotion_candidate_key(item.identity))
    return [_promotion_out(item) for item in matched[:MAX_PROMOTION_MATCHES]]


def _promotion_out(item: PromotionCandidate) -> RoleImportPromotionCandidate:
    identity = item.identity
    return RoleImportPromotionCandidate(
        candidate_key=promotion_candidate_key(identity),
        display_name=item.display_value,
        provider=identity.provider,
        direct_hit_count=item.direct_hit_count,
        latest_occurred_at=item.latest_occurred_at,
        sources=[
            RoleImportPromotionSource(
                object_id=source.id,
                provider=source.provider,
                title=source.title,
                occurred_at=source.occurred_at,
            )
            for source in item.sources
        ],
    )


def _role_resolutions(
    session: Session, user_id: UUID, rows: list[RoleImportItem]
) -> list[RoleImportRoleResolution]:
    identities: list[tuple[str, str]] = []
    for row in rows:
        try:
            identities.append(role_term_identity(row.role))
        except PersonRoleTextError as exc:
            raise ValidationError(exc.message) from exc
    exact = _exact_terms(session, user_id, {key for _display, key in identities})
    suggestions: dict[str, list[str]] = {}
    resolved: list[RoleImportRoleResolution] = []
    for display, key in identities:
        term = exact.get(key)
        if term is not None:
            resolved.append(
                RoleImportRoleResolution(
                    state="reuse_existing",
                    role_term_id=term.id,
                    display_text=term.display_text,
                )
            )
            continue
        if key not in suggestions:
            suggestions[key] = _suggestion_texts(session, user_id, key)
        resolved.append(
            RoleImportRoleResolution(
                state="propose_new",
                display_text=display,
                suggestions=suggestions[key],
            )
        )
    return resolved


def _exact_terms(session: Session, user_id: UUID, keys: set[str]) -> dict[str, PersonRoleTerm]:
    if not keys:
        return {}
    rows = session.scalars(
        select(PersonRoleTerm).where(
            PersonRoleTerm.user_id == user_id,
            PersonRoleTerm.normalized_key.in_(keys),
        )
    ).all()
    return {row.normalized_key: row for row in rows}


def _suggestion_texts(session: Session, user_id: UUID, key: str) -> list[str]:
    rows = session.scalars(
        select(PersonRoleTerm)
        .where(
            PersonRoleTerm.user_id == user_id,
            PersonRoleTerm.normalized_key.contains(key, autoescape=True),
            PersonRoleTerm.normalized_key != key,
        )
        .order_by(PersonRoleTerm.normalized_key, PersonRoleTerm.id)
        .limit(MAX_ROLE_SUGGESTIONS)
    ).all()
    return [row.display_text for row in rows]


def _grounding_revision(proposal: RoleImportGroundedProposal) -> str:
    payload = proposal.model_dump(mode="json", exclude={"grounding_revision"})
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _strict_item(item: RoleImportGroundInputItem) -> RoleImportItem:
    person_name = _collapse(item.person_name)
    role = _collapse(item.role)
    evidence = _collapse(item.evidence_text)
    context = _collapse(item.context) if item.context is not None else None
    locator = _collapse(item.source_locator) if item.source_locator is not None else None
    if not person_name or not role or not evidence:
        raise ValidationError("role import row is invalid")
    if len(evidence) > _EVIDENCE_MAX:
        evidence = evidence[:_EVIDENCE_MAX]
    if locator is not None and len(locator) > _LOCATOR_MAX:
        locator = locator[:_LOCATOR_MAX]
    return RoleImportItem(
        person_name=person_name,
        role=role,
        context=context,
        evidence_text=evidence,
        source_locator=locator,
    )


def _collapse(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = " ".join(value.split())
    return collapsed or None


def _display_key(value: str) -> str:
    return " ".join(value.split()).casefold()
