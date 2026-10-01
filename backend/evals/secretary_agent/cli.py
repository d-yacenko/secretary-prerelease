"""Score a local eval run or validate the scenario catalogue. No model access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals.secretary_agent.catalog import SCENARIOS
from evals.secretary_agent.models import EvalRun
from evals.secretary_agent.scorer import score_run
from evals.secretary_agent.validate import validate_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secretary-agent-eval")
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score")
    score.add_argument("run_json", type=Path)
    score.add_argument("--json", action="store_true", dest="as_json")
    sub.add_parser("validate-catalog")
    args = parser.parse_args(argv)
    if args.command == "validate-catalog":
        errors = validate_catalog()
        if errors:
            for error in errors:
                print(error)
            return 1
        print(f"catalog ok: {len(SCENARIOS)} scenarios")
        return 0
    run = EvalRun.model_validate_json(args.run_json.read_text())
    scenario = SCENARIOS.get(run.scenario_id)
    if scenario is None:
        print(f"unknown scenario {run.scenario_id}")
        return 1
    report = score_run(scenario, run)
    if args.as_json:
        print(report.model_dump_json(indent=2))
    else:
        print(f"scenario {report.scenario_id}")
        print(f"overall {report.overall.value}")
        for item in report.dimensions:
            detail = "" if not item.reasons else ": " + "; ".join(item.reasons)
            print(f"{item.dimension} {item.status.value}{detail}")
    return 0 if report.overall.value != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
