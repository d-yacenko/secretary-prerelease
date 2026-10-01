# Current task — GR1.1 search-filter scope isolation

Human GR1 gate found a client-side UX regression on 2026-10-01.

Production is healthy and remains:
- runtime/ref: `0719e9bf5af75a8065a9916d8e27c0247a3921ec`
- Alembic: `0052 / 0052`

GR1 backend rollout is accepted. Do NOT redeploy production for this task.

Canonical Task layout remains `task-map-v2.2`.

## Human-observed incident

During GR1 verification the user:

1. removed/recreated old Publication relations;
2. reached the completed ICDM Task, which correctly disappeared from the ordinary overview after its old relation was removed;
3. searched for that completed Task using the Graph object search and selected the Task kind facet;
4. reopened/reconnected it;
5. then observed that all compact non-Task “dandelion” glyphs disappeared across the Graph;
6. after fully closing and reopening the client, the glyphs returned in the same places.

No data loss occurred.

The first screenshot showed an active Task kind-filter button; after restart the filter was reset and the glyphs returned.

## Verified root cause

Graph search facets and Graph canvas visibility are incorrectly coupled.

Current controller state:

- `searchKindFilter`
- `searchProviderFilter`

is passed to search API calls, which is correct.

But the same values also drive:

- `visibleNodes => _nodes.values.where(_matchesDisplayFilters)`
- `visibleEdges`
- `visiblePositions`
- the “Нет объектов по выбранным фильтрам” canvas state.

Graph toolbar `CompactObjectFilters` also calls `controller.applyDisplayFilters()` whenever a search facet changes.

Therefore selecting `kind=task` to find a completed Task hides every file/email/note/document/etc. node from the canvas. Hybrid LOD then has no non-Task endpoints to render, so every “dandelion” disappears. Restart resets the search facets to null and the canvas returns.

This is a client presentation-state defect. It is NOT a backend relation defect and NOT a persistence defect.

## Product invariant

**Search facets filter search results only. They must never alter semantic-window membership or Graph canvas visibility.**

The Graph canvas continues to represent the authoritative workspace returned by the backend.

Changing:
- search text;
- kind facet;
- provider facet;

may change only the search result strip / search request.

It must NOT:
- hide nodes already admitted to the workspace;
- hide edges;
- hide hybrid Flow/file/email/note glyphs;
- alter canonical Task centers;
- alter semantic-window membership;
- clear the current Graph selection solely because the selected object does not match the search facet.

There is currently no separately authorized Graph-display-filter feature. Do not preserve the accidental behavior as a hidden display filter.

## Required implementation

### Controller

Make Graph search facets search-only.

Preferred bounded change:

- `visibleNodes` returns the full current workspace node set;
- `visibleEdges` is based on full workspace node membership;
- `visiblePositions` is based on full workspace node membership;
- remove or stop using `_matchesDisplayFilters`, `hasActiveDisplayFilters`, and `applyDisplayFilters` for canvas presentation;
- keep `searchKindFilter` / `searchProviderFilter` as search request state unless a small rename is clearly safer and fully contained.

Do not introduce a new display-filter model in this slice.

### Graph toolbar

For `CompactObjectFilters` in Graph Tasks mode:

- kind/provider changes update the search facet;
- rerun the current search with the selected facet;
- do NOT mutate canvas visibility.

The active facet may remain visually highlighted because it still filters search results.

If a small Graph-specific tooltip/semantics clarification is easy and local, prefer wording that makes the scope clear, e.g. “Тип в поиске” / “Источник в поиске”. Do not make broad shared-component copy changes that could alter other screens unexpectedly.

### Canvas

Remove the Graph canvas empty-state branch that says “Нет объектов по выбранным фильтрам” solely because a search facet is active.

An empty Graph canvas should only reflect the actual workspace/mode state, not a search facet.

## Preserve completed-Task semantics

Do NOT change lifecycle semantics discovered during the incident:

- a terminal/completed Task that is no longer connected to an active overview component may disappear from ordinary overview;
- it remains searchable through object search;
- reconnecting it with an eligible confirmed Task relation may bring it back into the visible component.

That behavior is not the bug.

## Required regressions

Add focused client tests proving all of the following.

### A. Search kind facet does not hide hybrid glyphs

Fixture:
- overview contains an active Task;
- one or more connected non-Task objects (`file`, `note`, `email`) are rendered as hybrid dandelion glyphs;
- relation edges are visible.

Select search kind facet `task`.

Prove:
- search API request carries `kind=task`;
- search result strip follows the facet;
- all original workspace nodes remain in controller/canvas;
- HybridFlowGlyph(s) remain visible;
- relation hairlines remain visible;
- canonical Task position is unchanged;
- no “Нет объектов по выбранным фильтрам” canvas state appears.

### B. Provider facet is also search-only

Select a provider facet.

Prove:
- search API request carries the provider;
- canvas nodes/glyphs/edges remain unchanged.

### C. Selection is not cleared by a search facet

Select a non-Task object or Task on the Graph, then change a search facet that would not match it.

Prove selection remains unless another explicit navigation action changes it.

### D. Incident-shaped topology refresh

Fixture matching the user sequence at controller/widget level:

- overview has active Publication Task(s) plus hybrid non-Task evidence;
- `searchKindFilter='task'` is active;
- a completed Task is returned by search;
- a confirmed Task↔Task relation is created/rejected/recreated such that `refreshAfterTaskTopologyMutation()` runs;
- refreshed authoritative workspace still contains the evidence endpoints.

Prove after the topology refresh:
- search facet remains search-only;
- non-Task evidence remains visible;
- hybrid glyphs remain present;
- no global disappearance occurs.

Do not require real production data.

### E. Search reset/restart semantics

Clearing the search facet changes search request/results only; it must not produce a canvas membership change because there should no longer be one to undo.

## Preserve accepted behavior

Keep green:

- GR1 confirmed-agent relation removal/rejection;
- GR1 proposed attached endpoint visibility;
- user-origin physical relation DELETE;
- exceptional `вне текущей области` inventory navigation;
- TL2.2 `task-map-v2.2`;
- SW2-A semantic windows;
- hybrid dandelion/Focus LOD geometry;
- GFX-A/B/C;
- People shared world/camera;
- Graph search and search-result rerooting.

## Scope boundaries

Client-only.

Do NOT modify:

- backend;
- API contracts;
- schema/Alembic;
- production ref/deploy;
- Task-map algorithm/version;
- SW2-B;
- object lifecycle semantics;
- relation semantics;
- server workspace admission;
- client installation.

Do not add a new persistent Graph display-filter feature.

## Build / human gate

After implementation/tests pass:

- produce a fresh self-contained Linux debug bundle from a clean detached checkout of the exact implementation SHA;
- record exact SHA, UTC build time, executable path, adjacent BUILD_INFO, launcher SHA-256, kernel SHA-256 if present;
- do not install it.

Production backend already matches GR1 and needs no new rollout for this client-only fix.

## Completion contract

When complete:

1. record the root cause, exact client behavior change, tests, implementation SHA, bundle provenance/hashes, and limitations in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus a concise GR1.1 human-gate summary;
3. commit/push to `main`;
4. STOP.

Do not close GR1 as HUMAN-ACCEPTED. Do not start another Graph-cleanup slice.
