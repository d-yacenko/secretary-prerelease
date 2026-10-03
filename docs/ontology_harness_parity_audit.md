# Ontology / harness parity audit — current snapshot

Audited `main`: `df72686cc447cbc534739307f645420d867db8de`.
Audit date: 2026-10-01.
This document replaces the previous parity snapshot. It records contract truth on that SHA. It does not claim that a live model chooses the right tool.

Contract evidence is static code and the focused tests named in the completion record. Model behavior is `BEHAVIOR_UNVERIFIED` until a later eval run. AH1 did not call an external LLM or the production Assistant.

## Retired verdicts

These statements were true of an older snapshot and are false on the audited SHA. Do not carry them forward.

| Retired claim | Current contract | Evidence |
|---|---|---|
| `CreateTaskInput` / `UpdateTaskInput` omit `completion_mode`, and the prompt never names finite or ongoing | Optional `finite` \| `ongoing` on both inputs. Omit on create stays finite. Omit on update changes nothing. Explicit null is rejected. The system prompt and both tool descriptions name the distinction and forbid inferring `ongoing` from a due date or duration | `backend/app/tools/schemas.py`; `backend/app/tools/assistant_contracts.py` (`create_task`, `update_task`); `backend/app/llm/openai_assistant_provider.py` |
| `link_objects.relation_type` is an unconstrained string and an ontology escape hatch (`OVER_GENERIC`) | `GenericRelationType = Literal["related_to", "references", "depends_on", "part_of"]`, the same set as `GENERIC_RELATION_TYPES` / human `USER_RELATION_TYPES`. Actor roles stay on typed Task fields. `labeled_with` and `contains` are not generic writes | `backend/app/domain/generic_relations.py`; `LinkObjectsInput`; `DomainToolService.link_objects`; `backend/app/services/relation_service.py` |

`get_task_profile` still describes lifecycle and derived operational state only. The payload also carries `completion_mode`, `parent_task`, actor links, and planned start/end. That description gap remains open below. It is not the old write gap.

## Ontology kernel

`docs/architecture.md` defines one ontology and two interfaces. The audited prompt opens with the same meanings: Person = who; Task = commitment / Direction; Flow = evidence / context; Time = when; relations are explicit facts, never inferred (`SYSTEM_INSTRUCTIONS`).

| Meaning | Prompt | Tool / service | Human UI | Verdict |
|---|---|---|---|---|
| Person is who, not an organization chart | Resolve before communication. No organization tool | Person tools and identity feedback. No `member_of` / `manager_of` writer | People workspace rejects those types | `ALIGNED` |
| Task is the commitment. Ongoing is a Direction, not a new kind | `completion_mode` text | `create_task` / `update_task`; domain rejects ongoing marked done | Editor control `task_completion_mode`; profile shows «Направление» | `ALIGNED` |
| Flow is evidence, not automatic workload | Emails, events, files, and notes are not tasks by themselves | `references` via evidence ids or `link_objects` | Graph evidence is a relation, not a second Task | `ALIGNED` |
| Time is when, with separate primitives | `get_today`, Task `due_at`, reminders, calendar event | Distinct tools below | Editor due and planned interval; calendar is Flow | `ALIGNED` for the split. Planned-interval write is in the contract; model use is `BEHAVIOR_UNVERIFIED` |
| Relations are stored facts | Prompt forbids inference | Writers require ids from this turn | Graph dialog writes only the four generic types plus actor fields and labels | `ALIGNED` |

## Exposure

Flags are `assistant_exposed`, `mcp_exposed`, and membership in `PROACTIVE_READ_TOOL_NAMES`. Permission is the registry class. An exposure difference is a defect only when it creates a second meaning or a semantic inability on the interface that is supposed to perform the operation.

