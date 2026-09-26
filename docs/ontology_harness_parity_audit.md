# Ontology / Harness parity audit — H1

Diagnosis only. No tool schema, prompt, domain service, UI, or migration was changed.

North star from `docs/architecture.md`: one ontology, two interfaces. Actor/Person is who. Task/Commitment is what must happen. Flow is what happened and the evidence around Tasks. Time is a cross-cutting dimension. Human UI and the model Harness must share meaning, state, and provenance.

Verdicts: `ALIGNED`, `MODEL_GAP`, `HUMAN_GAP`, `OVER_GENERIC`, `PARALLEL_SEMANTICS`, `STALE_CONTRACT`, `INTENTIONALLY_ASYMMETRIC`.

Assistant and MCP exposure come from `TOOL_SPECS` in `backend/app/tools/registry.py`. Assistant JSON text comes from `backend/app/tools/assistant_contracts.py`. The system prompt is `SYSTEM_INSTRUCTIONS` in `backend/app/llm/openai_assistant_provider.py`.

## Task

| Capability | Meaning | Human | Assistant | MCP | Implementation | Write semantics | Verdict | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Discovery | Find Tasks by topic or by status/date | Graph, search, Today | `retrieve`, `query_objects` | `query_objects`, `search_objects` | retrieval and query services | read | `ALIGNED` | `registry.py`; prompt distinguishes retrieve vs query_objects |
| Exact read / bounded context | One object and a bounded neighborhood of content | Object detail, Graph | `get_object`, `get_context` | same | graph/context services | read | `ALIGNED` | `get_object`, `get_context` contracts |
| Task Profile | Lifecycle, actors, dependencies, composition, evidence, derived operational state | Task Profile UI | `get_task_profile` | same | `TaskProfileService` | read | `ALIGNED` | `TaskProfileOut`; tool text separates `status` from `operational.operational_state` |
| Create Task | Canonical `kind=task`, starts open | Task editor | `create_task` | same | `DomainToolService.create_task` | propose, then confirm on an approved plan | `INTENTIONALLY_ASYMMETRIC` | `CreateTaskInput`; prompt: new tasks start `status=open` |
| Edit title/body/due | Ordinary Task fields | Editor | `update_task` | same | domain update | same propose/confirm split | `ALIGNED` | `UpdateTaskInput`; contract says it does not change status |
| Lifecycle status | open, in_progress, done, cancelled, archived | Status actions | `set_task_status` | same | `TaskMutationService.set_task_status` | internal write, approval | `ALIGNED` | `SetTaskStatusValue` |
| Soft delete | Hide the Task, keep graph history | Delete action | `delete_task` | same | `soft_delete_task` | destructive internal write | `ALIGNED` | `delete_task` contract |
| `completion_mode` read | `finite` Task vs `ongoing` Direction. Not a separate kind | Profile and editor show «Направление» | visible on `ObjectOut` inside `get_object` / `get_task_profile` | same | `completion_mode` on the Task row | read | `ALIGNED` | `ObjectOut.completion_mode`; `task_management_actions.dart` |
| `completion_mode` create/edit | Human can set finite or ongoing. Domain rejects an ongoing Task that would break `part_of` or become done | Editor control `task_completion_mode` | no parameter | no parameter | `CreateTaskInput` and `UpdateTaskInput` omit the field | model cannot express it | `MODEL_GAP` | schemas stop at due/evidence/actors/dependencies. Prompt never names finite or ongoing |
| Evidence `references` | Task is source, evidence object is target | Graph dialog «Ссылается на»; Profile | `create_task` / `update_task` `evidence_object_ids` | same | `TaskRelationService.attach_evidence` and domain `_attach_evidence_references` | additive; removal is `remove_relation` | `ALIGNED` | prompt states additive evidence and `list_neighbors` then `remove_relation` |
| Actor roles | `requested_by`, `delegated_to`, `waiting_on`, `involves`: Task → Person | Profile sections | same id lists on create/update | same | `TaskRelationService.add_actor` | additive; removal is `remove_relation` | `ALIGNED` | `TASK_ACTOR_ROLES`; profile lists. Prompt does not name the four roles |
| `depends_on` | Dependent Task → prerequisite Task | Graph dialog «Зависит от»; Profile | `depends_on_task_ids` | same | `TaskRelationService.add_dependency` | additive; removal is `remove_relation` | `ALIGNED` | `add_dependency` stores task → dependency |
| `part_of` read | Child/source → parent/target. Profile `parent_task` is the outgoing target; `child_tasks` are incoming sources | Profile «Входит в» / «Состав»; map arrow | returned by `get_task_profile` | same | `TaskProfileService._links` | read | `ALIGNED` | `TaskProfileOut.parent_task`, `child_tasks`. The tool blurb does not mention those fields |
| `part_of` write | One non-rejected parent, no cycle, completion-mode matrix | Graph dialog «Входит в» | `link_objects` only | same | `validate_part_of_edge` | propose or confirmed after approval | `ALIGNED` | `link_objects` text: source is the child, target is the parent, do not infer it |
| Proposed / confirmed / rejected | State is orthogonal to type | Graph confirm/reject | create path proposes; `remove_relation` rejects | same | provenance on edges | no model tool confirms an edge | `INTENTIONALLY_ASYMMETRIC` | human decision UI; `remove_relation` sets `rejected` |
| Due | Task deadline | Editor | `due_at` on create/update | same | Task column | write | `ALIGNED` | `CreateTaskInput.due_at` |
| Planned start/end | Execution interval on the Task | Editor patches `planned_start_at` / `planned_end_at` | not a tool field | not a tool field | `ObjectUpdate` and profile read | read only for the model | `MODEL_GAP` | `TaskProfileOut.planned_start_at`; `task_management_actions.dart` |
| Generic graph write | A free relation string | Human dialog only offers four Task types | `link_objects.relation_type` is an unconstrained string | same | `DomainToolService.link_objects` | can store types the UI does not project | `OVER_GENERIC` | schema `relation_type: str`. Service rejects only `labeled_with`, and runs `part_of` checks only when the type is `part_of` |

