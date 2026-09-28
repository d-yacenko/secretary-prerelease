# Current task — PP1-HG2: People workspace visual baseline + usable promotion review

## State

- PP1 backend is live in production at `07bd8bafdb2f53a6a8475fc2d792687fa373a149`, Alembic `0051`.
- Exact HG1 client proved real production promotion candidates are present and Add / Do-not-suggest work.
- Human gate is NOT accepted: the current promotion review overflows, visually merges candidates/sources, and can hide the People graph.
- The Architect and user now also want the first usable visual baseline for working with the People graph, not a one-off overflow patch.
- No Executor implementation of HG2 has started yet; this task replaces the earlier narrower HG2 authorization.
- This remains a client-only slice. Do not change production/backend/schema/API semantics.

## Product goal

People should read as a workspace of meaningful human entities, not a generic object graph and not a text dump.

Deliver two coherent visual layers in one client slice:

1. **People overview graph** — compact person summary cards suitable for spatial scanning.
2. **Person focus/detail** — richer factual summary with task/direction participation and compact recent Flow evidence.
3. **Promotion review** — an auxiliary bounded/collapsible review surface using the same visual language and never blocking the graph.

The result does not need final visual polish, but it must be deliberately designed, dense, legible, and usable enough that the People graph can be evaluated as a product rather than as raw plumbing.

## Semantic boundary

Do not invent knowledge for visual completeness.

Allowed factual material already present in the current API:

- Person title/name;
- effective identity/provider cues;
- identity conflict state;
- open task count;
- recent communication count;
- rooted task involvement with canonical Task->Person actor role;
- rooted recent attributable Flow previews;
- rooted salience/activity explanation already present in the product.

Do **not** display an inferred global role such as manager, colleague, family member, employee, organization membership, or company affiliation unless such a canonical confirmed fact already exists. It does not exist in this slice.

Task-specific actor roles may be shown on the corresponding task tile because those are existing canonical edges. They must not be promoted into a global Person role.

There is no Organization/company ontology in this slice. Design visual primitives so a future object-kind icon could differ, but implement only the actual Person semantics now. Do not add a fake company kind.

## A. People overview graph card

Special-case `Object(kind=person)` presentation in the graph instead of rendering it as the generic object card.

Keep the spatial graph compact. Do not turn every overview node into a huge dossier.

Each Person node should have a deliberate dense layout with:

- a clear Person/avatar placeholder area using an existing Material person icon; no network avatar/photo lookup;
- Person name as the dominant text, visibly stronger than metadata;
- provider/contact cues from effective identities/routes where available;
- compact factual metrics such as:
  - open tasks;
  - recent communications;
- conflict cue when identity conflict exists;
- selected/bookmark behavior preserved.

Do not show the raw numeric salience score as the main identity of the card. Salience remains an activity/context signal, not a social rank.

Use the existing graph-node footprint unless a **small, bounded** Person-specific size increase is demonstrably required for readability. If size changes, update People overview spacing and edge endpoint sizing consistently and add regression coverage; do not destabilize Task graph geometry.

The overview should remain scannable at roughly tens of people. A node must not contain a list of messages/tasks.

## B. Person focus/detail = rich factual card

When the user chooses a Person from People overview, there must be an obvious path into the existing rooted Person truth surface so the richer data is available.

Prefer a simple interaction consistent with current graph navigation:
- selecting/opening a Person should make the rooted Person context readily accessible;
- do not require obscure secondary controls just to see participation/Flow.

Rework the rooted Person detail presentation into a compact visual summary inspired by the human mockup:

### Header

- prominent Person icon/avatar placeholder;
- name in a larger/bolder style;
- effective provider/contact cues;
- identity conflict cue if relevant.

### Metrics strip

Present a compact set of factual chips/metrics, for example:

- `Открытые задачи · N`;
- `Недавние коммуникации · N`;
- activity tier text if already available and useful, without implying importance.

If rooted recent Flow exists, a compact last-contact date may be derived from the newest returned preview. Do not imply completeness beyond the bounded truth surface.

### Participation / tasks / directions

Render existing rooted `taskInvolvement` as compact clickable tiles/cards, not full-width ListTiles.

Each tile may show:

- task/direction title;
- `Направление` when completion_mode is ongoing, otherwise task semantics;
- the canonical per-task actor role using existing labels;
- due date when available;
- proposal state cue where already supported.

Use a Wrap/responsive tile layout so several short items can sit side by side.

This section is factual participation, **not** a global Person role.

### Recent Flow

Render rooted recent communication previews as compact clickable evidence tiles in a Wrap-style layout:

- email/chat/calendar/event/other existing object kind icon where supported;
- title, max 1–2 lines with ellipsis;
- provider cue;
- compact date/time when available;
- existing object-detail navigation on tap;
- body/snippet must remain absent.

The visual goal is the user's sketch: a dense set of evidence tiles, not a vertical list consuming half the screen.

### Secondary truth

Known contacts, identity candidates, routes, detailed salience components, and correction actions must remain accessible, but they should no longer dominate the first visual impression. Put them below the primary summary or in clearly separated sections using the existing data/semantics.

Do not remove correction/reversibility functionality.

## C. Promotion review must never block the graph

