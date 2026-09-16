from dataclasses import dataclass


def add_optional(total: int | None, value: int | None) -> int | None:
    if value is None:
        return total
    return (total or 0) + value


@dataclass
class ResponsesUsageAccumulated:
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    responses_rounds: int = 0

    def accumulate(self, response: object) -> None:
        self.responses_rounds += 1
        usage = getattr(response, "usage", None)
        if usage is None:
            return

        self.input_tokens = add_optional(
            self.input_tokens, _usage_field(usage, "input_tokens")
        )
        self.output_tokens = add_optional(
            self.output_tokens, _usage_field(usage, "output_tokens")
        )

        input_details = _usage_subobject(usage, "input_tokens_details")
        if input_details is not None:
            self.cached_input_tokens = add_optional(
                self.cached_input_tokens,
                _detail_field(input_details, "cached_tokens"),
            )
            self.cache_write_tokens = add_optional(
                self.cache_write_tokens,
                _detail_field(input_details, "cache_write_tokens"),
            )

        output_details = _usage_subobject(usage, "output_tokens_details")
        if output_details is not None:
            self.reasoning_tokens = add_optional(
                self.reasoning_tokens,
                _detail_field(output_details, "reasoning_tokens"),
            )


def _usage_field(usage: object, field: str) -> int | None:
    value = getattr(usage, field, None)
    if value is None and isinstance(usage, dict):
        value = usage.get(field)
    return int(value) if value is not None else None


def _usage_subobject(usage: object, field: str) -> object | None:
    value = getattr(usage, field, None)
    if value is None and isinstance(usage, dict):
        value = usage.get(field)
    return value


def _detail_field(details: object, field: str) -> int | None:
    value = getattr(details, field, None)
    if value is None and isinstance(details, dict):
        value = details.get(field)
    return int(value) if value is not None else None


def response_hit_max_output_tokens(response: object) -> bool:
    status = getattr(response, "status", None)
    if status != "incomplete":
        return False
    incomplete = getattr(response, "incomplete_details", None)
    if incomplete is None:
        return False
    reason = getattr(incomplete, "reason", None)
    if reason is None and isinstance(incomplete, dict):
        reason = incomplete.get("reason")
    return reason == "max_output_tokens"