```exposure
retrieve assistant=1 mcp=0 proactive=1 permission=READ
query_objects assistant=1 mcp=1 proactive=1 permission=READ
search_objects assistant=0 mcp=1 proactive=0 permission=READ
get_object assistant=1 mcp=1 proactive=1 permission=READ
get_task_profile assistant=1 mcp=1 proactive=1 permission=READ
get_context assistant=1 mcp=1 proactive=1 permission=READ
list_neighbors assistant=1 mcp=1 proactive=1 permission=READ
list_notifications assistant=1 mcp=1 proactive=1 permission=READ
list_labels assistant=1 mcp=1 proactive=0 permission=READ
list_inbox_since_review_marker assistant=1 mcp=1 proactive=0 permission=READ
list_conversation_members assistant=1 mcp=1 proactive=0 permission=READ
resolve_person assistant=1 mcp=0 proactive=0 permission=READ
find_person_communications assistant=1 mcp=0 proactive=0 permission=READ
find_person_identity_candidates assistant=1 mcp=0 proactive=0 permission=READ
list_person_routes assistant=1 mcp=0 proactive=0 permission=READ
get_person_roles assistant=1 mcp=0 proactive=0 permission=READ
find_people_by_role assistant=1 mcp=0 proactive=0 permission=READ
record_person_route_choice assistant=1 mcp=0 proactive=0 permission=ANNOTATE
confirm_person_identity assistant=1 mcp=0 proactive=0 permission=ANNOTATE
reject_person_identity assistant=1 mcp=0 proactive=0 permission=ANNOTATE
retract_person_identity_feedback assistant=1 mcp=0 proactive=0 permission=ANNOTATE
set_inbox_review_marker assistant=1 mcp=1 proactive=0 permission=ANNOTATE
clear_inbox_review_marker assistant=1 mcp=1 proactive=0 permission=ANNOTATE
create_label assistant=1 mcp=1 proactive=0 permission=INTERNAL_WRITE
rename_label assistant=1 mcp=1 proactive=0 permission=INTERNAL_WRITE
assign_label assistant=1 mcp=1 proactive=0 permission=ANNOTATE
remove_label assistant=1 mcp=1 proactive=0 permission=ANNOTATE
delete_label assistant=1 mcp=1 proactive=0 permission=DESTRUCTIVE_INTERNAL_WRITE
create_task assistant=1 mcp=1 proactive=0 permission=INTERNAL_WRITE
update_task assistant=1 mcp=1 proactive=0 permission=INTERNAL_WRITE
set_task_status assistant=1 mcp=1 proactive=0 permission=INTERNAL_WRITE
delete_task assistant=1 mcp=1 proactive=0 permission=DESTRUCTIVE_INTERNAL_WRITE
link_objects assistant=1 mcp=1 proactive=0 permission=INTERNAL_WRITE
remove_relation assistant=1 mcp=1 proactive=0 permission=DESTRUCTIVE_INTERNAL_WRITE
get_today assistant=1 mcp=1 proactive=0 permission=READ
create_scheduled_activity assistant=1 mcp=1 proactive=0 permission=INTERNAL_WRITE
create_recurring_scheduled_activity assistant=1 mcp=1 proactive=0 permission=INTERNAL_WRITE
cancel_scheduled_activity assistant=1 mcp=1 proactive=0 permission=INTERNAL_WRITE
create_calendar_event assistant=1 mcp=1 proactive=0 permission=EXTERNAL_WRITE
send_email assistant=1 mcp=1 proactive=0 permission=COMMUNICATE
send_message assistant=1 mcp=1 proactive=0 permission=COMMUNICATE
edit_message assistant=1 mcp=0 proactive=0 permission=COMMUNICATE
delete_message assistant=1 mcp=0 proactive=0 permission=COMMUNICATE
mark_message_read assistant=1 mcp=0 proactive=0 permission=COMMUNICATE
```

