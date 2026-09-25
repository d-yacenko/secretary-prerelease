from collections.abc import Sequence
from uuid import UUID

import app.assistant.session as assistant_session
from app.assistant.action_plan_constants import MAX_ACTIONS_PER_PLAN
from app.assistant.constants import MAX_ASSISTANT_TOOL_CALLS_PER_TURN
from app.assistant.inbox_review_progress import InboxReviewTurnProgress
from app.assistant.reference_ids import (
    collect_resolved_person_id,
    collect_seen_edge_ids_from_bounded_tool,
    collect_seen_object_ids_from_bounded_tool,
    collect_seen_person_candidates,
    collect_seen_person_routes,
)
from app.assistant.tool_output import serialize_tool_output_for_assistant
from app.assistant.turn_telemetry import AssistantTurnTelemetry
from app.domain.person_assistant import feedback_identity_key, parse_feedback_identity
from app.domain.person_identity import PersonIdentityInputError, normalize_email
from app.tools.policy import ToolPermission
from app.tools.registry import get_tool_spec
from app.tools.results import ToolExecutionResult, ToolExecutionStatus

_IRREVERSIBLE_PERMISSIONS = frozenset({ToolPermission.EXTERNAL_WRITE, ToolPermission.COMMUNICATE})

_READ_TOOLS = frozenset(
    {
        "retrieve",
        "query_objects",
        "search_objects",
        "get_object",
        "get_task_profile",
        "get_context",
        "list_neighbors",
        "list_notifications",
        "list_labels",
        "list_inbox_since_review_marker",
        "list_conversation_members",
        "resolve_person",
        "find_person_communications",
        "find_person_identity_candidates",
        "list_person_routes",
    }
)
_EVIDENCE_WRITE_TOOLS = frozenset({"create_task", "update_task", "set_task_status", "delete_task"})
_OBJECT_TARGET_TOOLS = frozenset(
    {
        "update_task",
        "set_task_status",
        "delete_task",
        "edit_message",
        "delete_message",
        "mark_message_read",
    }
)
_SEND_MESSAGE_ANCHOR_TOOLS = frozenset({"send_message"})
_SEND_MESSAGE_ANCHOR_FIELDS = ("conversation_object_id", "reply_to_object_id")
_ACTIVITY_TARGET_TOOLS = frozenset({"cancel_scheduled_activity"})
# ANNOTATE tools execute without approval in the interactive turn, so both the
# target object and the label must have been exposed to the model this turn.
_ANNOTATION_TARGET_TOOLS = frozenset({"assign_label", "remove_label"})
_REVIEW_MARKER_TARGET_TOOLS = frozenset({"set_inbox_review_marker"})
_PERSON_READ_TOOLS = frozenset(
    {
        "find_person_communications",
        "find_person_identity_candidates",
        "list_person_routes",
    }
)
_PERSON_FEEDBACK_TOOLS = frozenset(
    {
        "confirm_person_identity",
        "reject_person_identity",
        "retract_person_identity_feedback",
    }
)
_PERSON_ROUTE_TOOLS = frozenset({"send_email", "send_message", "record_person_route_choice"})
_MUTATION_TOOLS = frozenset(
    {
        "create_task",
        "update_task",
        "set_task_status",
        "delete_task",
        "link_objects",
        "remove_relation",
        "create_scheduled_activity",
        "create_recurring_scheduled_activity",
        "cancel_scheduled_activity",
        "create_calendar_event",
        "send_email",
        "send_message",
        "edit_message",
        "delete_message",
        "mark_message_read",
        "create_label",
        "rename_label",
        "assign_label",
        "remove_label",
        "delete_label",
        "set_inbox_review_marker",
        "clear_inbox_review_marker",
        "confirm_person_identity",
        "reject_person_identity",
        "retract_person_identity_feedback",
        "record_person_route_choice",
    }
)


