"""Serializable Secretary agent eval records.

Timestamps are optional and are not part of structural equality.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DimensionStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class OverallStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"


class ToolCallRecord(BaseModel):
    sequence: int
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    success: bool = False
    status: str = "tool_error"
    approval_required: bool = False
    executed: bool = False
    effect: dict[str, Any] = Field(default_factory=dict)
    error_category: str | None = None


class EvalRun(BaseModel):
    scenario_id: str
    utterance: str
    run_id: str
    calls: list[ToolCallRecord] = Field(default_factory=list)
    symbols: dict[str, str] = Field(default_factory=dict)
    final_facts: dict[str, Any] = Field(default_factory=dict)
    final_answer: str = ""
    model: str | None = None
    timestamp: str | None = None


class DimensionScore(BaseModel):
    dimension: str
    status: DimensionStatus
    reasons: list[str] = Field(default_factory=list)


class ScoreReport(BaseModel):
    scenario_id: str
    overall: OverallStatus
    dimensions: list[DimensionScore]

    def dimension(self, name: str) -> DimensionScore:
        for item in self.dimensions:
            if item.dimension == name:
                return item
        raise KeyError(name)
