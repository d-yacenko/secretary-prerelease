"""Canonical Secretary domain tool registry."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.proactive.constants import PROACTIVE_READ_TOOL_NAMES
from app.services.domain_tool_service import DomainToolService
from app.tools.assistant_contracts import ASSISTANT_FUNCTION_SCHEMAS
from app.tools.policy import ToolPermission
from app.tools.schemas import (
    AssignLabelInput,
    CancelScheduledActivityInput,
    CreateCalendarEventCanonicalInput,
    CreateCalendarEventInput,
    CreateLabelCanonicalInput,
    CreateLabelInput,
    CreateRecurringScheduledActivityCanonicalInput,
    CreateRecurringScheduledActivityInput,
    CreateScheduledActivityCanonicalInput,
    CreateScheduledActivityInput,
    CreateTaskInput,
    DeleteLabelInput,
    DeleteTaskInput,
    FindPersonCommunicationsInput,
    GetContextInput,
    GetObjectInput,
    LinkObjectsInput,
    ListConversationMembersInput,
    ListInboxSinceReviewMarkerInput,
    ListLabelsInput,
    ListNeighborsInput,
    ListNotificationsInput,
    PersonIdentityFeedbackInput,
    QueryObjectsInput,
    RemoveLabelInput,
    RemoveRelationInput,
    RenameLabelCanonicalInput,
    RenameLabelInput,
    ResolvePersonInput,
    RetrieveInput,
    SearchObjectsInput,
    SendEmailCanonicalInput,
    SendEmailInput,
    SendMessageCanonicalInput,
    SendMessageInput,
    SetInboxReviewMarkerInput,
    SetTaskStatusInput,
    TelegramMtprotoDeleteCanonicalInput,
    TelegramMtprotoDeleteInput,
    TelegramMtprotoEditCanonicalInput,
    TelegramMtprotoEditInput,
    TelegramMtprotoMarkReadCanonicalInput,
    TelegramMtprotoMarkReadInput,
    ToolError,
    UpdateTaskInput,
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    permission: ToolPermission
    input_model: type[BaseModel] | None
    service_method: str
    assistant_exposed: bool
    mcp_exposed: bool
    assistant_definition: dict | None = None
    prepare_method: str | None = None
    execution_input_model: type[BaseModel] | None = None


def _assistant_definition(name: str) -> dict:
    return ASSISTANT_FUNCTION_SCHEMAS[name]


def _build_tool_registry(specs: tuple[ToolSpec, ...]) -> dict[str, ToolSpec]:
    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        seen: set[str] = set()
        duplicates = [name for name in names if name in seen or seen.add(name)]
        raise ValueError(f"duplicate tool registry names: {duplicates}")
    return {spec.name: spec for spec in specs}


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="retrieve",
        permission=ToolPermission.READ,
        input_model=RetrieveInput,
        service_method="retrieve",
        assistant_exposed=True,
        mcp_exposed=False,
        assistant_definition=_assistant_definition("retrieve"),
    ),
    ToolSpec(
        name="query_objects",
        permission=ToolPermission.READ,
        input_model=QueryObjectsInput,
        service_method="query_objects",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("query_objects"),
    ),
    ToolSpec(
        name="search_objects",
        permission=ToolPermission.READ,
        input_model=SearchObjectsInput,
        service_method="search_objects",
        assistant_exposed=False,
        mcp_exposed=True,
    ),
    ToolSpec(
        name="get_object",
        permission=ToolPermission.READ,
        input_model=GetObjectInput,
        service_method="get_object",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("get_object"),
    ),
    ToolSpec(
        name="get_context",
        permission=ToolPermission.READ,
        input_model=GetContextInput,
        service_method="get_context",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("get_context"),
    ),
    ToolSpec(
        name="list_neighbors",
        permission=ToolPermission.READ,
        input_model=ListNeighborsInput,
        service_method="list_neighbors",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("list_neighbors"),
    ),
    ToolSpec(
        name="list_notifications",
        permission=ToolPermission.READ,
        input_model=ListNotificationsInput,
        service_method="list_notifications",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("list_notifications"),
    ),
    ToolSpec(
        name="list_labels",
        permission=ToolPermission.READ,
        input_model=ListLabelsInput,
        service_method="list_labels",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("list_labels"),
    ),
    ToolSpec(
        name="list_inbox_since_review_marker",
        permission=ToolPermission.READ,
        input_model=ListInboxSinceReviewMarkerInput,
        service_method="list_inbox_since_review_marker",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("list_inbox_since_review_marker"),
    ),
    ToolSpec(
        name="list_conversation_members",
        permission=ToolPermission.READ,
        input_model=ListConversationMembersInput,
        service_method="list_conversation_members",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("list_conversation_members"),
    ),
    ToolSpec(
        name="resolve_person",
        permission=ToolPermission.READ,
        input_model=ResolvePersonInput,
        service_method="resolve_person",
        assistant_exposed=True,
        mcp_exposed=False,
        assistant_definition=_assistant_definition("resolve_person"),
    ),
    ToolSpec(
        name="find_person_communications",
        permission=ToolPermission.READ,
        input_model=FindPersonCommunicationsInput,
        service_method="find_person_communications",
        assistant_exposed=True,
        mcp_exposed=False,
        assistant_definition=_assistant_definition("find_person_communications"),
    ),
    ToolSpec(
        name="confirm_person_identity",
        permission=ToolPermission.ANNOTATE,
        input_model=PersonIdentityFeedbackInput,
        service_method="confirm_person_identity",
        assistant_exposed=True,
        mcp_exposed=False,
        assistant_definition=_assistant_definition("confirm_person_identity"),
    ),
    ToolSpec(
        name="reject_person_identity",
        permission=ToolPermission.ANNOTATE,
        input_model=PersonIdentityFeedbackInput,
        service_method="reject_person_identity",
        assistant_exposed=True,
        mcp_exposed=False,
        assistant_definition=_assistant_definition("reject_person_identity"),
    ),
    ToolSpec(
        name="retract_person_identity_feedback",
        permission=ToolPermission.ANNOTATE,
        input_model=PersonIdentityFeedbackInput,
        service_method="retract_person_identity_feedback",
        assistant_exposed=True,
        mcp_exposed=False,
        assistant_definition=_assistant_definition("retract_person_identity_feedback"),
    ),
    ToolSpec(
        name="set_inbox_review_marker",
        permission=ToolPermission.ANNOTATE,
        input_model=SetInboxReviewMarkerInput,
        service_method="set_inbox_review_marker",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("set_inbox_review_marker"),
    ),
    ToolSpec(
        name="clear_inbox_review_marker",
        permission=ToolPermission.ANNOTATE,
        input_model=None,
        service_method="clear_inbox_review_marker",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("clear_inbox_review_marker"),
    ),
    ToolSpec(
        name="create_label",
        permission=ToolPermission.INTERNAL_WRITE,
        input_model=CreateLabelInput,
        service_method="create_label",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("create_label"),
        prepare_method="prepare_create_label",
        execution_input_model=CreateLabelCanonicalInput,
    ),
    ToolSpec(
        name="rename_label",
        permission=ToolPermission.INTERNAL_WRITE,
        input_model=RenameLabelInput,
        service_method="rename_label",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("rename_label"),
        prepare_method="prepare_rename_label",
        execution_input_model=RenameLabelCanonicalInput,
    ),
    ToolSpec(
        name="assign_label",
        permission=ToolPermission.ANNOTATE,
        input_model=AssignLabelInput,
        service_method="assign_label",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("assign_label"),
    ),
    ToolSpec(
        name="remove_label",
        permission=ToolPermission.ANNOTATE,
        input_model=RemoveLabelInput,
        service_method="remove_label",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("remove_label"),
    ),
    ToolSpec(
        name="delete_label",
        permission=ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
        input_model=DeleteLabelInput,
        service_method="delete_label",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("delete_label"),
    ),
    ToolSpec(
        name="create_task",
        permission=ToolPermission.INTERNAL_WRITE,
        input_model=CreateTaskInput,
        service_method="create_task",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("create_task"),
    ),
    ToolSpec(
        name="update_task",
        permission=ToolPermission.INTERNAL_WRITE,
        input_model=UpdateTaskInput,
        service_method="update_task",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("update_task"),
    ),
    ToolSpec(
        name="set_task_status",
        permission=ToolPermission.INTERNAL_WRITE,
        input_model=SetTaskStatusInput,
        service_method="set_task_status",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("set_task_status"),
    ),
    ToolSpec(
        name="delete_task",
        permission=ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
        input_model=DeleteTaskInput,
        service_method="delete_task",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("delete_task"),
    ),
    ToolSpec(
        name="link_objects",
        permission=ToolPermission.INTERNAL_WRITE,
        input_model=LinkObjectsInput,
        service_method="link_objects",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("link_objects"),
    ),
    ToolSpec(
        name="remove_relation",
        permission=ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
        input_model=RemoveRelationInput,
        service_method="remove_relation",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("remove_relation"),
    ),
    ToolSpec(
        name="get_today",
        permission=ToolPermission.READ,
        input_model=None,
        service_method="get_today",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("get_today"),
    ),
    ToolSpec(
        name="create_scheduled_activity",
        permission=ToolPermission.INTERNAL_WRITE,
        input_model=CreateScheduledActivityInput,
        service_method="create_scheduled_activity",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("create_scheduled_activity"),
        prepare_method="prepare_create_scheduled_activity",
        execution_input_model=CreateScheduledActivityCanonicalInput,
    ),
    ToolSpec(
        name="create_recurring_scheduled_activity",
        permission=ToolPermission.INTERNAL_WRITE,
        input_model=CreateRecurringScheduledActivityInput,
        service_method="create_recurring_scheduled_activity",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("create_recurring_scheduled_activity"),
        prepare_method="prepare_create_recurring_scheduled_activity",
        execution_input_model=CreateRecurringScheduledActivityCanonicalInput,
    ),
    ToolSpec(
        name="cancel_scheduled_activity",
        permission=ToolPermission.INTERNAL_WRITE,
        input_model=CancelScheduledActivityInput,
        service_method="cancel_scheduled_activity",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("cancel_scheduled_activity"),
    ),
    ToolSpec(
        name="create_calendar_event",
        permission=ToolPermission.EXTERNAL_WRITE,
        input_model=CreateCalendarEventInput,
        service_method="create_calendar_event",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("create_calendar_event"),
        prepare_method="prepare_create_calendar_event",
        execution_input_model=CreateCalendarEventCanonicalInput,
    ),
    ToolSpec(
        name="send_email",
        permission=ToolPermission.COMMUNICATE,
        input_model=SendEmailInput,
        service_method="send_email",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("send_email"),
        prepare_method="prepare_send_email",
        execution_input_model=SendEmailCanonicalInput,
    ),
    ToolSpec(
        name="send_message",
        permission=ToolPermission.COMMUNICATE,
        input_model=SendMessageInput,
        service_method="send_message",
        assistant_exposed=True,
        mcp_exposed=True,
        assistant_definition=_assistant_definition("send_message"),
        prepare_method="prepare_send_message",
        execution_input_model=SendMessageCanonicalInput,
    ),
    ToolSpec(
        name="edit_message",
        permission=ToolPermission.COMMUNICATE,
        input_model=TelegramMtprotoEditInput,
        service_method="edit_message",
        assistant_exposed=True,
        mcp_exposed=False,
        assistant_definition=_assistant_definition("edit_message"),
        prepare_method="prepare_edit_message",
        execution_input_model=TelegramMtprotoEditCanonicalInput,
    ),
    ToolSpec(
        name="delete_message",
        permission=ToolPermission.COMMUNICATE,
        input_model=TelegramMtprotoDeleteInput,
        service_method="delete_message",
        assistant_exposed=True,
        mcp_exposed=False,
        assistant_definition=_assistant_definition("delete_message"),
        prepare_method="prepare_delete_message",
        execution_input_model=TelegramMtprotoDeleteCanonicalInput,
    ),
    ToolSpec(
        name="mark_message_read",
        permission=ToolPermission.COMMUNICATE,
        input_model=TelegramMtprotoMarkReadInput,
        service_method="mark_message_read",
        assistant_exposed=True,
        mcp_exposed=False,
        assistant_definition=_assistant_definition("mark_message_read"),
        prepare_method="prepare_mark_message_read",
        execution_input_model=TelegramMtprotoMarkReadCanonicalInput,
    ),
)

TOOL_REGISTRY: dict[str, ToolSpec] = _build_tool_registry(TOOL_SPECS)

if len(TOOL_SPECS) != len(TOOL_REGISTRY):
    raise RuntimeError("tool registry size mismatch after construction")

ASSISTANT_TOOL_DEFINITIONS: list[dict] = [
    spec.assistant_definition
    for spec in TOOL_SPECS
    if spec.assistant_exposed and spec.assistant_definition is not None
]

_PROACTIVE_READ_NAME_SET = frozenset(PROACTIVE_READ_TOOL_NAMES)
PROACTIVE_TOOL_DEFINITIONS: list[dict] = [
    TOOL_REGISTRY[name].assistant_definition
    for name in PROACTIVE_READ_TOOL_NAMES
    if TOOL_REGISTRY[name].assistant_definition is not None
]
if {item["name"] for item in PROACTIVE_TOOL_DEFINITIONS} != _PROACTIVE_READ_NAME_SET:
    raise RuntimeError("proactive tool definitions must match the read-only allowlist")

MCP_TOOL_NAMES: frozenset[str] = frozenset(
    spec.name for spec in TOOL_SPECS if spec.mcp_exposed
)


def get_tool_spec(tool_name: str) -> ToolSpec | None:
    return TOOL_REGISTRY.get(tool_name)


def registered_tool_names() -> frozenset[str]:
    return frozenset(TOOL_REGISTRY.keys())


def validate_tool_arguments(
    spec: ToolSpec,
    arguments: dict[str, Any],
    *,
    model: type[BaseModel] | None = None,
) -> dict[str, Any]:
    input_model = spec.input_model if model is None else model
    if input_model is None:
        return {}
    validated = input_model.model_validate(arguments)
    return validated.model_dump(mode="json", exclude_unset=True)


def prepare_registered_tool(
    tools: DomainToolService,
    spec: ToolSpec,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    prepare_method = getattr(spec, "prepare_method", None)
    if not prepare_method:
        return arguments
    method: Callable[..., BaseModel | dict[str, Any]] = getattr(tools, prepare_method)
    if spec.input_model is None:
        prepared = method()
    else:
        prepared = method(spec.input_model.model_validate(arguments))
    if isinstance(prepared, BaseModel):
        return prepared.model_dump(mode="json")
    return prepared


def execute_registered_tool(
    tools: DomainToolService,
    spec: ToolSpec,
    arguments: dict[str, Any],
) -> BaseModel:
    method: Callable[..., BaseModel] = getattr(tools, spec.service_method)
    execution_model = getattr(spec, "execution_input_model", None) or spec.input_model
    if execution_model is None:
        return method()
    validated = execution_model.model_validate(arguments)
    return method(validated)


def dispatch_registered_tool(
    tools: DomainToolService,
    tool_name: str,
    arguments: dict[str, Any],
) -> BaseModel:
    spec = get_tool_spec(tool_name)
    if spec is None:
        raise ToolError(f"unknown tool: {tool_name}")
    return execute_registered_tool(tools, spec, arguments)
