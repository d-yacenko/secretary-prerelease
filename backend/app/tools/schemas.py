import re
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.schemas import ContextItem, EdgeOut, NotificationOut, ObjectOut

MAX_CONTEXT_CHARS = 12000
DEFAULT_CONTEXT_CHARS = 8000
MAX_TASK_EVIDENCE_IDS = 8


class ToolError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ToolResult(BaseModel):
    success: bool
    tool_name: str
    error: str | None = None


QuerySortBy = Literal[
    "due_at",
    "start_at",
    "occurred_at",
    "created_at",
    "updated_at",
    "title",
]
QuerySortOrder = Literal["asc", "desc"]


class QueryObjectsInput(BaseModel):
    kinds: list[str] = Field(default_factory=list, max_length=8)
    providers: list[str] = Field(default_factory=list, max_length=8)
    statuses: list[str] = Field(default_factory=list, max_length=8)
    states: list[str] = Field(default_factory=list, max_length=4)
    due_from: datetime | None = None
    due_to: datetime | None = None
    start_from: datetime | None = None
    start_to: datetime | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    label_ids: list[UUID] = Field(default_factory=list, max_length=8)
    label_match: Literal["all", "any"] = "all"
    sort_by: QuerySortBy = "created_at"
    sort_order: QuerySortOrder = "desc"
    limit: int = Field(default=20, ge=1, le=50)


class QueryObjectItemOut(BaseModel):
    object_id: UUID
    title: str
    kind: str
    provider: str | None = None
    state: str
    status: str | None = None
    due_at: datetime | None = None
    start_at: datetime | None = None
    occurred_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class QueryObjectsOutput(BaseModel):
    objects: list[QueryObjectItemOut]


class SearchObjectsInput(BaseModel):
    query: str = Field(min_length=1)
    kind: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class SearchObjectsOutput(BaseModel):
    objects: list[ObjectOut]


class RetrieveInput(BaseModel):
    query: str = Field(min_length=1)
    kind: str | None = None
    time_scope: str = Field(default="auto")
    date_from: datetime | None = None
    date_to: datetime | None = None
    limit: int = Field(default=5, ge=1, le=5)


class RetrievalHitOut(BaseModel):
    object_id: UUID
    title: str
    kind: str
    provider: str | None = None
    state: str
    status: str | None = None
    occurred_at: datetime | None = None
    relevance: float
    reasons: list[str]
    excerpt: str


class RetrieveOutput(BaseModel):
    hits: list[RetrievalHitOut]
    time_scope_used: str
    horizon_days: int | None = None
    candidate_count: int = 0
    retrieval_mode: str = "strict"
    query_atom_count: int = 0
    selected_atom_count: int = 0


class GetObjectInput(BaseModel):
    object_id: UUID


class GetObjectOutput(BaseModel):
    object: ObjectOut


class GetContextInput(BaseModel):
    object_id: UUID | None = None
    query: str | None = None
    max_chars: int = Field(default=DEFAULT_CONTEXT_CHARS, ge=1, le=MAX_CONTEXT_CHARS)


class GetContextOutput(BaseModel):
    items: list[ContextItem]
    total_chars: int
    truncated: bool


class ListNeighborsInput(BaseModel):
    object_id: UUID
    limit: int | None = Field(default=None, ge=1, le=100)


class NeighborItem(BaseModel):
    object: ObjectOut
    edge: EdgeOut
    direction: str


class ListNeighborsOutput(BaseModel):
    object_id: UUID
    neighbors: list[NeighborItem]


class CreateTaskInput(BaseModel):
    title: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    body: str | None = None
    due_at: datetime | None = None
    evidence_object_ids: list[UUID] = Field(default_factory=list, max_length=MAX_TASK_EVIDENCE_IDS)


class CreateTaskOutput(BaseModel):
    object: ObjectOut


