# Secretary toolset completeness matrix (PHASE 28D-B-R1)

Capability-oriented view of current Secretary tools. Goal: completeness and truthful contracts, not maximum tool count. Tools remain atomic and composable — no phrase-routing or intent-specific convenience tools.

Status legend: **SUPPORTED** | **PARTIAL** | **INTENTIONALLY DEFERRED** | **MISSING**

## READ

| Capability | Status | Primary tools |
|------------|--------|---------------|
| Semantic / topic discovery | SUPPORTED | `retrieve` |
| Structured / date / status query | SUPPORTED | `query_objects` |
| Exact object read | SUPPORTED | `get_object` |
| Bounded context around object | SUPPORTED | `get_context` |
| Graph neighbors (with `edge.id`) | SUPPORTED | `list_neighbors` |
| Notifications inbox | SUPPORTED | `list_notifications` |
| Current local time / date | SUPPORTED | `get_today` |
| MCP structured search (non-Assistant) | SUPPORTED | `search_objects` (MCP only) |

## INTERNAL MUTATION

| Capability | Status | Primary tools | Notes |
|------------|--------|---------------|-------|
| Create task | SUPPORTED | `create_task` | Agent-proposed origin |
| Edit task fields (title, body, due) | SUPPORTED | `update_task` | Does not change lifecycle status |
| Add task evidence | SUPPORTED | `update_task(evidence_object_ids=…)` | **Additive only** — attaches new evidence; never removes |
| Task lifecycle status | SUPPORTED | `set_task_status` | open / in_progress / done / cancelled / archived |
| Soft-delete task | SUPPORTED | `delete_task` | `status=deleted`; graph history preserved |
| Add relation | SUPPORTED | `link_objects` | Proposed semantic edge |
| Remove relation | SUPPORTED | `remove_relation(edge_id)` | Sets `state=rejected`; no physical delete; requires exact `edge.id` from `list_neighbors` |

### Protected / non-removable relations (`remove_relation`)

- `contains` (thread/source containment)
- Any edge with `origin=source` or `origin=system`
- Removable types (user/agent origin): `references`, `related_to`, `depends_on`

## Documented but NOT implemented (future work)

| Capability | Status | Planned direction |
|------------|--------|-------------------|
| Notification dismiss / read mutation | INTENTIONALLY DEFERRED | Future inbox mutation tools |
| Confirm / reject proposed graph knowledge (non-edge) | PARTIAL | Graph UI + future confirm tools; `remove_relation` covers deactivation |
| External email actions | INTENTIONALLY DEFERRED | Safe External Actions after Source Completion |
| External calendar actions | INTENTIONALLY DEFERRED | Safe External Actions |
| Mattermost / chat sending | INTENTIONALLY DEFERRED | Safe External Actions |
| Cloud / local file mutations | INTENTIONALLY DEFERRED | Beyond explicit intake |
| `scheduled_activity` mutations | INTENTIONALLY DEFERRED | Proactive Secretary (see below) |

## Proactive Secretary — `scheduled_activity` roadmap (documented only)

Not implemented in PHASE 28D-B-R1.

- Real calendar entries remain `kind=event`.
- Inferred/local temporal commitments will use `kind=scheduled_activity` (meetings, calls, webinars, classes, trips, appointments from email/chat).
- Broad work periods / deadline scopes must **not** occupy calendar blocks.
- Source-derived activities normally start `origin=agent`, `state=proposed`.
- Temporal extraction happens asynchronously during ingestion, not when Week UI opens.
- Later messages may revise, move, or cancel the same activity; cancellation ≠ rejected inference.
- Future Week view projects `event` + `scheduled_activity`.
- Most READ operations should reuse `query_objects` / `get_object` / `get_context` / `list_neighbors` / `retrieve`.
- Do not add speculative scheduled-activity tools before backend capability exists.

## Assistant execution truthfulness (PHASE 28D-B-R1)

- `success=true` ≠ `changed=true`.
- Finalization uses deterministic execution-effect facts (`created`, `changed`, `removed`, `no_op`, `failed`).
- Unsupported mutation rule: never approximate with a different mutating tool.