Assistant is the interactive Secretary. MCP exposes the same canonical schemas for shared tools and a structured `search_objects` read instead of `retrieve`. `ExecutionContext.MCP` allows `READ` only. `ANNOTATE`, internal writes, destructive writes, external writes, and `COMMUNICATE` return `REQUIRE_APPROVAL`, and MCP has no trusted approval transport, so those calls do not commit (`backend/app/tools/policy.py`). That is one contract with a closed write door, not a parallel ontology.

Proactive execution is the seven read names above. It cannot mutate.

Person resolution, identity feedback, route memory, and Telegram message edit/delete/mark-read are Assistant-only. That is intentional: those flows are the interactive Secretary, not a second Person model.

## Task parity

Canonical state is the Task row plus relation edges. Provenance for a new agent Task is proposed until an approved action plan confirms. `success=true` is not `changed=true` (`FINALIZATION_INSTRUCTIONS`).

| Operation | Human affordance | Model affordance | Canonical state | Provenance / write | Verdict |
|---|---|---|---|---|---|
| Exact identity / read | Open the Task | `get_object` | Object row, including `completion_mode` | read | `ALIGNED` |
| Semantic discovery | Graph / Search | `retrieve` (Assistant). MCP uses `search_objects` | same objects | read | `INTENTIONALLY_ASYMMETRIC` |
| Structured query | Filters | `query_objects` | same | read | `ALIGNED` |
| Profile | Task Profile | `get_task_profile` | lifecycle `status` plus derived `operational_state` | read. Ignores proposed relations for operational state | `ALIGNED` on the payload. Description names parent, `completion_mode`, and the planned interval |
| Create | Editor | `create_task` | `kind=task`, `status=open` | propose, confirm on approved plan | `INTENTIONALLY_ASYMMETRIC` |
| Finite vs ongoing | Editor `task_completion_mode` | `completion_mode` enum | column; ongoing cannot become `done`; `part_of` matrix stays in the domain | write | `ALIGNED` |
| Title / body / due | Editor | `update_task` | columns | approval, then write. Status is untouched | `ALIGNED` |
| Lifecycle | Status control | `set_task_status`: open, in_progress, done, cancelled, archived | `status` | approval | `ALIGNED` |
| Soft delete | Delete | `delete_task` | `status=deleted`, history kept | destructive approval | `ALIGNED` |
| Evidence `references` | Link as основание | `evidence_object_ids` or `link_objects(references)` | edge | additive. Removal is `remove_relation` | `ALIGNED` |
| `requested_by`, `delegated_to`, `waiting_on`, `involves` | Actor controls | same id fields on create/update | typed edges, not generic types | additive. Removal is `remove_relation` | `ALIGNED` as a contract. Role meanings are not in the system prompt |
| `depends_on` | Graph type | `depends_on_task_ids` or `link_objects` | edge; source depends on target | additive / link | `ALIGNED` |
| `part_of` | «Входит в», child → parent | `link_objects` only | one parent, no cycle, completion-mode matrix | tool text states direction. Prompt does not name `part_of` | `ALIGNED` as a contract |
| `related_to` | Graph type | `link_objects` | generic edge | approval | `ALIGNED` |
| Remove / reject edge | «Удалить связь». User origin is physical DELETE. Agent origin is reject-in-place | `remove_relation(edge_id)` sets `state=rejected` | removable user/agent types only | model path does not physically delete | `INTENTIONALLY_ASYMMETRIC` |
| Confirm an existing proposal | Graph confirm | no confirm tool. A new write confirms through the approval card | `POST /relations/{id}/decision` exists for the human path | model cannot confirm an already proposed edge | `INTENTIONALLY_ASYMMETRIC` |
| Labels | Label UI | label tools. `assign_label` / `remove_label` are `ANNOTATE` and run immediately | `labeled_with` | vocabulary changes require approval | `ALIGNED` |
| Planned start / end | Editor writes `planned_start_at` / `planned_end_at` | `create_task` / `update_task` write the pair together. Profile reads it | columns. Both boundaries or neither. End after start | approval. Omit leaves the interval unchanged. Both null on update clears it | `ALIGNED` as a contract. `BEHAVIOR_UNVERIFIED` |
| Duplicate avoidance | Human sees existing Tasks | prompt: `retrieve` before `create_task`; do not create when a likely non-terminal equivalent exists | no deterministic duplicate service | instruction only | `BEHAVIOR_UNVERIFIED` |
| Operational vs lifecycle | Profile shows both | tool description separates `status` and `operational_state` | derived, proposed edges ignored | read | `ALIGNED` |

