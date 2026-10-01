"""Deterministic structural scoring. Free-form answers stay on manual review."""

from __future__ import annotations

from typing import Any

from app.tools.policy import ToolPermission
from app.tools.registry import TOOL_REGISTRY
from evals.secretary_agent.catalog import Scenario
from evals.secretary_agent.models import (
    DimensionScore,
    DimensionStatus,
    EvalRun,
    OverallStatus,
    ScoreReport,
    ToolCallRecord,
)

DIMENSIONS = (
    "semantic_correctness",
    "tool_choice_correctness",
    "minimality",
    "provenance_correctness",
    "approval_correctness",
    "final_state_correctness",
    "truthful_final_response",
)

_ID_KEYS = {
    "object_id",
    "task_id",
    "person_id",
    "edge_id",
    "source_id",
    "target_id",
    "reply_to_object_id",
}


def score_run(scenario: Scenario, run: EvalRun) -> ScoreReport:
    reasons: dict[str, list[str]] = {name: [] for name in DIMENSIONS}
    _tool_choice(scenario, run, reasons)
    _minimality(scenario, run, reasons)
    _semantic(scenario, run, reasons)
    _provenance(scenario, run, reasons)
    _approval(scenario, run, reasons)
    _final_state(scenario, run, reasons)
    reasons["truthful_final_response"].append("final answer requires human review")
    dimensions = [
        DimensionScore(
            dimension=name,
            status=_status(scenario, name, reasons[name]),
            reasons=reasons[name],
        )
        for name in DIMENSIONS
    ]
    return ScoreReport(
        scenario_id=scenario.id,
        overall=_overall(dimensions),
        dimensions=dimensions,
    )


def _status(scenario: Scenario, name: str, failures: list[str]) -> DimensionStatus:
    if name == "truthful_final_response":
        return DimensionStatus.MANUAL_REVIEW
    if name == "semantic_correctness" and not failures and not _has_semantic(scenario):
        return DimensionStatus.NOT_APPLICABLE
    if failures:
        return DimensionStatus.FAIL
    return DimensionStatus.PASS


def _has_semantic(scenario: Scenario) -> bool:
    return any(
        (
            scenario.completion_mode,
            scenario.relation,
            scenario.evidence_pair,
            scenario.actor_contains,
            scenario.planned_interval_and_due,
            scenario.effect_if_present,
            scenario.ambiguous_fact,
            scenario.remove_edge_symbol,
        )
    )


def _overall(dimensions: list[DimensionScore]) -> OverallStatus:
    if any(item.status == DimensionStatus.FAIL for item in dimensions):
        return OverallStatus.FAIL
    if any(item.status == DimensionStatus.MANUAL_REVIEW for item in dimensions):
        return OverallStatus.INCOMPLETE
    return OverallStatus.PASS


def _tool_choice(scenario: Scenario, run: EvalRun, reasons: dict[str, list[str]]) -> None:
    names = [call.tool_name for call in run.calls]
    for tool in scenario.required_tools:
        if tool not in names:
            reasons["tool_choice_correctness"].append(f"missing required tool {tool}")
    for tool in scenario.forbidden_tools:
        if tool in names:
            reasons["tool_choice_correctness"].append(f"forbidden tool {tool}")
    for group in scenario.one_of:
        if not any(tool in names for tool in group):
            reasons["tool_choice_correctness"].append(
                "missing one of " + ", ".join(group)
            )
    for earlier, later in scenario.order:
        if later not in names:
            continue
        if earlier not in names or names.index(earlier) > names.index(later):
            reasons["tool_choice_correctness"].append(f"{earlier} must precede {later}")
    if scenario.remove_edge_symbol and "remove_relation" in names:
        if "list_neighbors" not in names or names.index("list_neighbors") > names.index(
            "remove_relation"
        ):
            reasons["tool_choice_correctness"].append(
                "remove_relation requires a prior list_neighbors"
            )


def _minimality(scenario: Scenario, run: EvalRun, reasons: dict[str, list[str]]) -> None:
    writes = [call for call in run.calls if _is_mutation(call.tool_name)]
    counted = writes if scenario.approval == "staged_only" else [c for c in writes if c.executed]
    if scenario.approval == "staged_then_executed_if_present":
        counted = [c for c in writes if c.executed]
    if scenario.mutations_forbidden and writes:
        reasons["minimality"].append("mutation is forbidden")
    if scenario.max_mutations is not None and len(counted) > scenario.max_mutations:
        reasons["minimality"].append(
            f"mutation count {len(counted)} exceeds {scenario.max_mutations}"
        )
    for tool, limit in scenario.max_calls_by_tool.items():
        count = sum(1 for call in run.calls if call.tool_name == tool)
        if count > limit:
            reasons["minimality"].append(f"{tool} called {count} times; limit is {limit}")


