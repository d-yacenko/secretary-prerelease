"""REL1C-A read-only Assistant Person role tools."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import func, select

from app.assistant.constants import MAX_ASSISTANT_TOOL_OUTPUT_CHARS
from app.assistant.tool_output import serialize_tool_output_for_assistant
from app.assistant.tool_runner import BoundAssistantToolRunner, PerTurnToolBudget
from app.db.models import Edge, Object, PersonIdentity, PersonRoleAssignment, PersonRoleTerm
from app.domain.object_visibility import tombstone_object
from app.domain.person_identity import normalize_email
from app.llm.openai_assistant_provider import SYSTEM_INSTRUCTIONS
from app.services.person_identity_service import PersonIdentityService
from app.services.person_role_service import PersonRoleService
from app.services.provenance import REJECTED_STATE
from app.tools.policy import ToolPermission
from app.tools.registry import TOOL_REGISTRY
from tests.test_person_assistant import _patch_session, _user


def test_role_read_tools_are_assistant_reads_without_prepare() -> None:
    for name in ("get_person_roles", "find_people_by_role"):
        spec = TOOL_REGISTRY[name]
        assert spec.permission == ToolPermission.READ
        assert spec.assistant_exposed is True
        assert spec.mcp_exposed is False
        assert spec.prepare_method is None
    assert "assign_person_role" not in TOOL_REGISTRY
    assert "retract_person_role" not in TOOL_REGISTRY


def test_get_person_roles_requires_committed_resolution(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    first = people.create_person("Ольга")
    second = people.create_person("Ольга")
    people.attach(first.id, normalize_email("olga@example.com"))
    people.attach(second.id, normalize_email("other@example.com"))
    PersonRoleService(db_session, user_id).assign(first.id, "директор")
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    blocked = runner("get_person_roles", {"person_id": str(first.id)})
    assert blocked.success is False
    ambiguous = runner("resolve_person", {"query": "Ольга"})
    assert ambiguous.output["state"] == "ambiguous"
    budget.commit_model_visible_outputs()
    still_blocked = runner("get_person_roles", {"person_id": str(first.id)})
    assert still_blocked.success is False
    assert first.id not in budget._resolved_person_ids
    resolved = runner("resolve_person", {"query": "olga@example.com"})
    assert resolved.output["state"] == "resolved"
    budget.commit_model_visible_outputs()
    allowed = runner("get_person_roles", {"person_id": str(first.id)})
    assert allowed.success is True
    assert allowed.output["person_id"] == str(first.id)


def test_active_roles_keep_context_and_deterministic_order(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    person = _person_with_email(db_session, user_id, "Ada", "ada@example.com")
    roles = PersonRoleService(db_session, user_id)
    beta = roles.assign(person.id, "beta")
    alpha_z = roles.assign(person.id, "alpha", "z")
    alpha_m = roles.assign(person.id, "alpha", "m")
    roles.retract(person.id, beta.id)
    roles.assign(person.id, "gamma")
    runner = _resolved_runner(db_session, monkeypatch, user_id, "ada@example.com")
    result = runner("get_person_roles", {"person_id": str(person.id)})
    assert result.success is True
    listed = result.output["roles"]
    assert [(item["role"], item["context"]) for item in listed] == [
        ("alpha", "m"),
        ("alpha", "z"),
        ("gamma", None),
    ]
    assert {item["assignment_id"] for item in listed} == {
        str(alpha_m.id),
        str(alpha_z.id),
        listed[2]["assignment_id"],
    }
    assert all(item["role_term_id"] for item in listed)
    assert str(beta.id) not in {item["assignment_id"] for item in listed}
    dumped = json.dumps(result.model_visible_payload)
    assert "normalized_key" not in dumped
    assert "context_key" not in dumped
    assert "provenance" not in dumped
    assert "source_object_id" not in dumped
    assert "canonical_value" not in dumped


def test_hidden_and_foreign_people_do_not_leak(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    other = _user(db_session)
    visible = _person_with_email(db_session, user_id, "Visible", "visible@example.com")
    rejected = PersonIdentityService(db_session, user_id).create_person("Rejected")
    deleted = PersonIdentityService(db_session, user_id).create_person("Deleted")
    roles = PersonRoleService(db_session, user_id)
    roles.assign(visible.id, "директор")
    roles.assign(rejected.id, "директор")
    roles.assign(deleted.id, "директор")
    rejected.state = REJECTED_STATE
    tombstone_object(deleted)
    db_session.flush()
    foreign = PersonIdentityService(db_session, other).create_person("Foreign")
    PersonRoleService(db_session, other).assign(foreign.id, "директор")
    runner = _resolved_runner(db_session, monkeypatch, user_id, "visible@example.com")
    hidden = runner("get_person_roles", {"person_id": str(rejected.id)})
    assert hidden.success is False
    gone = runner("get_person_roles", {"person_id": str(deleted.id)})
    assert gone.success is False
    found = runner("find_people_by_role", {"role": "директор"})
    assert [item["person_id"] for item in found.output["people"]] == [str(visible.id)]


def test_exact_lexical_variants_resolve_one_term(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Ada")
    PersonRoleService(db_session, user_id).assign(person.id, "Директор")
    runner = BoundAssistantToolRunner(PerTurnToolBudget(), user_id)
    folded = runner("find_people_by_role", {"role": " директор "})
    shouted = runner("find_people_by_role", {"role": "ДИРЕКТОР"})
    assert folded.output["exact_match_term_id"] == shouted.output["exact_match_term_id"]
    assert folded.output["exact_role"] == "Директор"
    assert [item["person_id"] for item in folded.output["people"]] == [str(person.id)]


def test_near_role_is_suggestion_not_equality(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Ada")
    PersonRoleService(db_session, user_id).assign(person.id, "генеральный директор")
    runner = BoundAssistantToolRunner(PerTurnToolBudget(), user_id)
    found = runner("find_people_by_role", {"role": "директор"})
    assert found.output["exact_match_term_id"] is None
    assert found.output["people"] == []
    assert [item["display_text"] for item in found.output["suggestions"]] == [
        "генеральный директор"
    ]


def test_one_person_keeps_distinct_contexts(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Ada")
    roles = PersonRoleService(db_session, user_id)
    second = roles.assign(person.id, "директор", "Учебный центр")
    first = roles.assign(person.id, "директор", "Arenadata")
    runner = BoundAssistantToolRunner(PerTurnToolBudget(), user_id)
    found = runner("find_people_by_role", {"role": "директор"})
    assert len(found.output["people"]) == 1
    assert [item["context"] for item in found.output["people"][0]["assignments"]] == [
        "Arenadata",
        "Учебный центр",
    ]
    assert {item["assignment_id"] for item in found.output["people"][0]["assignments"]} == {
        str(first.id),
        str(second.id),
    }


def test_unused_term_is_exact_with_no_people(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Ada")
    roles = PersonRoleService(db_session, user_id)
    assignment = roles.assign(person.id, "наблюдатель")
    roles.retract(person.id, assignment.id)
    runner = BoundAssistantToolRunner(PerTurnToolBudget(), user_id)
    found = runner("find_people_by_role", {"role": "наблюдатель"})
    assert found.output["exact_role"] == "наблюдатель"
    assert found.output["people"] == []
    assert found.output["people_truncated"] is False


def test_people_limit_suggestions_and_output_cap(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    roles = PersonRoleService(db_session, user_id)
    for index in range(13):
        person = PersonIdentityService(db_session, user_id).create_person(f"Person {index:02d}")
        roles.assign(person.id, "студент")
    for index in range(9):
        holder = PersonIdentityService(db_session, user_id).create_person(f"Hint {index}")
        roles.assign(holder.id, f"студент {index}")
    runner = BoundAssistantToolRunner(PerTurnToolBudget(), user_id)
    found = runner("find_people_by_role", {"role": "студент", "limit": 12})
    assert len(found.output["people"]) == 12
    assert found.output["people_truncated"] is True
    assert [item["title"] for item in found.output["people"]] == [
        f"Person {index:02d}" for index in range(12)
    ]
    assert len(found.output["suggestions"]) <= 8
    rendered = serialize_tool_output_for_assistant("find_people_by_role", found.output)
    assert len(rendered.model_output_json) <= MAX_ASSISTANT_TOOL_OUTPUT_CHARS
    huge = {
        "query": "студент",
        "exact_match_term_id": None,
        "exact_role": "студент",
        "people_truncated": False,
        "suggestions": [],
        "people": [
            {
                "person_id": str(uuid.uuid4()),
                "title": "P" * 120,
                "assignments": [
                    {"assignment_id": str(uuid.uuid4()), "context": "C" * 200}
                    for _ in range(16)
                ],
            }
            for _ in range(12)
        ],
    }
    bounded = serialize_tool_output_for_assistant("find_people_by_role", huge)
    assert len(bounded.model_output_json) <= MAX_ASSISTANT_TOOL_OUTPUT_CHARS
    assert bounded.model_visible_payload["people_truncated"] is True


def test_role_search_does_not_resolve_person(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    person = _person_with_email(db_session, user_id, "Ada", "ada@example.com")
    PersonRoleService(db_session, user_id).assign(person.id, "директор")
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    found = runner("find_people_by_role", {"role": "директор"})
    assert found.success is True
    budget.commit_model_visible_outputs()
    assert person.id in budget.seen_object_ids
    assert person.id not in budget._resolved_person_ids
    blocked = runner("find_person_communications", {"person_id": str(person.id)})
    assert blocked.success is False


def test_role_reads_do_not_write(db_session, monkeypatch) -> None:
    _patch_session(db_session, monkeypatch)
    user_id = _user(db_session)
    person = _person_with_email(db_session, user_id, "Ada", "ada@example.com")
    PersonRoleService(db_session, user_id).assign(person.id, "директор", "курс")
    before = _counts(db_session, user_id)
    runner = _resolved_runner(db_session, monkeypatch, user_id, "ada@example.com")
    assert runner("get_person_roles", {"person_id": str(person.id)}).success is True
    assert runner("find_people_by_role", {"role": "директор"}).success is True
    assert _counts(db_session, user_id) == before


def test_role_instructions_are_descriptive_and_block_mutation() -> None:
    text = SYSTEM_INSTRUCTIONS
    assert "call resolve_person first" in text
    assert "state=resolved, call get_person_roles" in text
    assert "exact lexical RoleTerm match is authoritative" in text
    assert "do not silently substitute" in text
    assert "do not approximate with assign_label" in text
    assert "Person role terms" in text
    assert "role contexts" in text
    assert "not a Task actor role" in text
    assert "+50" not in text
    assert "role_weight" not in text


def _person_with_email(db_session, user_id, title: str, email: str):
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person(title)
    people.attach(person.id, normalize_email(email))
    return person


def _resolved_runner(db_session, monkeypatch, user_id, query: str) -> BoundAssistantToolRunner:
    _patch_session(db_session, monkeypatch)
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, user_id)
    resolved = runner("resolve_person", {"query": query})
    assert resolved.output["state"] == "resolved"
    budget.commit_model_visible_outputs()
    return runner


def _counts(db_session, user_id) -> dict[str, int]:
    def count(model) -> int:
        return int(
            db_session.scalar(
                select(func.count()).select_from(model).where(model.user_id == user_id)
            )
            or 0
        )

    return {
        "terms": count(PersonRoleTerm),
        "assignments": count(PersonRoleAssignment),
        "identities": count(PersonIdentity),
        "edges": count(Edge),
        "objects": count(Object),
    }
