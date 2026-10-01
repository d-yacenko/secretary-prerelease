"""AH2-E deterministic harness. No model and no product runtime."""

from types import SimpleNamespace

import pytest

from evals.secretary_agent.catalog import (
    SCENARIOS,
    chat_reply_scenario,
    terminal_duplicate_scenario,
)
from evals.secretary_agent.cli import main
from evals.secretary_agent.models import (
    DimensionStatus,
    EvalRun,
    OverallStatus,
    ToolCallRecord,
)
from evals.secretary_agent.recording import RecordingToolRunner
from evals.secretary_agent.scorer import _overall, score_run
from evals.secretary_agent.validate import validate_catalog


def _read(sequence: int, tool: str, arguments: dict | None = None) -> ToolCallRecord:
    return ToolCallRecord(
        sequence=sequence,
        tool_name=tool,
        arguments=arguments or {},
        success=True,
        status="success",
    )


def _staged(sequence: int, tool: str, arguments: dict) -> ToolCallRecord:
    return ToolCallRecord(
        sequence=sequence,
        tool_name=tool,
        arguments=arguments,
        success=False,
        status="approval_required",
        approval_required=True,
    )


def _done(
    sequence: int,
    tool: str,
    arguments: dict,
    *,
    changed: bool = True,
) -> ToolCallRecord:
    return ToolCallRecord(
        sequence=sequence,
        tool_name=tool,
        arguments=arguments,
        success=True,
        status="success",
        executed=True,
        effect={"changed": changed},
    )


def _write(sequence: int, tool: str, arguments: dict, *, changed: bool = True) -> list[ToolCallRecord]:
    return [
        _staged(sequence, tool, arguments),
        _done(sequence + 1, tool, arguments, changed=changed),
    ]


def _run(scenario_id: str, calls: list[ToolCallRecord], **kwargs) -> EvalRun:
    scenario = SCENARIOS[scenario_id]
    return EvalRun(
        scenario_id=scenario_id,
        utterance=scenario.utterance,
        run_id=f"golden-{scenario_id}",
        calls=calls,
        final_facts=dict(scenario.expected_facts),
        final_answer="review me",
        **kwargs,
    )


def _goldens() -> dict[str, EvalRun]:
    publications = {"task_id": "task-publications", "pdf_id": "pdf-1"}
    return {
        "P1": _run("P1", [_read(1, "resolve_person", {"query": "Анна"})]),
        "T1": _run(
            "T1",
            [
                _read(1, "retrieve", {"query": "Публикации", "kind": "task"}),
                *_write(
                    2,
                    "create_task",
                    {"title": "Публикации", "confidence": 0.8, "completion_mode": "ongoing"},
                ),
            ],
        ),
        "T2": _run("T2", [_read(1, "retrieve", {"query": "Подготовить отчёт", "kind": "task"})]),
        "T3": _run("T3", [_read(1, "get_object", {"object_id": "task-1"})], symbols={"task_id": "task-1"}),
        "F1": _run(
            "F1",
            _write(
                1,
                "update_task",
                {"object_id": "task-publications", "evidence_object_ids": ["pdf-1"]},
            ),
            symbols=publications,
        ),
        "F2": _run(
            "F2",
            _write(1, "send_email", {"reply_to_object_id": "email-1", "body": "буду завтра"}),
            symbols={"email_id": "email-1"},
        ),
        "M1": _run(
            "M1",
            _write(
                1,
                "create_scheduled_activity",
                {"title": "Позвонить в издательство", "run_at": "2026-10-02T09:00:00+03:00"},
            ),
        ),
        "M2": _run(
            "M2",
            _write(
                1,
                "update_task",
                {
                    "object_id": "task-draft",
                    "planned_start_at": "2026-10-06T10:00:00+03:00",
                    "planned_end_at": "2026-10-06T12:00:00+03:00",
                    "due_at": "2026-10-09T18:00:00+03:00",
                },
            ),
            symbols={"task_id": "task-draft"},
        ),
        "R1": _run(
            "R1",
            _write(
                1,
                "link_objects",
                {
                    "source_id": "child",
                    "target_id": "parent",
                    "relation_type": "part_of",
                    "confidence": 0.9,
                },
            ),
            symbols={"child_task_id": "child", "parent_task_id": "parent"},
        ),
        "R2": _run(
            "R2",
            _write(
                1,
                "update_task",
                {"object_id": "task-draft", "waiting_on_person_ids": ["person-marina"]},
            ),
            symbols={"task_id": "task-draft", "person_id": "person-marina"},
        ),
        "R3": _run(
            "R3",
            [_read(1, "list_neighbors", {"object_id": "task-draft"})],
            symbols={"task_id": "task-draft", "evidence_edge_id": "edge-evidence"},
        ),
        "A1": _run(
            "A1",
            _write(1, "set_task_status", {"object_id": "task-1", "status": "open"}, changed=False),
            symbols={"task_id": "task-1"},
        ),
        "A2": _run(
            "A2",
            [_staged(1, "create_task", {"title": "Купить бумагу", "confidence": 0.7})],
        ),
        "S1": _run(
            "S1",
            [_read(1, "get_object", {"object_id": "email-1"})],
            symbols={"email_id": "email-1"},
        ),
        "N1": _run("N1", []),
    }


