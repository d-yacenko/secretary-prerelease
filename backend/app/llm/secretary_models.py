from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ProposalType = Literal["task", "deadline", "meeting", "relation", "note"]


class SecretaryProposal(BaseModel):
    type: ProposalType
    title: str
    description: str | None = None
    due_at: datetime | None = None
    start_at: datetime | None = None
    relation_type: str | None = None
    target_object_id: UUID | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_item_indices: list[int] = Field(min_length=1)


class SecretaryAnalysis(BaseModel):
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    urgency: float | None = Field(default=None, ge=0.0, le=1.0)
    summary: str | None = None
    proposals: list[SecretaryProposal] = Field(default_factory=list)
    next_action: str | None = None


class SecretaryResult(BaseModel):
    success: bool
    analysis: SecretaryAnalysis | None = None
    error: str | None = None
