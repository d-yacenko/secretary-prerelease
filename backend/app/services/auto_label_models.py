from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from app.services.auto_label_constants import (
    AUTO_LABEL_MAX_ASSIGNMENTS,
    AUTO_LABEL_MAX_RATIONALE_CHARS,
    AUTO_LABEL_MIN_CONFIDENCE,
)


@dataclass(frozen=True)
class AutoLabelCandidate:
    label_id: UUID
    title: str
    description: str | None = None


@dataclass(frozen=True)
class AutoLabelObjectInput:
    object_id: UUID
    kind: str
    title: str
    provider: str | None
    content: str
    content_source: str


@dataclass(frozen=True)
class AutoLabelAssignment:
    label_id: UUID
    confidence: float
    rationale: str


@dataclass(frozen=True)
class AutoLabelClassifierResult:
    assignments: tuple[AutoLabelAssignment, ...] = ()
    raw_assignment_count: int = 0


@dataclass(frozen=True)
class BackgroundAssignOutcome:
    created: int = 0
    already_present: int = 0
    suppressed_rejected: int = 0


def validate_auto_label_assignments(
    raw_rows: list[object],
    allowed_ids: set[UUID],
) -> tuple[AutoLabelAssignment, ...]:
    strongest: dict[UUID, AutoLabelAssignment] = {}
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        try:
            label_id = UUID(str(row.get("label_id", "")))
        except (TypeError, ValueError):
            continue
        if label_id not in allowed_ids:
            continue
        confidence = _finite_confidence(row.get("confidence"))
        if confidence is None or confidence < AUTO_LABEL_MIN_CONFIDENCE:
            continue
        rationale = str(row.get("rationale", "")).strip()[:AUTO_LABEL_MAX_RATIONALE_CHARS]
        current = strongest.get(label_id)
        if current is None or confidence > current.confidence:
            strongest[label_id] = AutoLabelAssignment(
                label_id=label_id,
                confidence=confidence,
                rationale=rationale,
            )
    ranked = sorted(
        strongest.values(),
        key=lambda item: (-item.confidence, item.label_id.bytes),
    )
    return tuple(ranked[:AUTO_LABEL_MAX_ASSIGNMENTS])


def _finite_confidence(value: object) -> float | None:
    try:
        confidence = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(confidence):
        return None
    if confidence < 0.0 or confidence > 1.0:
        return None
    return confidence
