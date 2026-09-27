# Current task — Graph G3A: semantically complete constellation windows

Release R3 is accepted.

Production remains:
`6a38a22303c0af882fcb32c4a7ac91b708cb52f4`

Alembic:
`0050`

This task authorizes one Graph architecture corrective on `main` only.

NO production deploy is authorized.

Do not start G3B automatically.
Do not start S3 or H2D.

## Why this replaces the proposed Node Limit setting

Do NOT add a user-facing raw `node_limit` control in this task.

The human found the deeper UX problem:

A map that silently cuts arbitrary nodes inside a visible structure is not trustworthy. Even if 60 of 80 visible nodes are correct, the user cannot know whether a missing child, Direction, Flow item, or edge changes the meaning of what is currently visible.

The required contract is:

**If a Task constellation / Direction is shown in overview, its semantic unit is shown whole. Bound the number of whole semantic units in the current window, not arbitrary nodes inside them.**

For larger graphs, the eventual interaction is a lens over a larger surface:
- pan toward another area;
- adjacent whole constellations appear;
- distant whole constellations leave memory/view;
- the client never needs to render the entire graph at once.

G3A builds the semantic window and adjacent-window primitives.
G3B will later bind those primitives to actual pan thresholds.

## Semantic definitions

### Task constellation

A Task constellation is the complete active current-user `part_of` tree rooted at its topmost active Task.

- `part_of` semantics remain child/source -> parent/target.
- A Task with no active confirmed `part_of` parent is a constellation root.
- A standalone Task is a one-Task constellation.
- Nested Directions are NOT separate pages if they belong to the same top-level `part_of` tree.
- Existing V8B1 forest invariants remain authoritative.

### Explicit evidence belonging to a constellation

For every Task in the constellation, include the G2 priority Task<->Flow evidence:

- current user;
- `state == confirmed`;
- `origin in {user, agent}`;
- relation type in `references | related_to | depends_on`;
- exactly one endpoint is that Task;
- other endpoint is active/visible non-Task.

A shared Flow endpoint used by several Tasks in the same window is one node and all eligible persisted edges are retained by G1R edge closure.

### What is NOT required for overview completeness

Incidental `source` / `system` ordinary neighbors are NOT part of the overview semantic-completeness contract.

Do not let them determine which constellation fits in an overview window.

They remain discoverable through:
- the canonical direct relation inventory;
- rooted/local expansion such as `Показать связи`;
- search/navigation.

This distinction is deliberate:
overview = trustworthy semantic structure;
local expansion = additional surrounding context.

## Part A — replace node-wise overview admission with constellation-wise windowing

Refactor ONLY the Tasks overview path.

Do not use the current sequence:
`seed nodes -> arbitrary admission until node_limit -> trim individual nodes`
as the final overview membership rule.

Instead:

1. determine all active Task constellations for the current user using confirmed `part_of`;
2. compute each constellation as an indivisible unit:
   - every active Task in its tree;
   - every G2 priority Flow endpoint attached to those Tasks;
   - all persisted non-rejected edges whose endpoints are in that admitted unit/window via existing G1R closure;
3. order constellations deterministically;
4. pack whole constellations into semantic windows;
5. never split a constellation merely to hit the soft window target.

### Deterministic constellation ordering

Preserve the spirit of current seed priority.

For each constellation derive a stable priority key from its active Task members using the existing seed ordering dimensions:

- earliest non-null due_at first;
- confirmed state before non-confirmed where applicable;
- most recently updated Task;
- deterministic id tie-break.

The exact implementation may compute a representative/minimum member key, but:
- it must be deterministic;
- unchanged data must produce unchanged page order;
- adding an unrelated later constellation must not reshuffle earlier pages arbitrarily.

Document the chosen key in code/tests.

## Part B — soft window target, no silent partial constellation

Use a server-side soft target equivalent to the current overview scale:

`SOFT_WINDOW_NODE_TARGET = 80`

This is NOT a hard cut inside a constellation.

Packing rule:

