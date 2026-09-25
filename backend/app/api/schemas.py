from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.planned_execution import validate_planned_execution_interval
from app.services.provenance import (
    Origin,
    State,
    default_object_state,
    validate_agent_proposal,
    validate_confidence,
    validate_origin,
    validate_state,
)


class ObjectCreate(BaseModel):
    kind: str
    title: str
    origin: Origin
    body: str | None = None
    provider: str | None = None
    external_id: str | None = None
    canonical_uri: str | None = None
    status: str | None = None
    state: State | None = None
    start_at: datetime | None = None
    due_at: datetime | None = None
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        validate_origin(self.origin, "object")
        state = default_object_state(self.origin, self.state)
        validate_state(state, "object")
        validate_confidence(self.confidence, "object")
        validate_agent_proposal(self.origin, state, self.confidence, "object")
        validate_planned_execution_interval(
            self.kind, self.planned_start_at, self.planned_end_at
        )
        return self


class ObjectUpdate(BaseModel):
    kind: str | None = None
    title: str | None = None
    body: str | None = None
    provider: str | None = None
    external_id: str | None = None
    canonical_uri: str | None = None
    status: str | None = None
    state: State | None = None
    start_at: datetime | None = None
    due_at: datetime | None = None
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    metadata: dict[str, Any] | None = None
    confidence: float | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> Self:
        for field in ("kind", "title", "metadata", "state"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

    @model_validator(mode="after")
    def validate_confidence_range(self) -> Self:
        if "confidence" in self.model_fields_set:
            validate_confidence(self.confidence, "object")
        if self.state is not None:
            validate_state(self.state, "object")
        return self

    @model_validator(mode="after")
    def validate_planned_interval_payload(self) -> Self:
        start_set = "planned_start_at" in self.model_fields_set
        end_set = "planned_end_at" in self.model_fields_set
        if start_set and end_set:
            kind = self.kind if "kind" in self.model_fields_set else "task"
            validate_planned_execution_interval(
                kind, self.planned_start_at, self.planned_end_at
            )
        return self


class ObjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    title: str
    body: str | None
    provider: str | None
    external_id: str | None
    canonical_uri: str | None
    status: str | None
    start_at: datetime | None
    due_at: datetime | None
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    occurred_at: datetime | None
    deleted_at: datetime | None = None
    metadata: dict[str, Any]
    origin: str
    state: str
    confidence: float | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, obj: Any) -> "ObjectOut":
        return cls(
            id=obj.id,
            kind=obj.kind,
            title=obj.title,
            body=obj.body,
            provider=obj.provider,
            external_id=obj.external_id,
            canonical_uri=obj.canonical_uri,
            status=obj.status,
            start_at=obj.start_at,
            due_at=obj.due_at,
            planned_start_at=obj.planned_start_at,
            planned_end_at=obj.planned_end_at,
            occurred_at=obj.occurred_at,
            deleted_at=obj.deleted_at,
            metadata=obj.metadata_,
            origin=obj.origin,
            state=obj.state,
            confidence=obj.confidence,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class ObjectDeleteResponse(BaseModel):
    object_id: UUID
    deleted_at: datetime
    already_deleted: bool


class EdgeCreate(BaseModel):
    source_id: UUID
    target_id: UUID
    type: str
    origin: Origin
    state: State
    confidence: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        validate_origin(self.origin, "edge")
        validate_state(self.state, "edge")
        validate_confidence(self.confidence, "edge")
        validate_agent_proposal(self.origin, self.state, self.confidence, "edge")
        return self


class EdgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID
    target_id: UUID
    type: str
    origin: str
    confidence: float | None
    state: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, edge: Any) -> "EdgeOut":
        return cls(
            id=edge.id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            type=edge.type,
            origin=edge.origin,
            confidence=edge.confidence,
            state=edge.state,
            metadata=edge.metadata_,
            created_at=edge.created_at,
            updated_at=edge.updated_at,
        )


class NeighborOut(BaseModel):
    object: ObjectOut
    edge: EdgeOut
    direction: str


class NeighborsOut(BaseModel):
    object_id: UUID
    neighbors: list[NeighborOut]


class ContextOut(BaseModel):
    object: ObjectOut
    edges: list[EdgeOut]
    neighbors: list[ObjectOut]