Actor and evidence lists do not clear omitted ids. The update description says removal goes through `list_neighbors` then `remove_relation`. The system prompt says that only for evidence and `related_to`.

## Person parity

| Operation | Human affordance | Model affordance | Canonical state | Provenance / write | Verdict |
|---|---|---|---|---|---|
| Exact Person | People / object | `get_object` after resolution | Person object | read | `ALIGNED` |
| Ambiguity | Human picks | `resolve_person`; prompt says ask, do not merge names | candidates | read | `ALIGNED` as a contract. `BEHAVIOR_UNVERIFIED` |
| Communications | Person communications | `find_person_communications` | communication objects | Assistant only | `INTENTIONALLY_ASYMMETRIC` |
| Identity candidates and feedback | Confirm / reject / retract | `find_person_identity_candidates`, `confirm_person_identity`, `reject_person_identity`, `retract_person_identity_feedback` | identity evidence | `ANNOTATE`, immediate, Assistant only. Must repeat a candidate shown this turn | `INTENTIONALLY_ASYMMETRIC` |
| Routes and memory | Route choice | `list_person_routes`, `record_person_route_choice` | route memory | Assistant only | `INTENTIONALLY_ASYMMETRIC` |
| Actor roles on Tasks | Task actors | typed person id fields | actor edges | see Task table | `ALIGNED` |
| Organization / manager | Rejected in People | no tool | not canonical | fail closed | `ALIGNED` |

`test_owned_source_identity_is_conflict_not_confirmable` fails on this checkout. `find_person_identity_candidates` omits an owned identity unless `_grounded_duplicate` is true (`PersonAssistantService._source_candidates`), so the expected non-confirmable conflict row is absent. AH1 does not change that service. Treat the disagreement as unresolved test evidence, not as a second Person model.

## Flow parity

| Operation | Human affordance | Model affordance | Canonical state | Provenance / write | Verdict |
|---|---|---|---|---|---|
| Retrieve / query / read / context | Search, object, neighbors | `retrieve` or `search_objects`, `query_objects`, `get_object`, `get_context`, `list_neighbors` | Flow objects stay their kinds | read. `edge.id` comes from neighbors | `ALIGNED` |
| Provenance and neighbors | Graph neighbors | `list_neighbors` | edges with ids | read | `ALIGNED` |
| Evidence vs workload | Linking a file does not create a Task | prompt and evidence ids | `references` | write only when asked | `ALIGNED` |
| Provider-neutral email / chat / calendar | One object model | `send_email`, `send_message`, `create_calendar_event`. Provider is an argument, not a tool name | provider metadata stays on the object | approval before the provider write | `ALIGNED` |
| Reply to an exact object | Reply on that object | `reply_to_object_id` on the matching channel | same object | approval. Draft intent must not call the send tool | `ALIGNED` as a contract. `BEHAVIOR_UNVERIFIED` |
| File / note / event / message kinds | Distinct kinds | no parallel kind tools | `kind` on the object | read | `ALIGNED` |
| Inbox review frontier | «Просмотрено досюда» | `list_inbox_since_review_marker`, `set_inbox_review_marker`, `clear_inbox_review_marker` | global Secretary marker, not provider unread | annotate, no provider read-state write | `ALIGNED` |
| Conversation members | Read a thread | `list_conversation_members` | member objects | read. Does not move the marker | `ALIGNED` |

