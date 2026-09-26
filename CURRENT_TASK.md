# Current task — Task Map V8E2: first-party part_of creation in Graph UI

Task Map V8E1/V8E1R are accepted. Backend composition semantics, Task Profile, workspace hierarchy closure, and V8B2 radial presentation already support confirmed `part_of`.

This phase closes the first-party creation gap in the existing Graph relation dialog.

Client Graph UI only unless a genuinely missing API contract is discovered. No schema/migration. No new relation semantics. No production deploy. No relation-direction repair.

## Canonical meaning

`part_of` is Task composition:

- selected/source Task = child;
- chosen/target Task = parent;
- stored direction is child/source -> parent/target;
- UI label is `Входит в`.

Do not add a reverse `contains` action.
Do not reinterpret legacy `contains`.

## Dialog behavior

Use the existing `GraphWorkspaceScreen._addRelation` dialog.

### When the selected source object is a Task

The relation type dropdown must include:

- `Связано с` -> `related_to`
- `Ссылается на` -> `references`
- `Зависит от` -> `depends_on`
- `Входит в` -> `part_of`

For `part_of`, make the direction explicit in the dialog with a compact helper/caption such as:

`Выбранная задача входит в выбранную родительскую задачу.`

Do not rely on arrow intuition alone.

### When the selected source is not a Task

Do not offer `part_of` in the dropdown.

Existing relation types/behavior remain unchanged.

## Target search for part_of

When `relationType == "part_of"`:

- call the existing object search with `kind: "task"`;
- never show the source Task itself as a target;
- never allow a non-Task target to remain selected;
- when switching into/out of `part_of`, clear any stale selected target and stale result list so a previous non-Task target cannot be submitted accidentally.

Do not add a new search endpoint or client-side whole-dataset fetch.

For the other three relation types, preserve the existing search behavior.

## Creation

On Create for `part_of`, call the existing Relation API exactly as:

- `source_id = selected Task id`
- `target_id = chosen parent Task id`
- `type = "part_of"`

Do not pre-implement composition rules in Flutter.

Canonical backend validation remains authoritative for:

- self-parent;
- second active/proposed parent;
- cycle;
- non-Task endpoint;
- completion-mode compatibility.

Surface the existing backend `ApiException.message` through the existing snackbar path.

Do not silently reverse endpoints after an error.

## Refresh / hierarchy

Keep using the existing `mergeRelationContext(source.id, target:, edge:)` path after successful creation.

That rooted refresh now includes V8E1 confirmed `part_of` closure, so a successful composition link may bring the rest of the confirmed tree into the workspace.

Do not add a second refresh.
Do not mutate canonical controller positions.
Do not request fit solely because the hierarchy changed.
V8B2 presentation may naturally recompute Task geography from the new confirmed hierarchy.

## Existing profile/removal behavior

Do not redesign Task Profile in V8E2.

The newly created user/confirmed `part_of` should appear through existing:
- relation audit row;
- Task Profile parent/children projection after refresh;
- structural child -> parent arrow;
- radial confirmed hierarchy.

Existing user-created relation deletion remains the way to remove it. Do not add reparent/replace semantics.

## Tests

Add focused Flutter/widget tests proving at minimum:

1. Task source relation dropdown contains `Входит в`;
2. non-Task source relation dropdown does not contain `Входит в`;
3. switching to `part_of` clears a previously selected non-Task target/results;
4. `part_of` search calls `/search` with `kind=task`;
5. source Task is excluded from target choices even if search returns it;
6. non-Task results are not selectable for `part_of` even if a mock response is malformed/mixed;
7. Create sends child/source -> parent/target with `type=part_of`;
8. successful creation goes through existing relation-context refresh and the returned relation is visible;
9. backend validation error is shown and endpoints are not reversed/retried;
10. existing `related_to`, `references`, and `depends_on` creation tests/behavior remain unchanged;
11. existing V8B1 relation presentation / Task Profile tests remain green;
12. existing V8B2 hierarchy presentation tests remain green;
13. V8C1 proposal tests remain green;
14. V8C2 pane tests remain green.

Run the focused Graph screen/relation/Profile/hierarchy suites, Flutter analyze on touched files, Linux debug build, and `git diff --check`.

The three historical detail-screen failures may remain only if they are the exact same pre-existing failures already documented. Report them precisely; do not broaden V8E2 to fix them.

## Scope guard

Do not:
- change backend `part_of` validation;
- add automatic reparenting;
- create a Project entity;
- migrate legacy `contains`;
- repair legacy relation direction;
- change V8B2 geometry;
- change People mode semantics;
- change production backend/client deployment.

## Completion

Record in `PROJECT_STATE.md`:

- implementation SHA;
- exact UI wording/direction;
- search filtering behavior;
- request endpoint orientation;
- refresh behavior;
- exact test counts;
- whether backend code changed.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start V8E3.
Do not deploy production.
