from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class AssistantHistoryMessage:
    role: str
    content: str


@dataclass
class AssistantProviderResult:
    answer: str
    candidate_object_ids: list[UUID] = field(default_factory=list)
    affected_object_ids: list[UUID] = field(default_factory=list)
    store_false_used: bool = True
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