`CreateTaskInput` / `UpdateTaskInput` do not include `completion_mode`. That spot-check is a real write gap, not a stale suspicion. Read is already on the object payload. The prompt’s unsupported-mutation rule tells the model not to fake the change with another tool, so the gap fails closed, but the model still cannot perform the operation the editor can.

## Person / Actor

| Capability | Meaning | Human | Assistant | MCP | Implementation | Verdict | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Resolve a name | Do not guess that two names are one Person | People workspace | `resolve_person` before retrieve | not exposed | person identity service | `INTENTIONALLY_ASYMMETRIC` | prompt; `mcp_exposed=False` |
| Exact identities | Read effective identity | People detail | `resolve_person` result | not exposed | `PersonIdentityService` | `ALIGNED` | `resolve_person` contract |
| Identity candidates | Discover possible matches | People UI | `find_person_identity_candidates` | not exposed | identity candidate service | `ALIGNED` | registry |
| Confirm / reject / retract | User feedback on identity evidence | People correction | three annotate tools | not exposed | identity feedback | `ALIGNED` | `confirm_person_identity`, `reject_person_identity`, `retract_person_identity_feedback` |
| Routes | List communication routes | People routes | `list_person_routes` | not exposed | route service | `ALIGNED` | prompt: call it after resolve |
| Remember a route | Record the chosen route | People UI | `record_person_route_choice` | not exposed | route memory | `ALIGNED` | registry, annotate permission |
| Communications | Flow objects for a resolved Person | People graph | `find_person_communications` | not exposed | communication lookup | `ALIGNED` | prompt forbids guessing |
| Send | Email or chat through a route from this turn, after approval | Compose / reply | `send_email`, `send_message` | both exposed | external action services | `ALIGNED` | prompt: no provider-specific send tools; approval card is the commit |
| Actor questions | Who requested, who is delegated, whom we wait on | Profile sections | `get_task_profile` lists | same | canonical actor edges | `ALIGNED` | profile fields, not free-text search |
| Organization / manager | `member_of`, `manager_of`, and similar | not a product relation | no tool | no tool | People workspace forbids those edge types | future ontology | `_FORBIDDEN_EDGE_TYPES` in `person_graph_workspace_service.py` |