class PerTurnToolBudget:
    def __init__(
        self,
        max_calls: int = MAX_ASSISTANT_TOOL_CALLS_PER_TURN,
        telemetry: AssistantTurnTelemetry | None = None,
        initial_seen_object_ids: Sequence[UUID] | None = None,
        inbox_review_purpose: str | None = None,
    ) -> None:
        self._max_calls = max_calls
        self._calls = 0
        self._telemetry = telemetry
        self._seen_object_ids: set[UUID] = set(initial_seen_object_ids or [])
        self._pending_seen_object_ids: set[UUID] = set()
        self._seen_edge_ids: set[UUID] = set()
        self._pending_seen_edge_ids: set[UUID] = set()
        self._seen_person_candidates: set[tuple[UUID, str, str, str, str]] = set()
        self._pending_seen_person_candidates: set[tuple[UUID, str, str, str, str]] = set()
        self._resolved_person_ids: set[UUID] = set()
        self._pending_resolved_person_ids: set[UUID] = set()
        self._seen_person_routes: set[tuple[UUID, str]] = set()
        self._pending_seen_person_routes: set[tuple[UUID, str]] = set()
        self._staged_actions: list[dict] = []
        self._plan_sealed = False
        self._inbox_review_purpose = inbox_review_purpose
        self.inbox_review = InboxReviewTurnProgress()

    @property
    def calls_made(self) -> int:
        return self._calls

    @property
    def seen_object_ids(self) -> set[UUID]:
        return set(self._seen_object_ids)

    @property
    def pending_seen_object_ids(self) -> set[UUID]:
        return set(self._pending_seen_object_ids)

    @property
    def staged_actions(self) -> list[dict]:
        return list(self._staged_actions)

    def seed_seen_object_ids(self, object_ids: Sequence[UUID]) -> None:
        self._seen_object_ids.update(object_ids)

    def commit_model_visible_outputs(self) -> None:
        """Promote IDs from the last model response after outputs were delivered to input."""
        self._seen_object_ids.update(self._pending_seen_object_ids)
        self._pending_seen_object_ids.clear()
        self._seen_edge_ids.update(self._pending_seen_edge_ids)
        self._pending_seen_edge_ids.clear()
        self._seen_person_candidates.update(self._pending_seen_person_candidates)
        self._pending_seen_person_candidates.clear()
        self._resolved_person_ids.update(self._pending_resolved_person_ids)
        self._pending_resolved_person_ids.clear()
        self._seen_person_routes.update(self._pending_seen_person_routes)
        self._pending_seen_person_routes.clear()
        if self._staged_actions:
            self._plan_sealed = True

    def run(self, user_id: UUID, tool_name: str, arguments: dict) -> ToolExecutionResult:
        if self._calls >= self._max_calls:
            if self._telemetry is not None:
                self._telemetry.tool_calls += 1
            if tool_name == "list_inbox_since_review_marker":
                self.inbox_review.mark_limit_reached()
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="tool call limit reached",
                limit_reached=True,
                status=ToolExecutionStatus.LIMIT_REACHED,
            )
        self._calls += 1

        if tool_name == "list_inbox_since_review_marker" and self._inbox_review_purpose:
            arguments = {
                **arguments,
                "purpose": self._inbox_review_purpose,
            }

        if tool_name in _MUTATION_TOOLS or _is_irreversible_tool(tool_name):
            if self._plan_sealed:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return ToolExecutionResult(
                    success=False,
                    tool_name=tool_name,
                    error="action plan already staged for approval",
                    status=ToolExecutionStatus.TOOL_ERROR,
                )
            if len(self._staged_actions) >= MAX_ACTIONS_PER_PLAN:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return ToolExecutionResult(
                    success=False,
                    tool_name=tool_name,
                    error="action plan exceeds maximum actions",
                    status=ToolExecutionStatus.TOOL_ERROR,
                )
            irreversible_error = self._irreversible_staging_error(tool_name)
            if irreversible_error is not None:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return irreversible_error

        if tool_name in _EVIDENCE_WRITE_TOOLS:
            evidence_error = self._validate_evidence_allowlist(tool_name, arguments)
            if evidence_error is not None:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return evidence_error
            relation_error = self._validate_task_relation_allowlist(tool_name, arguments)
            if relation_error is not None:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return relation_error

        if tool_name == "get_task_profile":
            target_error = self._validate_object_target_allowlist(
                tool_name,
                {"object_id": arguments.get("task_id")},
            )
            if target_error is not None:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return target_error

        if tool_name in _OBJECT_TARGET_TOOLS:
            target_error = self._validate_object_target_allowlist(tool_name, arguments)
            if target_error is not None:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return target_error

        if tool_name in _SEND_MESSAGE_ANCHOR_TOOLS:
            anchor_error = self._validate_send_message_anchor_allowlist(tool_name, arguments)
            if anchor_error is not None:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return anchor_error

        if tool_name == "send_email":
            anchor_error = self._validate_email_reply_anchor_allowlist(tool_name, arguments)
            if anchor_error is not None:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return anchor_error

        if tool_name in _ACTIVITY_TARGET_TOOLS:
            target_error = self._validate_activity_target_allowlist(tool_name, arguments)
            if target_error is not None:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return target_error

        if tool_name == "remove_relation":
            edge_error = self._validate_edge_id_allowlist(tool_name, arguments)
            if edge_error is not None:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return edge_error

        if tool_name in _ANNOTATION_TARGET_TOOLS:
            annotation_error = self._validate_annotation_target_allowlist(tool_name, arguments)
            if annotation_error is not None:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return annotation_error

        if tool_name in _PERSON_READ_TOOLS:
            person_error = self._validate_seen_person(tool_name, arguments)
            if person_error is not None:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return person_error

        if tool_name in _PERSON_ROUTE_TOOLS and arguments.get("person_id"):
            route_error = self._validate_person_route(tool_name, arguments)
            if route_error is not None:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return route_error

        if tool_name in _PERSON_FEEDBACK_TOOLS:
            feedback_error = self._validate_person_feedback_allowlist(tool_name, arguments)
            if feedback_error is not None:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return feedback_error

        if tool_name in _REVIEW_MARKER_TARGET_TOOLS:
            marker_error = self._validate_review_marker_target_allowlist(tool_name, arguments)
            if marker_error is not None:
                if self._telemetry is not None:
                    self._telemetry.tool_calls += 1
                return marker_error

        result = assistant_session.run_assistant_tool(user_id, tool_name, arguments)
        if result.status == ToolExecutionStatus.APPROVAL_REQUIRED and result.staged_action:
            self._stage_action(result.staged_action)
            if self._telemetry is not None:
                self._telemetry.tool_calls += 1
            return result

        if result.success and result.output:
            model_output = serialize_tool_output_for_assistant(tool_name, result.output)
            if (
                tool_name in _READ_TOOLS
                or tool_name in _EVIDENCE_WRITE_TOOLS
                or tool_name
                in (
                    "create_scheduled_activity",
                    "create_recurring_scheduled_activity",
                    "cancel_scheduled_activity",
                )
            ):
                for object_id in collect_seen_object_ids_from_bounded_tool(
                    tool_name, model_output.model_visible_payload
                ):
                    self._pending_seen_object_ids.add(object_id)
            for edge_id in collect_seen_edge_ids_from_bounded_tool(
                tool_name, model_output.model_visible_payload
            ):
                self._pending_seen_edge_ids.add(edge_id)
            for candidate in collect_seen_person_candidates(
                tool_name, model_output.model_visible_payload
            ):
                self._pending_seen_person_candidates.add(candidate)
            resolved_person_id = collect_resolved_person_id(
                tool_name, model_output.model_visible_payload
            )
            if resolved_person_id is not None:
                self._pending_resolved_person_ids.add(resolved_person_id)
            for route_token in collect_seen_person_routes(
                tool_name, model_output.model_visible_payload
            ):
                self._pending_seen_person_routes.add(route_token)
            result = result.model_copy(
                update={
                    "model_output_json": model_output.model_output_json,
                    "model_visible_payload": model_output.model_visible_payload,
                }
            )
            if self._telemetry is not None:
                self._telemetry.record_tool(tool_name, result.output)
        else:
            if tool_name == "list_inbox_since_review_marker":
                if result.limit_reached or result.status == ToolExecutionStatus.LIMIT_REACHED:
                    self.inbox_review.mark_limit_reached()
                else:
                    self.inbox_review.mark_failed()
            if self._telemetry is not None:
                self._telemetry.tool_calls += 1
        if tool_name == "list_inbox_since_review_marker" and result.success:
            progress_payload = result.model_visible_payload
            if progress_payload is not None:
                self.inbox_review.observe(
                    arguments=result.validated_arguments or arguments,
                    payload=progress_payload,
                )
        return result

    def _irreversible_staging_error(self, tool_name: str) -> ToolExecutionResult | None:
        if self._has_irreversible_staged():
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="no additional mutation may be staged after an external action",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        if _is_irreversible_tool(tool_name) and self._staged_actions:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="external action cannot be mixed with other staged actions",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        return None

    def _has_irreversible_staged(self) -> bool:
        return any(
            _is_irreversible_tool(action.get("tool_name")) for action in self._staged_actions
        )

    def _stage_action(self, staged_action: dict) -> None:
        if self._is_duplicate_action(staged_action):
            return
        tool_name = staged_action.get("tool_name")
        if self._has_irreversible_staged():
            return
        if _is_irreversible_tool(tool_name) and self._staged_actions:
            return
        self._staged_actions.append(staged_action)

    def _is_duplicate_action(self, staged_action: dict) -> bool:
        for existing in self._staged_actions:
            if existing.get("tool_name") == staged_action.get("tool_name") and existing.get(
                "arguments"
            ) == staged_action.get("arguments"):
                return True
        return False

    def _validate_evidence_allowlist(
        self, tool_name: str, arguments: dict
    ) -> ToolExecutionResult | None:
        evidence_raw = arguments.get("evidence_object_ids")
        if not evidence_raw:
            return None
        for raw_id in evidence_raw:
            try:
                parsed = UUID(str(raw_id))
            except (ValueError, TypeError):
                return ToolExecutionResult(
                    success=False,
                    tool_name=tool_name,
                    error="invalid evidence object id",
                    status=ToolExecutionStatus.TOOL_ERROR,
                )
            if parsed not in self._seen_object_ids:
                return ToolExecutionResult(
                    success=False,
                    tool_name=tool_name,
                    error="evidence object was not exposed in this Assistant turn",
                    status=ToolExecutionStatus.TOOL_ERROR,
                )
        return None

    def _validate_task_relation_allowlist(
        self, tool_name: str, arguments: dict
    ) -> ToolExecutionResult | None:
        raw_ids = []
        single = arguments.get("requested_by_person_id")
        if single:
            raw_ids.append(single)
        for field in (
            "delegated_to_person_ids",
            "waiting_on_person_ids",
            "involved_person_ids",
            "depends_on_task_ids",
        ):
            values = arguments.get(field) or []
            if isinstance(values, list):
                raw_ids.extend(values)
        for raw_id in raw_ids:
            try:
                parsed = UUID(str(raw_id))
            except (ValueError, TypeError):
                return ToolExecutionResult(
                    success=False,
                    tool_name=tool_name,
                    error="invalid task relation object id",
                    status=ToolExecutionStatus.TOOL_ERROR,
                )
            if parsed not in self._seen_object_ids:
                return ToolExecutionResult(
                    success=False,
                    tool_name=tool_name,
                    error="task relation object was not exposed in this Assistant turn",
                    status=ToolExecutionStatus.TOOL_ERROR,
                )
        return None

    def _validate_object_target_allowlist(
        self, tool_name: str, arguments: dict
    ) -> ToolExecutionResult | None:
        raw_id = arguments.get("object_id")
        if raw_id is None:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="object_id is required",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        try:
            parsed = UUID(str(raw_id))
        except (ValueError, TypeError):
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="invalid object id",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        if parsed not in self._seen_object_ids:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="target object was not exposed in this Assistant turn",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        return None

    def _validate_send_message_anchor_allowlist(
        self, tool_name: str, arguments: dict
    ) -> ToolExecutionResult | None:
        supplied: list[tuple[str, object]] = []
        for field in _SEND_MESSAGE_ANCHOR_FIELDS:
            raw = arguments.get(field)
            if raw is None:
                continue
            supplied.append((field, raw))
        if len(supplied) != 1:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="exactly one of conversation_object_id or reply_to_object_id is required",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        _field, raw_id = supplied[0]
        try:
            parsed = UUID(str(raw_id))
        except (ValueError, TypeError, AttributeError):
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="invalid send_message anchor object id",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        if parsed not in self._seen_object_ids:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="target object was not exposed in this Assistant turn",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        return None

    def _validate_email_reply_anchor_allowlist(
        self, tool_name: str, arguments: dict
    ) -> ToolExecutionResult | None:
        raw_id = arguments.get("reply_to_object_id")
        if raw_id is None:
            return None
        try:
            parsed = UUID(str(raw_id))
        except (ValueError, TypeError, AttributeError):
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="invalid send_email reply object id",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        if parsed not in self._seen_object_ids:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="target object was not exposed in this Assistant turn",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        return None

    def _validate_activity_target_allowlist(
        self, tool_name: str, arguments: dict
    ) -> ToolExecutionResult | None:
        raw_id = arguments.get("activity_id")
        if raw_id is None:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="activity_id is required",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        try:
            parsed = UUID(str(raw_id))
        except (ValueError, TypeError):
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="invalid activity id",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        if parsed not in self._seen_object_ids:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="target object was not exposed in this Assistant turn",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        return None

    def _validate_annotation_target_allowlist(
        self, tool_name: str, arguments: dict
    ) -> ToolExecutionResult | None:
        for key, label in (("object_id", "object"), ("label_id", "label")):
            raw_id = arguments.get(key)
            if raw_id is None:
                return ToolExecutionResult(
                    success=False,
                    tool_name=tool_name,
                    error=f"{key} is required",
                    status=ToolExecutionStatus.TOOL_ERROR,
                )
            try:
                parsed = UUID(str(raw_id))
            except (ValueError, TypeError):
                return ToolExecutionResult(
                    success=False,
                    tool_name=tool_name,
                    error=f"invalid {label} id",
                    status=ToolExecutionStatus.TOOL_ERROR,
                )
            if parsed not in self._seen_object_ids:
                hint = " (use list_labels first)" if key == "label_id" else ""
                return ToolExecutionResult(
                    success=False,
                    tool_name=tool_name,
                    error=f"target {label} was not exposed in this Assistant turn{hint}",
                    status=ToolExecutionStatus.TOOL_ERROR,
                )
        return None

    def _validate_review_marker_target_allowlist(
        self, tool_name: str, arguments: dict
    ) -> ToolExecutionResult | None:
        raw_id = arguments.get("after_object_id")
        if raw_id is None:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="after_object_id is required",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        try:
            parsed = UUID(str(raw_id))
        except (ValueError, TypeError):
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="invalid object id",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        if parsed not in self._seen_object_ids:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="target object was not exposed in this Assistant turn",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        return None

    def _validate_person_route(self, tool_name: str, arguments: dict) -> ToolExecutionResult | None:
        try:
            person_id = UUID(str(arguments.get("person_id")))
        except (ValueError, TypeError):
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="invalid person id",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        if person_id not in self._resolved_person_ids:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="person was not resolved in this Assistant turn",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        if tool_name == "record_person_route_choice":
            token = str(arguments.get("route_key") or "")
        elif tool_name == "send_email":
            recipients = arguments.get("to") or []
            if not isinstance(recipients, list) or len(recipients) != 1:
                token = ""
            else:
                try:
                    token = f"email:{normalize_email(str(recipients[0])).canonical_value}"
                except PersonIdentityInputError:
                    token = ""
        else:
            raw_anchor = arguments.get("conversation_object_id") or arguments.get("reply_to_object_id")
            token = f"anchor:{raw_anchor}"
        if (person_id, token) not in self._seen_person_routes:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="person route was not exposed in this Assistant turn",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        return None

    def _validate_seen_person(self, tool_name: str, arguments: dict) -> ToolExecutionResult | None:
        raw_id = arguments.get("person_id")
        try:
            parsed = UUID(str(raw_id))
        except (ValueError, TypeError):
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="invalid person id",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        if parsed not in self._resolved_person_ids:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="person was not resolved in this Assistant turn",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        return None

    def _validate_person_feedback_allowlist(
        self, tool_name: str, arguments: dict
    ) -> ToolExecutionResult | None:
        raw_id = arguments.get("person_id")
        try:
            person_id = UUID(str(raw_id))
            identity = parse_feedback_identity(
                str(arguments.get("identity_type") or ""),
                str(arguments.get("provider") or ""),
                str(arguments.get("realm") or ""),
                str(arguments.get("canonical_value") or ""),
            )
        except (ValueError, TypeError, PersonIdentityInputError):
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="person identity was not exposed in this Assistant turn",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        key = (person_id, *feedback_identity_key(identity))
        if key not in self._seen_person_candidates:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="person identity was not exposed in this Assistant turn",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        return None

    def _validate_edge_id_allowlist(
        self, tool_name: str, arguments: dict
    ) -> ToolExecutionResult | None:
        raw_id = arguments.get("edge_id")
        if raw_id is None:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="edge_id is required",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        try:
            parsed = UUID(str(raw_id))
        except (ValueError, TypeError):
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="invalid edge id",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        if parsed not in self._seen_edge_ids:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error="edge was not exposed in this Assistant turn (use list_neighbors first)",
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        return None


class BoundAssistantToolRunner:
    """Adapter exposing PerTurnToolBudget to the Assistant provider loop."""

    def __init__(self, budget: PerTurnToolBudget, user_id: UUID) -> None:
        self._budget = budget
        self._user_id = user_id

    def __call__(self, tool_name: str, arguments: dict) -> ToolExecutionResult:
        return self._budget.run(self._user_id, tool_name, arguments)

    def commit_model_visible_outputs(self) -> None:
        self._budget.commit_model_visible_outputs()


def _is_irreversible_tool(tool_name: object) -> bool:
    if not isinstance(tool_name, str) or not tool_name:
        return False
    spec = get_tool_spec(tool_name)
    if spec is None:
        return False
    return spec.permission in _IRREVERSIBLE_PERMISSIONS