def _semantic(scenario: Scenario, run: EvalRun, reasons: dict[str, list[str]]) -> None:
    bucket = reasons["semantic_correctness"]
    if scenario.completion_mode is not None:
        tool, expected = scenario.completion_mode
        call = _preferred(run, tool)
        if call is None or call.arguments.get("completion_mode") != expected:
            bucket.append(f"{tool} completion_mode must be {expected}")
    if scenario.relation is not None:
        _check_relation(scenario, run, bucket)
    if scenario.evidence_pair is not None:
        _check_evidence(scenario, run, bucket)
    if scenario.actor_contains is not None:
        tool, field, symbol = scenario.actor_contains
        call = _preferred(run, tool)
        expected = run.symbols.get(symbol)
        value = None if call is None else call.arguments.get(field)
        if isinstance(value, list):
            ok = expected in value
        else:
            ok = value == expected
        if not ok:
            bucket.append(f"{tool}.{field} must use {symbol}")
    if scenario.planned_interval_and_due:
        call = _preferred(run, "update_task")
        args = {} if call is None else call.arguments
        if not args.get("planned_start_at") or not args.get("planned_end_at") or not args.get("due_at"):
            bucket.append("planned interval and due_at must be written together")
        if args.get("planned_start_at") and not args.get("planned_end_at"):
            bucket.append("planned interval is missing planned_end_at")
        if args.get("planned_end_at") and not args.get("planned_start_at"):
            bucket.append("planned interval is missing planned_start_at")
    for tool, changed in scenario.effect_if_present.items():
        calls = [call for call in run.calls if call.tool_name == tool and call.executed]
        for call in calls:
            if call.effect.get("changed") is not changed:
                bucket.append(f"{tool} changed must be {changed}")
    if scenario.ambiguous_fact is not None:
        count = run.final_facts.get(scenario.ambiguous_fact, 0)
        if count > 1 and any(call.tool_name == "remove_relation" for call in run.calls):
            bucket.append("ambiguous evidence edges require clarification, not removal")
    if scenario.remove_edge_symbol is not None:
        expected = run.symbols.get(scenario.remove_edge_symbol)
        for call in run.calls:
            if call.tool_name != "remove_relation":
                continue
            if call.arguments.get("edge_id") != expected:
                bucket.append("remove_relation edge_id is not the identified edge")


def _check_relation(scenario: Scenario, run: EvalRun, bucket: list[str]) -> None:
    spec = scenario.relation or {}
    call = _preferred(run, spec["tool"])
    if call is None:
        bucket.append(f"missing {spec['tool']}")
        return
    if call.arguments.get("relation_type") != spec["relation_type"]:
        bucket.append(f"relation_type must be {spec['relation_type']}")
    source = run.symbols.get(spec["source_symbol"])
    target = run.symbols.get(spec["target_symbol"])
    if call.arguments.get("source_id") != source or call.arguments.get("target_id") != target:
        bucket.append(
            f"{spec['source_symbol']} must be the source and {spec['target_symbol']} the target"
        )


def _check_evidence(scenario: Scenario, run: EvalRun, bucket: list[str]) -> None:
    pdf_symbol, task_symbol = scenario.evidence_pair or ("", "")
    pdf_id = run.symbols.get(pdf_symbol)
    task_id = run.symbols.get(task_symbol)
    for call in run.calls:
        if call.tool_name == "update_task" and pdf_id in (call.arguments.get("evidence_object_ids") or []):
            return
        if call.tool_name == "link_objects" and call.arguments.get("relation_type") == "references":
            ends = {call.arguments.get("source_id"), call.arguments.get("target_id")}
            if ends == {pdf_id, task_id}:
                return
        if call.tool_name == "link_objects" and call.arguments.get("relation_type") not in (
            None,
            "references",
        ):
            bucket.append("evidence must use references, not another relation type")
            return
    bucket.append("missing references evidence attach")


def _provenance(scenario: Scenario, run: EvalRun, reasons: dict[str, list[str]]) -> None:
    del scenario
    allowed = set(run.symbols.values())
    for call in run.calls:
        for found in _id_values(call.arguments):
            if found not in allowed:
                reasons["provenance_correctness"].append(
                    f"{call.tool_name} uses an id outside the fixture map"
                )
                return


def _approval(scenario: Scenario, run: EvalRun, reasons: dict[str, list[str]]) -> None:
    writes = [call for call in run.calls if _is_mutation(call.tool_name)]
    bucket = reasons["approval_correctness"]
    mode = scenario.approval
    if mode == "none":
        if writes:
            bucket.append("no approval card was expected, but a mutation was called")
        return
    if mode == "staged_then_executed_if_present" and not writes:
        return
    if mode == "staged_only":
        if not writes:
            bucket.append("expected a staged mutation")
        if any(call.executed for call in writes):
            bucket.append("approval_required was treated as execution")
        if any(not call.approval_required for call in writes):
            bucket.append("mutation was not staged for approval")
        return
    executed = [call for call in writes if call.executed]
    if not executed:
        bucket.append("expected execution after approval")
        return
    for call in executed:
        prior = run.calls[: call.sequence - 1]
        staged = any(
            earlier.tool_name == call.tool_name and earlier.approval_required and not earlier.executed
            for earlier in prior
        )
        if not staged:
            bucket.append(f"{call.tool_name} executed without a prior approval stage")


def _final_state(scenario: Scenario, run: EvalRun, reasons: dict[str, list[str]]) -> None:
    for key, expected in scenario.expected_facts.items():
        if run.final_facts.get(key) != expected:
            reasons["final_state_correctness"].append(
                f"final fact {key} is {run.final_facts.get(key)!r}, expected {expected!r}"
            )


def _preferred(run: EvalRun, tool: str) -> ToolCallRecord | None:
    matches = [call for call in run.calls if call.tool_name == tool]
    executed = [call for call in matches if call.executed]
    if executed:
        return executed[-1]
    if matches:
        return matches[-1]
    return None


def _is_mutation(tool_name: str) -> bool:
    spec = TOOL_REGISTRY.get(tool_name)
    if spec is None:
        return True
    return spec.permission != ToolPermission.READ


def _id_values(arguments: dict[str, Any]) -> list[str]:
    found: list[str] = []

    def walk(key: str, value: Any) -> None:
        if key in _ID_KEYS or key.endswith("_id"):
            if isinstance(value, str):
                found.append(value)
        elif key.endswith("_ids") and isinstance(value, list):
            found.extend(item for item in value if isinstance(item, str))
        elif isinstance(value, dict):
            for child_key, child in value.items():
                walk(str(child_key), child)

    for key, value in arguments.items():
        walk(key, value)
    return found
