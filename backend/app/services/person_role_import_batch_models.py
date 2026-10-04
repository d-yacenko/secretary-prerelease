"""Strict inputs and frozen payload for a role-import batch ActionPlan."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.person_role_import_grounding_service import (
    MAX_GROUND_ITEMS,
    RoleImportGroundInputItem,
)

SOURCE_CHANGED = "role_import_source_changed"
GROUNDING_CHANGED = "role_import_grounding_changed"
PROVENANCE_KIND = "role_import_confirmed"
IMPORT_ORIGIN = "user"


class RoleImportBatchSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=0, le=MAX_GROUND_ITEMS - 1)
    person_id: UUID | None = None
    promotion_candidate_key: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        if (self.person_id is None) == (self.promotion_candidate_key is None):
            raise ValueError("selection requires exactly one person target")
        return self


class ApplyRoleImportBatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_object_id: UUID
    source_revision: str = Field(min_length=1)
    grounding_revision: str = Field(min_length=1)
    items_truncated: bool
    items: list[RoleImportGroundInputItem] = Field(max_length=MAX_GROUND_ITEMS)
    selections: list[RoleImportBatchSelection] = Field(min_length=1, max_length=MAX_GROUND_ITEMS)


class FrozenRoleImportRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int
    extracted_person_name: str
    person_id: UUID | None = None
    promotion_candidate_key: str | None = None
    target_display: str
    role: str
    context: str | None = None
    vocabulary_mode: Literal["reuse_existing", "create_if_missing"]
    role_term_id: UUID | None = None
    evidence_kind: Literal["identity_participant", "name_mentions"] | None = None

    @model_validator(mode="after")
    def _frozen_shape(self) -> Self:
        if (self.person_id is None) == (self.promotion_candidate_key is None):
            raise ValueError("frozen row requires exactly one person target")
        if self.vocabulary_mode == "reuse_existing" and self.role_term_id is None:
            raise ValueError("reuse requires role_term_id")
        if self.vocabulary_mode == "create_if_missing" and self.role_term_id is not None:
            raise ValueError("new role has no role_term_id")
        return self


class ApplyRoleImportBatchCanonicalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    source_object_id: UUID
    source_revision: str
    source_kind: Literal["image", "text"]
    source_truncated: bool
    items_truncated: bool
    grounding_revision: str
    total_extracted_rows: int = Field(ge=0, le=MAX_GROUND_ITEMS)
    selected_rows: list[FrozenRoleImportRow] = Field(min_length=1, max_length=MAX_GROUND_ITEMS)


class RoleImportBatchRowResult(BaseModel):
    row_index: int
    person_id: UUID
    person_created: bool
    assignment_id: UUID
    role_term_id: UUID
    role: str
    context: str | None = None
    changed: bool
    status: Literal["applied", "already_active", "duplicate_selected_row"]


class ApplyRoleImportBatchOutput(BaseModel):
    changed: bool
    source_object_id: UUID
    selected_count: int
    people_created: int
    assignments_changed: int
    assignments_no_op: int
    duplicate_rows: int
    rows: list[RoleImportBatchRowResult]
