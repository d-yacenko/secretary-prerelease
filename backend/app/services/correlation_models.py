from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class CorrelationCandidate:
    object_id: UUID
    kind: str
    title: str
    primary_date: str | None
    content_summary: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    existing_relation: str | None = None


@dataclass(frozen=True)
class CorrelationDecision:
    target_object_id: UUID
    relation_type: str
    confidence: float
    rationale: str


@dataclass(frozen=True)
class CorrelationJudgeResult:
    decisions: tuple[CorrelationDecision, ...] = field(default_factory=tuple)
