"""AH2-PER1: Russian given-name variants suggest a Person without resolving it."""

import uuid

from sqlalchemy import func, select

from app.api.schemas import ObjectCreate
from app.assistant.tool_runner import PerTurnToolBudget
from app.db.models import Object, PersonIdentity, PersonIdentityEvidence, User
from app.llm.openai_assistant_provider import SYSTEM_INSTRUCTIONS
from app.services.graph_service import GraphService
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import CONFIRMED_STATE, USER_ORIGIN
from app.tools.assistant_contracts import ASSISTANT_FUNCTION_SCHEMAS
from app.tools.results import ToolExecutionStatus


def _user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="per1"))
    db_session.flush()
    return user_id


def _person(db_session, user_id: uuid.UUID, title: str):
    return PersonIdentityService(db_session, user_id).create_person(title)


def _counts(db_session, user_id: uuid.UUID) -> tuple[int, int, int]:
    people = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.user_id == user_id, Object.kind == "person")
    )
    identities = db_session.scalar(
        select(func.count()).select_from(PersonIdentity).where(PersonIdentity.user_id == user_id)
    )
    evidence = db_session.scalar(
        select(func.count())
        .select_from(PersonIdentityEvidence)
        .where(PersonIdentityEvidence.user_id == user_id)
    )
    return people, identities, evidence


def _bind(db_session, monkeypatch) -> None:
    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(db_session, name)

    import app.assistant.session as assistant_session_module

    monkeypatch.setattr(assistant_session_module, "SessionLocal", lambda: _TestSession())


def test_olga_diminutive_is_suggestion_only(db_session) -> None:
    user_id = _user(db_session)
    person = _person(db_session, user_id, "Ольга Володько")
    before = _counts(db_session, user_id)
    result = PersonAssistantService(db_session, user_id).resolve("Оля Володько")
    assert result.state == "ambiguous"
    assert result.person_id is None
    assert [item.person_id for item in result.candidates] == [person.id]
    assert "name_variant" in result.candidates[0].reasons
    assert _counts(db_session, user_id) == before


def test_olga_inflected_diminutive_is_suggestion_only(db_session) -> None:
    user_id = _user(db_session)
    person = _person(db_session, user_id, "Ольга Володько")
    result = PersonAssistantService(db_session, user_id).resolve("Оли Володько")
    assert result.state == "ambiguous"
    assert result.person_id is None
    assert [item.person_id for item in result.candidates] == [person.id]
    assert "name_variant" in result.candidates[0].reasons


def test_olga_inflected_canonical_form_is_suggestion_only(db_session) -> None:
    user_id = _user(db_session)
    person = _person(db_session, user_id, "Ольга Володько")
    result = PersonAssistantService(db_session, user_id).resolve("Ольги Володько")
    assert result.state == "ambiguous"
    assert result.person_id is None
    assert [item.person_id for item in result.candidates] == [person.id]
    assert "name_variant" in result.candidates[0].reasons


def test_different_surname_does_not_suggest_olga(db_session) -> None:
    user_id = _user(db_session)
    _person(db_session, user_id, "Ольга Володько")
    result = PersonAssistantService(db_session, user_id).resolve("Оли Иванова")
    assert result.state == "none"
    assert result.candidates == []


def test_different_given_name_does_not_suggest_olga(db_session) -> None:
    user_id = _user(db_session)
    _person(db_session, user_id, "Ольга Володько")
    result = PersonAssistantService(db_session, user_id).resolve("Олег Володько")
    assert result.state == "none"
    assert result.candidates == []


def test_single_token_does_not_use_the_variant_matcher(db_session) -> None:
    user_id = _user(db_session)
    _person(db_session, user_id, "Ольга Володько")
    result = PersonAssistantService(db_session, user_id).resolve("Оли")
    assert result.state == "none"
    assert result.candidates == []


def test_exact_title_wins_over_a_variant_candidate(db_session) -> None:
    user_id = _user(db_session)
    exact = _person(db_session, user_id, "Оли Володько")
    _person(db_session, user_id, "Ольга Володько")
    result = PersonAssistantService(db_session, user_id).resolve("Оли Володько")
    assert result.state == "resolved"
    assert result.person_id == exact.id
    assert result.candidates[0].reasons == ("alias",)


def test_two_canonical_variant_candidates_stay_ambiguous(db_session) -> None:
    user_id = _user(db_session)
    first = _person(db_session, user_id, "Ольга Володько")
    second = _person(db_session, user_id, "Ольга Володько")
    result = PersonAssistantService(db_session, user_id).resolve("Оли Володько")
    assert result.state == "ambiguous"
    assert result.person_id is None
    assert {item.person_id for item in result.candidates} == {first.id, second.id}
    assert all("name_variant" in item.reasons for item in result.candidates)