Person tools are Assistant-only by `mcp_exposed=False`. That is a chosen exposure split. The canonical services exist. An MCP client cannot run the identity session, but that does not create a second Person ontology.

## Flow

| Capability | Verdict | Evidence |
| --- | --- | --- |
| Semantic discovery | `ALIGNED` | `retrieve` |
| Structured/date/status search | `ALIGNED` | `query_objects`; MCP also has `search_objects` |
| Exact read and bounded content | `ALIGNED` | `get_object`, `get_context` |
| Neighbors and provenance | `ALIGNED` | `list_neighbors` returns `edge.id`, origin, and state |
| Flow as Task evidence | `ALIGNED` | prompt: emails, events, files, and notes are evidence, not Tasks. `evidence_object_ids` stores Task → evidence `references` |
| Reply through an exact communication object | `ALIGNED` | `send_email(reply_to_object_id)`, `send_message(reply_to_object_id)` |
| Provider send boundary | `INTENTIONALLY_ASYMMETRIC` | one `send_message` for Mattermost, Telegram, and Teams. Provider is an execution argument, not a new kind |
| Media / file / calendar / message objects | `ALIGNED` | they remain Flow kinds. Calendar create and message edit/delete/read are actions on those objects, not new domain types |

No source-specific Assistant tool name invents a parallel object kind. `search_objects` is the MCP search twin of Assistant `retrieve`, not a second ontology.

## Time

| Capability | Verdict | Evidence |
| --- | --- | --- |
| Current date/time | `ALIGNED` | `get_today` |
| Task due read/write | `ALIGNED` | profile and `due_at` |
| Task planned interval | `MODEL_GAP` | read on the profile; human editor writes it; tools do not |
| Calendar Flow | `ALIGNED` | `kind=event`; `create_calendar_event` after approval |
| Reminder | `ALIGNED` | `create_scheduled_activity` creates an internal notification. Prompt forbids using `create_task` as the scheduler |
| Recurrence | `ALIGNED` | `create_recurring_scheduled_activity` until `cancel_scheduled_activity` |
| Conflict with Task | none found | scheduled activity is a temporal execution primitive. It is not a Commitment and it does not write the provider calendar |

## Escape hatches

`link_objects` JSON schema accepts any `relation_type` string. `DomainToolService.link_objects` refuses `labeled_with` and refuses a self-link. `GraphService.create_edge` then refuses a second `labeled_with` path and, only when the type is `part_of`, calls `validate_part_of_edge`. Any other string is stored.

That overlaps the specialized writers:

- evidence, actors, and dependencies also have typed fields on `create_task` / `update_task`;
- `part_of` has no typed field and correctly goes through `link_objects`;
- labels correctly refuse `link_objects` and use `assign_label`.

Typed Task fields are useful composability. `part_of` through `link_objects` is the right single writer. An unconstrained `relation_type` is an ontology escape hatch: the model can store a type that Task Profile, the Graph dialog, and the map grammar do not understand. Human `RelationService` is tighter: `USER_RELATION_TYPES` is `related_to`, `references`, `depends_on`, `part_of`.

`remove_relation` is narrower than `link_objects`. `REMOVABLE_EDGE_TYPES` is the eight semantic types above. `contains` and `labeled_with` stay protected. Source and system origins stay protected. The model cannot delete containment by rejecting it.

Assistant vs MCP, from the registry flags:

- Assistant only: `retrieve`, the Person tools, and Telegram `edit_message` / `delete_message` / `mark_message_read`.
- MCP only: `search_objects`.
- Shared: Task, label, relation, reminder, calendar, `send_email`, and `send_message`.

The flags are explicit. They are an exposure split, not an accidental second schema.

## Prompt comprehension

