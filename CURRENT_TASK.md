# CURRENT_TASK

HOLD

## REL1D-HG4B — COMPLETE

### Result

Client-only instant Task-actor feedback for a Person selected from the unrooted People overview.

Implementation SHA: `d04ab40c8a3a2a36c38cfa2ad7c65d57232c22fe`

Files:
- `client/lib/graph/graph_workspace_screen.dart`
- `client/test/graph/person_task_bridge_test.dart`

### Behavior

- Foreground mutation apply/reconcile gating uses `_personDetailStillCurrent` (People mode + same tracked Person) and no longer requires `controller.rootId == personId`.
- Successful add/remove/confirm/reject updates the visible Person detail immediately while overview stays unrooted.
- Background reconciliation still uses the single-flight generation-aware path; rooted install is unchanged; unrooted responses update only the detail card.
- Prior HG3.2.x rooted invariants remain: stale detail-load guards, pending reconcile target, authoritative `openTaskCount` preservation.

### Checks

- Focused Flutter suite (`person_task_bridge`, `relation_target_label`, `graph_relation_target_disambiguation`): 39 passed, 0 failed
- `dart analyze lib/graph/graph_workspace_screen.dart`: 0 errors (pre-existing info only)
- `git diff --check` clean

### Boundaries

No backend/API/schema, People overview paging/HG4C, production, provider/model, or role-import image extraction change.

No next coding phase is authorized by this HOLD.
