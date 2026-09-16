import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AssistantTurnTelemetry:
    tool_calls: int = 0
    retrieve_horizon_days: int | None = None
    retrieve_candidate_count: int | None = None
    retrieve_hit_count: int | None = None
    retrieve_mode: str | None = None
    retrieve_query_atom_count: int | None = None
    retrieve_selected_atom_count: int | None = None
    get_context_calls: int = 0
    openai_input_tokens: int | None = None
    openai_cached_input_tokens: int | None = None
    openai_cache_write_tokens: int | None = None
    openai_output_tokens: int | None = None
    openai_reasoning_tokens: int | None = None
    openai_responses_rounds: int | None = None
    openai_model: str | None = None
    openai_reasoning_effort: str | None = None
    openai_verbosity: str | None = None
    openai_max_output_tokens: int | None = None

    def record_tool(self, tool_name: str, output: dict | None) -> None:
        self.tool_calls += 1
        if tool_name == "get_context":
            self.get_context_calls += 1
        if tool_name == "retrieve" and output is not None:
            self.retrieve_horizon_days = output.get("horizon_days")
            self.retrieve_candidate_count = output.get("candidate_count")
            self.retrieve_hit_count = len(output.get("hits", []))
            self.retrieve_mode = output.get("retrieval_mode")
            self.retrieve_query_atom_count = output.get("query_atom_count")
            self.retrieve_selected_atom_count = output.get("selected_atom_count")

    def log_turn(self) -> None:
        logger.info(
            "assistant_turn tool_calls=%d retrieve_horizon_days=%s "
            "retrieve_candidate_count=%s retrieve_hit_count=%s retrieve_mode=%s "
            "retrieve_query_atom_count=%s retrieve_selected_atom_count=%s "
            "get_context_calls=%d openai_input_tokens=%s openai_cached_input_tokens=%s "
            "openai_cache_write_tokens=%s openai_output_tokens=%s "
            "openai_reasoning_tokens=%s openai_responses_rounds=%s openai_model=%s "
            "openai_reasoning_effort=%s openai_verbosity=%s openai_max_output_tokens=%s",
            self.tool_calls,
            self.retrieve_horizon_days,
            self.retrieve_candidate_count,
            self.retrieve_hit_count,
            self.retrieve_mode,
            self.retrieve_query_atom_count,
            self.retrieve_selected_atom_count,
            self.get_context_calls,
            self.openai_input_tokens,
            self.openai_cached_input_tokens,
            self.openai_cache_write_tokens,
            self.openai_output_tokens,
            self.openai_reasoning_tokens,
            self.openai_responses_rounds,
            self.openai_model,
            self.openai_reasoning_effort,
            self.openai_verbosity,
            self.openai_max_output_tokens,
        )

    def log_action_plan_resume(
        self,
        *,
        success: bool,
        elapsed_ms: int,
    ) -> None:
        logger.info(
            "assistant_action_plan_resume success=%s elapsed_ms=%d openai_input_tokens=%s "
            "openai_cached_input_tokens=%s openai_cache_write_tokens=%s "
            "openai_output_tokens=%s openai_reasoning_tokens=%s openai_responses_rounds=%s "
            "openai_model=%s openai_reasoning_effort=%s openai_verbosity=%s "
            "openai_max_output_tokens=%s",
            success,
            elapsed_ms,
            self.openai_input_tokens,
            self.openai_cached_input_tokens,
            self.openai_cache_write_tokens,
            self.openai_output_tokens,
            self.openai_reasoning_tokens,
            self.openai_responses_rounds,
            self.openai_model,
            self.openai_reasoning_effort,
            self.openai_verbosity,
            self.openai_max_output_tokens,
        )
