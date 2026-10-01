"""Eval-only provider with the production run() surface. It makes no network call."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any


class ScriptedProvider:
    def __init__(self, rounds: tuple | list = ()) -> None:
        self.rounds = tuple(rounds)
        self.outputs: list[list[Any]] = []
        self.commits = 0
        self.seen: dict[str, Any] = {}

    def bind_rounds(self, rounds: tuple | list) -> None:
        if hasattr(rounds, "final_facts") or hasattr(rounds, "symbols"):
            raise TypeError("scripted provider accepts tool rounds, not a fixture")
        self.rounds = tuple(rounds)

    def run(
        self,
        message: str,
        history: list,
        ui_context: str,
        reference_datetime: datetime,
        timezone: str,
        tool_runner,
        identity_facts=None,
        *,
        system_instructions: str | None = None,
        tool_definitions: list | None = None,
    ):
        self.seen = {
            "message": message,
            "reference_datetime": reference_datetime,
            "timezone": timezone,
            "system_instructions": system_instructions,
            "tool_definitions": tool_definitions,
        }
        self.outputs = []
        self.commits = 0
        for tool_round in self.rounds:
            recorded = []
            for name, arguments in tool_round:
                recorded.append(tool_runner(name, arguments))
            self.outputs.append(recorded)
            tool_runner.commit_model_visible_outputs()
            self.commits += 1
        return SimpleNamespace(answer="review")
