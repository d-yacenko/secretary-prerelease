"""Deterministic execution-effect classification for action-plan finalization."""

from typing import Any


def classify_tool_execution_effect(tool_name: str, output: dict[str, Any] | None) -> str:
    if not output:
        return "failed"
    if tool_name == "create_task":
        return "created"
    if tool_name in ("create_scheduled_activity", "create_recurring_scheduled_activity"):
        return "created"
    if tool_name == "create_calendar_event":
        return "created" if output.get("changed") else "no_op"
    if tool_name == "send_email":
        return "created" if output.get("changed") else "no_op"
    if tool_name == "send_message":
        return "created" if output.get("changed") else "no_op"
    if tool_name == "remove_relation":
        return "removed" if output.get("changed") else "no_op"
    if tool_name == "link_objects":
        return "created" if output.get("created") else "no_op"
    if tool_name in ("update_task", "set_task_status", "delete_task", "cancel_scheduled_activity"):
        return "changed" if output.get("changed") else "no_op"
    if output.get("changed"):
        return "changed"
    return "no_op"


def describe_execution_effect(tool_name: str, output: dict[str, Any] | None) -> str:
    effect = classify_tool_execution_effect(tool_name, output)
    if effect == "created":
        if tool_name == "link_objects":
            edge = (output or {}).get("edge") or {}
            return (
                f"link_objects: created relation {edge.get('type')} "
                f"({edge.get('source_id')} -> {edge.get('target_id')})"
            )
        if tool_name == "create_calendar_event":
            return (
                f"create_calendar_event: created calendar event "
                f"{(output or {}).get('event_id')} via {(output or {}).get('provider')} "
                f"on {(output or {}).get('account_email')}; "
                f"changed=true"
            )
        if tool_name == "send_email":
            if (output or {}).get("provider") == "yandex":
                copy_status = (output or {}).get("sent_copy_status")
                if copy_status in ("stored", "already_present"):
                    return "Письмо отправлено. Копия сохранена в Отправленных."
                if copy_status == "unconfirmed":
                    return (
                        "Письмо отправлено, но не удалось подтвердить сохранение "
                        "копии в Отправленных."
                    )
            return (
                f"send_email: sent via {(output or {}).get('provider')} "
                f"from {(output or {}).get('account_email')}; changed=true"
            )
        if tool_name == "send_message":
            return (
                f"send_message: sent via {(output or {}).get('provider')} "
                f"mode={(output or {}).get('mode')} "
                f"provider_message_id={(output or {}).get('provider_message_id')}; "
                f"changed=true"
            )
        obj = (output or {}).get("object") or {}
        return f"{tool_name}: created object {obj.get('id')} ({obj.get('kind')})"
    if effect == "removed":
        if tool_name == "remove_relation":
            edge = (output or {}).get("edge") or {}
            return (
                f"remove_relation: deactivated edge {edge.get('id')} "
                f"({edge.get('type')}, {output.get('previous_state')} -> rejected)"
            )
        obj = (output or {}).get("object") or {}
        return f"{tool_name}: removed/deactivated task {obj.get('id')}"
    if effect == "changed":
        if tool_name == "update_task":
            added = len((output or {}).get("evidence_added_object_ids") or [])
            if added:
                return f"update_task: attached {added} evidence object(s); changed=true"
            return "update_task: task fields updated; changed=true"
        if tool_name == "set_task_status":
            return (
                f"set_task_status: {output.get('previous_status')} -> "
                f"{output.get('new_status')}; changed=true"
            )
        if tool_name == "delete_task":
            return "delete_task: soft-deleted task; changed=true"
        return f"{tool_name}: changed=true"
    if effect == "no_op":
        if tool_name == "update_task":
            already = len((output or {}).get("evidence_already_linked_object_ids") or [])
            if already:
                return (
                    f"update_task: no field changes; evidence already linked "
                    f"({already} object(s)); changed=false"
                )
        if tool_name == "remove_relation":
            return "remove_relation: edge already rejected; changed=false"
        if tool_name == "link_objects":
            return "link_objects: relation already existed; changed=false"
        if tool_name == "set_task_status":
            return (
                f"set_task_status: status already {output.get('new_status')}; changed=false"
            )
        if tool_name == "create_calendar_event":
            return (
                f"create_calendar_event: event already present "
                f"{(output or {}).get('event_id')}; changed=false"
            )
        if tool_name == "send_email":
            return (
                f"send_email: already delivered "
                f"{(output or {}).get('provider_message_id')}; changed=false"
            )
        if tool_name == "send_message":
            return (
                f"send_message: already sent "
                f"{(output or {}).get('provider_message_id')}; changed=false"
            )
        return f"{tool_name}: no state change; changed=false"
    return f"{tool_name}: execution failed or produced no output"
