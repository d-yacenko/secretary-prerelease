# Current task — PP1-HG2: usable promotion review without blocking People graph

## State

- PP1 backend is live in production at `07bd8bafdb2f53a6a8475fc2d792687fa373a149`, Alembic `0051`.
- Human HG1 exact client proved real assisted-promotion suggestions are present and Add / Do-not-suggest work on production data.
- Human gate is NOT accepted because the promotion review UX is unusable at realistic suggestion volume.
- Current production must not be changed in this task.
- This is a client-only UX correction plus a fresh human-gate Linux bundle.

## Observed defect

Current `GraphWorkspaceScreen` inserts the promotion review as an unbounded `Column` before the `Expanded` People graph. Each candidate uses full-width `ListTile` rows for the person and every source Flow item.

With the current max-5 candidate batch this produces a long undifferentiated text stream, consumes most/all vertical space, triggers Flutter bottom overflow, and can make the People graph effectively inaccessible.

Promotion review is auxiliary. It must never replace or block the People graph.

## Product/UX contract

### 1. The People graph is always available

On People overview with suggestions:

- the graph canvas must remain rendered and visibly usable regardless of candidate/source count;
- promotion review must have a bounded maximum height;
- the promotion area must scroll independently when its content exceeds that bound;
- the promotion area must be collapsible to a compact header without processing candidates;
- collapsing/expanding must be a local UI action only and must not alter server data;
- processing one candidate must not force the panel open again if the user collapsed it.

Use a responsive bound, not an unbounded pre-graph Column. The graph must retain meaningful space on both wide desktop and smaller supported desktop windows.

Do not solve this by hiding the graph behind a second route or requiring the user to finish proposals first.

### 2. Candidate = visually distinct card

Each suggested person must be a clearly separated card/container, not a continuation of a text list.

Each card must show:

- strong display name;
- exact identity/contact in secondary text when different from display name;
- provider;
- concise existing explanation such as direct-contact count + recency;
- actions `Добавить` and `Не предлагать` visibly associated with that person.

Use a responsive card layout:
- wide desktop: multiple candidate cards may sit beside each other where space allows;
- narrow widths: cards may become one-per-row;
- no horizontal page overflow.

The visual boundary between two people must be obvious without reading the text.

### 3. Source Flow = compact clickable tiles

Do not render source evidence as full-width `ListTile` rows.

Inside each candidate card, render the existing body-free source previews as compact clickable tiles/chips/cards in a `Wrap`-style layout:

- several source tiles can sit next to each other;
- source title is bounded to a small number of lines with ellipsis;
- provider remains visible;
- optional existing date may be shown compactly if already available in the preview;
- tapping a source must preserve the existing object-detail navigation;
- no message body/snippet may be added.

The source evidence should explain the proposal without making one candidate occupy half a screen.

### 4. Review header and counts

Use a compact review header that makes the surface understandable, for example:

- `Предлагаемые люди · 5` for the currently visible batch;
- existing partial/truncation disclosure when applicable;
- clear `Свернуть` / `Развернуть` action.

Do NOT claim a total number of all possible candidates: backend intentionally exposes only a bounded current batch and scan truncation does not prove the exact remaining candidate count.

It is acceptable to say only how many are shown now.

### 5. Hidden suggestions stay compact

`Скрытые предложения` must not become another tall list.

Keep it visually separate and compact, preferably collapsed by default or represented as compact rows/chips inside the same bounded review panel. `Вернуть` remains reversible and exact-identity scoped.

Do not change backend suppression semantics.

## Functional invariants

Preserve all accepted PP1 behavior:

- max current candidate batch from backend unchanged;
- candidate eligibility/ranking unchanged;
- Add still approves exact identity and refreshes overview;
- Do-not-suggest still suppresses exact identity;
- Restore still retracts suppression;
- source click still opens existing object detail;
- no body/snippet;
- rooted Person view does not show promotion review;
- no relationship/manager/organization inference;
- no backend/schema/API change unless a client compatibility blocker is found; if so STOP and report instead of expanding scope.

## Required Flutter regression coverage

Add or update focused widget tests proving at minimum:

1. five candidates with three source previews each render without overflow at a representative desktop viewport;
2. the graph canvas region still has non-zero meaningful height while promotion review is expanded;
3. promotion review has a bounded independently scrollable content area;
4. collapse reduces it to a compact header and leaves the graph available;
5. collapsed state survives candidate refresh after Add/Do-not-suggest during the same screen lifetime;
6. candidate cards are visually/seman­tically distinct and associated actions target the correct identity;
7. source previews render as compact tiles rather than full-width evidence rows;
8. source title overflow is bounded;
9. tapping a source preserves existing object-detail navigation;
10. Add / Do-not-suggest / Restore existing tests remain green;
11. rooted Person detail still omits promotion review;
12. narrow supported desktop width does not horizontally overflow.

Use stable keys where needed so the tests assert layout behavior rather than brittle text ordering.

Run the relevant broader People/Graph client tests. Existing unrelated baseline Graph failures may be reported separately; do not fix them in this slice.

Run Flutter analyze on touched files and `git diff --check`.

## Human-gate bundle

Build a fresh Linux debug bundle from the completed HG2 implementation.

Place it under a clearly named temp path containing `pp1-hg2`.

Provide:
- exact implementation SHA;
- executable path;
- executable SHA-256;
- focused test results;
- analyze result.

Do not install or replace the user's existing client automatically.

## Explicitly out of scope

- No production backend deploy.
- No database/schema migration.
- No production ref movement.
- No provider/model call.
- No synthetic production data.
- No change to promotion eligibility/ranking.
- No change to max-5 backend batch.
- No Person Knowledge / manager / colleague / family inference.
- No contextual task-creation prompts.
- No Organization/social graph work.
- No client auto-updater/versioning redesign.
- No unrelated graph redesign.

## Completion

1. Commit the client UX fix and tests.
2. Record exact implementation SHA, tests, analyze result, and HG2 bundle path/checksum in `PROJECT_STATE.md`.
3. Return `CURRENT_TASK.md` to HOLD with PP1 human acceptance still pending.
4. Push implementation + HOLD to `main`.
5. Report exact SHA/test/bundle results and STOP.

Human acceptance is performed by the user with the HG2 bundle.
