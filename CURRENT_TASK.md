# Current task — RP1 dense relation-target picker

GR1 / GR1.1 / GR1.2 are HUMAN-ACCEPTED and CLOSED.

Authorized base includes:
- GR1.2 implementation `88d60d8dfb6e706ade06f2dbc6c594f370b932a0`;
- GR1.2 Architect human-gate acceptance `b73b0cda6e241434cc9a1a4617b1ce35326b8538`;
- production backend `0719e9bf5af75a8065a9916d8e27c0247a3921ec`;
- Alembic `0052 / 0052`;
- canonical Task layout `task-map-v2.2`.

This is a client-only UX slice for the “Добавить связь” target picker. Do NOT deploy production.

## Human-observed problem

The relation target search currently renders every candidate as a two-line `ListTile`:

- first line: title;
- second line: textual kind such as “Задача”, “Файл”, “Письмо”.

This wastes vertical space and becomes hard to scan when search returns dozens of objects.

Duplicate Task disambiguation also only works for exact case-sensitive title duplicates. Therefore visually equivalent titles such as:

- `создание курсов`
- `Создание курсов`

are not disambiguated even though the user needs the confirmed parent Direction/Task to choose correctly.

The picker also omits visual identity cues that already exist elsewhere in the product:
- object-kind glyph;
- ongoing/Direction infinity cue;
- provider/source identity (Google/Yandex/etc.);
- colored bookmark.

## Product goal

Make relation-target selection fast to scan at high result counts while preserving exact identity and existing relation semantics.

**One candidate should normally occupy one compact row.**

The row should communicate identity visually before the user has to read auxiliary text.

## A. Duplicate Task disambiguation

### Display-only normalization

Extend `relationTargetLabel()` duplicate detection for Tasks so visually equivalent titles are grouped by a display-normalized key.

Required normalization:
- trim leading/trailing whitespace;
- collapse internal whitespace runs to one space;
- compare case-insensitively using the normal Dart lowercase behavior.

Examples that must be considered duplicates:
- `Создание курсов`
- `создание курсов`
- `  Создание   курсов `

Do NOT mutate stored titles.

Do NOT merge object identities.

Do NOT fuzzy-match different wording.

### Parent suffix

When two or more Task results share the normalized display title:
- append the confirmed current `part_of` parent title to every matching Task row;
- if no confirmed parent exists, append `(без родителя)`.

Examples:
- `Создание курсов (Направление преподавания)`
- `создание курсов (Samsung)`

Use the existing confirmed-parent lookup semantics:
- confirmed `part_of` only;
- proposed/rejected parent edges are not established context.

This disambiguation applies to relation-target search generally, not only when the chosen relation type itself is `part_of`.

For `part_of` relation mode, keep the existing candidate filtering to Tasks and source-self exclusion.

## B. One-row visual target presentation

Replace the current two-line target `ListTile` presentation with a dense single-row presentation.

Preferred row order:

1. object-kind / semantic glyph;
2. provider/source glyph when the provider has identity;
3. single-line display title (including duplicate parent suffix when needed);
4. optional bookmark glyph at the trailing side.

### Semantic glyph

Reuse existing product presentation.

- finite Task: existing Task kind icon;
- ongoing Task / Direction: use the same infinity/ongoing cue already used by Graph for ongoing Tasks, not a new ontology kind;
- file/email/note/calendar/etc.: existing `iconForKind` / object presentation icon.

Do not print textual `Задача / Файл / Письмо` as a permanent second line.

Accessibility/tooltip semantics may still name the kind.

### Provider/source identity

If `providerHasIdentity(item.provider)`:
- render the existing compact provider mark / `ProviderSourceIcon`;
- preserve Google/Yandex/etc. identity exactly as elsewhere in Inbox/Graph;
- do not invent new provider colors/icons.

No provider text line is required.

### Bookmark cue

If the result object has a bookmark color:
- show the existing read-only colored bookmark glyph;
- no editing palette inside the relation picker.

Use the existing `ObjectBookmarkController` and batch reconciliation path.

Relation picker results may not be part of the current canvas, so after a successful search result batch:
- reconcile bookmark state for the returned candidate IDs;
- fail soft if bookmark loading fails;
- do not block target selection on bookmark availability;
- do not issue one bookmark request per row.

If `bookmarkController == null`, render rows normally without bookmark cues.

## C. Density and scrolling

The results list must remain bounded inside the dialog.

Requirements:
- one candidate normally one row;
- target row height should be materially smaller than the current two-line ListTile;
- title is single-line and ellipsized;
- list remains vertically scrollable when results exceed available dialog height;
- dialog itself must not grow beyond the viewport;
- no horizontal overflow at the existing approximately 360 px content width;
- selected-row state remains obvious;
- keyboard/mouse tap target remains usable; do not make rows so short that they become impractical.

