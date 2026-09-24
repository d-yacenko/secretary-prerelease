"""Planning model for bounded Person identity enrichment.

The plan chooses who is worth resolving. It does not call a provider or a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domain.person_identity import NormalizedPersonIdentity

ATTACH_EXACT = "attach_exact"
RECORD_PROVIDER_EVIDENCE = "record_provider_evidence"
NEEDS_CONFIRMATION = "needs_confirmation"
NEEDS_PROVIDER_LOOKUP = "needs_provider_lookup"
IGNORE_FOR_NOW = "ignore_for_now"

NEXT_STEPS = frozenset(
    {
        ATTACH_EXACT,
        RECORD_PROVIDER_EVIDENCE,
        NEEDS_CONFIRMATION,
        NEEDS_PROVIDER_LOOKUP,
        IGNORE_FOR_NOW,
    }
)

PROVIDER_CATEGORIES = ("email", "mattermost", "teams", "telegram")
MAX_ENRICHMENT_SCAN = 40
MAX_ENRICHMENT_CANDIDATES = 20
MAX_SOURCE_REFS = 3

_STEP_RANK = {
    ATTACH_EXACT: 0,
    RECORD_PROVIDER_EVIDENCE: 1,
    NEEDS_PROVIDER_LOOKUP: 2,
    NEEDS_CONFIRMATION: 3,
    IGNORE_FOR_NOW: 4,
}


@dataclass(frozen=True)
class PersonCoverage:
    person_id: UUID
    known: tuple[str, ...]
    missing: tuple[str, ...]


@dataclass(frozen=True)
class PersonEnrichmentCandidate:
    person_id: UUID | None
    identity: NormalizedPersonIdentity | None
    provider: str
    reasons: tuple[str, ...]
    assessment_resolution: str | None
    salience_tier: str | None
    salience_score: int | None
    next_step: str
    source_object_ids: tuple[UUID, ...]
    truncated: bool


@dataclass(frozen=True)
class PersonResolutionPlan:
    candidates: tuple[PersonEnrichmentCandidate, ...]
    coverage: tuple[PersonCoverage, ...]
    truncated: bool


def provider_category(identity: NormalizedPersonIdentity) -> str | None:
    if identity.identity_type == "email" or identity.provider == "email":
        return "email"
    if identity.provider == "mattermost":
        return "mattermost"
    if identity.provider == "teams":
        return "teams"
    if identity.provider == "telegram_mtproto":
        return "telegram"
    return None


def candidate_sort_key(candidate: PersonEnrichmentCandidate) -> tuple:
    identity = candidate.identity.canonical_value if candidate.identity is not None else ""
    return (
        1 if candidate.next_step == IGNORE_FOR_NOW else 0,
        -(candidate.salience_score or 0),
        _STEP_RANK[candidate.next_step],
        str(candidate.person_id or ""),
        candidate.provider,
        identity,
    )
