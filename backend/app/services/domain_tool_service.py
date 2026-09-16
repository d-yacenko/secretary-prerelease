from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    EdgeCreate,
    EdgeOut,
    NotificationOut,
    ObjectCreate,
    ObjectOut,
)
from app.db.models import Edge, Object
from app.domain.labels import EDGE_TYPE_LABELED_WITH
from app.domain.object_visibility import is_object_tombstoned
from app.domain.task_lifecycle import (
    TASK_STATUS_DELETED,
    TASK_STATUS_OPEN,
    canonical_task_status_for_model,
)
from app.llm.embedding_service import EmbeddingService
from app.services.context_service import ContextService
from app.services.domain_write_mode import DomainWriteMode
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.inbox_review_marker import InboxReviewMarkerService
from app.services.job_queue_service import JobQueueService
from app.services.label_service import LabelRecord, LabelService
from app.services.notification_service import NotificationService
from app.services.object_query_service import ObjectQueryService
from app.services.provenance import (
    AGENT_ORIGIN,
    CONFIRMED_STATE,
    PROPOSED_STATE,
    REJECTED_STATE,
)
from app.services.relation_removal import is_edge_removable, removable_edge_rejection_reason
from app.services.retrieval_service import RetrievalService
from app.services.search_service import SearchService
from app.services.task_mutation_service import TaskMutationService
from app.tools.datetime_utils import normalize_tool_datetime
from app.tools.schemas import (
    MAX_TASK_EVIDENCE_IDS,
    AssignLabelInput,
    AssignLabelOutput,
    CancelScheduledActivityInput,
    CancelScheduledActivityOutput,
    ClearInboxReviewMarkerOutput,
    CreateCalendarEventCanonicalInput,
    CreateCalendarEventInput,
    CreateCalendarEventOutput,
    CreateLabelCanonicalInput,
    CreateLabelInput,
    CreateLabelOutput,
    CreateRecurringScheduledActivityCanonicalInput,
    CreateRecurringScheduledActivityInput,
    CreateScheduledActivityCanonicalInput,
    CreateScheduledActivityInput,
    CreateScheduledActivityOutput,
    CreateTaskInput,
    CreateTaskOutput,
    DeleteLabelInput,
    DeleteLabelOutput,
    DeleteTaskInput,
    DeleteTaskOutput,
    GetContextInput,
    GetContextOutput,
    GetObjectInput,
    GetObjectOutput,
    GetTodayOutput,
    InboxReviewCompactItemOut,
    InboxReviewStackOut,
    InboxSinceReviewMarkerItemOut,
    LabelItemOut,
    LinkObjectsInput,
    LinkObjectsOutput,
    ListInboxSinceReviewMarkerInput,
    ListInboxSinceReviewMarkerOutput,
    ListConversationMembersInput,
    ListConversationMembersOutput,
    ConversationMemberOut,
    ListLabelsInput,
    ListLabelsOutput,
    ListNeighborsInput,
    ListNeighborsOutput,
    ListNotificationsInput,
    ListNotificationsOutput,
    NeighborItem,
    QueryObjectItemOut,
    QueryObjectsInput,
    QueryObjectsOutput,
    RemoveLabelInput,
    RemoveLabelOutput,
    RemoveRelationInput,
    RemoveRelationOutput,
    RenameLabelCanonicalInput,
    RenameLabelInput,
    RenameLabelOutput,
    RetrievalHitOut,
    RetrieveInput,
    RetrieveOutput,
    SearchObjectsInput,
    SearchObjectsOutput,
    SendEmailCanonicalInput,
    SendEmailInput,
    SendEmailOutput,
    SendMessageCanonicalInput,
    SendMessageInput,
    SendMessageOutput,
    SetInboxReviewMarkerInput,
    SetInboxReviewMarkerOutput,
    SetTaskStatusInput,
    SetTaskStatusOutput,
    ToolError,
    UpdateTaskInput,
    UpdateTaskOutput,
)


