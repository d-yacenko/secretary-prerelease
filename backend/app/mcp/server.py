import logging
from datetime import datetime

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as McpToolError
from pydantic import ValidationError as PydanticValidationError

from app.mcp.gateway_runner import execute_mcp_tool
from app.tools.registry import MCP_TOOL_NAMES  # noqa: F401 — re-exported for tests
from app.tools.schemas import (
    AssignLabelOutput,
    CancelScheduledActivityOutput,
    ClearInboxReviewMarkerOutput,
    CreateCalendarEventOutput,
    CreateLabelOutput,
    CreateScheduledActivityOutput,
    CreateTaskOutput,
    DeleteLabelOutput,
    DeleteTaskOutput,
    GetContextOutput,
    GetObjectOutput,
    GetTodayOutput,
    LinkObjectsOutput,
    ListInboxSinceReviewMarkerOutput,
    ListConversationMembersOutput,
    ListLabelsOutput,
    ListNeighborsOutput,
    ListNotificationsOutput,
    QueryObjectsOutput,
    RemoveLabelOutput,
    RemoveRelationOutput,
    RenameLabelOutput,
    SearchObjectsOutput,
    SendEmailOutput,
    SendMessageOutput,
    SetInboxReviewMarkerOutput,
    SetTaskStatusOutput,
    ToolError,
    UpdateTaskOutput,
)

logger = logging.getLogger(__name__)


def _run_tool(operation: str, tool_name: str, arguments: dict) -> object:
    try:
        return execute_mcp_tool(tool_name, arguments)
    except ToolError as exc:
        logger.warning("mcp tool %s failed: %s", operation, exc.message)
        raise McpToolError(exc.message) from exc
    except PydanticValidationError:
        logger.warning("mcp tool %s rejected invalid input", operation)
        raise McpToolError("invalid tool input") from None
    except ValueError:
        logger.warning("mcp tool %s rejected invalid value", operation)
        raise McpToolError("invalid tool input") from None
    except Exception:
        logger.exception("mcp tool %s unexpected failure", operation)
        raise McpToolError(f"{operation} failed") from None


