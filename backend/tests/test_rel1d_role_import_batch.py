"""Frozen role-import batch ActionPlan and atomic approval."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError as ModelValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.assistant.execution_effects import (
    classify_tool_execution_effect,
    describe_execution_effect,
)
from app.db.models import (
    AITrace,
    AITraceEvent,
    Object,
    PendingActionPlan,
    PersonIdentity,
    PersonIdentityEvidence,
    PersonRoleAssignment,
    PersonRoleTerm,
    Representation,
)
from app.db.session import engine
from app.services.action_plan_service import ActionPlanService
from app.services.client_representation_service import ClientRepresentationPersistence
from app.services.domain_tool_service import DomainToolService
from app.services.domain_write_mode import DomainWriteMode
from app.services.errors import ConflictError, ValidationError
from app.services.person_consolidation_service import PersonConsolidationService
from app.services.person_identity_service import PersonIdentityService
from app.services.person_promotion_service import PersonPromotionService
from app.services.person_role_import_batch_models import (
    ApplyRoleImportBatchInput,
    RoleImportBatchSelection,
)
from app.services.person_role_import_batch_service import PersonRoleImportBatchService
from app.services.person_role_import_grounding_service import (
    RoleImportGroundInputItem,
)
from app.services.person_role_import_source_service import PersonRoleImportSourceService
from app.services.person_role_service import (
    MANUAL_PROVENANCE_KEY,
    MANUAL_PROVENANCE_KIND,
    PersonRoleService,
)
from app.services.representation_service import KIND_FULL, RepresentationService
from app.services.user_serialization_gate import lock_user_serialization_row
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.policy import PolicyDecision, evaluate_policy
from app.tools.registry import (
    ASSISTANT_TOOL_DEFINITIONS,
    MCP_TOOL_NAMES,
    TOOL_REGISTRY,
    get_tool_spec,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_rel1d_role_import_grounding import _ground, _mail, _row
from tests.test_rel1d_role_import_source import _text_object

_NAME = "REL1DC Резолв Один"
_AMBIGUOUS = "REL1DC Двойной"
_PROMO = "REL1DC Уникада"
_PROMO_B = "REL1DC Вторая"
_ROLE = "rel1dcдиректор"
_ROLE_B = "rel1dcсекретарь"
_FORBIDDEN = ("evidence_text", "source_locator", "canonical_value", "salience", "normalized_key")


def test_prepare_creates_one_pending_plan_without_person_or_role_writes(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    before = _fact_counts(db_session)
    plan = _prepare(db_session, tmp_path, [_row(_NAME, _ROLE)], [{"row_index": 0, "person_id": person.id}])
    after = _fact_counts(db_session)
    stored = db_session.get(PendingActionPlan, plan.id)
    assert plan.status == "pending"
    assert stored is not None
    assert len(stored.actions) == 1
    assert stored.actions[0]["tool_name"] == "apply_role_import_batch"
    assert after["people"] == before["people"]
    assert after["assignments"] == before["assignments"]
    assert after["terms"] == before["terms"]
    assert after["identities"] == before["identities"]
    assert after["plans"] == before["plans"] + 1


def test_batch_tool_has_no_generic_prepare_path() -> None:
    spec = TOOL_REGISTRY["apply_role_import_batch"]
    assert spec.prepare_method is None
    assert not hasattr(DomainToolService, "prepare_apply_role_import_batch")
    assert spec.permission.value == "INTERNAL_WRITE"
    assert spec.assistant_exposed is False
    assert spec.mcp_exposed is False
    assert spec.assistant_definition is None
    assert spec.execution_input_model.__name__ == "ApplyRoleImportBatchCanonicalInput"


def test_specialized_endpoint_prepares_one_frozen_plan(auth_client, db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    source, revision, proposal = _proposal(db_session, tmp_path, [_row(_NAME, _ROLE)])
    response = auth_client.post(
        "/people/role-import/action-plan",
        json=_body(
            source.id,
            revision,
            proposal.grounding_revision,
            [_row(_NAME, _ROLE)],
            [{"row_index": 0, "person_id": str(person.id)}],
        ),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    assert len(payload["actions"]) == 1
    assert payload["actions"][0]["tool_name"] == "apply_role_import_batch"
    assert payload["actions"][0]["arguments"]["selected_rows"][0]["person_id"] == str(person.id)


def test_tool_is_internal_and_baseline_execute_does_not_persist(db_session) -> None:
    spec = get_tool_spec("apply_role_import_batch")
    assert spec is not None
    assert spec.permission.value == "INTERNAL_WRITE"
    assert spec.assistant_exposed is False
    assert spec.mcp_exposed is False
    assert spec.assistant_definition is None
    assert spec.name not in MCP_TOOL_NAMES
    assert spec.name not in {item["name"] for item in ASSISTANT_TOOL_DEFINITIONS}
    assert evaluate_policy(spec.permission, ExecutionContext.INTERACTIVE_ASSISTANT) == (
        PolicyDecision.REQUIRE_APPROVAL
    )
    before = _fact_counts(db_session)
    result = ToolExecutionGateway().execute(
        DomainToolService(db_session, BOOTSTRAP_USER_ID, None),
        spec.name,
        {
            "source_object_id": str(uuid4()),
            "source_revision": "abc",
            "grounding_revision": "def",
            "items_truncated": False,
            "items": [_row(_NAME, _ROLE)],
            "selections": [{"row_index": 0, "person_id": str(uuid4())}],
        },
    )
    assert result.success is False
    assert _fact_counts(db_session) == before


def test_invalid_empty_duplicate_and_injected_selections_fail(auth_client, db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    source, revision, proposal = _proposal(db_session, tmp_path, [_row(_NAME, _ROLE)])
    body = _body(source.id, revision, proposal.grounding_revision, [_row(_NAME, _ROLE)], [])
    with pytest.raises(ModelValidationError):
        ApplyRoleImportBatchInput.model_validate(body)
    duplicate = _body(
        source.id,
        revision,
        proposal.grounding_revision,
        [_row(_NAME, _ROLE)],
        [{"row_index": 0, "person_id": str(person.id)}, {"row_index": 0, "person_id": str(person.id)}],
    )
    with pytest.raises(ValidationError, match="duplicate role import selection"):
        _service(db_session, tmp_path).prepare_plan(ApplyRoleImportBatchInput.model_validate(duplicate))
    response = auth_client.post(
        "/people/role-import/action-plan",
        json={
            **body,
            "selections": [{"row_index": 0, "person_id": str(person.id), "role_term_id": str(uuid4())}],
        },
    )
    assert response.status_code == 422
    injected = auth_client.post(
        "/people/role-import/action-plan",
        json={**_body(source.id, revision, proposal.grounding_revision, [_row(_NAME, _ROLE)], [
            {"row_index": 0, "person_id": str(person.id)}
        ]), "create_role": True},
    )
    assert injected.status_code == 422


def test_selection_rules_follow_grounded_state(db_session, tmp_path) -> None:
    resolved = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    first = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_AMBIGUOUS)
    PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_AMBIGUOUS)
    _mail(db_session, f"{_PROMO} <uniquada-c1@example.com>")
    _mail(db_session, f"{_PROMO} <uniquada-c1@example.com>")
    items = [
        _row(_NAME, _ROLE),
        _row(_AMBIGUOUS, _ROLE_B),
        _row(_PROMO, "rel1dcпромо"),
        _row("Никого Нет C1", "rel1dcпусто"),
    ]
    source, revision, proposal = _proposal(db_session, tmp_path, items)
    states = [item.person_resolution.state for item in proposal.items]
    assert states == ["resolved", "ambiguous", "promotion_candidates", "unresolved"]
    frozen = _service(db_session, tmp_path).prepare(
        _input(
            source.id,
            revision,
            proposal.grounding_revision,
            items,
            [
                {"row_index": 0, "person_id": resolved.id},
                {"row_index": 1, "person_id": first.id},
                {"row_index": 2, "promotion_candidate_key": proposal.items[2].person_resolution.promotion_candidates[0].candidate_key},
            ],
        )
    )
    assert frozen.selected_rows[0].person_id == resolved.id
    assert frozen.selected_rows[1].person_id == first.id
    assert frozen.selected_rows[2].promotion_candidate_key
    with pytest.raises(ValidationError, match="unresolved role import row cannot be selected"):
        _service(db_session, tmp_path).prepare(
            _input(source.id, revision, proposal.grounding_revision, items, [{"row_index": 3, "person_id": resolved.id}])
        )
    with pytest.raises(ValidationError, match="selected person is not grounded"):
        _service(db_session, tmp_path).prepare(
            _input(source.id, revision, proposal.grounding_revision, items, [{"row_index": 1, "person_id": resolved.id}])
        )
    with pytest.raises(ValidationError, match="selected promotion candidate is not grounded"):
        _service(db_session, tmp_path).prepare(
            _input(
                source.id,
                revision,
                proposal.grounding_revision,
                items,
                [{"row_index": 0, "promotion_candidate_key": "a" * 64}],
            )
        )


def test_source_and_grounding_staleness_fail_prepare(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    source, revision, proposal = _proposal(db_session, tmp_path, [_row(_NAME, _ROLE)])
    with pytest.raises(ValidationError, match="role_import_source_changed"):
        _service(db_session, tmp_path).prepare_plan(
            _input(source.id, "stale-revision", proposal.grounding_revision, [_row(_NAME, _ROLE)], [
                {"row_index": 0, "person_id": person.id}
            ])
        )
    person.title = "REL1DC Другое имя"
    db_session.flush()
    with pytest.raises(ValidationError, match="role_import_grounding_changed"):
        _service(db_session, tmp_path).prepare_plan(
            _input(source.id, revision, proposal.grounding_revision, [_row(_NAME, _ROLE)], [
                {"row_index": 0, "person_id": person.id}
            ])
        )


def test_frozen_arguments_omit_evidence_and_raw_identity(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    plan = _prepare(db_session, tmp_path, [_row(_NAME, _ROLE, context="совет")], [{"row_index": 0, "person_id": person.id}])
    stored = db_session.get(PendingActionPlan, plan.id)
    arguments = stored.actions[0]["arguments"]
    blob = str(arguments)
    assert arguments["selected_rows"][0]["vocabulary_mode"] == "create_if_missing"
    assert "role_term_id" not in arguments["selected_rows"][0]
    for token in _FORBIDDEN:
        assert token not in blob


def test_presentation_is_bounded_and_omits_private_keys(db_session, tmp_path) -> None:
    _mail(db_session, f"{_PROMO} <uniquada-c1-card@example.com>")
    _mail(db_session, f"{_PROMO} <uniquada-c1-card@example.com>")
    items = [_row(_PROMO, _ROLE, context="совет")]
    source, revision, proposal = _proposal(db_session, tmp_path, items)
    key = proposal.items[0].person_resolution.promotion_candidates[0].candidate_key
    plan = _service(db_session, tmp_path).prepare_plan(
        _input(source.id, revision, proposal.grounding_revision, items, [
            {"row_index": 0, "promotion_candidate_key": key}
        ])
    )
    presentation = plan.actions[0]["presentation"]
    assert presentation["operation"] == "apply_role_import_batch"
    assert presentation["source_title"] == "notes"
    assert presentation["selected_count"] == 1
    assert presentation["total_extracted_rows"] == 1
    assert presentation["rows"][0]["target_mode"] == "promote_person"
    assert presentation["rows"][0]["vocabulary_mode"] == "create_if_missing"
    blob = str(presentation)
    assert key not in blob
    assert "uniquada-c1-card@example.com" not in blob
    for token in _FORBIDDEN:
        assert token not in blob


def test_reject_and_expire_write_no_person_or_role_facts(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    before = _fact_counts(db_session)
    rejected = _prepare(db_session, tmp_path, [_row(_NAME, _ROLE)], [{"row_index": 0, "person_id": person.id}])
    view = ActionPlanService(db_session, BOOTSTRAP_USER_ID).reject(rejected.id)
    assert view.status == "rejected"
    expired = _prepare(db_session, tmp_path, [_row(_NAME, _ROLE_B)], [{"row_index": 0, "person_id": person.id}])
    row = db_session.get(PendingActionPlan, expired.id)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=5)
    expired_view = ActionPlanService(db_session, BOOTSTRAP_USER_ID).approve(expired.id)
    assert expired_view.status == "expired"
    after = _fact_counts(db_session)
    assert after["people"] == before["people"]
    assert after["assignments"] == before["assignments"]
    assert after["terms"] == before["terms"]
    assert after["plans"] == before["plans"] + 2


def test_approve_existing_person_reuses_and_creates_roles(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    other = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("REL1DC Носитель термина")
    existing = PersonRoleService(db_session, BOOTSTRAP_USER_ID).assign(other.id, _ROLE)
    items = [_row(_NAME, _ROLE), _row(_NAME, _ROLE_B)]
    plan = _prepare(
        db_session,
        tmp_path,
        items,
        [{"row_index": 0, "person_id": person.id}, {"row_index": 1, "person_id": person.id}],
    )
    view = _approve(db_session, plan.id)
    assert view.status == "executed"
    output = view.result["actions"][0]["output"]
    assert output["changed"] is True
    assert output["assignments_changed"] == 2
    assert output["rows"][0]["status"] == "applied"
    assert output["rows"][0]["role_term_id"] == str(existing.role_term_id)
    assert output["rows"][1]["status"] == "applied"
    assert output["rows"][1]["role_term_id"] != str(existing.role_term_id)


def test_approve_uses_only_the_explicit_ambiguous_person(db_session, tmp_path) -> None:
    chosen = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_AMBIGUOUS)
    other = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_AMBIGUOUS)
    plan = _prepare(db_session, tmp_path, [_row(_AMBIGUOUS, _ROLE)], [{"row_index": 0, "person_id": chosen.id}])
    output = _approve(db_session, plan.id).result["actions"][0]["output"]
    assert output["rows"][0]["person_id"] == str(chosen.id)
    assert _assignments_for(db_session, other.id) == []


def test_approve_promotion_creates_person_identity_and_role(db_session, tmp_path) -> None:
    _mail(db_session, f"{_PROMO} <uniquada-c1-apply@example.com>")
    _mail(db_session, f"{_PROMO} <uniquada-c1-apply@example.com>")
    source, revision, proposal = _proposal(db_session, tmp_path, [_row(_PROMO, _ROLE)])
    key = proposal.items[0].person_resolution.promotion_candidates[0].candidate_key
    plan = _service(db_session, tmp_path).prepare_plan(
        _input(source.id, revision, proposal.grounding_revision, [_row(_PROMO, _ROLE)], [
            {"row_index": 0, "promotion_candidate_key": key}
        ])
    )
    output = _approve(db_session, plan.id).result["actions"][0]["output"]
    assert output["people_created"] == 1
    assert output["rows"][0]["person_created"] is True
    person_id = output["rows"][0]["person_id"]
    assert db_session.get(Object, person_id).title == _PROMO
    assert db_session.scalar(select(func.count()).select_from(PersonIdentity).where(PersonIdentity.person_object_id == person_id)) == 1
    assert db_session.scalar(
        select(func.count()).select_from(PersonIdentityEvidence).where(PersonIdentityEvidence.person_object_id == person_id)
    ) == 1


def test_two_roles_for_one_promotion_create_one_person(db_session, tmp_path) -> None:
    _mail(db_session, f"{_PROMO} <uniquada-c1-two@example.com>")
    _mail(db_session, f"{_PROMO} <uniquada-c1-two@example.com>")
    items = [_row(_PROMO, _ROLE), _row(_PROMO, _ROLE_B, context="совет")]
    source, revision, proposal = _proposal(db_session, tmp_path, items)
    key = proposal.items[0].person_resolution.promotion_candidates[0].candidate_key
    plan = _service(db_session, tmp_path).prepare_plan(
        _input(source.id, revision, proposal.grounding_revision, items, [
            {"row_index": 0, "promotion_candidate_key": key},
            {"row_index": 1, "promotion_candidate_key": key},
        ])
    )
    output = _approve(db_session, plan.id).result["actions"][0]["output"]
    assert output["people_created"] == 1
    assert output["assignments_changed"] == 2
    assert output["rows"][0]["person_id"] == output["rows"][1]["person_id"]
    assert output["rows"][1]["person_created"] is False


def test_semantic_duplicate_rows_create_one_assignment(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    items = [_row(_NAME, "REL1DC Директор"), _row(_NAME, "rel1dc   директор")]
    plan = _prepare(
        db_session,
        tmp_path,
        items,
        [{"row_index": 0, "person_id": person.id}, {"row_index": 1, "person_id": person.id}],
    )
    output = _approve(db_session, plan.id).result["actions"][0]["output"]
    assert output["assignments_changed"] == 1
    assert output["duplicate_rows"] == 1
    assert output["rows"][1]["status"] == "duplicate_selected_row"
    assert output["rows"][1]["changed"] is False
    assert len(_assignments_for(db_session, person.id)) == 1


def test_same_role_with_different_contexts_stays_distinct(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    items = [_row(_NAME, _ROLE, context="совет"), _row(_NAME, _ROLE, context="проект")]
    plan = _prepare(
        db_session,
        tmp_path,
        items,
        [{"row_index": 0, "person_id": person.id}, {"row_index": 1, "person_id": person.id}],
    )
    output = _approve(db_session, plan.id).result["actions"][0]["output"]
    assert output["assignments_changed"] == 2
    assert len(_assignments_for(db_session, person.id)) == 2


def test_manual_assignment_noop_preserves_provenance_and_source(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    existing = PersonRoleService(db_session, BOOTSTRAP_USER_ID).assign(person.id, _ROLE, "совет")
    plan = _prepare(
        db_session,
        tmp_path,
        [_row(_NAME, _ROLE, context="совет")],
        [{"row_index": 0, "person_id": person.id}],
    )
    output = _approve(db_session, plan.id).result["actions"][0]["output"]
    assert output["changed"] is False
    assert output["rows"][0]["status"] == "already_active"
    row = db_session.get(PersonRoleAssignment, existing.id)
    assert row.origin == "user"
    assert row.provenance_kind == MANUAL_PROVENANCE_KIND
    assert row.provenance_key == MANUAL_PROVENANCE_KEY
    assert row.source_object_id is None


def test_new_import_assignment_records_confirmed_provenance(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    plan = _prepare(db_session, tmp_path, [_row(_NAME, _ROLE)], [{"row_index": 0, "person_id": person.id}])
    output = _approve(db_session, plan.id).result["actions"][0]["output"]
    stored = db_session.get(PendingActionPlan, plan.id)
    operation_id = stored.actions[0]["arguments"]["operation_id"]
    row = db_session.get(PersonRoleAssignment, output["rows"][0]["assignment_id"])
    assert row.origin == "user"
    assert row.provenance_kind == "role_import_confirmed"
    assert row.provenance_key == f"role-import:{operation_id}"
    assert str(row.source_object_id) == stored.actions[0]["arguments"]["source_object_id"]


def test_rel1c_provenance_stays_unchanged_on_noop(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    existing, _changed = PersonRoleService(db_session, BOOTSTRAP_USER_ID).assign_outcome(
        person.id,
        _ROLE,
        "совет",
        origin="agent",
        provenance_kind="assistant_action_plan",
        provenance_key="aap:rel1c-existing",
    )
    plan = _prepare(
        db_session,
        tmp_path,
        [_row(_NAME, _ROLE, context="совет")],
        [{"row_index": 0, "person_id": person.id}],
    )
    _approve(db_session, plan.id)
    row = db_session.get(PersonRoleAssignment, existing.id)
    assert row.origin == "agent"
    assert row.provenance_kind == "assistant_action_plan"
    assert row.provenance_key == "aap:rel1c-existing"
    assert row.source_object_id is None


def test_exact_role_term_appearing_after_staging_is_reused(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    holder = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person("REL1DC Держатель")
    plan = _prepare(db_session, tmp_path, [_row(_NAME, _ROLE)], [{"row_index": 0, "person_id": person.id}])
    raced = PersonRoleService(db_session, BOOTSTRAP_USER_ID).assign(holder.id, _ROLE.upper())
    output = _approve(db_session, plan.id).result["actions"][0]["output"]
    assert output["rows"][0]["role_term_id"] == str(raced.role_term_id)
    assert _term_count(db_session, _ROLE) == 1


def test_cap_failure_rolls_back_the_whole_plan(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    roles = PersonRoleService(db_session, BOOTSTRAP_USER_ID)
    for index in range(15):
        roles.assign(person.id, f"rel1dcзанято {index}")
    items = [_row(_NAME, "rel1dcновый а"), _row(_NAME, "rel1dcновый б")]
    plan = _prepare(
        db_session,
        tmp_path,
        items,
        [{"row_index": 0, "person_id": person.id}, {"row_index": 1, "person_id": person.id}],
    )
    view = _approve(db_session, plan.id)
    assert view.status == "failed"
    assert "active role assignment cap reached" in view.failure
    assert len(_assignments_for(db_session, person.id)) == 15


def test_source_person_and_promotion_drift_fail_the_plan(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    source_plan = _prepare(db_session, tmp_path, [_row(_NAME, _ROLE)], [{"row_index": 0, "person_id": person.id}])
    source = db_session.get(Object, db_session.get(PendingActionPlan, source_plan.id).actions[0]["arguments"]["source_object_id"])
    source.body = "replacement body for role import"
    db_session.flush()
    source_view = _approve(db_session, source_plan.id)
    assert source_view.status == "failed"
    assert "role_import_source_changed" in source_view.failure

    person_plan = _prepare(db_session, tmp_path, [_row(_NAME, _ROLE_B)], [{"row_index": 0, "person_id": person.id}])
    person.title = "REL1DC Уже не то имя"
    db_session.flush()
    person_view = _approve(db_session, person_plan.id)
    assert person_view.status == "failed"
    assert "role_import_grounding_changed" in person_view.failure

    _mail(db_session, f"{_PROMO_B} <second-c1@example.com>")
    _mail(db_session, f"{_PROMO_B} <second-c1@example.com>")
    items = [_row(_PROMO_B, "rel1dcдрейф")]
    source_row, revision, proposal = _proposal(db_session, tmp_path, items)
    key = proposal.items[0].person_resolution.promotion_candidates[0].candidate_key
    promo_plan = _service(db_session, tmp_path).prepare_plan(
        _input(source_row.id, revision, proposal.grounding_revision, items, [
            {"row_index": 0, "promotion_candidate_key": key}
        ])
    )
    mail = db_session.scalar(select(Object).where(Object.metadata_["sender"].astext == f"{_PROMO_B} <second-c1@example.com>"))
    db_session.delete(mail)
    db_session.flush()
    promo_view = _approve(db_session, promo_plan.id)
    assert promo_view.status == "failed"
    assert "role_import_grounding_changed" in promo_view.failure
    assert _fact_counts(db_session)["assignments"] == 0 or _assignments_for(db_session, person.id) == []


def test_identity_conflict_fails_the_plan(db_session, tmp_path, monkeypatch) -> None:
    _mail(db_session, f"{_PROMO} <conflict-c1@example.com>")
    _mail(db_session, f"{_PROMO} <conflict-c1@example.com>")
    items = [_row(_PROMO, _ROLE)]
    source, revision, proposal = _proposal(db_session, tmp_path, items)
    key = proposal.items[0].person_resolution.promotion_candidates[0].candidate_key
    plan = _service(db_session, tmp_path).prepare_plan(
        _input(source.id, revision, proposal.grounding_revision, items, [
            {"row_index": 0, "promotion_candidate_key": key}
        ])
    )
    before = _fact_counts(db_session)

    def _conflict(self, identity):
        raise ConflictError("person identity is already bound")

    monkeypatch.setattr(PersonPromotionService, "approve", _conflict)
    view = _approve(db_session, plan.id)
    assert view.status == "failed"
    assert "role import identity conflict" in view.failure
    assert _fact_counts(db_session)["people"] == before["people"]
    assert _fact_counts(db_session)["identities"] == before["identities"]


def test_later_row_failure_rolls_back_earlier_promotion_and_role(db_session, tmp_path, monkeypatch) -> None:
    _mail(db_session, f"{_PROMO} <rollback-a@example.com>")
    _mail(db_session, f"{_PROMO} <rollback-a@example.com>")
    _mail(db_session, f"{_PROMO_B} <rollback-b@example.com>")
    _mail(db_session, f"{_PROMO_B} <rollback-b@example.com>")
    items = [_row(_PROMO, _ROLE), _row(_PROMO_B, _ROLE_B)]
    source, revision, proposal = _proposal(db_session, tmp_path, items)
    keys = [
        proposal.items[0].person_resolution.promotion_candidates[0].candidate_key,
        proposal.items[1].person_resolution.promotion_candidates[0].candidate_key,
    ]
    plan = _service(db_session, tmp_path).prepare_plan(
        _input(source.id, revision, proposal.grounding_revision, items, [
            {"row_index": 0, "promotion_candidate_key": keys[0]},
            {"row_index": 1, "promotion_candidate_key": keys[1]},
        ])
    )
    before = _fact_counts(db_session)
    real = PersonPromotionService.approve

    def _second_conflicts(self, identity):
        if not hasattr(_second_conflicts, "calls"):
            _second_conflicts.calls = 0
        _second_conflicts.calls += 1
        if _second_conflicts.calls > 1:
            raise ConflictError("person identity is already bound")
        return real(self, identity)

    monkeypatch.setattr(PersonPromotionService, "approve", _second_conflicts)
    view = _approve(db_session, plan.id)
    assert view.status == "failed"
    after = _fact_counts(db_session)
    assert after["people"] == before["people"]
    assert after["identities"] == before["identities"]
    assert after["evidence"] == before["evidence"]
    assert after["assignments"] == before["assignments"]
    assert after["terms"] == before["terms"]


def test_repeated_approve_is_idempotent(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    plan = _prepare(db_session, tmp_path, [_row(_NAME, _ROLE)], [{"row_index": 0, "person_id": person.id}])
    first = _approve(db_session, plan.id)
    second = _approve(db_session, plan.id)
    assert first.status == "executed"
    assert second.status == "executed"
    assert second.result == first.result
    assert len(_assignments_for(db_session, person.id)) == 1


def test_result_counts_and_statuses_are_truthful(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    PersonRoleService(db_session, BOOTSTRAP_USER_ID).assign(person.id, _ROLE, "совет")
    items = [
        _row(_NAME, _ROLE_B),
        _row(_NAME, f"  {_ROLE_B.upper()} "),
        _row(_NAME, _ROLE, context="совет"),
    ]
    plan = _prepare(
        db_session,
        tmp_path,
        items,
        [
            {"row_index": 0, "person_id": person.id},
            {"row_index": 1, "person_id": person.id},
            {"row_index": 2, "person_id": person.id},
        ],
    )
    output = _approve(db_session, plan.id).result["actions"][0]["output"]
    assert output["selected_count"] == 3
    assert output["people_created"] == 0
    assert output["assignments_changed"] == 1
    assert output["assignments_no_op"] == 1
    assert output["duplicate_rows"] == 1
    assert [row["status"] for row in output["rows"]] == [
        "applied",
        "duplicate_selected_row",
        "already_active",
    ]
    assert output["changed"] is True
    effect = classify_tool_execution_effect("apply_role_import_batch", output)
    description = describe_execution_effect("apply_role_import_batch", output)
    assert effect == "changed"
    assert "people_created=0" in description
    assert "assignments_changed=1" in description
    assert str(person.id) not in description


def test_prepare_and_approve_create_no_ai_trace(db_session, tmp_path) -> None:
    person = PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(_NAME)
    before = _fact_counts(db_session)
    plan = _prepare(db_session, tmp_path, [_row(_NAME, _ROLE)], [{"row_index": 0, "person_id": person.id}])
    _approve(db_session, plan.id)
    after = _fact_counts(db_session)
    assert after["traces"] == before["traces"]
    assert after["trace_events"] == before["trace_events"]


def test_batch_holds_user_gate(monkeypatch) -> None:
    _during_held_batch(
        monkeypatch,
        lambda _source, _person, _rep, _original: _expect_lock(
            lock_user_serialization_row, BOOTSTRAP_USER_ID
        ),
    )


def test_concurrent_role_writer_is_blocked(monkeypatch) -> None:
    def _probe(_source, person_id, _rep, original) -> None:
        with Session(engine) as other:
            other.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError):
                original(PersonRoleService(other, BOOTSTRAP_USER_ID), person_id, "rel1dcчужая")

    _during_held_batch(monkeypatch, _probe)


def test_concurrent_identity_and_consolidation_writers_are_blocked(monkeypatch) -> None:
    def _probe(_source, person_id, _rep, _original) -> None:
        with Session(engine) as other:
            other.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError):
                PersonIdentityService(other, BOOTSTRAP_USER_ID).attach(
                    person_id, _email_identity()
                )
        with Session(engine) as other:
            other.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError):
                PersonConsolidationService(other, BOOTSTRAP_USER_ID).apply(person_id, uuid4())

    _during_held_batch(monkeypatch, _probe)


def test_source_object_row_is_locked(monkeypatch) -> None:
    def _probe(source_id, _person, _rep, _original) -> None:
        with Session(engine) as other:
            other.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError):
                other.execute(select(Object).where(Object.id == source_id).with_for_update())

    _during_held_batch(monkeypatch, _probe)


def test_body_fallback_blocks_first_client_representation_insert(monkeypatch) -> None:
    def _probe(source_id, _person, _rep, _original) -> None:
        _expect_representation_timeout(
            lambda other: ClientRepresentationPersistence(other, BOOTSTRAP_USER_ID).replace_for_object(
                source_id,
                "notes.txt",
                [{"kind": "full", "text": "inserted over body"}],
                False,
            )
        )

    _during_held_body_batch(monkeypatch, _probe)


def test_body_fallback_blocks_ingest_text_content(monkeypatch) -> None:
    def _probe(source_id, _person, _rep, _original) -> None:
        _expect_representation_timeout(
            lambda other: RepresentationService(other, BOOTSTRAP_USER_ID).ingest_text_content(
                source_id, "inserted over body"
            )
        )

    _during_held_body_batch(monkeypatch, _probe)


def test_body_fallback_blocks_representation_delete(monkeypatch) -> None:
    def _probe(source_id, _person, _rep, _original) -> None:
        _expect_representation_timeout(
            lambda other: ClientRepresentationPersistence(other, BOOTSTRAP_USER_ID).delete_all_for_object(
                source_id
            )
        )

    _during_held_body_batch(monkeypatch, _probe)


def test_representation_write_succeeds_after_batch_releases(monkeypatch) -> None:
    def _probe(source_id, _person, _rep, _original) -> None:
        _expect_representation_timeout(
            lambda other: RepresentationService(other, BOOTSTRAP_USER_ID).ingest_text_content(
                source_id, "still blocked"
            )
        )

    def _after(source_id) -> None:
        with Session(engine) as other:
            RepresentationService(other, BOOTSTRAP_USER_ID).ingest_text_content(source_id, "released text")
            other.commit()
            stored = other.scalar(
                select(Representation).where(
                    Representation.object_id == source_id,
                    Representation.kind == KIND_FULL,
                )
            )
            assert stored is not None
            assert stored.text == "released text"

    _during_held_body_batch(monkeypatch, _probe, _after)


def test_used_representation_rows_are_locked(monkeypatch) -> None:
    def _probe(_source, _person, rep_id, _original) -> None:
        with Session(engine) as other:
            other.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError):
                other.execute(select(Representation).where(Representation.id == rep_id).with_for_update())

    _during_held_batch(monkeypatch, _probe)


def _during_held_batch(monkeypatch, probe) -> None:
    source_id, person_id, rep_id = _commit_lock_fixture()
    holder = Session(engine)
    original = PersonRoleService.assign_outcome

    def _wrapped(self, *args, **kwargs):
        probe(source_id, person_id, rep_id, original)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PersonRoleService, "assign_outcome", _wrapped)
    try:
        source = _sources(holder, _unused_root()).load(source_id)
        proposal = _ground(holder, _unused_root(), source_id, source.source_revision, [_row("REL1DC Лок", _ROLE)])
        plan = _service(holder, _unused_root()).prepare_plan(
            _input(source_id, source.source_revision, proposal.grounding_revision, [_row("REL1DC Лок", _ROLE)], [
                {"row_index": 0, "person_id": person_id}
            ])
        )
        view = ActionPlanService(holder, BOOTSTRAP_USER_ID).approve(plan.id)
        assert view.status == "executed"
    finally:
        holder.rollback()
        holder.close()
        _cleanup_lock_fixture(source_id, person_id)


def _during_held_body_batch(monkeypatch, probe, after_release=None) -> None:
    source_id, person_id = _commit_body_fixture()
    holder = Session(engine)
    original = PersonRoleService.assign_outcome

    def _wrapped(self, *args, **kwargs):
        probe(source_id, person_id, None, original)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PersonRoleService, "assign_outcome", _wrapped)
    try:
        source = _sources(holder, _unused_root()).load(source_id)
        assert source.source_kind == "text"
        proposal = _ground(
            holder, _unused_root(), source_id, source.source_revision, [_row("REL1DC Тело", _ROLE)]
        )
        plan = _service(holder, _unused_root()).prepare_plan(
            _input(
                source_id,
                source.source_revision,
                proposal.grounding_revision,
                [_row("REL1DC Тело", _ROLE)],
                [{"row_index": 0, "person_id": person_id}],
            )
        )
        view = ActionPlanService(holder, BOOTSTRAP_USER_ID).approve(plan.id)
        assert view.status == "executed"
    finally:
        holder.rollback()
        holder.close()
        try:
            if after_release is not None:
                after_release(source_id)
        finally:
            _cleanup_lock_fixture(source_id, person_id)


def _commit_body_fixture():
    with Session(engine) as session:
        person = PersonIdentityService(session, BOOTSTRAP_USER_ID).create_person("REL1DC Тело")
        source = Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="document",
            title="body notes",
            body="body fallback role import source",
            origin="user",
            state="confirmed",
            metadata_={},
        )
        session.add(source)
        session.commit()
        return source.id, person.id


def _expect_representation_timeout(call) -> None:
    with Session(engine) as other:
        other.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(OperationalError):
            call(other)


def _commit_lock_fixture():
    with Session(engine) as session:
        person = PersonIdentityService(session, BOOTSTRAP_USER_ID).create_person("REL1DC Лок")
        source = Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="document",
            title="locked notes",
            body=None,
            origin="user",
            state="confirmed",
            metadata_={},
        )
        session.add(source)
        session.flush()
        representation = Representation(
            object_id=source.id,
            kind=KIND_FULL,
            text="locked role import source",
            metadata_={},
        )
        session.add(representation)
        session.commit()
        return source.id, person.id, representation.id


def _cleanup_lock_fixture(source_id, person_id) -> None:
    with Session(engine) as session:
        session.query(PersonRoleAssignment).filter(PersonRoleAssignment.person_object_id == person_id).delete()
        session.query(Representation).filter(Representation.object_id == source_id).delete()
        session.query(Object).filter(Object.id.in_([source_id, person_id])).delete(synchronize_session=False)
        session.commit()


def _expect_lock(fn, *args) -> None:
    with Session(engine) as other:
        other.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(OperationalError):
            fn(other, *args)


def _email_identity():
    from app.domain.person_identity import normalize_email

    return normalize_email("rel1dc-lock@example.com")


def _unused_root():
    from pathlib import Path

    return Path("/tmp")


def _prepare(db_session, tmp_path, items, selections):
    source, revision, proposal = _proposal(db_session, tmp_path, items)
    return _service(db_session, tmp_path).prepare_plan(
        _input(source.id, revision, proposal.grounding_revision, items, selections)
    )


def _proposal(db_session, tmp_path, items):
    source = _text_object(db_session, "role import batch source")
    revision = _sources(db_session, tmp_path).load(source.id).source_revision
    proposal = _ground(db_session, tmp_path, source.id, revision, items)
    return source, revision, proposal


def _approve(db_session, plan_id):
    return ActionPlanService(db_session, BOOTSTRAP_USER_ID).approve(plan_id)


def _service(db_session, tmp_path) -> PersonRoleImportBatchService:
    return PersonRoleImportBatchService(db_session, BOOTSTRAP_USER_ID, tmp_path / "uploads")


def _sources(db_session, tmp_path) -> PersonRoleImportSourceService:
    return PersonRoleImportSourceService(db_session, BOOTSTRAP_USER_ID, tmp_path / "uploads")


def _input(source_id, revision, grounding_revision, items, selections) -> ApplyRoleImportBatchInput:
    return ApplyRoleImportBatchInput(
        source_object_id=source_id,
        source_revision=revision,
        grounding_revision=grounding_revision,
        items_truncated=False,
        items=[RoleImportGroundInputItem.model_validate(item) for item in items],
        selections=[RoleImportBatchSelection.model_validate(item) for item in selections],
    )


def _body(source_id, revision, grounding_revision, items, selections) -> dict:
    return {
        "source_object_id": str(source_id),
        "source_revision": revision,
        "grounding_revision": grounding_revision,
        "items_truncated": False,
        "items": items,
        "selections": selections,
    }


def _assignments_for(db_session, person_id) -> list[PersonRoleAssignment]:
    return list(
        db_session.scalars(
            select(PersonRoleAssignment).where(PersonRoleAssignment.person_object_id == person_id)
        )
    )


def _term_count(db_session, role: str) -> int:
    from app.domain.person_role_text import role_term_identity

    _display, key = role_term_identity(role)
    return db_session.scalar(
        select(func.count()).select_from(PersonRoleTerm).where(
            PersonRoleTerm.user_id == BOOTSTRAP_USER_ID,
            PersonRoleTerm.normalized_key == key,
        )
    )


def _fact_counts(db_session) -> dict[str, int]:
    people = db_session.scalar(select(func.count()).select_from(Object).where(Object.kind == "person"))
    return {
        "people": people,
        "assignments": db_session.scalar(select(func.count()).select_from(PersonRoleAssignment)),
        "terms": db_session.scalar(select(func.count()).select_from(PersonRoleTerm)),
        "identities": db_session.scalar(select(func.count()).select_from(PersonIdentity)),
        "evidence": db_session.scalar(select(func.count()).select_from(PersonIdentityEvidence)),
        "plans": db_session.scalar(select(func.count()).select_from(PendingActionPlan)),
        "traces": db_session.scalar(select(func.count()).select_from(AITrace)),
        "trace_events": db_session.scalar(select(func.count()).select_from(AITraceEvent)),
    }


def test_direct_approved_mode_is_required(db_session) -> None:
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, None, write_mode=DomainWriteMode.AGENT_PROPOSED)
    with pytest.raises(Exception, match="tool execution requires approval"):
        tools.apply_role_import_batch(None)