Use existing Material density/minimum hit-area conventions; do not hardcode an inaccessible tiny row.

## D. Keep relation creation semantics unchanged

Do not change:
- relation type choices;
- direction meanings;
- `part_of` source child -> target parent semantics;
- target search API query semantics;
- relation creation endpoint;
- GFX-C scroll behavior;
- target identity;
- post-create topology refresh logic.

This slice is presentation/disambiguation only.

## Required tests

### 1. Case/whitespace-insensitive Task duplicate labels

Unit-test `relation_target_label.dart`:

Fixture results:
- Task A title `Создание курсов`, confirmed parent `Направление А`;
- Task B title `создание   курсов`, confirmed parent `Направление Б`;
- Task C unrelated title.

Prove:
- A and B both receive parent suffixes;
- C remains unsuffixed;
- original stored titles are unchanged;
- object IDs remain distinct;
- proposed/rejected parent does not count;
- missing confirmed parent renders `без родителя`.

Also keep exact-duplicate tests green.

### 2. Dense row visual grammar

Widget-test relation picker with mixed results:
- finite Task;
- ongoing Task/Direction;
- Gmail email;
- Yandex email;
- file;
- bookmarked item.

Prove:
- every result is one candidate row;
- no permanent `Задача / Письмо / Файл` subtitle text is rendered for those rows;
- finite Task gets Task glyph;
- ongoing Task gets infinity/ongoing cue distinct from finite Task;
- provider marks for Google/Yandex are present;
- bookmark glyph appears with the expected color for a bookmarked candidate;
- unbookmarked candidate has no bookmark glyph.

Use stable keys/semantics rather than pixel matching.

### 3. Duplicate visual case in actual picker

Search returns:
- `Создание курсов`
- `создание курсов`

with different confirmed parents.

Prove both rows are distinguishable before selection.

### 4. Large result set / scroll

Return at least 20–30 candidates.

At the normal desktop test viewport:
- dialog fits the viewport;
- no overflow exception;
- result list scrolls;
- an initially offscreen row can be scrolled into view and selected;
- selected target enables “Создать”.

### 5. Bookmark batching

With bookmark controller enabled:
- one candidate batch causes a bounded/batch bookmark reconciliation for returned IDs;
- no per-row N+1 bookmark fetch pattern;
- bookmark fetch failure leaves rows usable.

If existing bookmark test harness makes exact request-count assertion awkward, assert through the existing batch endpoint/harness rather than introducing test-only production code.

### 6. Existing relation picker behavior

Keep green:
- relation type dropdown previews/semantics;
- `part_of` candidate filtering;
- duplicate parent lookup;
- scrollable long target list from GFX-C;
- target selection and create enablement;
- actual createRelation source/target/type payload.

## Reuse existing components

Prefer existing:
- `relationTargetLabel`;
- `SecretaryObject.isOngoingTask`;
- `iconForKind` / object presentation;
- `ProviderSourceIcon` / provider compact glyph;
- `providerHasIdentity`;
- `ObjectBookmarkController.reconcileVisible`;
- `ObjectBookmarkGlyph`;
- bookmark token colors.

A small private relation-target row widget/helper is fine if it keeps the dialog readable/testable.

Do not create a second provider/bookmark/icon design system.

## Explicitly out of scope

- backend/API changes;
- schema/Alembic;
- production rollout;
- client installation;
- fuzzy identity matching or duplicate merge;
- relation editor / change-type / reverse;
- relation deduplication;
- agent audit/harness;
- Graph global search-result chips outside this relation dialog;
- SW2-B;
- GUX1;
- Task layout/version changes.

## Build / human gate

After implementation/tests:

- produce a fresh self-contained Linux debug bundle from a clean detached checkout of the exact implementation SHA;
- record exact source SHA, UTC build time, executable path, adjacent BUILD_INFO, launcher SHA-256, kernel SHA-256 if present;
- do not install it.

Human check should use a relation search that returns:
- the two “Создание курсов” variants;
- mixed Task/file/email results;
- enough rows to scroll.

Verify:
1. duplicate course Tasks are immediately distinguished by parent context;
2. rows are visibly denser and one-line;
3. object kind / Direction / provider / bookmark cues are easy to scan;
4. 20+ results remain usable by scrolling;
5. selecting a target and creating a relation still behaves exactly as before.

## Completion contract

When complete:

1. record root cause, normalized duplicate rule, exact row visual grammar, bookmark loading behavior, tests, implementation SHA, bundle provenance/hashes, and limitations in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus concise RP1 human-gate summary;
3. commit/push to `main`;
4. STOP.

Do not deploy production and do not start another slice.