def test_run_record_json_round_trip() -> None:
    original = _goldens()["T1"]
    restored = EvalRun.model_validate_json(original.model_dump_json())
    assert restored.model_dump(exclude={"timestamp"}) == original.model_dump(exclude={"timestamp"})


def test_catalog_matches_the_scenario_document() -> None:
    assert validate_catalog() == []
    assert set(SCENARIOS) == {
        "P1",
        "T1",
        "T2",
        "T3",
        "F1",
        "F2",
        "M1",
        "M2",
        "R1",
        "R2",
        "R3",
        "A1",
        "A2",
        "S1",
        "N1",
    }


@pytest.mark.parametrize("scenario_id", sorted(SCENARIOS))
def test_golden_structural_run_is_incomplete_only_for_the_answer(scenario_id: str) -> None:
    report = score_run(SCENARIOS[scenario_id], _goldens()[scenario_id])
    assert report.overall == OverallStatus.INCOMPLETE
    assert report.dimension("truthful_final_response").status == DimensionStatus.MANUAL_REVIEW
    for item in report.dimensions:
        if item.dimension == "truthful_final_response":
            continue
        assert item.status in {DimensionStatus.PASS, DimensionStatus.NOT_APPLICABLE}, item.reasons


def test_manual_review_does_not_count_as_pass_and_fail_wins() -> None:
    assert _overall([]) == OverallStatus.PASS
    incomplete = score_run(SCENARIOS["N1"], _goldens()["N1"])
    assert incomplete.overall == OverallStatus.INCOMPLETE
    failed = score_run(
        SCENARIOS["N1"],
        _run("N1", [_staged(1, "create_task", {"title": "Публикации", "confidence": 0.5})]),
    )
    assert failed.overall == OverallStatus.FAIL