`SYSTEM_INSTRUCTIONS` does distinguish Task lifecycle from operational state only indirectly: lifecycle is in the prompt, operational state is in the `get_task_profile` description. That description is sufficient once the tool is called.

The prompt does not explain finite Task versus ongoing Direction. That semantics is also absent from the create/update tool text. This is a prompt gap and the same write gap as the missing field.

Actor roles are stored and returned canonically. The prompt treats People as identity and route targets. It does not say that “who requested this” is `get_task_profile.requested_by`. The data path is canonical; the first-attempt hint is thin.

`part_of` is explicit on `link_objects` and absent from the system prompt. The tool text is the right place, and it says composition, child → parent, one parent, do not infer. Removal of `part_of` and actor edges is possible through `remove_relation`, but the prompt only names evidence and `related_to`. That is a prompt gap, not a missing tool.

Flow-as-evidence is explicit. The prompt says not to materialize every message or event as a Task, and not to use `create_task` as a reminder.

No prompt sentence still says that email, calendar, chat send, or scheduled-activity tools are unimplemented. Those sentences in `docs/SECRETARY_TOOLSET_MATRIX.md` were the stale contract. The prompt matches the registry more closely than that matrix did before this audit.

Important behavior that exists only as backend validation, with a short tool hint: the `part_of` completion-mode matrix and cycle rejection. The tool says one parent and both ends are Tasks. It does not spell the finite/ongoing matrix. Validation still rejects the bad write.

## Gap list for H2

### Blocking semantic parity gaps

1. The model cannot set `completion_mode`. The editor and domain can. Read already works. Smallest H2: optional `completion_mode` on `CreateTaskInput` and `UpdateTaskInput`, with `finite` / `ongoing` in the tool text, and the existing domain guards left in place.

### Risky escape hatches / ambiguous contracts

1. `link_objects.relation_type` is not limited to the human relation allowlist. Smallest H2: reject types outside the canonical user/actor set before `create_edge`. Do not add a new relation.
2. The system prompt under-names which edges `remove_relation` may reject (`part_of` and actor roles are legal; the prompt mentions evidence and `related_to`). Smallest H2: one sentence in the prompt or the `remove_relation` description. No new tool.

### Useful but non-blocking affordance gaps

1. Planned start/end are human-editable and profile-readable, not tool-writable. Smallest H2: optional planned fields on `update_task` only if the editor contract should be mirrored.
2. `get_task_profile` returns parent, children, actors, and `completion_mode`, but its description names lifecycle and operational state only. Smallest H2: extend that description. No schema change.
3. Person identity tools are Assistant-only. Smallest H2, only if an MCP client must resolve people: set `mcp_exposed=True` for those read/annotate specs. Not required for the human People UI.

### Intentional asymmetries

1. Model writes are proposed until an approved plan confirms them. Human Graph creates a confirmed user edge.
2. The model has no “confirm edge” tool. The human confirm/reject controls are the approval surface. `remove_relation` is the reject path.
3. `retrieve` versus MCP `search_objects`, and Assistant-only Telegram message maintenance, are exposure choices. They share the same objects.
4. `part_of` is created through `link_objects` rather than `create_task`. The direction text is already on that tool.

### Future ontology, not a tool gap

Manager, member-of, and organization edges are not canonical. `person_graph_workspace_service.py` forbids `member_of`, `role_at`, `manager_of`, `works_with`, `colleague`, `manager`, and `friend`. Do not add tools or People-visual semantics for them in H2.

## Recommendation

1. The current Harness is sufficient for a People visual prototype without an ontology change. Resolve, identity feedback, routes, communications, and Task actor reads already use the canonical Person and actor edges.
2. No H2 fix should block that prototype. `completion_mode` and the `link_objects` allowlist are Task-contract hardening. They do not change who a Person is or which actor edge is canonical.
3. Before a later Task stabilization pass, do the blocking `completion_mode` field and the `link_objects` allowlist. Prompt/description sentences and planned-interval fields can wait in the same pass. Organization edges stay out until a separate ontology decision.