- add whole constellations in order;
- if the window is non-empty and adding the next whole constellation would cross the soft target, place that constellation in the next window;
- if the FIRST constellation itself exceeds the soft target, include it whole rather than truncating it.

Add an explicit emergency safety ceiling:

`MAX_COMPLETE_WINDOW_NODES = 500`

If one indivisible constellation by itself exceeds that emergency ceiling:
- DO NOT return a partial constellation;
- fail explicitly with a typed/handled Graph error stating that the constellation is too large for complete overview rendering;
- do not silently omit descendants/evidence;
- add a client error state explaining that a focused large-constellation view is required;
- do not implement that focused view in G3A.

The emergency ceiling is a fail-safe, not a normal product tuning control.

Do NOT expose either number in profile settings.

## Part C — overview paging contract

Extend `GET /graph/workspace` for unrooted Tasks overview with an optional:

`window_index` integer, default `0`.

Keep rooted requests backward-compatible.

Extend `GraphWorkspaceOut` with additive fields for Tasks overview:

- `window_index`;
- `window_count`;
- `has_previous_window`;
- `has_next_window`;
- `constellation_root_ids`;
- `semantic_window_complete` = true for successful G3A overview responses.

For rooted/non-overview responses, use sensible nullable/default values without breaking existing clients/tests.

Do NOT use `truncated` to mean "some nodes inside this visible constellation were omitted".

For G3A overview:
- `truncated=true` may mean there are other semantic windows outside the current one;
- visible constellations themselves must still be complete.

If `window_index` is outside the current range:
- return a validation/not-found style response consistently;
- do not silently clamp to a different page.

No DB/schema migration.

## Part D — rooted behavior

### Rooted Task

When `root_id` is a Task:

- its complete active `part_of` constellation must be included;
- include G2 priority Task<->Flow evidence for every Task in that constellation;
- then preserve the existing bounded ordinary/local expansion behavior for extra context;
- never remove constellation members to make room for ordinary neighbors.

Ordinary context may be partial/truncated; the structural constellation may not.

### Rooted non-Task

Preserve current behavior.

Do not cause a non-Task root to pull the entire constellation of every Task it touches.

## Part E — client window navigation primitive

Do NOT implement pan-trigger loading yet.

Add controller primitives:

- `loadOverviewWindow(int index)`;
- `loadNextOverviewWindow()`;
- `loadPreviousOverviewWindow()`.

Switching overview windows must REPLACE the prior overview workspace state rather than merge indefinitely.

This is important: G3A establishes bounded memory semantics for the later lens.

Preserve:
- search re-root;
- explicit `В центр`;
- `Показать связи`;
- selected-object direct inventory;
- Preserve/Relax;
- bookmarks.

If the selected object is not in the newly loaded window, clear selection explicitly.

## Part F — temporary/fallback adjacent-window controls

Add small toolbar controls that remain useful even after G3B:

- previous semantic area;
- next semantic area.

Use understandable Russian tooltips, e.g.:
- `Предыдущая область графа`;
- `Следующая область графа`.

Disable them at the first/last window.

Add a compact status indicator such as:

`Область 2 из 4`

Do NOT expose node counts as the primary meaning of the control.

## Part G — trustworthy truncation UX

Replace the current generic banner for successful semantic overview windows.

When more windows exist, say in substance:

`Показана часть пространства графа: направления и соцветия в этой области показаны целиком. Перейдите в соседнюю область, чтобы увидеть остальные.`

Do not claim the whole database is loaded.

In rooted/local expansion, the existing warning about additional hidden context may remain, but make the distinction clear:
- semantic overview window = complete visible constellations;
- local context expansion may be bounded.

The direct relation inventory remains canonical truth for direct relations and may still show `не на карте` for objects in another semantic window or optional context.

## Part H — relation and layout invariants

Preserve all accepted invariants:

