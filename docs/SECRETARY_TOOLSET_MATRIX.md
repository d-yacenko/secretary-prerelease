# Secretary toolset completeness matrix (PHASE 28D-B-R1)

Capability-oriented view of current Secretary tools. Goal: completeness and truthful contracts, not maximum tool count. Tools remain atomic and composable — no phrase-routing or intent-specific convenience tools.

Status legend: **SUPPORTED** | **PARTIAL** | **INTENTIONALLY DEFERRED** | **MISSING**

## READ

| Capability | Status | Primary tools |
|------------|--------|---------------|
| Semantic / topic discovery | SUPPORTED | `retrieve` (Assistant only) |
| Structured / date / status query | SUPPORTED | `query_objects` |
| Exact object read | SUPPORTED | `get_object` |
| Bounded context around object | SUPPORTED | `get_context` |
| Graph neighbors (with `edge.id`) | SUPPORTED | `list_neighbors` |
| Task profile and derived operational state | SUPPORTED | `get_task_profile` |
| Notifications inbox | SUPPORTED | `list_notifications` |
| Current local time / date | SUPPORTED | `get_today` |
| MCP structured search (non-Assistant) | SUPPORTED | `search_objects` (MCP only) |
| Resolve a named Person | SUPPORTED | `resolve_person` (Assistant only) |
| Person communications, identity candidates, routes | SUPPORTED | `find_person_communications`, `find_person_identity_candidates`, `list_person_routes` (Assistant only) |

## INTERNAL MUTATION

| Capability | Status | Primary tools | Notes |
|------------|--------|---------------|-------|
| Create task | SUPPORTED | `create_task` | Agent-proposed until an approved plan confirms. No `completion_mode` field |
| Edit task fields (title, body, due) | SUPPORTED | `update_task` | Does not change lifecycle status or `completion_mode` |
| Add task evidence | SUPPORTED | `update_task(evidence_object_ids=…)` | **Additive only** — attaches `references`; never removes |
| Actor roles and dependencies | SUPPORTED | `create_task` / `update_task` id lists | Additive `requested_by`, `delegated_to`, `waiting_on`, `involves`, `depends_on` |
| Task composition `part_of` | SUPPORTED | `link_objects` | Child/source → parent/target. Not a field on `create_task` |
| `completion_mode` finite/ongoing | PARTIAL | Human editor; read via `get_object` / `get_task_profile` | Tools cannot set it |
| Planned start/end | PARTIAL | Human editor; read on Task Profile | Tools cannot set it |
| Task lifecycle status | SUPPORTED | `set_task_status` | open / in_progress / done / cancelled / archived |
| Soft-delete task | SUPPORTED | `delete_task` | Tombstone; graph history preserved |
| Add relation | SUPPORTED | `link_objects` | `relation_type` is a free string except `labeled_with` and `part_of` checks |
| Remove relation | SUPPORTED | `remove_relation(edge_id)` | Sets `state=rejected`; no physical delete |
| Labels | SUPPORTED | `list_labels`, `assign_label`, `remove_label`, `create_label`, `rename_label`, `delete_label` | `labeled_with` is not created through `link_objects` |
| Person identity feedback and route memory | SUPPORTED | `confirm_person_identity`, `reject_person_identity`, `retract_person_identity_feedback`, `record_person_route_choice` | Assistant only |
| One-shot or recurring reminder | SUPPORTED | `create_scheduled_activity`, `create_recurring_scheduled_activity`, `cancel_scheduled_activity` | Internal notification, not a Task and not a provider calendar write |
| Send email | SUPPORTED | `send_email` | Approval required before the provider write |
| Send chat message | SUPPORTED | `send_message` | Mattermost, Telegram, and Teams share this tool. Approval required |
| Edit / delete / mark read a Telegram message | SUPPORTED | `edit_message`, `delete_message`, `mark_message_read` | Assistant only. Approval required |
| Create provider calendar event | SUPPORTED | `create_calendar_event` | Approval required |

### Protected / non-removable relations (`remove_relation`)

- `contains` and `labeled_with`
- Any edge with `origin=source` or `origin=system`
- Removable types when origin is `user` or `agent`: `references`, `related_to`, `depends_on`, `part_of`, `requested_by`, `delegated_to`, `waiting_on`, `involves`

## Still not a tool

| Capability | Status | Notes |
|------------|--------|-------|
| Notification dismiss / read mutation | INTENTIONALLY DEFERRED | Inbox review marker is separate and is implemented |
| Confirm / reject a proposed edge from the model | PARTIAL | Human Graph UI confirms or rejects. `remove_relation` rejects. There is no model tool that confirms an edge |
| Cloud / local file mutations | INTENTIONALLY DEFERRED | Beyond explicit intake |
| Manager / organization membership edges | NOT CANONICAL | People workspace rejects `member_of`, `role_at`, `manager_of`, and similar types |

## Time primitives

- `kind=event` is a provider calendar Flow object. `create_calendar_event` writes one after approval.
- `kind=scheduled_activity` is an internal reminder. Create, recur, list via `query_objects`, and cancel are implemented. It is not a Task and it does not write the provider calendar.
- Task `due_at` is editable by `update_task`. Task `planned_start_at` / `planned_end_at` are visible on Task Profile and editable in the human editor, not by tools.
- `get_today` is the current local date-time for the user.

## Assistant execution truthfulness (PHASE 28D-B-R1)

- `success=true` ≠ `changed=true`.
- Finalization uses deterministic execution-effect facts (`created`, `changed`, `removed`, `no_op`, `failed`).
- Unsupported mutation rule: never approximate with a different mutating tool.
