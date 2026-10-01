"""Eval-only wrapper around the Assistant tool-runner callable."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from evals.secretary_agent.models import ToolCallRecord


class RecordingToolRunner:
    """Forward calls unchanged and keep an in-memory trace for scoring."""

    def __init__(self, delegate: Callable[..., Any]) -> None:
        self._delegate = delegate
        self.calls: list[ToolCallRecord] = []

    def __call__(self, tool_name: str, arguments: dict) -> Any:
        recorded_arguments = copy.deepcopy(arguments)
        sequence = len(self.calls) + 1
        try:
            result = self._delegate(tool_name, arguments)
        except Exception as exc:
            self.calls.append(
                ToolCallRecord(
                    sequence=sequence,
                    tool_name=tool_name,
                    arguments=recorded_arguments,
                    success=False,
                    status="exception",
                    error_category=type(exc).__name__,
                )
            )
            raise
        self.calls.append(_record(sequence, tool_name, recorded_arguments, result))
        return result

    def commit_model_visible_outputs(self) -> None:
        commit = getattr(self._delegate, "commit_model_visible_outputs", None)
        if commit is None:
            raise AttributeError("delegate has no commit_model_visible_outputs")
        commit()


def _record(sequence: int, tool_name: str, arguments: dict, result: Any) -> ToolCallRecord:
    status = getattr(result, "status", None)
    status_value = getattr(status, "value", status) or "success"
    output = getattr(result, "output", None)
    effect = dict(output) if isinstance(output, dict) else {}
    return ToolCallRecord(
        sequence=sequence,
        tool_name=tool_name,
        arguments=arguments,
        success=bool(getattr(result, "success", False)),
        status=str(status_value),
        approval_required=bool(getattr(result, "approval_required", False)),
        executed=bool(getattr(result, "success", False))
        and not bool(getattr(result, "approval_required", False)),
        effect=effect,
        error_category=None if getattr(result, "success", False) else str(status_value),
    )