class ContextItem(BaseModel):
    object_id: UUID
    kind: str
    title: str
    content: str
    origin: str
    state: str
    confidence: float | None = None
    representation_kind: str | None = None
    relation_type: str | None = None
    relation_origin: str | None = None
    relation_state: str | None = None
    relation_confidence: float | None = None
    why_included: str
    canonical_uri: str | None = None


class ContextBuildResult(BaseModel):
    items: list[ContextItem]
    total_chars: int
    truncated: bool


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    body: str | None
    priority: str
    status: str
    source_object_id: UUID | None
    related_object_id: UUID | None
    result_object_id: UUID | None
    proposal: dict[str, Any]
    read_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, notification: Any) -> "NotificationOut":
        return cls(
            id=notification.id,
            title=notification.title,
            body=notification.body,
            priority=notification.priority,
            status=notification.status,
            source_object_id=notification.source_object_id,
            related_object_id=notification.related_object_id,
            result_object_id=notification.result_object_id,
            proposal=notification.proposal_,
            read_at=notification.read_at,
            created_at=notification.created_at,
            updated_at=notification.updated_at,
        )


class NotificationListOut(BaseModel):
    notifications: list[NotificationOut]


class TodayOut(BaseModel):
    date: str
    timezone: str
    day_start: datetime
    tasks: list["TodayTaskOut"]
    calendar_events: list[ObjectOut]
    notifications: list[NotificationOut]


class WeekEventOut(ObjectOut):
    all_day: bool

    @classmethod
    def from_event(cls, obj: Any) -> "WeekEventOut":
        from app.services.calendar_event_query import event_is_all_day

        base = ObjectOut.from_model(obj)
        return cls(**base.model_dump(), all_day=event_is_all_day(obj))


class WeekTemporalHintOut(BaseModel):
    id: UUID
    title: str
    start_at: datetime
    due_at: datetime | None = None
    end_precision: str
    participation: str
    primary_provider: str | None = None
    primary_kind: str | None = None
    evidence_count: int = 1
    extraction_confidence: float | None = None

    @classmethod
    def from_hint(cls, obj: Any) -> "WeekTemporalHintOut":
        from app.domain.temporal_hint import END_PRECISION_UNKNOWN
        from app.services.temporal_signals_constants import (
            METADATA_END_PRECISION,
            METADATA_EVIDENCE_COUNT,
            METADATA_EXTRACTION_CONFIDENCE,
            METADATA_PARTICIPATION,
            METADATA_PRIMARY_EVIDENCE_KIND,
            METADATA_PRIMARY_EVIDENCE_PROVIDER,
        )

        metadata = obj.metadata_ or {}
        evidence_count = metadata.get(METADATA_EVIDENCE_COUNT, 1)
        try:
            count = int(evidence_count)
        except (TypeError, ValueError):
            count = 1
        confidence = metadata.get(METADATA_EXTRACTION_CONFIDENCE, obj.confidence)
        try:
            confidence_value = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_value = None
        return cls(
            id=obj.id,
            title=obj.title,
            start_at=obj.start_at,
            due_at=obj.due_at,
            end_precision=str(metadata.get(METADATA_END_PRECISION) or END_PRECISION_UNKNOWN),
            participation=str(metadata.get(METADATA_PARTICIPATION) or ""),
            primary_provider=metadata.get(METADATA_PRIMARY_EVIDENCE_PROVIDER),
            primary_kind=metadata.get(METADATA_PRIMARY_EVIDENCE_KIND),
            evidence_count=count,
            extraction_confidence=confidence_value,
        )


class WeekScheduledWorkOut(BaseModel):
    id: UUID
    title: str
    planned_start_at: datetime
    planned_end_at: datetime
    status: str | None = None

    @classmethod
    def from_task(cls, obj: Any) -> "WeekScheduledWorkOut":
        return cls(
            id=obj.id,
            title=obj.title,
            planned_start_at=obj.planned_start_at,
            planned_end_at=obj.planned_end_at,
            status=obj.status,
        )


class WeekDayOut(BaseModel):
    date: str
    is_today: bool
    events: list[WeekEventOut]
    scheduled_work: list[WeekScheduledWorkOut] = Field(default_factory=list)
    temporal_hints: list[WeekTemporalHintOut] = Field(default_factory=list)


class WeekOut(BaseModel):
    week_start: str
    week_end: str
    timezone: str
    window_start: datetime
    window_end: datetime
    today_date: str
    is_current_week: bool
    days: list[WeekDayOut]


