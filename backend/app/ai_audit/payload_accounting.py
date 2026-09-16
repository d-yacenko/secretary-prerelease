"""Character-size accounting for Assistant request components."""

import json
from typing import Any


def _char_len(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _is_terminal_action_plan_content(content: str) -> bool:
    lowered = content.lower()
    return "terminal action plan" in lowered or "action plan" in lowered


def _is_ui_context_content(content: str) -> bool:
    return "explicit ui context" in content.lower() or "ui context" in content.lower()


def compute_assistant_input_component_sizes(
    *,
    instructions: str,
    input_items: list[dict],
    tool_definitions: list[dict] | None,
    user_message: str | None = None,
) -> dict[str, int]:
    history_chars = 0
    ui_context_chars = 0
    terminal_action_plan_chars = 0
    current_user_message_chars = 0
    function_call_chars = 0
    function_output_chars = 0

    last_plain_user_index: int | None = None
    for index, item in enumerate(input_items):
        if item.get("type") == "function_call" or item.get("type") == "function_call_output":
            continue
        role = item.get("role")
        content = item.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        if role == "user" and not _is_terminal_action_plan_content(content) and not _is_ui_context_content(content):
            last_plain_user_index = index

    for index, item in enumerate(input_items):
        item_type = item.get("type")
        if item_type == "function_call":
            function_call_chars += _char_len(item)
            continue
        if item_type == "function_call_output":
            function_output_chars += _char_len(item.get("output"))
            continue
        role = item.get("role")
        content = item.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        if role in ("user", "assistant"):
            if index == last_plain_user_index:
                current_user_message_chars += len(content)
            elif _is_terminal_action_plan_content(content):
                terminal_action_plan_chars += len(content)
            elif _is_ui_context_content(content):
                ui_context_chars += len(content)
            else:
                history_chars += len(content)

    if user_message and current_user_message_chars == 0:
        current_user_message_chars = len(user_message)

    tool_definition_chars = _char_len(tool_definitions or [])

    return {
        "system_instructions_chars": len(instructions),
        "conversation_history_chars": history_chars,
        "terminal_action_plan_history_chars": terminal_action_plan_chars,
        "explicit_ui_context_chars": ui_context_chars,
        "current_user_message_chars": current_user_message_chars,
        "accumulated_function_call_chars": function_call_chars,
        "accumulated_function_output_chars": function_output_chars,
        "tool_definition_chars": tool_definition_chars,
    }


def extract_responses_usage_fields(response: object) -> dict[str, int | None]:
    from app.llm.openai_usage import _detail_field, _usage_field, _usage_subobject

    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    result: dict[str, int | None] = {
        "input_tokens": _usage_field(usage, "input_tokens"),
        "output_tokens": _usage_field(usage, "output_tokens"),
    }
    input_details = _usage_subobject(usage, "input_tokens_details")
    if input_details is not None:
        result["cached_input_tokens"] = _detail_field(input_details, "cached_tokens")
        result["cache_write_tokens"] = _detail_field(input_details, "cache_write_tokens")
    output_details = _usage_subobject(usage, "output_tokens_details")
    if output_details is not None:
        result["reasoning_tokens"] = _detail_field(output_details, "reasoning_tokens")
    return result
