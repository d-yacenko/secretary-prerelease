"""Deterministic Person-candidate score derived from evidence rows.

The score explains a proposal. It never attaches an identity or merges People.
"""

from __future__ import annotations

from dataclasses import dataclass

EXACT_IDENTIFIER = "exact_identifier"
PROVIDER_PROFILE = "provider_profile"
NAME_SIMILARITY = "name_similarity"
ORGANIZATION_MATCH = "organization_match"
GRAPH_CONTEXT = "graph_context"
LLM_SUGGESTION = "llm_suggestion"
USER_ROUTE_CHOICE = "user_route_choice"
USER_CONFIRMED = "user_confirmed"
USER_REJECTED = "user_rejected"

EVIDENCE_TYPES = frozenset(
    {
        EXACT_IDENTIFIER,
        PROVIDER_PROFILE,
        NAME_SIMILARITY,
        ORGANIZATION_MATCH,
        GRAPH_CONTEXT,
        LLM_SUGGESTION,
        USER_ROUTE_CHOICE,
        USER_CONFIRMED,
        USER_REJECTED,
    }
)

POSITIVE = "positive"
NEGATIVE = "negative"
ACTIVE = "active"
RETRACTED = "retracted"

CONFIRMED = "confirmed"
LIKELY = "likely"
POSSIBLE = "possible"
REJECTED = "rejected"

# Name, route choice, and model suggestions stay under this line.
# Crossing it still does not attach or merge; only an explicit confirmation
# produces the confirmed state.
AUTOMATIC_LINK_THRESHOLD = 90
LIKELY_MIN = 50

_WEIGHTS = {
    EXACT_IDENTIFIER: 80,
    PROVIDER_PROFILE: 60,
    NAME_SIMILARITY: 15,
    ORGANIZATION_MATCH: 15,
    GRAPH_CONTEXT: 20,
    LLM_SUGGESTION: 10,
    USER_ROUTE_CHOICE: 25,
    USER_CONFIRMED: 100,
    USER_REJECTED: 100,
}


def evidence_weight(evidence_type: str) -> int:
    if evidence_type not in _WEIGHTS:
        raise ValueError("unknown person evidence type")
    return _WEIGHTS[evidence_type]


def evidence_polarity(evidence_type: str) -> str:
    if evidence_type == USER_REJECTED:
        return NEGATIVE
    return POSITIVE


@dataclass(frozen=True)
class ScoreComponent:
    evidence_type: str
    polarity: str
    weight: int
    provenance_key: str
    explanation: str | None


@dataclass(frozen=True)
class CandidateAssessment:
    score: int
    resolution: str
    components: tuple[ScoreComponent, ...]
    contradictory: bool


def assess_evidence(rows: list[object]) -> CandidateAssessment:
    components: list[ScoreComponent] = []
    positive = 0
    negative = 0
    confirmed = False
    rejected = False
    for row in rows:
        if getattr(row, "state", ACTIVE) != ACTIVE:
            continue
        polarity = row.polarity
        weight = int(row.weight)
        if polarity == POSITIVE:
            positive += weight
            if row.evidence_type == USER_CONFIRMED:
                confirmed = True
        elif polarity == NEGATIVE:
            negative += weight
            if row.evidence_type == USER_REJECTED:
                rejected = True
        components.append(
            ScoreComponent(
                evidence_type=row.evidence_type,
                polarity=polarity,
                weight=weight,
                provenance_key=row.provenance_key,
                explanation=getattr(row, "explanation", None),
            )
        )
    contradictory = positive > 0 and negative > 0
    if rejected:
        return CandidateAssessment(0, REJECTED, tuple(components), contradictory)
    if confirmed:
        return CandidateAssessment(100, CONFIRMED, tuple(components), contradictory)
    raw = max(0, min(100, positive - negative))
    if raw >= LIKELY_MIN:
        resolution = LIKELY
    else:
        resolution = POSSIBLE
    return CandidateAssessment(raw, resolution, tuple(components), contradictory)