- G1 deterministic ordinary ordering;
- G1 `part_of` closure;
- G1R edge completeness among admitted nodes;
- G2 priority Task<->Flow predicate;
- `part_of` direction child/source -> parent/target;
- no status cascade;
- no due inheritance;
- ongoing Direction remains kind=task;
- existing relation grammar;
- client Flow compact LOD and satellite cap 20;
- Preserve/Relax semantics.

Do not add new relation types.

Do not change Task completion_mode.

## Backend regression requirements

Add a focused G3A test suite covering at least:

1. **no split of part_of tree**
   - one constellation would cross the soft target;
   - its entire Task tree remains together in one window.

2. **priority Flow stays with constellation**
   - G2 user/agent confirmed evidence for Tasks in the tree stays on the same window.

3. **next constellation moves whole**
   - if adding another constellation would cross target, none of its nodes appear in current window;
   - the entire constellation appears in the next window.

4. **standalone Task is a constellation**
   - standalone Tasks page correctly.

5. **shared Flow inside one window**
   - one shared Flow occupies one node and all eligible edges remain.

6. **cross-window relation honesty**
   - an edge to a Task/Flow in another semantic window does not drag the other constellation into the current window;
   - direct relation API remains able to reveal it separately.

7. **deterministic ordering**
   - repeated unchanged calls give identical constellation/page membership;
   - adding an unrelated lower-priority constellation does not reshuffle earlier pages.

8. **rooted Task completeness**
   - rooted Task includes its entire structural constellation even when ordinary context is truncated.

9. **rooted non-Task guard**
   - no accidental full Task-tree expansion from a non-Task root.

10. **emergency ceiling**
    - an oversized single constellation fails explicitly;
    - it is never silently sliced.

11. **window bounds**
    - first/last flags correct;
    - invalid index handled explicitly.

Run existing relevant suites:
- G1;
- G1R;
- G2;
- part_of closure;
- graph workspace;
- caps;
- relations API.

Known bootstrap-user baseline failures are not authorization to change unrelated code.

## Client regression requirements

Cover:

- window 0 loads normally;
- next/previous replace, not merge, overview state;
- selection clears if object leaves the window;
- previous/next disabled correctly;
- `Область N из M` correct;
- whole Task hierarchy and G2 Flow glyphs render in one window;
- existing `Показать связи` still performs local rooted expansion;
- returning to overview restores semantic-window mode;
- Preserve/Relax do not affect page membership;
- direct relation inventory still shows off-window direct truth.

Run Flutter analyze on touched client files.

Linux debug build required because client product code changes.

Run:
`git diff --check`

## Explicitly NOT G3A

Do NOT:

- implement pan/edge-trigger loading yet;
- listen to InteractiveViewer transform thresholds yet;
- preload adjacent pages yet;
- maintain three simultaneous window tiles yet;
- implement old-window eviction by distance yet;
- add a raw Node Limit profile setting;
- raise/remove global safety limits as the product solution;
- add DB migrations;
- inspect/mutate production user data;
- deploy;
- move `origin/production`;
- change saved API URL precedence;
- add graph search ranking/AI salience;
- start S3;
- start H2D;
- fix unrelated failures.

Those pan/lens mechanics belong to G3B after G3A human validation.

## Completion

On completion:

1. update `PROJECT_STATE.md` with:
   - exact semantic-window definition;
   - constellation ordering;
   - soft target / emergency ceiling behavior;
   - API contract;
   - backend/client test results;
   - implementation SHA;
   - whether schema-neutral rollout is possible;
2. return `CURRENT_TASK.md` to HOLD;
3. push implementation/HOLD commits to `main`;
4. do not deploy;
5. STOP.

Final report must state:

- confirmed old failure mode;
- semantic definition of a constellation;
- overview membership algorithm;
- whether a constellation can ever be partially returned;
- paging API fields;
- rooted Task behavior;
- emergency ceiling behavior;
- client previous/next behavior;
- backend tests;
- client tests/analyze/build;
- implementation SHA;
- HOLD/main SHA;
- whether G3A is schema-neutral deployable from current production.

Then STOP. Do not start G3B yourself.