On People overview:

- graph canvas remains rendered and visibly usable regardless of suggestion count;
- promotion review has bounded responsive max height;
- overflowing review content scrolls independently;
- review can be collapsed/expanded without processing candidates;
- collapsed state survives Add / Do-not-suggest refreshes during the screen lifetime;
- processing suggestions is never required to regain access to the graph.

The review header should show only the current visible batch count, e.g. `Предлагаемые люди · 5`, plus existing partial-scan disclosure where applicable. Do not invent a total remaining count.

## D. Promotion candidate visual design

Each candidate is a visually distinct compact Person card using the same visual language as real Person cards:

- person icon/avatar placeholder;
- strong display name;
- exact identity/contact secondary text when different;
- provider;
- direct-contact count + recency explanation;
- Add / Do-not-suggest actions clearly attached to that candidate.

Wide desktop may place multiple cards beside each other; narrow supported widths fall back to one per row without horizontal overflow.

### Promotion source evidence

Candidate source previews must be compact clickable Flow tiles in a Wrap, not full-width ListTiles:

- title max 1–2 lines;
- provider;
- kind/icon where supported;
- compact date if available;
- existing object-detail navigation;
- no body/snippet.

### Hidden suggestions

Keep hidden suggestions visually separate and compact, preferably collapsed by default inside the same bounded review surface. Restore remains exact-identity/reversible. Do not change backend suppression semantics.

## Visual design baseline

Use existing Material theme/color scheme, spacing primitives, icons, border radii, and typography. Do not introduce a new design system or arbitrary hard-coded colors.

Minimum aesthetic intent:

- clear visual hierarchy;
- obvious card boundaries;
- consistent rounded containers;
- restrained elevation/borders;
- compact spacing;
- metadata visually quieter than names/titles;
- actions visually attached to the entity they affect;
- no giant blank regions inside cards;
- no text collisions/overflow.

The user's sketch is conceptual, not a pixel specification. Preserve its information hierarchy, not its hand-drawn geometry.

## Functional invariants

Preserve:

- promotion max batch and eligibility/ranking;
- Add exact approval semantics;
- Do-not-suggest exact suppression;
- Restore;
- source object navigation;
- no message bodies/snippets;
- no promotion review on rooted Person;
- manual Person fallback;
- all identity correction/retract functionality;
- Task graph appearance/geometry unless unavoidable shared code is proven safe;
- backend/API/schema unchanged.

If the required UI cannot be implemented from existing response data, STOP and report the exact missing field instead of silently widening the backend contract.

## Required Flutter regression coverage

At minimum prove:

### Promotion layout
1. five candidates x three source previews render at representative desktop viewport without vertical/horizontal overflow;
2. graph canvas retains meaningful non-zero visible height while review expanded;
3. review has bounded independently scrollable content;
4. collapse/expand works and preserves graph access;
5. collapsed state survives promotion refresh in same screen lifetime;
6. candidate actions target the correct identity;
7. candidate source evidence is compact/bounded and navigation still works;
8. hidden suggestions stay compact and Restore remains functional;
9. narrow supported desktop viewport has no horizontal overflow.

### People cards
10. Person overview node uses the Person-specific summary card and shows strong name + factual metrics;
11. multiple provider cues remain bounded;
12. identity-conflict cue remains;
13. Task-mode generic graph cards are not visually regressed.

### Rooted Person summary
14. rooted Person header/metrics render;
15. task involvement renders as compact clickable tiles with task-specific actor role;
16. ongoing task is labeled as Direction/Направление rather than silently as finite task;
17. recent Flow renders as compact body-free clickable tiles;
18. long task/Flow titles ellipsize without overflow;
19. correction/contact/salience truth remains reachable;
20. a Person with no tasks or no recent Flow has a clean compact empty-state, not a large blank panel.

Use stable keys for layout-sensitive assertions.

Run focused People/promotion tests plus relevant broader Graph client suites. Existing unrelated baseline failures may be reported separately; do not fix them in this slice.

Run Flutter analyze on touched files and `git diff --check`.

## Human-gate bundle

Build a fresh Linux debug bundle from the completed HG2 implementation under a temp path containing `pp1-hg2`.

Report:

- implementation SHA;
- executable path;
- executable SHA-256;
- focused/broader test results;
- analyze result.

Do not install or replace the user's existing client automatically.

## Explicitly out of scope

- No backend/API/schema change.
- No production deployment/ref movement.
- No DB mutation.
- No provider/model/avatar network lookup.
- No synthetic production data.
- No change to promotion eligibility/ranking/batch size.
- No global manager/colleague/family/client inference.
- No Organization/company ontology.
- No Person-to-Person social graph.
- No contextual task-creation promotion prompts.
- No client updater/versioning redesign.
- No unrelated Task graph redesign.

## Completion

1. Commit client UX implementation and regressions.
2. Record exact implementation SHA, tests, analyze result, bundle path/checksum in `PROJECT_STATE.md`.
3. Return `CURRENT_TASK.md` to HOLD with PP1 human acceptance pending.
4. Push implementation + HOLD to `main`.
5. Report exact SHA/tests/bundle and STOP.

Human acceptance is performed by the user with the HG2 bundle.