Telegram `edit_message`, `delete_message`, and `mark_message_read` are Assistant-only `COMMUNICATE` tools and require approval. They are provider message operations, not a second ontology.

## Time parity

| Operation | Human affordance | Model affordance | Canonical state | Provenance / write | Verdict |
|---|---|---|---|---|---|
| Current local date/time | Clock | `get_today` | user-local now | read | `ALIGNED` |
| Task due | Editor | `due_at` | Task column | write | `ALIGNED` |
| Planned interval | Editor | `create_task` / `update_task` | Task columns | pair write. Not `due_at`, a reminder, or calendar busy time | `ALIGNED` as a contract. `BEHAVIOR_UNVERIFIED` |
| Calendar Flow | Calendar objects | `query_objects` / `create_calendar_event` | `kind=event` after approval | external write | `ALIGNED` |
| One-shot reminder | Reminder, not a Task | `create_scheduled_activity` | `kind=scheduled_activity` | internal notification only | `ALIGNED` |
| Recurring reminder | Recurrence | `create_recurring_scheduled_activity` | schedule until `cancel_scheduled_activity` | internal | `ALIGNED` |
| Lifecycle interaction | Done is status | `set_task_status`. Ongoing cannot be done | status vs `completion_mode` | domain guard | `ALIGNED` |

## Relation parity with the accepted Graph

Human Graph writes `related_to`, `references`, `depends_on`, and `part_of`, plus actor roles and labels. The model uses that same generic literal and the same typed actor fields. It cannot invent a relation type: the schema enum and `DomainToolService.link_objects` both refuse anything outside `GENERIC_RELATION_TYPES`.

`remove_relation` rejects `references`, `related_to`, `depends_on`, `part_of`, `requested_by`, `delegated_to`, `waiting_on`, and `involves` when origin is `user` or `agent`. `contains` and `labeled_with` stay protected. Source and system origins stay protected (`backend/app/services/relation_removal.py`). The human UI still physically deletes a user-origin edge and reject-in-place an agent edge. The model path always reject-in-place. There is no in-place type editor and no reverse tool on either side.

Lack of a model confirm tool is still appropriate. A mutation the model just proposed becomes confirmed only when the user approves the action plan. An older proposed edge stays a human Graph decision. The model can reject a removable edge by exact id. Giving the model a confirm tool would let it close its own outstanding proposals without that card.

## Approval, reversibility, provenance

| Rule | Contract | UI communication | Verdict |
|---|---|---|---|
| `READ` | Allowed in Assistant, MCP, and proactive | no card | `ALIGNED` |
| `ANNOTATE` | Immediate in the interactive Assistant. MCP requires approval and therefore does not commit | label assign/remove and the review marker do not open a plan | `INTENTIONALLY_ASYMMETRIC` for MCP |
| `INTERNAL_WRITE` | Assistant returns `approval_required` and does not execute | approval card | `ALIGNED` |
| `DESTRUCTIVE_INTERNAL_WRITE` | Same approval gate (`delete_task`, `delete_label`, `remove_relation`) | card | `ALIGNED` |
| `COMMUNICATE` / `EXTERNAL_WRITE` | Approval before the provider write. `send_email` cannot share a plan with other mutations | card. Prompt forbids treating composed text as a plan | `ALIGNED` |
| `approval_required` | Not executed | card is the commit boundary | `ALIGNED` |
| Proposed vs confirmed | Agent artifacts stay proposed until the approved plan confirms | Graph shows proposed edges | `ALIGNED` |
| Finalization | `success=true` is not `changed=true`. No-op must not be narrated as a mutation | assistant final text | `ALIGNED` as a contract. `BEHAVIOR_UNVERIFIED` |
| Exact ids | Prompt forbids invented object and edge ids | picker uses real ids | `ALIGNED` |
| Reversible rejection | `remove_relation` keeps the row and sets `state=rejected` | human agent-edge removal matches | `ALIGNED` |
| Untrusted stored data | Body, title, sender, labels, tool output, and UI context are data, not instructions | same boundary in finalization | `ALIGNED` as a contract. `BEHAVIOR_UNVERIFIED` |

