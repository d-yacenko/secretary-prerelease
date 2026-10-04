"""Frozen role-import batch. Prepare writes only a pending ActionPlan."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PersonRoleTerm
from app.domain.person_promotion import promotion_candidate_key
from app.domain.person_role_text import (
    PersonRoleTextError,
    role_context_identity,
    role_term_identity,
)
from app.domain.role_import_mentions import mention_candidate_key
from app.services.action_plan_service import ActionPlanService, PendingActionPlanView
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_identity_service import PersonIdentityService
from app.services.person_promotion_service import PersonPromotionService
from app.services.person_role_import_batch_models import (
    GROUNDING_CHANGED,
    IMPORT_ORIGIN,
    PROVENANCE_KIND,
    ApplyRoleImportBatchCanonicalInput,
    ApplyRoleImportBatchInput,
    ApplyRoleImportBatchOutput,
    FrozenRoleImportRow,
    RoleImportBatchRowResult,
)
from app.services.person_role_import_grounding_service import (
    PersonRoleImportGroundingService,
    RoleImportGroundedItem,
    RoleImportGroundRequest,
    _display_key,
)
from app.services.person_role_import_mention_service import PersonRoleImportMentionEvidenceService
from app.services.person_role_import_source_service import PersonRoleImportSourceService
from app.services.person_role_service import PersonRoleService
from app.services.user_serialization_gate import lock_user_serialization_row
from app.tools.schemas import ResolvePersonOutput

TOOL_NAME = "apply_role_import_batch"


class PersonRoleImportBatchService:
    def __init__(self, session: Session, user_id: UUID, upload_root: Path) -> None:
        self._session = session
        self._user_id = user_id
        self._upload_root = upload_root
        self._sources = PersonRoleImportSourceService(session, user_id, upload_root)
        self._grounding = PersonRoleImportGroundingService(session, user_id, upload_root)

    def prepare_plan(self, request: ApplyRoleImportBatchInput) -> PendingActionPlanView:
        canonical = self.prepare(request)
        return ActionPlanService(self._session, self._user_id).create_plan(
            [
                {
                    "tool_name": TOOL_NAME,
                    "arguments": canonical.model_dump(mode="json", exclude_none=True),
                }
            ]
        )

    def prepare(self, request: ApplyRoleImportBatchInput) -> ApplyRoleImportBatchCanonicalInput:
        _unique_selections(request)
        grounded = self._grounding.ground(
            RoleImportGroundRequest(
                source_object_id=request.source_object_id,
                source_revision=request.source_revision,
                items_truncated=request.items_truncated,
                items=request.items,
            )
        )
        if grounded.grounding_revision != request.grounding_revision:
            raise ValidationError(GROUNDING_CHANGED)
        by_index = {item.row_index: item for item in grounded.items}
        selected = [
            _freeze_row(_selected_item(by_index, selection.row_index), selection)
            for selection in request.selections
        ]
        return ApplyRoleImportBatchCanonicalInput(
            operation_id=uuid4(),
            source_object_id=grounded.source_object_id,
            source_revision=grounded.source_revision,
            source_kind=grounded.source_kind,  # type: ignore[arg-type]
            source_truncated=grounded.source_truncated,
            items_truncated=grounded.items_truncated,
            grounding_revision=grounded.grounding_revision,
            total_extracted_rows=len(grounded.items),
            selected_rows=selected,
        )

    def execute(self, payload: ApplyRoleImportBatchCanonicalInput) -> ApplyRoleImportBatchOutput:
        if lock_user_serialization_row(self._session, self._user_id) is None:
            raise NotFoundError("user", self._user_id)
        self._sources.lock_for_execution(payload.source_object_id)
        source = self._sources.load(payload.source_object_id)
        if source.source_revision != payload.source_revision:
            raise ValidationError("role_import_source_changed")
        people = PersonAssistantService(self._session, self._user_id)
        promotion = PersonPromotionService(self._session, self._user_id)
        roles = PersonRoleService(self._session, self._user_id)
        identities = PersonIdentityService(self._session, self._user_id)
        contacts = promotion.eligible_role_import_participants()
        mention_evidence = _mention_evidence(self._session, self._user_id, payload.selected_rows)
        promoted: dict[str, UUID] = {}
        seen: dict[tuple[UUID, str, str], RoleImportBatchRowResult] = {}
        results: list[RoleImportBatchRowResult] = []
        for row in payload.selected_rows:
            person_id, person_created = _person_target(
                row, people, promotion, identities, contacts, mention_evidence, promoted
            )
            role_display, role_key = _revalidated_role(self._session, self._user_id, row)
            _context, context_key = role_context_identity(row.context)
            dedup_key = (person_id, role_key, context_key)
            prior = seen.get(dedup_key)
            if prior is not None:
                duplicate = prior.model_copy(
                    update={
                        "row_index": row.row_index,
                        "person_created": False,
                        "changed": False,
                        "status": "duplicate_selected_row",
                    }
                )
                results.append(duplicate)
                continue
            assignment, changed = roles.assign_outcome(
                person_id,
                role_display,
                row.context,
                origin=IMPORT_ORIGIN,
                provenance_kind=PROVENANCE_KIND,
                provenance_key=f"role-import:{payload.operation_id}",
                source_object_id=payload.source_object_id,
            )
            result = RoleImportBatchRowResult(
                row_index=row.row_index,
                person_id=person_id,
                person_created=person_created,
                assignment_id=assignment.id,
                role_term_id=assignment.role_term_id,
                role=role_display,
                context=row.context,
                changed=changed,
                status="applied" if changed else "already_active",
            )
            seen[dedup_key] = result
            results.append(result)
        people_created = sum(1 for row in results if row.person_created)
        assignments_changed = sum(1 for row in results if row.status == "applied")
        assignments_no_op = sum(1 for row in results if row.status == "already_active")
        duplicate_rows = sum(1 for row in results if row.status == "duplicate_selected_row")
        return ApplyRoleImportBatchOutput(
            changed=people_created > 0 or assignments_changed > 0,
            source_object_id=payload.source_object_id,
            selected_count=len(payload.selected_rows),
            people_created=people_created,
            assignments_changed=assignments_changed,
            assignments_no_op=assignments_no_op,
            duplicate_rows=duplicate_rows,
            rows=results,
        )


def _unique_selections(request: ApplyRoleImportBatchInput) -> None:
    indexes = [selection.row_index for selection in request.selections]
    if len(indexes) != len(set(indexes)):
        raise ValidationError("duplicate role import selection")


def _selected_item(by_index: dict[int, RoleImportGroundedItem], row_index: int) -> RoleImportGroundedItem:
    item = by_index.get(row_index)
    if item is None:
        raise ValidationError("role import row is not in the grounded proposal")
    return item


def _freeze_row(item: RoleImportGroundedItem, selection) -> FrozenRoleImportRow:
    person = item.person_resolution
    role = item.role_resolution
    if selection.person_id is not None:
        if person.state == "resolved" and person.person_id == selection.person_id:
            display = person.title or item.person_name
        elif person.state == "ambiguous" and any(
            candidate.person_id == selection.person_id for candidate in person.candidates
        ):
            display = next(
                candidate.title
                for candidate in person.candidates
                if candidate.person_id == selection.person_id
            )
        elif person.state == "unresolved":
            raise ValidationError("unresolved role import row cannot be selected")
        else:
            raise ValidationError("selected person is not grounded")
        person_id = selection.person_id
        candidate_key = None
        evidence_kind = None
    else:
        if person.state != "promotion_candidates":
            raise ValidationError("selected promotion candidate is not grounded")
        match = next(
            (
                candidate
                for candidate in person.promotion_candidates
                if candidate.candidate_key == selection.promotion_candidate_key
            ),
            None,
        )
        if match is None:
            raise ValidationError("selected promotion candidate is not grounded")
        display = match.display_name
        person_id = None
        candidate_key = match.candidate_key
        evidence_kind = match.evidence_kind
    if role.state == "reuse_existing":
        mode = "reuse_existing"
        role_term_id = role.role_term_id
    else:
        mode = "create_if_missing"
        role_term_id = None
    return FrozenRoleImportRow(
        row_index=item.row_index,
        extracted_person_name=item.person_name,
        person_id=person_id,
        promotion_candidate_key=candidate_key,
        target_display=display,
        role=item.role,
        context=item.context,
        vocabulary_mode=mode,  # type: ignore[arg-type]
        role_term_id=role_term_id,
        evidence_kind=evidence_kind,  # type: ignore[arg-type]
    )


def _mention_evidence(session: Session, user_id: UUID, rows: list[FrozenRoleImportRow]) -> dict:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.evidence_kind != "name_mentions" or row.extracted_person_name in seen:
            continue
        seen.add(row.extracted_person_name)
        names.append(row.extracted_person_name)
    if not names:
        return {}
    return PersonRoleImportMentionEvidenceService(session, user_id).evidence_for(names)


def _person_target(row, people, promotion, identities, contacts, mention_evidence, promoted):
    resolved = people.resolve(row.extracted_person_name)
    if row.person_id is not None:
        if not _person_still_grounded(resolved, row.person_id):
            raise ValidationError(GROUNDING_CHANGED)
        return row.person_id, False
    if row.evidence_kind == "name_mentions":
        return _mention_person(row, resolved, contacts, mention_evidence, identities, promoted)
    key = row.promotion_candidate_key
    cached = promoted.get(key)
    if cached is not None:
        return cached, False
    if resolved.state != "none":
        raise ValidationError(GROUNDING_CHANGED)
    match = next(
        (
            item
            for item in contacts
            if promotion_candidate_key(item.identity) == key
            and _display_key(item.display_value) == _display_key(row.extracted_person_name)
        ),
        None,
    )
    if match is None:
        raise ValidationError(GROUNDING_CHANGED)
    owner_before = identities.resolve(match.identity)
    try:
        person = promotion.approve_role_import_participant(
            match.identity,
            display_name=row.extracted_person_name,
        )
    except ConflictError as exc:
        raise ValidationError("role import identity conflict") from exc
    except ValidationError as exc:
        raise ValidationError(GROUNDING_CHANGED) from exc
    created = owner_before is None
    promoted[key] = person.id
    return person.id, created


def _mention_person(row, resolved, contacts, mention_evidence, identities, promoted):
    key = row.promotion_candidate_key
    cached = promoted.get(key)
    if cached is not None:
        return cached, False
    if resolved.state != "none":
        raise ValidationError(GROUNDING_CHANGED)
    wanted = _display_key(row.extracted_person_name)
    if any(_display_key(item.display_value) == wanted for item in contacts):
        raise ValidationError(GROUNDING_CHANGED)
    evidence = mention_evidence.get(row.extracted_person_name)
    if (
        evidence is None
        or evidence.candidate_key != key
        or evidence.candidate_key != mention_candidate_key(row.extracted_person_name)
        or _display_key(row.target_display) != wanted
    ):
        raise ValidationError(GROUNDING_CHANGED)
    person = identities.create_person(row.extracted_person_name)
    promoted[key] = person.id
    return person.id, True


def _person_still_grounded(resolved: ResolvePersonOutput, person_id: UUID) -> bool:
    if resolved.state == "resolved" and resolved.person_id == person_id:
        return True
    if resolved.state == "ambiguous":
        return any(candidate.person_id == person_id for candidate in resolved.candidates)
    return False


def _revalidated_role(session: Session, user_id: UUID, row: FrozenRoleImportRow) -> tuple[str, str]:
    try:
        display, key = role_term_identity(row.role)
    except PersonRoleTextError as exc:
        raise ValidationError(exc.message) from exc
    if row.vocabulary_mode == "reuse_existing":
        term = session.get(PersonRoleTerm, row.role_term_id)
        if term is None or term.user_id != user_id or term.normalized_key != key:
            raise ValidationError(GROUNDING_CHANGED)
        return term.display_text, key
    existing = session.scalar(
        select(PersonRoleTerm).where(
            PersonRoleTerm.user_id == user_id,
            PersonRoleTerm.normalized_key == key,
        )
    )
    if existing is not None:
        return existing.display_text, key
    return display, key