def create_mcp_server() -> MCPServer:
    mcp = MCPServer(
        "personal-secretary",
        instructions="Personal Secretary domain tools over the internal object graph.",
    )

    @mcp.tool()
    def query_objects(
        kinds: list[str] | None = None,
        providers: list[str] | None = None,
        statuses: list[str] | None = None,
        states: list[str] | None = None,
        due_from: datetime | None = None,
        due_to: datetime | None = None,
        start_from: datetime | None = None,
        start_to: datetime | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
        label_ids: list[str] | None = None,
        label_match: str = "all",
        sort_by: str = "created_at",
        sort_order: str = "desc",
        limit: int = 20,
    ) -> QueryObjectsOutput:
        """Structured object query with filters and deterministic ordering."""
        arguments: dict = {
            "sort_by": sort_by,
            "sort_order": sort_order,
            "limit": limit,
        }
        if kinds is not None:
            arguments["kinds"] = kinds
        if providers is not None:
            arguments["providers"] = providers
        if statuses is not None:
            arguments["statuses"] = statuses
        if states is not None:
            arguments["states"] = states
        if due_from is not None:
            arguments["due_from"] = due_from
        if due_to is not None:
            arguments["due_to"] = due_to
        if start_from is not None:
            arguments["start_from"] = start_from
        if start_to is not None:
            arguments["start_to"] = start_to
        if occurred_from is not None:
            arguments["occurred_from"] = occurred_from
        if occurred_to is not None:
            arguments["occurred_to"] = occurred_to
        if label_ids is not None:
            arguments["label_ids"] = label_ids
        if label_match is not None:
            arguments["label_match"] = label_match
        return _run_tool("query_objects", "query_objects", arguments)

    @mcp.tool()
    def search_objects(
        query: str,
        kind: str | None = None,
        limit: int = 20,
    ) -> SearchObjectsOutput:
        """Search objects by semantic and lexical match."""
        return _run_tool(
            "search_objects",
            "search_objects",
            {"query": query, "kind": kind, "limit": limit},
        )

    @mcp.tool()
    def get_object(object_id: str) -> GetObjectOutput:
        """Fetch one object by id."""
        return _run_tool(
            "get_object",
            "get_object",
            {"object_id": object_id},
        )

    @mcp.tool()
    def get_context(
        object_id: str | None = None,
        query: str | None = None,
        max_chars: int = 8000,
    ) -> GetContextOutput:
        """Build bounded context using the Context Resolver."""
        return _run_tool(
            "get_context",
            "get_context",
            {
                "object_id": object_id,
                "query": query,
                "max_chars": max_chars,
            },
        )

    @mcp.tool()
    def list_neighbors(object_id: str) -> ListNeighborsOutput:
        """List direct graph neighbors for an object."""
        return _run_tool(
            "list_neighbors",
            "list_neighbors",
            {"object_id": object_id},
        )

    @mcp.tool()
    def create_task(
        title: str,
        confidence: float,
        body: str | None = None,
        due_at: datetime | None = None,
        evidence_object_ids: list[str] | None = None,
    ) -> CreateTaskOutput:
        """Create an agent-proposed task with required confidence."""
        return _run_tool(
            "create_task",
            "create_task",
            {
                "title": title,
                "confidence": confidence,
                "body": body,
                "due_at": due_at,
                "evidence_object_ids": evidence_object_ids or [],
            },
        )

    @mcp.tool()
    def update_task(
        object_id: str,
        title: str | None = None,
        body: str | None = None,
        due_at: datetime | None = None,
        evidence_object_ids: list[str] | None = None,
    ) -> UpdateTaskOutput:
        """Update task fields or attach evidence without changing lifecycle status."""
        arguments: dict = {"object_id": object_id}
        if title is not None:
            arguments["title"] = title
        if body is not None:
            arguments["body"] = body
        if due_at is not None:
            arguments["due_at"] = due_at
        if evidence_object_ids is not None:
            arguments["evidence_object_ids"] = evidence_object_ids
        return _run_tool("update_task", "update_task", arguments)

    @mcp.tool()
    def set_task_status(object_id: str, status: str) -> SetTaskStatusOutput:
        """Set canonical task lifecycle status."""
        return _run_tool(
            "set_task_status",
            "set_task_status",
            {"object_id": object_id, "status": status},
        )

    @mcp.tool()
    def delete_task(object_id: str) -> DeleteTaskOutput:
        """Soft-delete a task (status=deleted)."""
        return _run_tool(
            "delete_task",
            "delete_task",
            {"object_id": object_id},
        )

    @mcp.tool()
    def link_objects(
        source_id: str,
        target_id: str,
        relation_type: str,
        confidence: float,
    ) -> LinkObjectsOutput:
        """Create an agent-proposed relation between two objects."""
        return _run_tool(
            "link_objects",
            "link_objects",
            {
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relation_type,
                "confidence": confidence,
            },
        )

    @mcp.tool()
    def remove_relation(edge_id: str) -> RemoveRelationOutput:
        """Deactivate a semantic graph relation by exact edge_id (requires approval)."""
        return _run_tool(
            "remove_relation",
            "remove_relation",
            {"edge_id": edge_id},
        )

    @mcp.tool()
    def list_notifications(
        status: str | None = None,
        limit: int = 50,
    ) -> ListNotificationsOutput:
        """List inbox notifications with optional status filter."""
        return _run_tool(
            "list_notifications",
            "list_notifications",
            {"status": status, "limit": limit},
        )

    @mcp.tool()
    def list_labels(limit: int = 100) -> ListLabelsOutput:
        """List active organizational labels."""
        return _run_tool("list_labels", "list_labels", {"limit": limit})

    @mcp.tool()
    def list_inbox_since_review_marker(
        limit: int = 20,
        purpose: str = "inspect",
        cursor: str | None = None,
    ) -> ListInboxSinceReviewMarkerOutput:
        """List Inbox objects strictly newer than the Secretary review marker."""
        arguments: dict = {"limit": limit, "purpose": purpose}
        if cursor:
            arguments["cursor"] = cursor
        return _run_tool(
            "list_inbox_since_review_marker",
            "list_inbox_since_review_marker",
            arguments,
        )

    @mcp.tool()
    def list_conversation_members(
        object_id: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ListConversationMembersOutput:
        """List chronological members of the Conversation Stack containing object_id."""
        arguments: dict = {"object_id": object_id, "limit": limit}
        if cursor:
            arguments["cursor"] = cursor
        return _run_tool(
            "list_conversation_members",
            "list_conversation_members",
            arguments,
        )

    @mcp.tool()
    def set_inbox_review_marker(after_object_id: str) -> SetInboxReviewMarkerOutput:
        """Set the global Inbox review marker (requires approval over MCP)."""
        return _run_tool(
            "set_inbox_review_marker",
            "set_inbox_review_marker",
            {"after_object_id": after_object_id},
        )

    @mcp.tool()
    def clear_inbox_review_marker() -> ClearInboxReviewMarkerOutput:
        """Clear the global Inbox review marker (requires approval over MCP)."""
        return _run_tool("clear_inbox_review_marker", "clear_inbox_review_marker", {})

    @mcp.tool()
    def create_label(name: str) -> CreateLabelOutput:
        """Create an organizational label (requires approval)."""
        return _run_tool("create_label", "create_label", {"name": name})

    @mcp.tool()
    def rename_label(label_id: str, name: str) -> RenameLabelOutput:
        """Rename an organizational label (requires approval)."""
        return _run_tool(
            "rename_label",
            "rename_label",
            {"label_id": label_id, "name": name},
        )

    @mcp.tool()
    def assign_label(object_id: str, label_id: str) -> AssignLabelOutput:
        """Assign a label to an object (requires approval)."""
        return _run_tool(
            "assign_label",
            "assign_label",
            {"object_id": object_id, "label_id": label_id},
        )

    @mcp.tool()
    def remove_label(object_id: str, label_id: str) -> RemoveLabelOutput:
        """Remove a labeled_with assignment (requires approval)."""
        return _run_tool(
            "remove_label",
            "remove_label",
            {"object_id": object_id, "label_id": label_id},
        )

    @mcp.tool()
    def delete_label(label_id: str) -> DeleteLabelOutput:
        """Tombstone a label (requires approval)."""
        return _run_tool("delete_label", "delete_label", {"label_id": label_id})

    @mcp.tool()
    def get_today() -> GetTodayOutput:
        """Return the current datetime in SECRETARY_TIMEZONE."""
        return _run_tool("get_today", "get_today", {})

    @mcp.tool()
    def create_scheduled_activity(
        title: str,
        run_at: datetime,
        body: str | None = None,
        priority: str = "normal",
    ) -> CreateScheduledActivityOutput:
        """Schedule a one-shot internal reminder (requires approval; MCP cannot execute)."""
        arguments: dict = {"title": title, "run_at": run_at, "priority": priority}
        if body is not None:
            arguments["body"] = body
        return _run_tool("create_scheduled_activity", "create_scheduled_activity", arguments)

    @mcp.tool()
    def create_recurring_scheduled_activity(
        title: str,
        schedule_kind: str,
        local_time: str,
        body: str | None = None,
        timezone: str | None = None,
        weekdays: list[str] | None = None,
        priority: str = "normal",
    ) -> CreateScheduledActivityOutput:
        """Schedule a daily/weekly internal reminder (requires approval; MCP cannot execute)."""
        arguments: dict = {
            "title": title,
            "schedule_kind": schedule_kind,
            "local_time": local_time,
            "priority": priority,
        }
        if body is not None:
            arguments["body"] = body
        if timezone is not None:
            arguments["timezone"] = timezone
        if weekdays is not None:
            arguments["weekdays"] = weekdays
        return _run_tool(
            "create_recurring_scheduled_activity",
            "create_recurring_scheduled_activity",
            arguments,
        )

    @mcp.tool()
    def cancel_scheduled_activity(activity_id: str) -> CancelScheduledActivityOutput:
        """Cancel a scheduled activity before future occurrences fire (requires approval)."""
        return _run_tool(
            "cancel_scheduled_activity",
            "cancel_scheduled_activity",
            {"activity_id": activity_id},
        )

    @mcp.tool()
    def create_calendar_event(
        summary: str,
        start_at: datetime,
        end_at: datetime,
        description: str | None = None,
        location: str | None = None,
        account_email: str | None = None,
    ) -> CreateCalendarEventOutput:
        """Create a Google Calendar event (requires approval; MCP cannot execute the write)."""
        arguments: dict = {
            "summary": summary,
            "start_at": start_at,
            "end_at": end_at,
        }
        if description is not None:
            arguments["description"] = description
        if location is not None:
            arguments["location"] = location
        if account_email is not None:
            arguments["account_email"] = account_email
        return _run_tool("create_calendar_event", "create_calendar_event", arguments)

    @mcp.tool()
    def send_email(
        to: list[str],
        subject: str,
        body: str,
        account_email: str | None = None,
    ) -> SendEmailOutput:
        """Send a plain-text email (requires approval; MCP cannot execute the send)."""
        arguments: dict = {
            "to": to,
            "subject": subject,
            "body": body,
        }
        if account_email is not None:
            arguments["account_email"] = account_email
        return _run_tool("send_email", "send_email", arguments)

    @mcp.tool()
    def send_message(
        body: str,
        conversation_object_id: str | None = None,
        reply_to_object_id: str | None = None,
    ) -> SendMessageOutput:
        """Send a Mattermost message in an existing conversation (requires approval; MCP cannot execute the send)."""
        arguments: dict = {"body": body}
        if conversation_object_id is not None:
            arguments["conversation_object_id"] = conversation_object_id
        if reply_to_object_id is not None:
            arguments["reply_to_object_id"] = reply_to_object_id
        return _run_tool("send_message", "send_message", arguments)

    return mcp