class UpdateTaskInput(BaseModel):
    object_id: UUID
    title: str | None = Field(default=None, min_length=1)
    body: str | None = None
    due_at: datetime | None = None
    evidence_object_ids: list[UUID] = Field(default_factory=list, max_length=MAX_TASK_EVIDENCE_IDS)

    @model_validator(mode="after")
    def reject_invalid_title(self) -> Self:
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title must be a non-empty string when provided")
        return self


class UpdateTaskOutput(BaseModel):
    object: ObjectOut
    changed: bool = False
    evidence_edges_created: int = 0
    evidence_added_object_ids: list[UUID] = Field(default_factory=list)
    evidence_already_linked_object_ids: list[UUID] = Field(default_factory=list)


SetTaskStatusValue = Literal["open", "in_progress", "done", "cancelled", "archived"]


class SetTaskStatusInput(BaseModel):
    object_id: UUID
    status: SetTaskStatusValue


class SetTaskStatusOutput(BaseModel):
    object: ObjectOut
    changed: bool = False
    previous_status: str | None = None
    new_status: str


class DeleteTaskInput(BaseModel):
    object_id: UUID


class DeleteTaskOutput(BaseModel):
    object: ObjectOut
    changed: bool = False
    previous_status: str | None = None
    new_status: str


class LinkObjectsInput(BaseModel):
    source_id: UUID
    target_id: UUID
    relation_type: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class LinkObjectsOutput(BaseModel):
    edge: EdgeOut
    created: bool = True


class RemoveRelationInput(BaseModel):
    edge_id: UUID


class RemoveRelationOutput(BaseModel):
    edge: EdgeOut
    changed: bool = False
    previous_state: str
    new_state: str


class GetTodayOutput(BaseModel):
    datetime: datetime
    timezone: str


class ListNotificationsInput(BaseModel):
    status: str | None = None
    limit: int = Field(default=50, ge=1, le=100)


class ListNotificationsOutput(BaseModel):
    notifications: list[NotificationOut]


class ListLabelsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=100, ge=1, le=200)


class LabelItemOut(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    object_count: int = 0


class ListLabelsOutput(BaseModel):
    labels: list[LabelItemOut]


class CreateLabelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


class CreateLabelCanonicalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)


class CreateLabelOutput(BaseModel):
    label: LabelItemOut
    created: bool


class RenameLabelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_id: UUID
    name: str


class RenameLabelCanonicalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_id: UUID
    name: str = Field(min_length=1, max_length=80)


class RenameLabelOutput(BaseModel):
    label: LabelItemOut
    changed: bool


class DeleteLabelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_id: UUID


class DeleteLabelOutput(BaseModel):
    label: LabelItemOut
    changed: bool


class AssignLabelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: UUID
    label_id: UUID


class AssignLabelOutput(BaseModel):
    object_id: UUID
    label_id: UUID
    created: bool


class RemoveLabelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: UUID
    label_id: UUID


class RemoveLabelOutput(BaseModel):
    object_id: UUID
    label_id: UUID
    changed: bool


class ListInboxSinceReviewMarkerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: Literal["inspect", "review"] = "inspect"
    limit: int = Field(default=20, ge=1, le=50)
    cursor: str | None = None

    @field_validator("cursor")
    @classmethod
    def _empty_cursor(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class InboxSinceReviewMarkerItemOut(BaseModel):
    object_id: UUID
    kind: str
    provider: str | None = None
    title: str | None = None
    feed_at: datetime
    excerpt: str | None = None


class InboxReviewStackOut(BaseModel):
    stack_id: str
    fingerprint: str
    object_ids: list[UUID]
    provider: str | None = None
    conversation_label: str
    message_count: int
    start_at: datetime
    end_at: datetime
    summary: str | None = None
    fallback_summary: str
    summary_status: str


class InboxReviewCompactItemOut(BaseModel):
    type: Literal["stack", "singleton"]
    object_id: UUID | None = None
    kind: str | None = None
    provider: str | None = None
    title: str | None = None
    feed_at: datetime | None = None
    excerpt: str | None = None
    stack: InboxReviewStackOut | None = None
    narration: str | None = None


class ListInboxSinceReviewMarkerOutput(BaseModel):
    marker_present: bool
    marker_not_set: bool
    purpose: Literal["inspect", "review"] = "inspect"
    anchor_object_id: UUID | None = None
    anchor_feed_at: datetime | None = None
    snapshot_top_object_id: UUID | None = None
    snapshot_top_feed_at: datetime | None = None
    total_count: int = 0
    returned_count: int = 0
    remaining_count: int = 0
    conversation_count: int | None = None
    page_conversation_count: int = 0
    conversation_count_exact: bool = False
    items: list[InboxSinceReviewMarkerItemOut]
    compact_items: list[InboxReviewCompactItemOut] = Field(default_factory=list)
    has_more: bool
    next_cursor: str | None = None
    message: str | None = None


class ListConversationMembersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: UUID
    limit: int = Field(default=20, ge=1, le=50)
    cursor: str | None = None

    @field_validator("cursor")
    @classmethod
    def _empty_members_cursor(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ConversationMemberOut(BaseModel):
    object_id: UUID
    occurred_at: datetime | None = None
    feed_at: datetime
    sender: str | None = None
    title: str | None = None
    excerpt: str | None = None
    media_type: str | None = None
    narration: str


class ListConversationMembersOutput(BaseModel):
    object_id: UUID
    provider: str
    conversation_label: str
    stack_fingerprint: str
    total_member_count: int
    returned_count: int
    remaining_count: int
    members: list[ConversationMemberOut]
    has_more: bool
    next_cursor: str | None = None
    message: str | None = None


class SetInboxReviewMarkerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    after_object_id: UUID


class SetInboxReviewMarkerOutput(BaseModel):
    anchor_object_id: UUID
    anchor_feed_at: datetime
    updated_at: datetime


class ClearInboxReviewMarkerOutput(BaseModel):
    changed: bool


MAX_CALENDAR_EVENT_SUMMARY_CHARS = 300
MAX_CALENDAR_EVENT_DESCRIPTION_CHARS = 4000
MAX_CALENDAR_EVENT_LOCATION_CHARS = 500


def _strip_optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return value  # type: ignore[return-value]
    stripped = value.strip()
    return stripped or None


ExternalActionProvider = Literal["google", "yandex"]


def _normalize_provider(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip().lower()
        return stripped or None
    return value


class CreateCalendarEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=MAX_CALENDAR_EVENT_SUMMARY_CHARS)
    start_at: datetime
    end_at: datetime
    description: str | None = Field(default=None, max_length=MAX_CALENDAR_EVENT_DESCRIPTION_CHARS)
    location: str | None = Field(default=None, max_length=MAX_CALENDAR_EVENT_LOCATION_CHARS)
    account_email: str | None = None
    provider: ExternalActionProvider | None = None

    @field_validator("summary", mode="before")
    @classmethod
    def _strip_summary(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("description", "location", "account_email", mode="before")
    @classmethod
    def _strip_optional(cls, value: object) -> object:
        return _strip_optional_text(value)

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> object:
        return _normalize_provider(value)

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class CreateCalendarEventCanonicalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=MAX_CALENDAR_EVENT_SUMMARY_CHARS)
    start_at: datetime
    end_at: datetime
    description: str | None = Field(default=None, max_length=MAX_CALENDAR_EVENT_DESCRIPTION_CHARS)
    location: str | None = Field(default=None, max_length=MAX_CALENDAR_EVENT_LOCATION_CHARS)
    account_email: str = Field(min_length=1)
    calendar_id: Literal["primary"] = "primary"
    operation_id: str = Field(min_length=5, max_length=1024)
    provider: ExternalActionProvider | None = None
    calendar_href: str | None = Field(default=None, max_length=2000)
    calendar_label: str | None = Field(default=None, max_length=300)

    @field_validator("summary", "account_email", "operation_id", mode="before")
    @classmethod
    def _strip_required(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("description", "location", "calendar_href", "calendar_label", mode="before")
    @classmethod
    def _strip_optional(cls, value: object) -> object:
        return _strip_optional_text(value)

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> object:
        return _normalize_provider(value)

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class CreateCalendarEventOutput(BaseModel):
    provider: Literal["google_calendar", "yandex_calendar"] = "google_calendar"
    account_email: str
    calendar_id: Literal["primary"] = "primary"
    event_id: str
    summary: str
    start_at: datetime
    end_at: datetime
    canonical_uri: str | None = None
    changed: bool


MAX_EMAIL_TO_RECIPIENTS = 10
MAX_EMAIL_SUBJECT_CHARS = 300
MAX_EMAIL_BODY_CHARS = 20_000
_EMAIL_ADDRESS_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _reject_crlf(value: object, field_name: str) -> object:
    if isinstance(value, str) and ("\r" in value or "\n" in value):
        raise ValueError(f"{field_name} must not contain CR/LF")
    return value


def _normalize_email_address(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid email address")  # noqa: TRY004
    if "\r" in value or "\n" in value:
        raise ValueError("invalid email address")
    stripped = value.strip()
    if not stripped or not _EMAIL_ADDRESS_RE.match(stripped):
        raise ValueError("invalid email address")
    return stripped


class SendEmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_email: str | None = None
    provider: ExternalActionProvider | None = None
    to: list[str] | None = Field(default=None, max_length=MAX_EMAIL_TO_RECIPIENTS)
    subject: str | None = Field(default=None, max_length=MAX_EMAIL_SUBJECT_CHARS)
    body: str = Field(min_length=1, max_length=MAX_EMAIL_BODY_CHARS)
    reply_to_object_id: UUID | None = None

    @field_validator("account_email", mode="before")
    @classmethod
    def _strip_account(cls, value: object) -> object:
        return _strip_optional_text(value)

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> object:
        return _normalize_provider(value)

    @field_validator("subject", mode="before")
    @classmethod
    def _subject_no_crlf(cls, value: object) -> object:
        value = _reject_crlf(value, "subject")
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("body", mode="before")
    @classmethod
    def _body_required(cls, value: object) -> object:
        if isinstance(value, str) and ("\r" in value or "\x00" in value):
            return value.replace("\r\n", "\n").replace("\r", "\n")
        return value

    @field_validator("to")
    @classmethod
    def _validate_to(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            normalized.append(_normalize_email_address(value=item))
        if not normalized:
            raise ValueError("at least one recipient is required")
        return normalized

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> Self:
        reply = self.reply_to_object_id is not None
        has_compose = self.to is not None or self.subject is not None
        if reply and has_compose:
            raise ValueError("reply mode must not include to or subject")
        if not reply and (self.to is None or self.subject is None):
            raise ValueError("compose mode requires to and subject")
        return self


class SendEmailCanonicalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_email: str = Field(min_length=1)
    to: list[str] = Field(min_length=1, max_length=MAX_EMAIL_TO_RECIPIENTS)
    subject: str = Field(min_length=1, max_length=MAX_EMAIL_SUBJECT_CHARS)
    body: str = Field(min_length=1, max_length=MAX_EMAIL_BODY_CHARS)
    operation_id: str = Field(min_length=5, max_length=1024)
    rfc822_message_id: str = Field(min_length=5, max_length=200)
    provider: ExternalActionProvider | None = None
    reply_to_object_id: UUID | None = None
    in_reply_to: str | None = None
    references: str | None = None
    gmail_thread_id: str | None = None

    @field_validator("account_email", "operation_id", "rfc822_message_id", mode="before")
    @classmethod
    def _strip_required(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> object:
        return _normalize_provider(value)

    @field_validator("subject", mode="before")
    @classmethod
    def _subject_no_crlf(cls, value: object) -> object:
        value = _reject_crlf(value, "subject")
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("to")
    @classmethod
    def _validate_to(cls, value: list[str]) -> list[str]:
        return [_normalize_email_address(item) for item in value]


class SendEmailOutput(BaseModel):
    provider: Literal["gmail", "yandex"] = "gmail"
    account_email: str
    to: list[str]
    subject: str
    provider_message_id: str | None = None
    delivery_status: Literal["sent", "already_sent", "uncertain", "failed"]
    changed: bool
    sent_copy_status: Literal["stored", "already_present", "unconfirmed"] | None = None


SendMessageMode = Literal["compose", "reply"]
SendMessageDeliveryStatus = Literal["sent", "already_sent", "uncertain", "failed"]
SendMessageProvider = Literal["mattermost", "telegram", "teams"]
_LEGACY_MATTERMOST_ROUTE_KEYS = (
    "account_id",
    "server_url",
    "channel_id",
    "channel_type",
    "channel_name",
    "channel_display_name",
    "source_post_id",
    "root_id",
    "pending_post_id",
)


def _normalize_message_body(value: object) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in normalized:
        raise ValueError("body must not contain NUL")
    if not normalized.strip():
        raise ValueError("body must not be empty")
    from app.connectors.mattermost.constants import MAX_MESSAGE_BODY_CHARS

    if len(normalized) > MAX_MESSAGE_BODY_CHARS:
        raise ValueError("body exceeds maximum length")
    return normalized


class SendMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str
    conversation_object_id: UUID | None = None
    reply_to_object_id: UUID | None = None

    @field_validator("body", mode="before")
    @classmethod
    def _normalize_body(cls, value: object) -> object:
        return _normalize_message_body(value)

    @model_validator(mode="after")
    def _exactly_one_anchor(self) -> Self:
        has_conversation = self.conversation_object_id is not None
        has_reply = self.reply_to_object_id is not None
        if has_conversation == has_reply:
            raise ValueError(
                "exactly one of conversation_object_id or reply_to_object_id is required"
            )
        return self


class MattermostSendRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    server_url: str = Field(min_length=1)
    channel_id: str = Field(min_length=1)
    channel_type: str | None = None
    channel_name: str | None = None
    channel_display_name: str | None = None
    source_post_id: str = Field(min_length=1)
    root_id: str | None = None
    pending_post_id: str = Field(min_length=5, max_length=200)

    @field_validator(
        "server_url",
        "channel_id",
        "source_post_id",
        "pending_post_id",
        mode="before",
    )
    @classmethod
    def _strip_required(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator(
        "root_id", "channel_type", "channel_name", "channel_display_name", mode="before"
    )
    @classmethod
    def _strip_optional(cls, value: object) -> object:
        return _strip_optional_text(value)


class TelegramSendRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    business_connection_id: str = Field(min_length=1)
    business_user_id: str = Field(min_length=1)
    chat_id: str = Field(min_length=1)
    source_message_id: str = Field(min_length=1)
    reply_to_message_id: str | None = None
    chat_display_name: str | None = None
    chat_username: str | None = None

    @field_validator(
        "business_connection_id",
        "business_user_id",
        "chat_id",
        "source_message_id",
        mode="before",
    )
    @classmethod
    def _strip_required(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("reply_to_message_id", "chat_display_name", "chat_username", mode="before")
    @classmethod
    def _strip_optional(cls, value: object) -> object:
        return _strip_optional_text(value)


class TelegramMtprotoSendRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    peer_id: int
    source_message_id: int | None = None
    reply_to_message_id: int | None = None
    peer_title: str | None = None

    @field_validator("peer_title", mode="before")
    @classmethod
    def _strip_title(cls, value: object) -> object:
        return _strip_optional_text(value)

    @field_validator("peer_id", "source_message_id", "reply_to_message_id")
    @classmethod
    def _positive_provider_id(cls, value: int | None, info) -> int | None:
        if value is None:
            return value
        if isinstance(value, bool) or value == 0:
            raise ValueError(f"{info.field_name} must be nonzero")
        if info.field_name != "peer_id" and value <= 0:
            raise ValueError(f"{info.field_name} must be positive")
        if value < -(2**63) or value > 2**63 - 1:
            raise ValueError(f"{info.field_name} is out of range")
        return value


class TeamsSendRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    tenant_id: str = Field(min_length=1)
    teams_user_id: str = Field(min_length=1)
    chat_id: str = Field(min_length=1)
    chat_type: str = Field(min_length=1)
    source_message_id: str = Field(min_length=1)
    quoted_message_id: str | None = None
    chat_display_title: str | None = None

    @field_validator(
        "tenant_id",
        "teams_user_id",
        "chat_id",
        "chat_type",
        "source_message_id",
        mode="before",
    )
    @classmethod
    def _strip_required(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("quoted_message_id", "chat_display_title", mode="before")
    @classmethod
    def _strip_optional(cls, value: object) -> object:
        return _strip_optional_text(value)


def _legacy_mattermost_route_from_flat(data: dict) -> dict:
    route = {}
    for key in _LEGACY_MATTERMOST_ROUTE_KEYS:
        if key in data:
            route[key] = data[key]
    return route


class SendMessageCanonicalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: SendMessageProvider
    mode: SendMessageMode
    anchor_object_id: UUID
    body: str
    operation_id: str = Field(min_length=5, max_length=1024)
    route: MattermostSendRoute | TelegramSendRoute | TelegramMtprotoSendRoute | TeamsSendRoute

    @model_validator(mode="before")
    @classmethod
    def _compat_legacy_mattermost(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if "route" in data:
            return data
        provider = data.get("provider", "mattermost")
        if provider != "mattermost":
            return data
        if "pending_post_id" not in data and "channel_id" not in data:
            return data
        lifted = {
            key: value for key, value in data.items() if key not in _LEGACY_MATTERMOST_ROUTE_KEYS
        }
        lifted["provider"] = "mattermost"
        lifted["route"] = _legacy_mattermost_route_from_flat(data)
        return lifted

    @field_validator("operation_id", mode="before")
    @classmethod
    def _strip_operation_id(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("body", mode="before")
    @classmethod
    def _normalize_body(cls, value: object) -> object:
        return _normalize_message_body(value)

    @model_validator(mode="after")
    def _provider_route_invariants(self) -> Self:
        if self.provider == "mattermost":
            if not isinstance(self.route, MattermostSendRoute):
                raise ValueError("mattermost send_message requires a Mattermost route")
            expected = f"secretary:{self.operation_id.replace('-', '').lower()}"
            if self.route.pending_post_id != expected:
                raise ValueError("pending_post_id does not match operation_id")
            if self.mode == "compose" and self.route.root_id is not None:
                raise ValueError("compose mode must not include root_id")
            return self
        if self.provider == "telegram":
            if not isinstance(self.route, (TelegramSendRoute, TelegramMtprotoSendRoute)):
                raise ValueError("telegram send_message requires a Telegram route")
            if self.mode == "compose" and self.route.reply_to_message_id is not None:
                raise ValueError("compose mode must not include reply_to_message_id")
            if self.mode == "reply" and not self.route.reply_to_message_id:
                raise ValueError("reply mode requires reply_to_message_id")
            return self
        if self.provider == "teams":
            if not isinstance(self.route, TeamsSendRoute):
                raise ValueError("teams send_message requires a Teams route")
            if self.route.chat_type not in {"oneOnOne", "group"}:
                raise ValueError("unsupported Teams chat type")
            if self.mode == "compose" and self.route.quoted_message_id is not None:
                raise ValueError("compose mode must not include quoted_message_id")
            if self.mode == "reply" and not self.route.quoted_message_id:
                raise ValueError("reply mode requires quoted_message_id")
            return self
        raise ValueError("unsupported send_message provider")

    @property
    def mattermost_route(self) -> MattermostSendRoute:
        if not isinstance(self.route, MattermostSendRoute):
            raise TypeError("send_message route is not Mattermost")
        return self.route

    @property
    def telegram_route(self) -> TelegramSendRoute:
        if not isinstance(self.route, TelegramSendRoute):
            raise TypeError("send_message route is not Telegram")
        return self.route

    @property
    def telegram_mtproto_route(self) -> TelegramMtprotoSendRoute:
        if not isinstance(self.route, TelegramMtprotoSendRoute):
            raise TypeError("send_message route is not Telegram MTProto")
        return self.route

    @property
    def teams_route(self) -> TeamsSendRoute:
        if not isinstance(self.route, TeamsSendRoute):
            raise TypeError("send_message route is not Teams")
        return self.route

    @property
    def account_id(self) -> UUID:
        return self.route.account_id

    @property
    def server_url(self) -> str:
        return self.mattermost_route.server_url

    @property
    def channel_id(self) -> str:
        return self.mattermost_route.channel_id

    @property
    def channel_type(self) -> str | None:
        return self.mattermost_route.channel_type

    @property
    def channel_name(self) -> str | None:
        return self.mattermost_route.channel_name

    @property
    def channel_display_name(self) -> str | None:
        return self.mattermost_route.channel_display_name

    @property
    def source_post_id(self) -> str:
        return self.mattermost_route.source_post_id

    @property
    def root_id(self) -> str | None:
        return self.mattermost_route.root_id

    @property
    def pending_post_id(self) -> str:
        return self.mattermost_route.pending_post_id


class SendMessageOutput(BaseModel):
    provider: SendMessageProvider
    mode: SendMessageMode
    provider_message_id: str | None = None
    object_id: UUID | None = None
    delivery_status: SendMessageDeliveryStatus
    changed: bool


class TelegramMtprotoObjectMutationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: UUID


class TelegramMtprotoDeleteInput(TelegramMtprotoObjectMutationInput):
    pass


class TelegramMtprotoMarkReadInput(TelegramMtprotoObjectMutationInput):
    pass


class TelegramMtprotoEditInput(TelegramMtprotoObjectMutationInput):
    body: str

    @field_validator("body", mode="before")
    @classmethod
    def _normalize_edit_body(cls, value: object) -> object:
        return _normalize_message_body(value)


class TelegramMtprotoEditRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    peer_id: int
    message_id: int
    body: str
    peer_title: str | None = None


class TelegramMtprotoDeleteRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    peer_id: int
    message_id: int
    peer_title: str | None = None


class TelegramMtprotoMarkReadRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    peer_id: int
    max_message_id: int
    peer_title: str | None = None


class TelegramMtprotoEditCanonicalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(min_length=5, max_length=1024)
    object_id: UUID
    route: TelegramMtprotoEditRoute


class TelegramMtprotoDeleteCanonicalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(min_length=5, max_length=1024)
    object_id: UUID
    route: TelegramMtprotoDeleteRoute


class TelegramMtprotoMarkReadCanonicalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(min_length=5, max_length=1024)
    object_id: UUID
    route: TelegramMtprotoMarkReadRoute


TelegramMtprotoMutationStatus = Literal["succeeded", "already_succeeded", "uncertain", "failed"]


class TelegramMtprotoMutationOutput(BaseModel):
    operation: Literal["edit", "delete", "mark_read"]
    object_id: UUID
    status: TelegramMtprotoMutationStatus
    changed: bool


MAX_SCHEDULED_ACTIVITY_TITLE_CHARS = 300
MAX_SCHEDULED_ACTIVITY_BODY_CHARS = 5000
ScheduledActivityPriority = Literal["low", "normal", "high", "urgent"]
ScheduledActivityWeekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
RecurringScheduleKind = Literal["daily", "weekly"]


class CreateScheduledActivityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_SCHEDULED_ACTIVITY_TITLE_CHARS)
    body: str | None = Field(default=None, max_length=MAX_SCHEDULED_ACTIVITY_BODY_CHARS)
    run_at: datetime
    priority: ScheduledActivityPriority = "normal"

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("body", mode="before")
    @classmethod
    def _strip_body(cls, value: object) -> object:
        return _strip_optional_text(value)


class CreateScheduledActivityCanonicalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_SCHEDULED_ACTIVITY_TITLE_CHARS)
    body: str | None = Field(default=None, max_length=MAX_SCHEDULED_ACTIVITY_BODY_CHARS)
    run_at: datetime
    priority: ScheduledActivityPriority = "normal"

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("body", mode="before")
    @classmethod
    def _strip_body(cls, value: object) -> object:
        return _strip_optional_text(value)


class CreateScheduledActivityOutput(BaseModel):
    object: ObjectOut


class CreateRecurringScheduledActivityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_SCHEDULED_ACTIVITY_TITLE_CHARS)
    body: str | None = Field(default=None, max_length=MAX_SCHEDULED_ACTIVITY_BODY_CHARS)
    schedule_kind: RecurringScheduleKind
    local_time: str
    timezone: str | None = None
    weekdays: list[ScheduledActivityWeekday] | None = None
    priority: ScheduledActivityPriority = "normal"

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("body", mode="before")
    @classmethod
    def _strip_body(cls, value: object) -> object:
        return _strip_optional_text(value)

    @field_validator("timezone", mode="before")
    @classmethod
    def _strip_timezone(cls, value: object) -> object:
        return _strip_optional_text(value)

    @field_validator("local_time")
    @classmethod
    def _validate_local_time(cls, value: str) -> str:
        from app.domain.recurrence import parse_local_time

        try:
            parse_local_time(value)
        except ValueError as exc:
            raise ValueError("local_time must be HH:MM") from exc
        return value

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from app.domain.recurrence import require_iana_timezone

        try:
            return require_iana_timezone(value)
        except ValueError as exc:
            raise ValueError("invalid timezone") from exc

    @model_validator(mode="after")
    def _validate_weekdays(self) -> Self:
        from app.domain.recurrence import canonicalize_weekdays

        try:
            weekdays = canonicalize_weekdays(
                list(self.weekdays) if self.weekdays is not None else None,
                required=self.schedule_kind == "weekly",
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        if self.schedule_kind == "weekly":
            self.weekdays = list(weekdays)
        else:
            self.weekdays = None
        return self


class CreateRecurringScheduledActivityCanonicalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_SCHEDULED_ACTIVITY_TITLE_CHARS)
    body: str | None = Field(default=None, max_length=MAX_SCHEDULED_ACTIVITY_BODY_CHARS)
    schedule_kind: RecurringScheduleKind
    local_time: str
    timezone: str
    weekdays: list[ScheduledActivityWeekday] | None = None
    priority: ScheduledActivityPriority = "normal"
    run_at: datetime

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("body", mode="before")
    @classmethod
    def _strip_body(cls, value: object) -> object:
        return _strip_optional_text(value)

    @field_validator("local_time")
    @classmethod
    def _validate_local_time(cls, value: str) -> str:
        from app.domain.recurrence import parse_local_time

        try:
            parse_local_time(value)
        except ValueError as exc:
            raise ValueError("local_time must be HH:MM") from exc
        return value

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        from app.domain.recurrence import require_iana_timezone

        try:
            return require_iana_timezone(value)
        except ValueError as exc:
            raise ValueError("invalid timezone") from exc

    @model_validator(mode="after")
    def _validate_weekdays(self) -> Self:
        from app.domain.recurrence import canonicalize_weekdays

        try:
            weekdays = canonicalize_weekdays(
                list(self.weekdays) if self.weekdays is not None else None,
                required=self.schedule_kind == "weekly",
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        if self.schedule_kind == "weekly":
            self.weekdays = list(weekdays)
        else:
            self.weekdays = None
        return self


class CancelScheduledActivityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: UUID


class CancelScheduledActivityOutput(BaseModel):
    object: ObjectOut
    changed: bool = False
    status: str