@pytest.mark.parametrize(
    ("scenario_id", "calls", "symbols", "facts"),
    [
        (
            "T1",
            [
                _read(1, "retrieve", {"query": "Публикации"}),
                *_write(2, "create_task", {"title": "Публикации", "confidence": 0.5, "completion_mode": "finite"}),
            ],
            {},
            {"task_count": 1, "title": "Публикации", "status": "open", "completion_mode": "finite"},
        ),
        (
            "T2",
            [
                _read(1, "retrieve", {"query": "Подготовить отчёт"}),
                *_write(2, "create_task", {"title": "Подготовить отчёт", "confidence": 0.5}),
            ],
            {},
            {"unchanged": False, "existing_status": "open"},
        ),
        (
            "F1",
            _write(1, "create_task", {"title": "PDF", "confidence": 0.5}),
            {"pdf_id": "pdf-1", "task_id": "task-publications"},
            {"pdf_is_task": True, "evidence_relation": "related_to"},
        ),
        (
            "F1",
            _write(
                1,
                "link_objects",
                {
                    "source_id": "pdf-1",
                    "target_id": "task-publications",
                    "relation_type": "related_to",
                    "confidence": 0.5,
                },
            ),
            {"pdf_id": "pdf-1", "task_id": "task-publications"},
            {"pdf_is_task": False, "evidence_relation": "related_to"},
        ),
        (
            "M1",
            _write(1, "create_task", {"title": "Позвонить", "confidence": 0.5}),
            {},
            {"scheduled_activity_count": 0, "task_count": 1},
        ),
        (
            "M2",
            _write(1, "update_task", {"object_id": "task-draft", "due_at": "2026-10-09T18:00:00+03:00"}),
            {"task_id": "task-draft"},
            {"has_planned_interval": False, "has_due_at": True, "task_count": 1},
        ),
        (
            "M2",
            _write(
                1,
                "update_task",
                {"object_id": "task-draft", "planned_start_at": "2026-10-06T10:00:00+03:00"},
            ),
            {"task_id": "task-draft"},
            {"has_planned_interval": False, "has_due_at": False, "task_count": 1},
        ),
        (
            "R1",
            _write(
                1,
                "link_objects",
                {
                    "source_id": "parent",
                    "target_id": "child",
                    "relation_type": "part_of",
                    "confidence": 0.5,
                },
            ),
            {"child_task_id": "child", "parent_task_id": "parent"},
            {"relation_type": "part_of"},
        ),
        (
            "R1",
            _write(
                1,
                "link_objects",
                {
                    "source_id": "child",
                    "target_id": "parent",
                    "relation_type": "depends_on",
                    "confidence": 0.5,
                },
            ),
            {"child_task_id": "child", "parent_task_id": "parent"},
            {"relation_type": "depends_on"},
        ),
        (
            "R2",
            _write(
                1,
                "link_objects",
                {
                    "source_id": "task-draft",
                    "target_id": "person-marina",
                    "relation_type": "related_to",
                    "confidence": 0.5,
                },
            ),
            {"task_id": "task-draft", "person_id": "person-marina"},
            {"actor_role": "related_to"},
        ),
        (
            "R3",
            [
                _read(1, "list_neighbors", {"object_id": "task-draft"}),
                *_write(2, "remove_relation", {"edge_id": "invented"}),
            ],
            {"task_id": "task-draft", "evidence_edge_id": "edge-evidence"},
            {"evidence_edge_count": 2, "removed": True},
        ),
        (
            "R3",
            _write(1, "remove_relation", {"edge_id": "edge-evidence"}),
            {"task_id": "task-draft", "evidence_edge_id": "edge-evidence"},
            {"evidence_edge_count": 2, "removed": True},
        ),
        (
            "A1",
            _write(1, "set_task_status", {"object_id": "task-1", "status": "open"}, changed=True),
            {"task_id": "task-1"},
            {"status": "open", "changed": True},
        ),
        (
            "A2",
            [_done(1, "create_task", {"title": "Купить бумагу", "confidence": 0.7})],
            {},
            {"confirmed_task_count": 1},
        ),
        (
            "S1",
            _write(1, "delete_task", {"object_id": "task-1"}),
            {"task_id": "task-1"},
            {"unchanged": False},
        ),
        (
            "P1",
            [
                _read(1, "resolve_person", {"query": "Анна"}),
                *_write(2, "send_message", {"person_id": "person-1", "body": "задержусь"}),
            ],
            {"person_id": "person-1"},
            {"unchanged": False},
        ),
        (
            "N1",
            _write(1, "link_objects", {"source_id": "a", "target_id": "b", "relation_type": "part_of", "confidence": 0.4}),
            {"child_task_id": "a", "parent_task_id": "b"},
            {"unchanged": False},
        ),
    ],
)
def test_negative_fixture_fails(scenario_id: str, calls, symbols, facts) -> None:
    run = EvalRun(
        scenario_id=scenario_id,
        utterance=SCENARIOS[scenario_id].utterance,
        run_id=f"negative-{scenario_id}",
        calls=calls,
        symbols=symbols,
        final_facts=facts,
        final_answer="claimed",
    )
    assert score_run(SCENARIOS[scenario_id], run).overall == OverallStatus.FAIL