class AvailabilityBusyIntervalOut(BaseModel):
    start_at: datetime
    end_at: datetime
    event_ids: list[UUID]


class AvailabilityFreeIntervalOut(BaseModel):
    start_at: datetime
    end_at: datetime
    duration_minutes: int


class AvailabilityOut(BaseModel):
    timezone: str
    window_start: datetime
    window_end: datetime
    min_duration_minutes: int
    availability_complete: bool
    busy_intervals: list[AvailabilityBusyIntervalOut]
    free_intervals: list[AvailabilityFreeIntervalOut]
    unknown_end_event_ids: list[UUID]


class InboxSourceObjectOut(BaseModel):
    id: UUID
    title: str
    kind: str
    provider: str | None
    origin: str
    state: str
    status: str | None
    primary_at: datetime | None
    feed_at: datetime
    excerpt: str | None


class InboxConversationStackOut(BaseModel):
    stack_id: str
    fingerprint: str
    object_ids: list[UUID]
    display_object_ids: list[UUID]
    provider: str
    conversation_key: str
    conversation_label: str
    participants: list[str]
    message_count: int
    start_at: datetime
    end_at: datetime
    summary: str | None = None
    fallback_summary: str
    summary_status: str
    marker_side: str | None = None


class InboxConversationGroupOut(BaseModel):
    type: Literal["stack", "singleton"]
    object_id: UUID | None = None
    stack: InboxConversationStackOut | None = None


class SourceSyncStatusOut(BaseModel):
    source: str
    provider: str
    account_id: UUID
    account_label: str
    enabled: bool
    status: str
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    next_sync_at: datetime | None
    last_error: str | None
    error_kind: str | None = None
    retryable: bool = False


class InboxReviewMarkerOut(BaseModel):
    anchor_feed_at: datetime
    anchor_object_id: UUID
    updated_at: datetime


class InboxOut(BaseModel):
    unresolved_notifications: list[NotificationOut]
    recent_source_objects: list[InboxSourceObjectOut]
    source_sync_status: list[SourceSyncStatusOut]
    recent_next_cursor: str | None = None
    recent_has_more: bool = False
    review_marker: InboxReviewMarkerOut | None = None
    conversation_groups: list[InboxConversationGroupOut] = Field(default_factory=list)


class InboxFeedOut(BaseModel):
    items: list[InboxSourceObjectOut]
    next_cursor: str | None
    has_more: bool
    conversation_groups: list[InboxConversationGroupOut] = Field(default_factory=list)


class SourceStatusListOut(BaseModel):
    sources: list[SourceSyncStatusOut]


class SourceSyncTriggerOut(BaseModel):
    triggered: list[str]
    count: int


class ResourceRegisterRequest(BaseModel):
    kind: str
    title: str
    canonical_uri: str | None = None
    provider: str | None = None
    external_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    text: str | None = None
    local_path_metadata: dict[str, Any] | None = None
    ingest_content: bool = False


class ResourceRegisterOut(BaseModel):
    object_id: UUID
    status: str
    kind: str
    title: str
    canonical_uri: str | None
    provider: str | None
    external_id: str | None
    jobs_enqueued: int
    representations_created: int


class TaskPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1)
    body: str | None = None
    due_at: datetime | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one editable field must be supplied")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null or empty")
        return self


class TaskMutationResponse(BaseModel):
    object: ObjectOut
    changed: bool


class TaskStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


class TaskStatusResponse(BaseModel):
    object: ObjectOut
    changed: bool
    previous_status: str | None
    new_status: str


class SearchFacetValueOut(BaseModel):
    value: str
    count: int


class SearchFacetsOut(BaseModel):
    kinds: list[SearchFacetValueOut]
    providers: list[SearchFacetValueOut]


class GraphWorkspaceOut(BaseModel):
    root_id: UUID | None
    seed_ids: list[UUID]
    nodes: list[ObjectOut]
    edges: list[EdgeOut]
    truncated: bool


class PersonIdentityPresentation(BaseModel):
    provider: str
    identity_type: str
    display_value: str
    realm: str = ""
    canonical_value: str
    state: str
    confirmable: bool = False


class PersonRoutePresentation(BaseModel):
    provider: str
    label: str
    route_key: str


class PersonPresentation(BaseModel):
    person_id: UUID
    title: str
    salience_score: int
    identities: list[PersonIdentityPresentation]
    routes: list[PersonRoutePresentation]
    identity_conflict: bool
    open_task_count: int
    recent_communication_count: int


