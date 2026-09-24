"""Server-owned Assistant conversations.

Persisted transcript is canonical for the new client. Model context stays the
recent bounded tail. Client-supplied history is not used in persistent mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.action_plan_constants import PENDING_ACTION_PLAN_STATUS_PENDING
from app.assistant.constants import MAX_ASSISTANT_HISTORY_MESSAGES
from app.assistant.inbox_review_progress import InboxReviewReceipt
from app.db.models import AssistantConversation, AssistantMessage, PendingActionPlan
from app.llm.assistant_models import AssistantHistoryMessage
from app.services.assistant_service import (
    AssistantAffectedObject,
    AssistantMessageResult,
    AssistantPendingAction,
    AssistantPendingActionPlan,
    AssistantReference,
    AssistantResumeResult,
)
from app.services.errors import ConflictError, NotFoundError

CONVERSATION_LIST_LIMIT = 50
MESSAGE_PAGE_LIMIT = 50
MESSAGE_PAGE_MAX = 100
TITLE_MAX_CHARS = 72
UNRESOLVED_PENDING_ACTION_PLAN = "unresolved_pending_action_plan"
INCOMPLETE_PERSISTENT_TURN = "incomplete_persistent_turn"


@dataclass
class ConversationView:
    id: UUID
    title: str | None
    is_current: bool
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None


@dataclass
class StoredTurn:
    result: AssistantMessageResult
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID


class IncompletePersistentTurnError(ConflictError):
    def __init__(self) -> None:
        super().__init__(INCOMPLETE_PERSISTENT_TURN)


def conversation_title_from_message(message: str) -> str:
    compact = " ".join(message.split())
    if len(compact) <= TITLE_MAX_CHARS:
        return compact
    return compact[: TITLE_MAX_CHARS - 1].rstrip() + "…"


class AssistantConversationService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def list_conversations(self, *, limit: int = CONVERSATION_LIST_LIMIT) -> list[ConversationView]:
        bounded = min(max(limit, 1), CONVERSATION_LIST_LIMIT)
        rows = self._session.scalars(
            select(AssistantConversation)
            .where(AssistantConversation.user_id == self._user_id)
            .order_by(
                AssistantConversation.last_message_at.desc().nulls_last(),
                AssistantConversation.created_at.desc(),
                AssistantConversation.id.desc(),
            )
            .limit(bounded)
        ).all()
        return [_conversation_view(row) for row in rows]

    def get_current(self) -> ConversationView:
        row = self._current_row()
        if row is None:
            raise NotFoundError("assistant_conversation", self._user_id)
        return _conversation_view(row)

    def create_current(self) -> ConversationView:
        current = self._lock_current()
        if current is not None and self._has_unresolved_plan(current.id):
            raise ConflictError(UNRESOLVED_PENDING_ACTION_PLAN)
        if current is not None:
            current.is_current = False
            current.updated_at = datetime.now(UTC)
            self._session.flush()
        created_at = datetime.now(UTC)
        if current is not None and current.created_at >= created_at:
            created_at = current.created_at + timedelta(microseconds=1)
        created = AssistantConversation(
            user_id=self._user_id,
            title=None,
            is_current=True,
            last_message_at=None,
            created_at=created_at,
            updated_at=created_at,
        )
        self._session.add(created)
        self._session.flush()
        return _conversation_view(created)

    def select(self, conversation_id: UUID) -> ConversationView:
        target = self._owned(conversation_id, lock=True)
        current = self._lock_current()
        if (
            current is not None
            and current.id != target.id
            and self._has_unresolved_plan(current.id)
        ):
            raise ConflictError(UNRESOLVED_PENDING_ACTION_PLAN)
        if current is not None and current.id != target.id:
            current.is_current = False
            current.updated_at = datetime.now(UTC)
            self._session.flush()
        target.is_current = True
        target.updated_at = datetime.now(UTC)
        self._session.flush()
        return _conversation_view(target)

    def list_messages(
        self,
        conversation_id: UUID,
        *,
        limit: int = MESSAGE_PAGE_LIMIT,
        before_id: UUID | None = None,
    ) -> tuple[list[AssistantMessage], bool]:
        self._owned(conversation_id)
        bounded = min(max(limit, 1), MESSAGE_PAGE_MAX)
        query = select(AssistantMessage).where(
            AssistantMessage.conversation_id == conversation_id,
            AssistantMessage.user_id == self._user_id,
        )
        if before_id is not None:
            cursor = self._session.get(AssistantMessage, before_id)
            if (
                cursor is None
                or cursor.user_id != self._user_id
                or cursor.conversation_id != conversation_id
            ):
                raise NotFoundError("assistant_message", before_id)
            query = query.where(
                (AssistantMessage.created_at < cursor.created_at)
                | (
                    (AssistantMessage.created_at == cursor.created_at)
                    & (AssistantMessage.id < cursor.id)
                )
            )
        rows = self._session.scalars(
            query.order_by(
                AssistantMessage.created_at.desc(),
                AssistantMessage.id.desc(),
            ).limit(bounded + 1)
        ).all()
        has_more = len(rows) > bounded
        page = list(reversed(rows[:bounded]))
        return page, has_more

    def bounded_history(self, conversation_id: UUID) -> list[AssistantHistoryMessage]:
        self._owned(conversation_id)
        rows = self._session.scalars(
            select(AssistantMessage)
            .where(
                AssistantMessage.conversation_id == conversation_id,
                AssistantMessage.user_id == self._user_id,
                AssistantMessage.role.in_(("user", "assistant")),
            )
            .order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc())
            .limit(MAX_ASSISTANT_HISTORY_MESSAGES)
        ).all()
        history: list[AssistantHistoryMessage] = []
        for row in reversed(rows):
            content = row.content.strip()
            if not content:
                continue
            history.append(AssistantHistoryMessage(role=row.role, content=content))
        return history

    def stored_turn(self, conversation_id: UUID, client_turn_id: UUID) -> StoredTurn | None:
        self._owned(conversation_id)
        user_message = self._session.scalar(
            select(AssistantMessage).where(
                AssistantMessage.conversation_id == conversation_id,
                AssistantMessage.user_id == self._user_id,
                AssistantMessage.role == "user",
                AssistantMessage.client_turn_id == client_turn_id,
            )
        )
        if user_message is None:
            return None
        assistant_message = self._session.scalar(
            select(AssistantMessage).where(
                AssistantMessage.conversation_id == conversation_id,
                AssistantMessage.user_id == self._user_id,
                AssistantMessage.role == "assistant",
                AssistantMessage.client_turn_id == client_turn_id,
            )
        )
        if assistant_message is None:
            raise IncompletePersistentTurnError()
        return StoredTurn(
            result=self._result_from_message(assistant_message),
            conversation_id=conversation_id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
        )

    def persist_completed_turn(
        self,
        *,
        conversation_id: UUID,
        client_turn_id: UUID,
        user_text: str,
        result: AssistantMessageResult,
    ) -> StoredTurn:
        conversation = self._owned(conversation_id, lock=True)
        existing = self._session.scalar(
            select(AssistantMessage).where(
                AssistantMessage.conversation_id == conversation_id,
                AssistantMessage.role == "user",
                AssistantMessage.client_turn_id == client_turn_id,
            )
        )
        if existing is not None:
            stored = self.stored_turn(conversation_id, client_turn_id)
            if stored is None:
                raise IncompletePersistentTurnError()
            return stored
        now = datetime.now(UTC)
        user_message = AssistantMessage(
            conversation_id=conversation.id,
            user_id=self._user_id,
            role="user",
            content=user_text,
            client_turn_id=client_turn_id,
            created_at=now,
        )
        assistant_message = AssistantMessage(
            conversation_id=conversation.id,
            user_id=self._user_id,
            role="assistant",
            content=result.answer,
            client_turn_id=client_turn_id,
            presentation=_presentation_snapshot(result),
            pending_action_plan_id=(
                None
                if result.pending_action_plan is None
                else result.pending_action_plan.id
            ),
            created_at=now + timedelta(microseconds=1),
        )
        self._session.add(user_message)
        self._session.add(assistant_message)
        if conversation.title is None:
            conversation.title = conversation_title_from_message(user_text)
        conversation.last_message_at = now
        conversation.updated_at = now
        self._session.flush()
        return StoredTurn(
            result=result,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
        )

    def stored_resume(self, plan_id: UUID) -> AssistantResumeResult | None:
        message = self._resume_message(plan_id)
        if message is None:
            return None
        presentation = message.presentation or {}
        return AssistantResumeResult(
            answer=message.content,
            affected_objects=_affected_from_presentation(presentation),
        )

    def persist_resume(
        self,
        plan_id: UUID,
        result: AssistantResumeResult,
    ) -> AssistantResumeResult:
        existing = self.stored_resume(plan_id)
        if existing is not None:
            return existing
        anchor = self._session.scalar(
            select(AssistantMessage).where(
                AssistantMessage.user_id == self._user_id,
                AssistantMessage.pending_action_plan_id == plan_id,
            )
        )
        if anchor is None:
            return result
        now = datetime.now(UTC)
        conversation = self._owned(anchor.conversation_id, lock=True)
        message = AssistantMessage(
            conversation_id=anchor.conversation_id,
            user_id=self._user_id,
            role="assistant",
            content=result.answer,
            presentation={
                "references": [],
                "affected_objects": [
                    {
                        "object_id": str(item.object_id),
                        "title": item.title,
                        "kind": item.kind,
                        "state": item.state,
                        "status": item.status,
                    }
                    for item in result.affected_objects
                ],
                "inbox_review_receipt": None,
            },
            resume_plan_id=plan_id,
            created_at=now,
        )
        self._session.add(message)
        conversation.last_message_at = now
        conversation.updated_at = now
        self._session.flush()
        return result

    def message_result(self, message: AssistantMessage) -> AssistantMessageResult:
        return self._result_from_message(message)

    def hydrate_plan(self, plan_id: UUID | None) -> AssistantPendingActionPlan | None:
        if plan_id is None:
            return None
        plan = self._session.get(PendingActionPlan, plan_id)
        if plan is None or plan.user_id != self._user_id:
            return None
        return AssistantPendingActionPlan(
            id=plan.id,
            status=plan.status,
            expires_at=plan.expires_at,
            actions=[
                AssistantPendingAction(
                    tool_name=str(action.get("tool_name")),
                    arguments=dict(action.get("arguments") or {}),
                )
                for action in plan.actions
                if isinstance(action, dict)
            ],
        )

    def _result_from_message(self, message: AssistantMessage) -> AssistantMessageResult:
        presentation = message.presentation or {}
        return AssistantMessageResult(
            answer=message.content,
            references=_references_from_presentation(presentation),
            affected_objects=_affected_from_presentation(presentation),
            pending_action_plan=self.hydrate_plan(message.pending_action_plan_id),
            inbox_review_receipt=_receipt_from_presentation(presentation),
        )

    def _resume_message(self, plan_id: UUID) -> AssistantMessage | None:
        return self._session.scalar(
            select(AssistantMessage).where(
                AssistantMessage.user_id == self._user_id,
                AssistantMessage.resume_plan_id == plan_id,
            )
        )

    def _has_unresolved_plan(self, conversation_id: UUID) -> bool:
        now = datetime.now(UTC)
        plan_id = self._session.scalar(
            select(PendingActionPlan.id)
            .join(
                AssistantMessage,
                AssistantMessage.pending_action_plan_id == PendingActionPlan.id,
            )
            .where(
                AssistantMessage.conversation_id == conversation_id,
                AssistantMessage.user_id == self._user_id,
                PendingActionPlan.user_id == self._user_id,
                PendingActionPlan.status == PENDING_ACTION_PLAN_STATUS_PENDING,
                PendingActionPlan.expires_at > now,
            )
            .limit(1)
        )
        return plan_id is not None

    def _current_row(self) -> AssistantConversation | None:
        return self._session.scalar(
            select(AssistantConversation).where(
                AssistantConversation.user_id == self._user_id,
                AssistantConversation.is_current.is_(True),
            )
        )

    def _lock_current(self) -> AssistantConversation | None:
        return self._session.scalar(
            select(AssistantConversation)
            .where(
                AssistantConversation.user_id == self._user_id,
                AssistantConversation.is_current.is_(True),
            )
            .with_for_update()
        )

    def _owned(self, conversation_id: UUID, *, lock: bool = False) -> AssistantConversation:
        query = select(AssistantConversation).where(
            AssistantConversation.id == conversation_id,
            AssistantConversation.user_id == self._user_id,
        )
        if lock:
            query = query.with_for_update()
        row = self._session.scalar(query)
        if row is None:
            raise NotFoundError("assistant_conversation", conversation_id)
        return row


def _conversation_view(row: AssistantConversation) -> ConversationView:
    return ConversationView(
        id=row.id,
        title=row.title,
        is_current=row.is_current,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_message_at=row.last_message_at,
    )


def _presentation_snapshot(result: AssistantMessageResult) -> dict:
    receipt = result.inbox_review_receipt
    return {
        "references": [
            {
                "object_id": str(item.object_id),
                "title": item.title,
                "kind": item.kind,
                "canonical_uri": item.canonical_uri,
                "provider": item.provider,
                "primary_at": None if item.primary_at is None else item.primary_at.isoformat(),
            }
            for item in result.references
        ],
        "affected_objects": [
            {
                "object_id": str(item.object_id),
                "title": item.title,
                "kind": item.kind,
                "state": item.state,
                "status": item.status,
            }
            for item in result.affected_objects
        ],
        "inbox_review_receipt": None
        if receipt is None
        else {
            "anchor_before_object_id": str(receipt.anchor_before_object_id),
            "anchor_before_feed_at": receipt.anchor_before_feed_at.isoformat(),
            "snapshot_top_object_id": str(receipt.snapshot_top_object_id),
            "snapshot_top_feed_at": receipt.snapshot_top_feed_at.isoformat(),
            "total_count": receipt.total_count,
        },
    }


def _references_from_presentation(presentation: dict) -> list[AssistantReference]:
    raw_items = presentation.get("references") or []
    references: list[AssistantReference] = []
    if not isinstance(raw_items, list):
        return references
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            object_id = UUID(str(item.get("object_id")))
        except ValueError:
            continue
        primary_raw = item.get("primary_at")
        primary_at = None
        if isinstance(primary_raw, str) and primary_raw:
            primary_at = datetime.fromisoformat(primary_raw)
        references.append(
            AssistantReference(
                object_id=object_id,
                title=str(item.get("title") or ""),
                kind=str(item.get("kind") or ""),
                canonical_uri=item.get("canonical_uri"),
                provider=item.get("provider"),
                primary_at=primary_at,
            )
        )
    return references


def _receipt_from_presentation(presentation: dict) -> InboxReviewReceipt | None:
    raw = presentation.get("inbox_review_receipt")
    if not isinstance(raw, dict):
        return None
    try:
        return InboxReviewReceipt(
            anchor_before_object_id=UUID(str(raw["anchor_before_object_id"])),
            anchor_before_feed_at=datetime.fromisoformat(str(raw["anchor_before_feed_at"])),
            snapshot_top_object_id=UUID(str(raw["snapshot_top_object_id"])),
            snapshot_top_feed_at=datetime.fromisoformat(str(raw["snapshot_top_feed_at"])),
            total_count=int(raw["total_count"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _affected_from_presentation(presentation: dict) -> list[AssistantAffectedObject]:
    raw_items = presentation.get("affected_objects") or []
    affected: list[AssistantAffectedObject] = []
    if not isinstance(raw_items, list):
        return affected
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            object_id = UUID(str(item.get("object_id")))
        except ValueError:
            continue
        affected.append(
            AssistantAffectedObject(
                object_id=object_id,
                title=str(item.get("title") or ""),
                kind=str(item.get("kind") or ""),
                state=str(item.get("state") or ""),
                status=item.get("status"),
            )
        )
    return affected
