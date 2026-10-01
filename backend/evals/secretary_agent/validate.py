"""Drift checks between the scenario document and the executable catalogue."""

from __future__ import annotations

import re
from pathlib import Path

from app.domain.generic_relations import GENERIC_RELATION_TYPES
from app.domain.task_relations import TASK_ACTOR_ROLES
from app.tools.registry import TOOL_REGISTRY
from evals.secretary_agent.catalog import SCENARIOS, Scenario

_DOC = Path(__file__).resolve().parents[3] / "docs" / "SECRETARY_AGENT_EVAL_SCENARIOS.md"
_HEADING = re.compile(r"^### ([A-Z][A-Z0-9]*) —", re.MULTILINE)
_SECTION = re.compile(r"^## (.+)$", re.MULTILINE)
_SECTION_CATEGORY = {
    "Person": "Person",
    "Task": "Task",
    "Flow": "Flow",
    "Time": "Time",
    "Relations": "Relations",
    "Approval and provenance": "Approval",
    "Prompt injection and safety": "Safety",
    "Ambiguity and no-op": "Ambiguity",
}


def documented_ids() -> list[str]:
    return _HEADING.findall(_DOC.read_text())


def documented_categories() -> dict[str, str]:
    text = _DOC.read_text()
    categories: dict[str, str] = {}
    current = ""
    for line in text.splitlines():
        section = _SECTION.match(line)
        if section:
            current = _SECTION_CATEGORY.get(section.group(1), "")
            continue
        heading = _HEADING.match(line)
        if heading and current:
            categories[heading.group(1)] = current
    return categories


def validate_catalog() -> list[str]:
    errors: list[str] = []
    documented = documented_ids()
    if len(documented) != len(set(documented)):
        errors.append("documented scenario ids are not unique")
    missing = [item for item in documented if item not in SCENARIOS]
    extra = [item for item in SCENARIOS if item not in documented]
    if missing:
        errors.append("missing executable scenarios: " + ", ".join(missing))
    if extra:
        errors.append("undocumented executable scenarios: " + ", ".join(extra))
    categories = documented_categories()
    for scenario_id, scenario in SCENARIOS.items():
        if categories.get(scenario_id) != scenario.category:
            errors.append(
                f"{scenario_id} category {scenario.category} does not match the document"
            )
        errors.extend(_vocabulary(scenario))
    return errors


def _vocabulary(scenario: Scenario) -> list[str]:
    errors: list[str] = []
    names = set(scenario.required_tools) | set(scenario.forbidden_tools)
    for group in scenario.one_of:
        names.update(group)
    for earlier, later in scenario.order:
        names.add(earlier)
        names.add(later)
    for name in sorted(names):
        if name not in TOOL_REGISTRY:
            errors.append(f"{scenario.id} names unknown tool {name}")
    for relation in scenario.relation_types:
        if relation not in GENERIC_RELATION_TYPES:
            errors.append(f"{scenario.id} relation {relation} is not generic")
    if scenario.relation is not None:
        relation = scenario.relation["relation_type"]
        if relation not in GENERIC_RELATION_TYPES:
            errors.append(f"{scenario.id} relation {relation} is not generic")
    for role in scenario.actor_roles:
        if role not in TASK_ACTOR_ROLES:
            errors.append(f"{scenario.id} actor role {role} is not canonical")
    return errors