class DomainToolService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        embedding_service: EmbeddingService | None = None,
        defer_write_embeddings: bool = False,
        write_mode: DomainWriteMode = DomainWriteMode.AGENT_PROPOSED,
        client_timezone: str | None = None,
        calendar_transport=None,
        calendar_token_session_factory=None,
        gmail_transport=None,
        gmail_token_session_factory=None,
        attempt_session_factory=None,
        yandex_smtp_transport=None,
        yandex_imap_transport=None,
        yandex_caldav_transport=None,
        mattermost_transport=None,
        telegram_transport=None,
        teams_transport=None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._write_mode = write_mode
        self._calendar_transport = calendar_transport
        self._calendar_token_session_factory = calendar_token_session_factory
        self._gmail_transport = gmail_transport
        self._gmail_token_session_factory = gmail_token_session_factory
        self._attempt_session_factory = attempt_session_factory
        self._yandex_smtp_transport = yandex_smtp_transport
        self._yandex_imap_transport = yandex_imap_transport
        self._yandex_caldav_transport = yandex_caldav_transport
        self._mattermost_transport = mattermost_transport
        self._telegram_transport = telegram_transport
        self._teams_transport = teams_transport
        from app.core.client_timezone import get_request_timezone

        self._client_timezone = client_timezone or get_request_timezone()
        self._graph = GraphService(session, user_id, embedding_service)
        self._search = SearchService(session, user_id)
        self._retrieval = RetrievalService(session, user_id)
        self._object_query = ObjectQueryService(session, user_id)
        self._context = ContextService(session, user_id, embedding_service)
        self._notifications = NotificationService(session, user_id)
        self._defer_write_embeddings = defer_write_embeddings
        if defer_write_embeddings:
            self._write_graph = GraphService(session, user_id, None)
            self._job_queue = JobQueueService(session)
        else:
            self._write_graph = self._graph
            self._job_queue = None

    def _task_mutations(self) -> TaskMutationService:
        embedding = self._write_graph._embedding_service
        return TaskMutationService(self._session, self._user_id, embedding)

    def _tool_error_from_mutation(self, exc: Exception) -> ToolError:
        if isinstance(exc, NotFoundError):
            return ToolError(f"object not found: {exc.entity_id}")
        if isinstance(exc, ValidationError):
            return ToolError(exc.message)
        if isinstance(exc, ConflictError):
            return ToolError(exc.message)
        raise exc

    def _label_service(self) -> LabelService:
        return LabelService(
            self._session,
            self._user_id,
            origin=AGENT_ORIGIN,
            state=self._new_artifact_state(),
        )

    def _label_annotation_service(self) -> LabelService:
        """ANNOTATE assignments are canonical confirmed labeled_with edges.

        assign_label/remove_label execute directly on user request (no approval
        plan), so a proposed-state edge would surface as an undecidable
        "proposed relation". Provenance stays visible via origin=agent.
        """
        return LabelService(
            self._session,
            self._user_id,
            origin=AGENT_ORIGIN,
            state=CONFIRMED_STATE,
        )

    def _label_item(self, record: LabelRecord) -> LabelItemOut:
        return LabelItemOut(
            id=record.id,
            title=record.title,
            created_at=record.created_at,
            updated_at=record.updated_at,
            description=record.description,
            object_count=record.object_count,
        )

    def _label_item_from_object(self, label, *, object_count: int = 0) -> LabelItemOut:
        from app.services.label_service import label_description

        return LabelItemOut(
            id=label.id,
            title=label.title,
            created_at=label.created_at,
            updated_at=label.updated_at,
            description=label_description(label),
            object_count=object_count,
        )

    def _enqueue_object_embedding(self, object_id: UUID) -> None:
        if self._job_queue is None:
            return
        from app.services.pipeline_enqueue import enqueue_embed_object

        enqueue_embed_object(self._session, object_id, self._user_id)

    def list_notifications(self, input: ListNotificationsInput) -> ListNotificationsOutput:
        try:
            rows = self._notifications.list_notifications(
                status=input.status,
                limit=input.limit,
            )
        except ValidationError as exc:
            raise ToolError(exc.message) from exc
        return ListNotificationsOutput(
            notifications=[NotificationOut.from_model(row) for row in rows]
        )

    def list_labels(self, input: ListLabelsInput) -> ListLabelsOutput:
        records = self._label_service().list_labels(limit=input.limit)
        return ListLabelsOutput(labels=[self._label_item(item) for item in records])

    def list_inbox_since_review_marker(
        self, input: ListInboxSinceReviewMarkerInput
    ) -> ListInboxSinceReviewMarkerOutput:
        from app.services.recent_source_service import RecentSourceService, inbox_feed_at

        try:
            page = InboxReviewMarkerService(
                self._session, self._user_id
            ).list_inbox_since_review_marker(
                limit=input.limit, cursor=input.cursor, purpose=input.purpose
            )
        except ValidationError as exc:
            raise ToolError(exc.message) from exc
        if page.marker is None:
            return ListInboxSinceReviewMarkerOutput(
                marker_present=False,
                marker_not_set=True,
                purpose=input.purpose,
                items=[],
                compact_items=[],
                has_more=False,
                total_count=0,
                returned_count=0,
                remaining_count=0,
                conversation_count=0,
                page_conversation_count=0,
                conversation_count_exact=True,
                message="Inbox review marker is not set",
            )
        items = [
            InboxSinceReviewMarkerItemOut(
                object_id=obj.id,
                kind=obj.kind,
                provider=obj.provider,
                title=obj.title,
                feed_at=inbox_feed_at(obj),
                excerpt=RecentSourceService.excerpt(obj.body),
            )
            for obj in page.items
        ]
        compact_items, page_conversation_count = self._inbox_compact_items(page.items)
        conversation_count, conversation_count_exact = self._frozen_conversation_count(
            page, purpose=input.purpose, page_conversation_count=page_conversation_count
        )
        message = None
        if page.has_more and page.next_cursor:
            message = (
                f"Frozen snapshot has {page.remaining_count} more objects after this page "
                f"(total_count={page.total_count}). Pass the exact next_cursor to continue "
                "the same snapshot; do not reconstruct timestamps or UUIDs."
            )
        return ListInboxSinceReviewMarkerOutput(
            marker_present=True,
            marker_not_set=False,
            purpose=input.purpose,
            anchor_object_id=page.marker.anchor_object_id,
            anchor_feed_at=page.marker.anchor_feed_at,
            snapshot_top_object_id=page.snapshot_top_object_id,
            snapshot_top_feed_at=page.snapshot_top_feed_at,
            total_count=page.total_count,
            returned_count=page.returned_count,
            remaining_count=page.remaining_count,
            conversation_count=conversation_count,
            page_conversation_count=page_conversation_count,
            conversation_count_exact=conversation_count_exact,
            items=items,
            compact_items=compact_items,
            has_more=page.has_more,
            next_cursor=page.next_cursor,
            message=message,
        )

    def _inbox_compact_items(self, objects: list[Object]) -> tuple[list[InboxReviewCompactItemOut], int]:
        from app.services.conversation_stack import conversation_unit_count
        from app.services.inbox_conversation_overlay import build_inbox_conversation_groups
        from app.services.recent_source_service import RecentSourceService, inbox_feed_at

        by_id = {obj.id: obj for obj in objects}
        groups = build_inbox_conversation_groups(
            objects,
            marker=None,
            session=self._session,
            user_id=self._user_id,
            enqueue_summaries=True,
        )
        compact: list[InboxReviewCompactItemOut] = []
        for group in groups:
            if group.item_type == "stack" and group.stack is not None:
                stack = group.stack
                semantic = stack.semantic_summary
                narration = (
                    f"{stack.fallback_summary.rstrip('.')} {(': ' + semantic) if semantic else '.'}"
                )
                if semantic:
                    provider_label = stack.fallback_summary.split(",")[0]
                    narration = (
                        f"{provider_label}, {stack.conversation_label}, "
                        f"{stack.message_count} сообщений: {semantic}"
                    )
                else:
                    narration = stack.fallback_summary
                compact.append(
                    InboxReviewCompactItemOut(
                        type="stack",
                        stack=InboxReviewStackOut(
                            stack_id=stack.stack_id,
                            fingerprint=stack.fingerprint,
                            object_ids=list(stack.object_ids),
                            provider=stack.provider,
                            conversation_label=stack.conversation_label,
                            message_count=stack.message_count,
                            start_at=stack.start_at,
                            end_at=stack.end_at,
                            summary=stack.semantic_summary,
                            fallback_summary=stack.fallback_summary,
                            summary_status=stack.summary_status,
                        ),
                        narration=narration,
                    )
                )
                continue
            obj = by_id[group.object_ids[0]]
            compact.append(
                InboxReviewCompactItemOut(
                    type="singleton",
                    object_id=obj.id,
                    kind=obj.kind,
                    provider=obj.provider,
                    title=obj.title,
                    feed_at=inbox_feed_at(obj),
                    excerpt=RecentSourceService.excerpt(obj.body),
                    narration=obj.title,
                )
            )
        return compact, conversation_unit_count(groups)

    def list_conversation_members(
        self, input: ListConversationMembersInput
    ) -> ListConversationMembersOutput:
        from app.services.conversation_member_read import (
            list_conversation_members_page,
            member_narration,
        )
        from app.services.conversation_projection import project_inbox_object
        from app.services.errors import NotFoundError, ValidationError
        from app.services.recent_source_service import inbox_feed_at

        try:
            page = list_conversation_members_page(
                self._session,
                self._user_id,
                object_id=input.object_id,
                limit=input.limit,
                cursor=input.cursor,
            )
        except NotFoundError as exc:
            raise ToolError(exc.message) from exc
        except ValidationError as exc:
            raise ToolError(exc.message) from exc
        members = []
        for obj in page["members"]:
            projection = project_inbox_object(obj)
            narration, excerpt, media_type = member_narration(obj)
            members.append(
                ConversationMemberOut(
                    object_id=obj.id,
                    occurred_at=obj.occurred_at,
                    feed_at=inbox_feed_at(obj),
                    sender=projection.sender_label if projection else None,
                    title=obj.title,
                    excerpt=excerpt,
                    media_type=media_type,
                    narration=narration,
                )
            )
        message = None
        if page["has_more"] and page["next_cursor"]:
            message = (
                f"This conversation has {page['remaining_count']} more members after this page "
                f"(total_member_count={page['total_member_count']}). Pass the exact next_cursor "
                "to continue oldest-to-newest; do not invent it."
            )
        return ListConversationMembersOutput(
            object_id=page["object_id"],
            provider=page["provider"],
            conversation_label=page["conversation_label"],
            stack_fingerprint=page["stack_fingerprint"],
            total_member_count=page["total_member_count"],
            returned_count=page["returned_count"],
            remaining_count=page["remaining_count"],
            members=members,
            has_more=page["has_more"],
            next_cursor=page["next_cursor"],
            message=message,
        )

    def _frozen_conversation_count(
        self,
        page,
        *,
        purpose: str,
        page_conversation_count: int,
    ) -> tuple[int | None, bool]:
        from app.services.conversation_stack import (
            CONVERSATION_COUNT_EXACT_MAX_OBJECTS,
            conversation_unit_count,
        )
        from app.services.inbox_conversation_overlay import build_inbox_conversation_groups

        if page.total_count <= 0:
            return 0, True
        if page.total_count > CONVERSATION_COUNT_EXACT_MAX_OBJECTS:
            return None, False
        if not page.has_more and page.returned_count == page.total_count:
            return page_conversation_count, True
        if page.marker is None or page.snapshot_top_object_id is None or page.snapshot_top_feed_at is None:
            return None, False
        objects = InboxReviewMarkerService(
            self._session, self._user_id
        ).list_frozen_window_objects(
            marker=page.marker,
            snapshot_top_object_id=page.snapshot_top_object_id,
            snapshot_top_feed_at=page.snapshot_top_feed_at,
            purpose=purpose,
            max_objects=CONVERSATION_COUNT_EXACT_MAX_OBJECTS,
        )
        if objects is None or len(objects) != page.total_count:
            return None, False
        groups = build_inbox_conversation_groups(
            objects,
            marker=None,
            session=self._session,
            user_id=self._user_id,
            enqueue_summaries=False,
        )
        return conversation_unit_count(groups), True

    def set_inbox_review_marker(
        self, input: SetInboxReviewMarkerInput
    ) -> SetInboxReviewMarkerOutput:
        try:
            record = InboxReviewMarkerService(self._session, self._user_id).set_marker(
                input.after_object_id
            )
        except (NotFoundError, ValidationError, ConflictError) as exc:
            raise self._tool_error_from_mutation(exc) from exc
        return SetInboxReviewMarkerOutput(
            anchor_object_id=record.anchor_object_id,
            anchor_feed_at=record.anchor_feed_at,
            updated_at=record.updated_at,
        )

    def clear_inbox_review_marker(self) -> ClearInboxReviewMarkerOutput:
        changed = InboxReviewMarkerService(self._session, self._user_id).clear_marker()
        return ClearInboxReviewMarkerOutput(changed=changed)

    def prepare_create_label(self, input: CreateLabelInput) -> CreateLabelCanonicalInput:
        from app.services.label_service import normalize_label_name

        try:
            display, _key = normalize_label_name(input.name)
        except ValidationError as exc:
            raise ToolError(exc.message) from exc
        return CreateLabelCanonicalInput(name=display)

    def create_label(self, input: CreateLabelCanonicalInput) -> CreateLabelOutput:
        try:
            result = self._label_service().create_label(input.name)
        except (NotFoundError, ValidationError, ConflictError) as exc:
            raise self._tool_error_from_mutation(exc) from exc
        return CreateLabelOutput(
            label=self._label_item_from_object(result.label),
            created=result.created,
        )

    def prepare_rename_label(self, input: RenameLabelInput) -> RenameLabelCanonicalInput:
        from app.services.label_service import normalize_label_name

        try:
            display, _key = normalize_label_name(input.name)
        except ValidationError as exc:
            raise ToolError(exc.message) from exc
        return RenameLabelCanonicalInput(label_id=input.label_id, name=display)

    def rename_label(self, input: RenameLabelCanonicalInput) -> RenameLabelOutput:
        try:
            result = self._label_service().rename_label(input.label_id, input.name)
        except (NotFoundError, ValidationError, ConflictError) as exc:
            raise self._tool_error_from_mutation(exc) from exc
        return RenameLabelOutput(
            label=self._label_item_from_object(result.label),
            changed=result.changed,
        )

    def delete_label(self, input: DeleteLabelInput) -> DeleteLabelOutput:
        try:
            result = self._label_service().delete_label(input.label_id)
        except (NotFoundError, ValidationError, ConflictError) as exc:
            raise self._tool_error_from_mutation(exc) from exc
        return DeleteLabelOutput(
            label=self._label_item_from_object(result.label),
            changed=result.changed,
        )

    def assign_label(self, input: AssignLabelInput) -> AssignLabelOutput:
        try:
            result = self._label_annotation_service().assign_label(
                input.object_id, input.label_id
            )
        except (NotFoundError, ValidationError, ConflictError) as exc:
            raise self._tool_error_from_mutation(exc) from exc
        return AssignLabelOutput(
            object_id=input.object_id,
            label_id=input.label_id,
            created=result.created,
        )

    def remove_label(self, input: RemoveLabelInput) -> RemoveLabelOutput:
        try:
            result = self._label_annotation_service().remove_label(
                input.object_id, input.label_id
            )
        except (NotFoundError, ValidationError, ConflictError) as exc:
            raise self._tool_error_from_mutation(exc) from exc
        return RemoveLabelOutput(
            object_id=input.object_id,
            label_id=input.label_id,
            changed=result.changed,
        )

    def search_objects(self, input: SearchObjectsInput) -> SearchObjectsOutput:
        objects = self._search.search(
            query=input.query,
            kind=input.kind,
            limit=input.limit,
        )
        return SearchObjectsOutput(objects=objects)

    def query_objects(self, input: QueryObjectsInput) -> QueryObjectsOutput:
        try:
            rows = self._object_query.query(
                kinds=input.kinds if input.kinds else None,
                providers=input.providers if input.providers else None,
                statuses=input.statuses if input.statuses else None,
                states=input.states if input.states else None,
                due_from=input.due_from,
                due_to=input.due_to,
                start_from=input.start_from,
                start_to=input.start_to,
                occurred_from=input.occurred_from,
                occurred_to=input.occurred_to,
                label_ids=input.label_ids if input.label_ids else None,
                label_match=input.label_match,
                sort_by=input.sort_by,
                sort_order=input.sort_order,
                limit=input.limit,
            )
        except ValidationError as exc:
            raise ToolError(exc.message) from exc
        return QueryObjectsOutput(
            objects=[
                QueryObjectItemOut(
                    object_id=obj.id,
                    title=obj.title,
                    kind=obj.kind,
                    provider=obj.provider,
                    state=obj.state,
                    status=(
                        canonical_task_status_for_model(obj.status)
                        if obj.kind == "task"
                        else obj.status
                    ),
                    due_at=obj.due_at,
                    start_at=obj.start_at,
                    occurred_at=obj.occurred_at,
                    created_at=obj.created_at,
                    updated_at=obj.updated_at,
                )
                for obj in rows
            ]
        )

    def retrieve(self, input: RetrieveInput) -> RetrieveOutput:
        try:
            result = self._retrieval.retrieve(
                query=input.query,
                kind=input.kind,
                time_scope=input.time_scope,
                date_from=input.date_from,
                date_to=input.date_to,
                limit=input.limit,
            )
        except ValidationError as exc:
            raise ToolError(exc.message) from exc
        hits = [
            RetrievalHitOut(
                object_id=hit.object_id,
                title=hit.title,
                kind=hit.kind,
                provider=hit.provider,
                state=hit.state,
                status=hit.status,
                occurred_at=hit.occurred_at,
                relevance=hit.relevance,
                reasons=hit.reasons,
                excerpt=hit.short_excerpt,
            )
            for hit in result.hits
        ]
        return RetrieveOutput(
            hits=hits,
            time_scope_used=result.time_scope_used,
            horizon_days=result.horizon_days,
            candidate_count=result.candidate_count,
            retrieval_mode=result.retrieval_mode,
            query_atom_count=result.query_atom_count,
            selected_atom_count=result.selected_atom_count,
        )

    def get_object(self, input: GetObjectInput) -> GetObjectOutput:
        try:
            obj = self._graph.get_object(input.object_id)
        except NotFoundError as exc:
            raise ToolError(f"object not found: {exc.entity_id}") from exc
        return GetObjectOutput(object=ObjectOut.from_model(obj))

    def get_context(self, input: GetContextInput) -> GetContextOutput:
        if input.object_id is None and input.query is None:
            raise ToolError("get_context requires object_id or query")
        if input.object_id is not None:
            try:
                self._graph.get_object(input.object_id)
            except NotFoundError as exc:
                raise ToolError(f"object not found: {exc.entity_id}") from exc
        result = self._context.build_context(
            object_id=input.object_id,
            query=input.query,
            max_chars=input.max_chars,
        )
        return GetContextOutput(
            items=result.items,
            total_chars=result.total_chars,
            truncated=result.truncated,
        )

    def list_neighbors(self, input: ListNeighborsInput) -> ListNeighborsOutput:
        try:
            rows = self._graph.get_neighbors(input.object_id, limit=input.limit)
        except NotFoundError as exc:
            raise ToolError(f"object not found: {exc.entity_id}") from exc
        neighbors = [
            NeighborItem(
                object=ObjectOut.from_model(neighbor),
                edge=EdgeOut.from_model(edge),
                direction=direction,
            )
            for neighbor, edge, direction in rows
        ]
        return ListNeighborsOutput(object_id=input.object_id, neighbors=neighbors)

    def _dedupe_evidence_ids(self, evidence_ids: list[UUID]) -> list[UUID]:
        if len(evidence_ids) > MAX_TASK_EVIDENCE_IDS:
            raise ToolError(
                f"evidence_object_ids must contain at most {MAX_TASK_EVIDENCE_IDS} ids"
            )
        seen: set[UUID] = set()
        unique: list[UUID] = []
        for object_id in evidence_ids:
            if object_id in seen:
                continue
            seen.add(object_id)
            unique.append(object_id)
        return unique

    def _validate_evidence_objects(self, evidence_ids: list[UUID]) -> list[Object]:
        objects: list[Object] = []
        for object_id in evidence_ids:
            try:
                obj = self._graph.get_object(object_id)
            except NotFoundError as exc:
                raise ToolError(f"evidence object not found: {exc.entity_id}") from exc
            if obj.state == REJECTED_STATE:
                raise ToolError(f"evidence object rejected: {object_id}")
            if obj.status == "deleted":
                raise ToolError(f"evidence object deleted: {object_id}")
            objects.append(obj)
        return objects

    def _new_artifact_state(self) -> str:
        if self._write_mode == DomainWriteMode.APPROVED_CONFIRMED:
            return CONFIRMED_STATE
        return PROPOSED_STATE

    def _attach_evidence_references(
        self,
        task_id: UUID,
        evidence_ids: list[UUID],
        confidence: float,
    ) -> tuple[int, list[UUID], list[UUID]]:
        created = 0
        added_ids: list[UUID] = []
        already_linked_ids: list[UUID] = []
        edge_state = self._new_artifact_state()
        for evidence_id in evidence_ids:
            existing = self._session.scalar(
                select(Edge).where(
                    Edge.user_id == self._user_id,
                    Edge.source_id == task_id,
                    Edge.target_id == evidence_id,
                    Edge.type == "references",
                )
            )
            if existing is not None and existing.state != REJECTED_STATE:
                already_linked_ids.append(evidence_id)
                continue
            self._write_graph.create_edge(
                EdgeCreate(
                    source_id=task_id,
                    target_id=evidence_id,
                    type="references",
                    origin=AGENT_ORIGIN,
                    state=edge_state,
                    confidence=confidence,
                )
            )
            added_ids.append(evidence_id)
            created += 1
        return created, added_ids, already_linked_ids

    def _get_task_for_mutation(self, object_id: UUID, *, allow_deleted: bool = False) -> Object:
        try:
            obj = self._graph.get_object(object_id)
        except NotFoundError as exc:
            raise ToolError(f"object not found: {exc.entity_id}") from exc
        if obj.kind != "task":
            raise ToolError("operation only supports task objects")
        if not allow_deleted and (
            is_object_tombstoned(obj) or obj.status == TASK_STATUS_DELETED
        ):
            raise ToolError("deleted task cannot be modified")
        return obj

    def create_task(self, input: CreateTaskInput) -> CreateTaskOutput:
        evidence_ids = self._dedupe_evidence_ids(input.evidence_object_ids)
        if evidence_ids:
            self._validate_evidence_objects(evidence_ids)
        due_at = normalize_tool_datetime(input.due_at)
        try:
            obj = self._write_graph.create_object(
                ObjectCreate(
                    kind="task",
                    title=input.title,
                    origin=AGENT_ORIGIN,
                    state=self._new_artifact_state(),
                    body=input.body,
                    status=TASK_STATUS_OPEN,
                    due_at=due_at,
                    confidence=input.confidence,
                )
            )
        except ValidationError as exc:
            raise ToolError(exc.message) from exc
        except ConflictError as exc:
            raise ToolError(exc.message) from exc
        if evidence_ids:
            _, _, _ = self._attach_evidence_references(
                obj.id, evidence_ids, input.confidence
            )
        self._enqueue_object_embedding(obj.id)
        return CreateTaskOutput(object=ObjectOut.from_model(obj))

    def _scheduled_activities(self):
        from app.services.scheduled_activity_service import ScheduledActivityService

        return ScheduledActivityService(self._session, self._user_id, self._write_graph)

    def prepare_create_scheduled_activity(
        self, payload: CreateScheduledActivityInput
    ) -> CreateScheduledActivityCanonicalInput:
        from app.services.scheduled_activity_service import require_future_run_at

        run_at = normalize_tool_datetime(payload.run_at, self._client_timezone)
        if run_at is None:
            raise ToolError("run_at is required")
        require_future_run_at(run_at)
        return CreateScheduledActivityCanonicalInput(
            title=payload.title,
            body=payload.body,
            run_at=run_at,
            priority=payload.priority,
        )

    def create_scheduled_activity(
        self, payload: CreateScheduledActivityCanonicalInput
    ) -> CreateScheduledActivityOutput:
        from app.services.scheduled_activity_service import require_future_run_at

        run_at = normalize_tool_datetime(payload.run_at, self._client_timezone)
        if run_at is None:
            raise ToolError("run_at is required")
        require_future_run_at(run_at)
        confidence = None if self._write_mode == DomainWriteMode.APPROVED_CONFIRMED else 1.0
        obj = self._scheduled_activities().create_once(
            title=payload.title,
            body=payload.body,
            run_at=run_at,
            priority=payload.priority,
            origin_state=self._new_artifact_state(),
            confidence=confidence,
            enqueue_embedding=self._job_queue is not None,
        )
        return CreateScheduledActivityOutput(object=ObjectOut.from_model(obj))

    def prepare_create_recurring_scheduled_activity(
        self, payload: CreateRecurringScheduledActivityInput
    ) -> dict:
        from app.domain.recurrence import RecurrenceSpec, next_occurrence, resolve_iana_timezone
        from app.services.scheduled_activity_service import require_future_run_at

        try:
            timezone = resolve_iana_timezone(payload.timezone, self._client_timezone)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        spec = RecurrenceSpec(
            schedule_kind=payload.schedule_kind,
            timezone=timezone,
            local_time=payload.local_time,
            weekdays=tuple(payload.weekdays or ()),
        )
        try:
            run_at = next_occurrence(spec, datetime.now(UTC))
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        require_future_run_at(run_at)
        canonical = CreateRecurringScheduledActivityCanonicalInput(
            title=payload.title,
            body=payload.body,
            schedule_kind=payload.schedule_kind,
            local_time=payload.local_time,
            timezone=timezone,
            weekdays=payload.weekdays,
            priority=payload.priority,
            run_at=run_at,
        )
        return canonical.model_dump(mode="json", exclude_none=True)

    def create_recurring_scheduled_activity(
        self, payload: CreateRecurringScheduledActivityCanonicalInput
    ) -> CreateScheduledActivityOutput:
        from app.domain.recurrence import RecurrenceSpec
        from app.services.scheduled_activity_service import require_future_run_at

        require_future_run_at(payload.run_at)
        spec = RecurrenceSpec(
            schedule_kind=payload.schedule_kind,
            timezone=payload.timezone,
            local_time=payload.local_time,
            weekdays=tuple(payload.weekdays or ()),
        )
        confidence = None if self._write_mode == DomainWriteMode.APPROVED_CONFIRMED else 1.0
        obj = self._scheduled_activities().create_recurring(
            title=payload.title,
            body=payload.body,
            spec=spec,
            run_at=payload.run_at,
            priority=payload.priority,
            origin_state=self._new_artifact_state(),
            confidence=confidence,
            enqueue_embedding=self._job_queue is not None,
        )
        return CreateScheduledActivityOutput(object=ObjectOut.from_model(obj))

    def cancel_scheduled_activity(
        self, payload: CancelScheduledActivityInput
    ) -> CancelScheduledActivityOutput:
        obj, changed = self._scheduled_activities().cancel(payload.activity_id)
        return CancelScheduledActivityOutput(
            object=ObjectOut.from_model(obj),
            changed=changed,
            status=obj.status or "",
        )

    def update_task(self, input: UpdateTaskInput) -> UpdateTaskOutput:
        obj = self._get_task_for_mutation(input.object_id)
        evidence_ids = self._dedupe_evidence_ids(input.evidence_object_ids)
        if evidence_ids:
            if input.object_id in evidence_ids:
                raise ToolError("task cannot reference itself as evidence")
            self._validate_evidence_objects(evidence_ids)

        fields_set = input.model_fields_set
        field_fields = {"title", "body", "due_at"}
        has_field_updates = any(field in fields_set for field in field_fields)

        updated = obj
        fields_changed = False
        if has_field_updates:
            try:
                patch_result = self._task_mutations().patch_task_fields(
                    input.object_id,
                    title=input.title if "title" in fields_set else None,
                    body=input.body if "body" in fields_set else None,
                    due_at=input.due_at if "due_at" in fields_set else None,
                    fields_set=fields_set,
                )
            except (NotFoundError, ValidationError) as exc:
                raise self._tool_error_from_mutation(exc) from exc
            updated = patch_result.object
            fields_changed = patch_result.changed
        elif not evidence_ids:
            raise ToolError("update_task requires at least one field to update")

        evidence_edges_created = 0
        evidence_added_object_ids: list[UUID] = []
        evidence_already_linked_object_ids: list[UUID] = []
        if evidence_ids:
            confidence = updated.confidence if updated.confidence is not None else 0.5
            (
                evidence_edges_created,
                evidence_added_object_ids,
                evidence_already_linked_object_ids,
            ) = self._attach_evidence_references(updated.id, evidence_ids, confidence)
        changed = fields_changed or evidence_edges_created > 0
        if fields_changed:
            self._enqueue_object_embedding(updated.id)
        return UpdateTaskOutput(
            object=ObjectOut.from_model(updated),
            changed=changed,
            evidence_edges_created=evidence_edges_created,
            evidence_added_object_ids=evidence_added_object_ids,
            evidence_already_linked_object_ids=evidence_already_linked_object_ids,
        )

    def set_task_status(self, input: SetTaskStatusInput) -> SetTaskStatusOutput:
        try:
            result = self._task_mutations().set_task_status(input.object_id, input.status)
        except (NotFoundError, ValidationError) as exc:
            raise self._tool_error_from_mutation(exc) from exc
        if result.changed:
            self._enqueue_object_embedding(result.object.id)
        return SetTaskStatusOutput(
            object=ObjectOut.from_model(result.object),
            changed=result.changed,
            previous_status=result.previous_status,
            new_status=result.new_status,
        )

    def delete_task(self, input: DeleteTaskInput) -> DeleteTaskOutput:
        try:
            result = self._task_mutations().soft_delete_task(input.object_id)
        except (NotFoundError, ValidationError) as exc:
            raise self._tool_error_from_mutation(exc) from exc
        if result.changed:
            self._enqueue_object_embedding(result.object.id)
        return DeleteTaskOutput(
            object=ObjectOut.from_model(result.object),
            changed=result.changed,
            previous_status=result.previous_status,
            new_status=result.new_status,
        )

    def link_objects(self, input: LinkObjectsInput) -> LinkObjectsOutput:
        if input.relation_type == EDGE_TYPE_LABELED_WITH:
            raise ToolError("labeled_with assignments must use assign_label")
        if input.source_id == input.target_id:
            raise ToolError("source and target must differ")
        existing = self._session.scalar(
            select(Edge).where(
                Edge.user_id == self._user_id,
                Edge.source_id == input.source_id,
                Edge.target_id == input.target_id,
                Edge.type == input.relation_type,
                Edge.state != REJECTED_STATE,
            )
        )
        if existing is not None:
            return LinkObjectsOutput(edge=EdgeOut.from_model(existing), created=False)
        try:
            edge = self._graph.create_edge(
                EdgeCreate(
                    source_id=input.source_id,
                    target_id=input.target_id,
                    type=input.relation_type,
                    origin=AGENT_ORIGIN,
                    state=self._new_artifact_state(),
                    confidence=input.confidence,
                )
            )
        except NotFoundError as exc:
            raise ToolError(f"object not found: {exc.entity_id}") from exc
        except ValidationError as exc:
            raise ToolError(exc.message) from exc
        return LinkObjectsOutput(edge=EdgeOut.from_model(edge), created=True)

    def remove_relation(self, input: RemoveRelationInput) -> RemoveRelationOutput:
        edge = self._session.scalar(
            select(Edge).where(Edge.id == input.edge_id, Edge.user_id == self._user_id)
        )
        if edge is None:
            raise ToolError(f"edge not found: {input.edge_id}")
        reason = removable_edge_rejection_reason(edge.origin, edge.type)
        if reason is not None:
            raise ToolError(reason)
        if not is_edge_removable(edge.origin, edge.type):
            raise ToolError("relation cannot be removed through remove_relation")
        previous_state = edge.state
        if previous_state == REJECTED_STATE:
            return RemoveRelationOutput(
                edge=EdgeOut.from_model(edge),
                changed=False,
                previous_state=previous_state,
                new_state=REJECTED_STATE,
            )
        edge.state = REJECTED_STATE
        self._session.flush()
        return RemoveRelationOutput(
            edge=EdgeOut.from_model(edge),
            changed=True,
            previous_state=previous_state,
            new_state=REJECTED_STATE,
        )

    def get_today(self) -> GetTodayOutput:
        tz_name = self._client_timezone
        now = datetime.now(ZoneInfo(tz_name))
        return GetTodayOutput(datetime=now, timezone=tz_name)

    def _calendar_actions(self):
        from app.services.calendar_external_action_service import CalendarExternalActionService

        kwargs = {}
        if self._calendar_transport is not None:
            kwargs["transport"] = self._calendar_transport
        if self._calendar_token_session_factory is not None:
            kwargs["token_session_factory"] = self._calendar_token_session_factory
        if self._yandex_caldav_transport is not None:
            kwargs["yandex_caldav_transport"] = self._yandex_caldav_transport
        if self._attempt_session_factory is not None:
            kwargs["attempt_session_factory"] = self._attempt_session_factory
        return CalendarExternalActionService(self._session, self._user_id, **kwargs)

    def _email_actions(self):
        from app.services.email_external_action_service import EmailExternalActionService

        kwargs = {}
        if self._gmail_transport is not None:
            kwargs["transport"] = self._gmail_transport
        if self._gmail_token_session_factory is not None:
            kwargs["token_session_factory"] = self._gmail_token_session_factory
        if self._attempt_session_factory is not None:
            kwargs["attempt_session_factory"] = self._attempt_session_factory
        if self._yandex_smtp_transport is not None:
            kwargs["yandex_smtp_transport"] = self._yandex_smtp_transport
        if self._yandex_imap_transport is not None:
            kwargs["yandex_imap_transport"] = self._yandex_imap_transport
        return EmailExternalActionService(self._session, self._user_id, **kwargs)

    def prepare_create_calendar_event(
        self, payload: CreateCalendarEventInput
    ) -> CreateCalendarEventCanonicalInput:
        return self._calendar_actions().prepare_create_event(payload, self._client_timezone)

    def create_calendar_event(
        self, payload: CreateCalendarEventCanonicalInput
    ) -> CreateCalendarEventOutput:
        return self._calendar_actions().create_event(payload)

    def prepare_send_email(self, payload: SendEmailInput) -> SendEmailCanonicalInput:
        return self._email_actions().prepare_send_email(payload)

    def send_email(self, payload: SendEmailCanonicalInput) -> SendEmailOutput:
        return self._email_actions().send_email(payload)

    def _communication_actions(self):
        from app.services.communication_external_action_service import (
            CommunicationExternalActionService,
        )

        kwargs = {}
        if self._mattermost_transport is not None:
            kwargs["transport"] = self._mattermost_transport
        if self._telegram_transport is not None:
            kwargs["telegram_transport"] = self._telegram_transport
        if self._teams_transport is not None:
            kwargs["teams_transport"] = self._teams_transport
        if self._attempt_session_factory is not None:
            kwargs["attempt_session_factory"] = self._attempt_session_factory
        return CommunicationExternalActionService(self._session, self._user_id, **kwargs)

    def prepare_send_message(self, payload: SendMessageInput) -> SendMessageCanonicalInput:
        return self._communication_actions().prepare_send_message(payload)

    def send_message(self, payload: SendMessageCanonicalInput) -> SendMessageOutput:
        return self._communication_actions().send_message(payload)