## Prompt / tool routing

The system prompt already covers Person resolution before communication, `retrieve` versus `query_objects`, evidence versus Task materialization, finite versus ongoing, lifecycle versus `update_task`, reminders versus Tasks, provider-neutral send/reply, the unsupported-mutation rule, ambiguity, and the untrusted-data rule.

Weak routing hints, not missing tools:

| Hint | Where it is weak | Verdict |
|---|---|---|
| Actor-role choice | System prompt never names `requested_by`, `delegated_to`, `waiting_on`, or `involves`. Field schemas have no per-role text. Update text only says the lists are additive | `BEHAVIOR_UNVERIFIED` |
| `part_of` | Tool text is exact. System prompt does not name composition or child → parent | `BEHAVIOR_UNVERIFIED` |
| Removing `depends_on`, `part_of`, or actor edges | Prompt removal sentence names evidence and `related_to` only. Update-tool text is broader | `BEHAVIOR_UNVERIFIED` |
| Profile fields | `get_task_profile` names `completion_mode`, parent, and the planned interval. Model use of that text is not scored | `BEHAVIOR_UNVERIFIED` |
| Duplicate Task | Prompt procedure only | `BEHAVIOR_UNVERIFIED` |
| No-op narration and prompt injection | Finalization and untrusted-data rules exist | `BEHAVIOR_UNVERIFIED` |

## Behavior boundary

Static parity is not evidence that the agent works well. The scenario catalogue is `docs/SECRETARY_AGENT_EVAL_SCENARIOS.md`. AH1 did not execute it against a model.

## Next slices

Do not start these inside AH1.

1. **AH2-P — prompt routing sentences.** Evidence: `SYSTEM_INSTRUCTIONS` omits actor-role names, `part_of`, and removal of those edges, while the tool texts already define them. User-facing consequence: the model can pick `related_to` or a new Task for «жду ответ» or «входит в». Smallest surface: `SYSTEM_INSTRUCTIONS` only. No schema, migration, or UI. Production effect requires a backend deploy and a human gate. Behavior stays unverified until AH2-M.
2. **AH2-D — tool descriptions for profile and actor fields.** Evidence: `get_task_profile` description and actor JSON fields. User-facing consequence: a read can return the parent or Direction and the model can ignore it. Smallest surface: description strings in `backend/app/tools/assistant_contracts.py`. No domain change. Deploy and human gate to affect production. No migration.
3. **AH2-T — planned interval write.** The static `MODEL_GAP` is closed: `create_task` and `update_task` write `planned_start_at` / `planned_end_at` as one pair through `TaskMutationService.patch_task_fields` and `PATCH /tasks/{id}`. Columns already existed, so no migration was added. Model behavior remains `BEHAVIOR_UNVERIFIED` until AH2-M. Production rollout is still pending.
4. **AH2-E — executable eval harness.** Evidence: the scenario catalogue. User-facing consequence: none until a model is scored. Smallest surface: a harness that checks tool traces and final-state fixtures without a live LLM. No deploy.
5. **AH2-M — real-model eval.** Evidence: every `BEHAVIOR_UNVERIFIED` row. User-facing consequence: unknown until scored. Smallest surface: one authorized provider run of the catalogue, then targeted prompt or tool fixes. Separate authorization. No schema change by itself.
6. **AH2-C — model confirm of an existing proposal.** Not next. Evidence: human Graph confirms; the model can reject and can confirm only its own new plan. User-facing consequence: the model cannot accept an older proposal. Smallest surface, if a later eval shows it matters: one decision tool on the existing relation decision endpoint. Backend, deploy, human gate. No relation editor and no new type.
