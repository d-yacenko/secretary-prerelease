from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.temporal_hint import (
    DATE_KIND_ABSOLUTE,
    DATE_KIND_RELATIVE_DAY,
    DATE_KIND_WEEKDAY,
    END_KIND_ABSOLUTE,
    END_KIND_DURATION_MINUTES,
    END_KIND_LOCAL_TIME,
    END_PRECISION_EXACT,
    END_PRECISION_UNKNOWN,
    PARTICIPATION_EXPECTED,
    PARTICIPATION_OTHERS_ONLY,
    PARTICIPATION_POSSIBLE,
    PARTICIPATION_UNKNOWN,
    RESULT_EXACT_TEMPORAL_SIGNAL,
    RESULT_NO_TEMPORAL_SIGNAL,
    RESULT_UNSUPPORTED_PRECISION,
)

RESULT_CLASSES = frozenset(
    {
        RESULT_NO_TEMPORAL_SIGNAL,
        RESULT_UNSUPPORTED_PRECISION,
        RESULT_EXACT_TEMPORAL_SIGNAL,
    }
)
DATE_KINDS = frozenset({DATE_KIND_ABSOLUTE, DATE_KIND_RELATIVE_DAY, DATE_KIND_WEEKDAY})
END_PRECISIONS = frozenset({END_PRECISION_EXACT, END_PRECISION_UNKNOWN})
END_KINDS = frozenset({END_KIND_DURATION_MINUTES, END_KIND_LOCAL_TIME, END_KIND_ABSOLUTE})
PARTICIPATIONS = frozenset(
    {
        PARTICIPATION_EXPECTED,
        PARTICIPATION_POSSIBLE,
        PARTICIPATION_OTHERS_ONLY,
        PARTICIPATION_UNKNOWN,
    }
)
WEEKDAYS = frozenset(
    {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
)


@dataclass(frozen=True)
class TemporalExtractionRequest:
    object_id: UUID
    kind: str
    provider: str | None
    title: str
    body: str
    source_reference_at: datetime | None
    timezone: str
    participation_roles: tuple[str, ...]
    is_channel_message: bool
    has_other_participants: bool
    semantic_summary: str | None = None


@dataclass(frozen=True)
class ParsedExactSignal:
    concise_title: str
    date_kind: str
    absolute_date: str | None
    relative_day_offset: int | None
    weekday: str | None
    start_hour: int
    start_minute: int
    end_precision: str
    end_kind: str | None
    end_duration_minutes: int | None
    end_hour: int | None
    end_minute: int | None
    end_absolute: str | None
    participation: str
    extraction_confidence: float
    semantic_subject: str | None


@dataclass(frozen=True)
class TemporalExtractionResult:
    result_class: str
    exact: ParsedExactSignal | None = None
    reject_reason: str | None = None


@dataclass(frozen=True)
class ResolvedTemporalSignal:
    title: str
    start_at: datetime
    due_at: datetime | None
    end_precision: str
    participation: str
    extraction_confidence: float
    semantic_subject: str | None
    source_reference_at: datetime


@dataclass(frozen=True)
class TemporalMatchCandidate:
    object_id: UUID
    kind: str
    title: str
    start_at: datetime | None
    due_at: datetime | None
    summary: str
    provider: str | None


@dataclass(frozen=True)
class TemporalMatchDecision:
    target_object_id: UUID
    confidence: float


@dataclass(frozen=True)
class TemporalMatchResult:
    decision: TemporalMatchDecision | None = None


def _bounded_str(value: object, max_chars: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:max_chars]


def _parse_local_time(value: object) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    parts = text.split(":")
    if len(parts) not in {2, 3}:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour, minute


def _finite_confidence(value: object) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(confidence) or confidence < 0.0 or confidence > 1.0:
        return None
    return confidence


def parse_extractor_payload(payload: object, *, max_title_chars: int, max_subject_chars: int) -> TemporalExtractionResult:
    if not isinstance(payload, dict):
        return TemporalExtractionResult(
            result_class=RESULT_NO_TEMPORAL_SIGNAL,
            reject_reason="invalid_payload",
        )
    result_class = str(payload.get("result_class") or "").strip()
    if result_class not in RESULT_CLASSES:
        return TemporalExtractionResult(
            result_class=RESULT_NO_TEMPORAL_SIGNAL,
            reject_reason="invalid_result_class",
        )
    if result_class != RESULT_EXACT_TEMPORAL_SIGNAL:
        return TemporalExtractionResult(result_class=result_class)

    title = _bounded_str(payload.get("concise_title"), max_title_chars)
    if title is None:
        return TemporalExtractionResult(
            result_class=RESULT_NO_TEMPORAL_SIGNAL,
            reject_reason="missing_title",
        )
    date_kind = str(payload.get("start_date_kind") or "").strip()
    if date_kind not in DATE_KINDS:
        return TemporalExtractionResult(
            result_class=RESULT_NO_TEMPORAL_SIGNAL,
            reject_reason="invalid_date_kind",
        )
    local_time = _parse_local_time(payload.get("start_local_time"))
    if local_time is None:
        return TemporalExtractionResult(
            result_class=RESULT_NO_TEMPORAL_SIGNAL,
            reject_reason="invalid_start_time",
        )
    end_precision = str(payload.get("end_precision") or "").strip()
    if end_precision not in END_PRECISIONS:
        return TemporalExtractionResult(
            result_class=RESULT_NO_TEMPORAL_SIGNAL,
            reject_reason="invalid_end_precision",
        )
    participation = str(payload.get("participation") or "").strip()
    if participation not in PARTICIPATIONS:
        return TemporalExtractionResult(
            result_class=RESULT_NO_TEMPORAL_SIGNAL,
            reject_reason="invalid_participation",
        )
    confidence = _finite_confidence(payload.get("extraction_confidence"))
    if confidence is None:
        return TemporalExtractionResult(
            result_class=RESULT_NO_TEMPORAL_SIGNAL,
            reject_reason="invalid_confidence",
        )

    absolute_date = None
    relative_day_offset = None
    weekday = None
    if date_kind == DATE_KIND_ABSOLUTE:
        raw_date = _bounded_str(payload.get("start_absolute_date"), 32)
        if raw_date is None:
            return TemporalExtractionResult(
                result_class=RESULT_NO_TEMPORAL_SIGNAL,
                reject_reason="missing_absolute_date",
            )
        absolute_date = raw_date
    elif date_kind == DATE_KIND_RELATIVE_DAY:
        try:
            relative_day_offset = int(payload.get("start_relative_day_offset"))
        except (TypeError, ValueError):
            return TemporalExtractionResult(
                result_class=RESULT_NO_TEMPORAL_SIGNAL,
                reject_reason="invalid_relative_offset",
            )
        if relative_day_offset < -1 or relative_day_offset > 30:
            return TemporalExtractionResult(
                result_class=RESULT_UNSUPPORTED_PRECISION,
                reject_reason="relative_offset_out_of_range",
            )
    else:
        raw_weekday = str(payload.get("start_weekday") or "").strip().casefold()
        if raw_weekday not in WEEKDAYS:
            return TemporalExtractionResult(
                result_class=RESULT_NO_TEMPORAL_SIGNAL,
                reject_reason="invalid_weekday",
            )
        weekday = raw_weekday

    end_kind = None
    end_duration_minutes = None
    end_hour = None
    end_minute = None
    end_absolute = None
    if end_precision == END_PRECISION_EXACT:
        end_kind = str(payload.get("end_kind") or "").strip()
        if end_kind not in END_KINDS:
            return TemporalExtractionResult(
                result_class=RESULT_NO_TEMPORAL_SIGNAL,
                reject_reason="invalid_end_kind",
            )
        if end_kind == END_KIND_DURATION_MINUTES:
            try:
                end_duration_minutes = int(payload.get("end_duration_minutes"))
            except (TypeError, ValueError):
                return TemporalExtractionResult(
                    result_class=RESULT_NO_TEMPORAL_SIGNAL,
                    reject_reason="invalid_duration",
                )
        elif end_kind == END_KIND_LOCAL_TIME:
            parsed_end = _parse_local_time(payload.get("end_local_time"))
            if parsed_end is None:
                return TemporalExtractionResult(
                    result_class=RESULT_NO_TEMPORAL_SIGNAL,
                    reject_reason="invalid_end_time",
                )
            end_hour, end_minute = parsed_end
        else:
            end_absolute = _bounded_str(payload.get("end_absolute_datetime"), 64)
            if end_absolute is None:
                return TemporalExtractionResult(
                    result_class=RESULT_NO_TEMPORAL_SIGNAL,
                    reject_reason="missing_end_absolute",
                )

    return TemporalExtractionResult(
        result_class=RESULT_EXACT_TEMPORAL_SIGNAL,
        exact=ParsedExactSignal(
            concise_title=title,
            date_kind=date_kind,
            absolute_date=absolute_date,
            relative_day_offset=relative_day_offset,
            weekday=weekday,
            start_hour=local_time[0],
            start_minute=local_time[1],
            end_precision=end_precision,
            end_kind=end_kind,
            end_duration_minutes=end_duration_minutes,
            end_hour=end_hour,
            end_minute=end_minute,
            end_absolute=end_absolute,
            participation=participation,
            extraction_confidence=confidence,
            semantic_subject=_bounded_str(payload.get("semantic_subject"), max_subject_chars),
        ),
    )