def test_variant_candidate_cannot_stage_an_actor_role(db_session, monkeypatch) -> None:
    user_id = _user(db_session)
    person = _person(db_session, user_id, "Ольга Володько")
    task = GraphService(db_session, user_id).create_object(
        ObjectCreate(kind="task", title="Черновик", origin=USER_ORIGIN, state=CONFIRMED_STATE, status="open")
    )
    _bind(db_session, monkeypatch)
    budget = PerTurnToolBudget()
    budget.seed_seen_object_ids([task.id])
    resolved = budget.run(user_id, "resolve_person", {"query": "Оли Володько"})
    assert resolved.success is True
    assert resolved.output["state"] == "ambiguous"
    budget.commit_model_visible_outputs()
    blocked = budget.run(
        user_id,
        "update_task",
        {"object_id": str(task.id), "waiting_on_person_ids": [str(person.id)]},
    )
    assert blocked.success is False
    assert "not resolved" in (blocked.error or "")
    assert budget.staged_actions == []


def test_exact_resolution_can_stage_waiting_on(db_session, monkeypatch) -> None:
    user_id = _user(db_session)
    person = _person(db_session, user_id, "Ольга Володько")
    task = GraphService(db_session, user_id).create_object(
        ObjectCreate(kind="task", title="Черновик", origin=USER_ORIGIN, state=CONFIRMED_STATE, status="open")
    )
    _bind(db_session, monkeypatch)
    budget = PerTurnToolBudget()
    budget.seed_seen_object_ids([task.id])
    resolved = budget.run(user_id, "resolve_person", {"query": "Ольга Володько"})
    assert resolved.output["state"] == "resolved"
    assert resolved.output["person_id"] == str(person.id)
    budget.commit_model_visible_outputs()
    staged = budget.run(
        user_id,
        "update_task",
        {"object_id": str(task.id), "waiting_on_person_ids": [str(person.id)]},
    )
    assert staged.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert budget.staged_actions[0]["arguments"]["waiting_on_person_ids"] == [str(person.id)]


def test_ambiguous_candidate_is_rejected_for_every_actor_field(db_session, monkeypatch) -> None:
    user_id = _user(db_session)
    person = _person(db_session, user_id, "Ольга Володько")
    task = GraphService(db_session, user_id).create_object(
        ObjectCreate(kind="task", title="Черновик", origin=USER_ORIGIN, state=CONFIRMED_STATE, status="open")
    )
    _bind(db_session, monkeypatch)
    budget = PerTurnToolBudget()
    budget.seed_seen_object_ids([task.id])
    budget.run(user_id, "resolve_person", {"query": "Оли Володько"})
    budget.commit_model_visible_outputs()
    fields = {
        "requested_by_person_id": str(person.id),
        "delegated_to_person_ids": [str(person.id)],
        "waiting_on_person_ids": [str(person.id)],
        "involved_person_ids": [str(person.id)],
    }
    for name, value in fields.items():
        blocked = budget.run(user_id, "update_task", {"object_id": str(task.id), name: value})
        assert blocked.success is False
        assert "not resolved" in (blocked.error or "")
    assert budget.staged_actions == []


def test_task_dependency_still_uses_the_seen_object_allowlist(db_session, monkeypatch) -> None:
    user_id = _user(db_session)
    graph = GraphService(db_session, user_id)
    task = graph.create_object(
        ObjectCreate(kind="task", title="Черновик", origin=USER_ORIGIN, state=CONFIRMED_STATE, status="open")
    )
    dependency = graph.create_object(
        ObjectCreate(kind="task", title="Основа", origin=USER_ORIGIN, state=CONFIRMED_STATE, status="open")
    )
    _bind(db_session, monkeypatch)
    budget = PerTurnToolBudget()
    hidden = budget.run(
        user_id,
        "update_task",
        {"object_id": str(task.id), "depends_on_task_ids": [str(dependency.id)]},
    )
    assert hidden.success is False
    assert "not exposed" in (hidden.error or "")
    budget.seed_seen_object_ids([task.id, dependency.id])
    staged = budget.run(
        user_id,
        "update_task",
        {"object_id": str(task.id), "depends_on_task_ids": [str(dependency.id)]},
    )
    assert staged.status == ToolExecutionStatus.APPROVAL_REQUIRED


def test_resolve_person_contract_requires_confirmation_before_mutation() -> None:
    text = ASSISTANT_FUNCTION_SCHEMAS["resolve_person"]["description"]
    assert "name_variant" in text
    assert "suggestion-only" in text
    assert "Do not mutate from that candidate." in text
    prompt = SYSTEM_INSTRUCTIONS
    assert "reason is name_variant" in prompt
    assert "call resolve_person again" in prompt
    assert "state=resolved" in prompt
    assert "Do not store a nickname alias" in prompt