class PeopleWorkspaceOut(BaseModel):
    root_id: UUID | None
    seed_ids: list[UUID]
    nodes: list[ObjectOut]
    edges: list[EdgeOut]
    truncated: bool
    people: list[PersonPresentation]


class PersonIdentityCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["confirm", "reject", "retract"]
    identity_type: str
    provider: str
    realm: str = ""
    canonical_value: str


class OpenTargetOut(BaseModel):
    available: bool
    action: str
    label: str
    url: str | None = None
    device_key: str | None = None
    local_path: str | None = None
    reason: str | None = None


class RelationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    target_id: UUID
    type: str


class RelationCreateResponse(BaseModel):
    edge: EdgeOut
    created: bool


class RelationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["confirm", "reject"]


class RelationDecisionResponse(BaseModel):
    edge: EdgeOut


class TaskActorOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: UUID
    person_id: UUID
    title: str
    contact_cue: str | None = None
    edge_state: str
    edge_origin: str
    edge_confidence: float | None = None


class TaskLinkOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: UUID
    object_id: UUID
    title: str
    kind: str
    edge_state: str
    edge_origin: str
    edge_confidence: float | None = None


class TaskOperationalDependencyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    title: str
    status: str | None = None


class TaskOperationalPersonOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: UUID
    title: str


class TaskOperationalOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operational_state: Literal[
        "terminal",
        "blocked",
        "waiting",
        "delegated",
        "scheduled_later",
        "actionable",
    ]
    is_overdue: bool
    is_scheduled_later: bool
    is_planned_now: bool
    due_at: datetime | None
    planned_start_at: datetime | None
    planned_end_at: datetime | None
    blocking_dependencies: list[TaskOperationalDependencyOut]
    waiting_on: list[TaskOperationalPersonOut]
    delegated_to: list[TaskOperationalPersonOut]
    reason_codes: list[str]


def task_operational_out(projection: Any) -> TaskOperationalOut:
    return TaskOperationalOut(
        operational_state=projection.operational_state,
        is_overdue=projection.is_overdue,
        is_scheduled_later=projection.is_scheduled_later,
        is_planned_now=projection.is_planned_now,
        due_at=projection.due_at,
        planned_start_at=projection.planned_start_at,
        planned_end_at=projection.planned_end_at,
        blocking_dependencies=[
            TaskOperationalDependencyOut(
                task_id=item.task_id, title=item.title, status=item.status
            )
            for item in projection.blocking_dependencies
        ],
        waiting_on=[
            TaskOperationalPersonOut(person_id=item.person_id, title=item.title)
            for item in projection.waiting_on
        ],
        delegated_to=[
            TaskOperationalPersonOut(person_id=item.person_id, title=item.title)
            for item in projection.delegated_to
        ],
        reason_codes=list(projection.reason_codes),
    )


class TodayTaskOut(ObjectOut):
    operational: TaskOperationalOut

    @classmethod
    def from_task(cls, obj: Any, projection: Any) -> "TodayTaskOut":
        base = ObjectOut.from_model(obj)
        return cls(**base.model_dump(), operational=task_operational_out(projection))


TodayOut.model_rebuild()


class TaskProfileOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: ObjectOut
    status: str | None
    start_at: datetime | None
    due_at: datetime | None
    planned_start_at: datetime | None
    planned_end_at: datetime | None
    requested_by: list[TaskActorOut]
    delegated_to: list[TaskActorOut]
    waiting_on: list[TaskActorOut]
    involves: list[TaskActorOut]
    depends_on: list[TaskLinkOut]
    dependent_tasks: list[TaskLinkOut]
    evidence: list[TaskLinkOut]
    operational: TaskOperationalOut
    requested_by_truncated: bool = False
    delegated_to_truncated: bool = False
    waiting_on_truncated: bool = False
    involves_truncated: bool = False
    depends_on_truncated: bool = False
    dependent_tasks_truncated: bool = False
    evidence_truncated: bool = False


class TaskActorAttachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: UUID
    role: Literal["requested_by", "delegated_to", "waiting_on", "involves"]


class TaskDependencyAttachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    depends_on_task_id: UUID


class TaskEvidenceAttachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: UUID


class TaskRelationMutationResponse(BaseModel):
    edge: EdgeOut
    created: bool = False
    changed: bool = False