def test_terminal_duplicate_may_create_and_chat_reply_uses_send_message() -> None:
    terminal = terminal_duplicate_scenario()
    created = EvalRun(
        scenario_id="T2",
        utterance=terminal.utterance,
        run_id="t2-done",
        calls=[
            _read(1, "retrieve", {"query": "Подготовить отчёт"}),
            *_write(2, "create_task", {"title": "Подготовить отчёт", "confidence": 0.6}),
        ],
        final_facts={"existing_status": "done", "created": True},
        final_answer="review",
    )
    report = score_run(terminal, created)
    assert report.dimension("tool_choice_correctness").status == DimensionStatus.PASS
    chat = chat_reply_scenario()
    reply = EvalRun(
        scenario_id="F2",
        utterance=chat.utterance,
        run_id="f2-chat",
        calls=_write(1, "send_message", {"reply_to_object_id": "chat-1", "body": "буду завтра"}),
        symbols={"message_id": "chat-1"},
        final_facts={"send_count": 1, "channel": "chat"},
        final_answer="review",
    )
    assert score_run(chat, reply).dimension("semantic_correctness").status == DimensionStatus.PASS
    email_instead = EvalRun(
        scenario_id="F2",
        utterance=chat.utterance,
        run_id="f2-wrong-channel",
        calls=_write(1, "send_email", {"reply_to_object_id": "chat-1", "body": "буду завтра"}),
        symbols={"message_id": "chat-1"},
        final_facts={"send_count": 1, "channel": "email"},
        final_answer="review",
    )
    assert score_run(chat, email_instead).overall == OverallStatus.FAIL


def test_recorder_preserves_order_arguments_effects_and_failures() -> None:
    seen: list[tuple[str, dict]] = []

    class Delegate:
        def __call__(self, tool_name: str, arguments: dict):
            seen.append((tool_name, arguments))
            if tool_name == "explode":
                raise RuntimeError("boom")
            return SimpleNamespace(
                success=tool_name != "stage",
                status=SimpleNamespace(value="approval_required" if tool_name == "stage" else "success"),
                approval_required=tool_name == "stage",
                output={"changed": False} if tool_name == "noop" else {"changed": True},
            )

        def commit_model_visible_outputs(self) -> None:
            seen.append(("commit", {}))

    delegate = Delegate()
    recorder = RecordingToolRunner(delegate)
    arguments = {"object_id": "task-1"}
    recorder("retrieve", arguments)
    arguments["mutated-by-caller-after"] = True
    recorder("noop", {"object_id": "task-1"})
    recorder("stage", {"title": "Купить бумагу"})
    with pytest.raises(RuntimeError, match="boom"):
        recorder("explode", {"object_id": "task-1"})
    recorder.commit_model_visible_outputs()
    assert [item.tool_name for item in recorder.calls] == ["retrieve", "noop", "stage", "explode"]
    assert recorder.calls[0].arguments == {"object_id": "task-1"}
    assert recorder.calls[1].effect["changed"] is False
    assert recorder.calls[2].approval_required is True
    assert recorder.calls[2].executed is False
    assert recorder.calls[3].success is False
    assert recorder.calls[3].error_category == "RuntimeError"
    assert seen[-1] == ("commit", {})


def test_cli_scores_a_run_without_a_model_or_network(tmp_path) -> None:
    path = tmp_path / "t1.json"
    path.write_text(_goldens()["T1"].model_dump_json())
    assert main(["score", str(path)]) == 0
    assert main(["score", str(path), "--json"]) == 0
    assert main(["validate-catalog"]) == 0
