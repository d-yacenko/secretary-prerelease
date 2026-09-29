# Current task — PL1-F People Landscape human-gate corrections

Authorized base: `3738563b2d8d7940c75289433ea4ab826709fe29`.
Production remains `666683134797948871266e84fd105f0ca0c43476`.

PL1 A-E is deployed, but the human gate found presentation/mapping defects. This slice is authorized now and is client-only.

## Goal

Correct the unrooted People Landscape so each Person is rendered at their own Task-derived geography, genuinely unanchored People are kept in a compact right-edge strip, and the overview remains usable as People density grows.

## Scope

1. Client only. Do not change backend, API contracts, migrations, production runtime, production data, deployment code, or the installed client.
2. Preserve the existing PL1 truth model:
   - confirmed canonical Task↔Person actor anchors only;
   - no role weighting;
   - no persisted Person coordinates;
   - incomplete/missing anchor context still fails closed to the existing whole `projectPeopleOverview` fallback;
   - Task context remains geography input only and must never render Task cards on the People canvas.
3. Fix Person-id-to-position correctness in the unrooted People overview. A rendered Person card must use the projection position for that exact Person id; list order, sorting, map iteration, rebuilds, or widget reuse must not permute cards between positions.
4. Replace the current unanchored shelf presentation for complete-empty-anchor People with a deterministic vertical strip at the far right of the People overview:
   - top-to-bottom deterministic order;
   - visually outside anchored Task geography;
   - no semantic meaning beyond “no current Task anchor”;
   - anchored People must never be placed in this strip.
5. Introduce a compact unrooted People overview card variant:
   - substantially smaller than the current card;
   - primary content is the Person display name;
   - optional secondary identity line only if short/useful;
   - omit overview-only metrics/body text that make cards tall/wide;
   - selection/tap behavior must still open the existing inspector/details;
   - rooted Person presentation and inspector/detail UI remain unchanged.
6. Add deterministic local anti-overlap for anchored People that resolve to the same or nearly the same Task-derived location:
   - preserve the coarse Task geography;
   - spread only locally;
   - no randomness;
   - stable by Person id;
   - do not reintroduce role/salience/authority weighting.
7. Manual Fit and automatic post-load fit must use the same final effective compact/spread positions and dimensions that are actually rendered.

## Human-gate regression examples

Use these only as regression intent, not as hard-coded names or coordinates:

- multiple anchored People must not swap positions with each other;
- a Person anchored to one Task region must stay in that region across rebuilds;
- several People around one Task/centroid must remain distinct and non-overlapping;
- unanchored People must remain visible in the right-edge strip.

Do not hard-code production Person ids, names, titles, Task ids, or pixel coordinates in product code.

## Tests

Add or update focused tests covering at least:

- exact Person-id → projected-position mapping with multiple anchored People, including order permutations/rebuilds;
- deterministic right-edge vertical strip for complete-empty-anchor People;
- anchored People never entering the unanchored strip;
- compact unrooted overview card dimensions/content while rooted Person and inspector/details remain unchanged;
- two or more People with identical or near-identical anchors do not overlap and remain near the anchor region;
- deterministic placement across repeated projection/rebuild;
- fail-closed fallback invariants for incomplete Task context, incomplete Person anchors, and missing expected Task geography;
- Task context still does not render Task cards on People canvas;
- manual and automatic Fit use the final effective People layout.

Reuse existing PL1 helpers where possible. Do not create a competing Task geography algorithm.

Run the focused PL1-F tests plus affected existing People landscape/workspace/screen regressions, `flutter analyze` for changed Dart files, and `git diff --check`.

## Completion contract

When complete:

- record implementation SHA, changed files, focused test results, analyze result, diff-check result, and any known limitations in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-F completion summary;
- commit and push to `main`;
- STOP.

Do not deploy, do not build another human-gate bundle, and do not begin PL1-G or any later slice without a new explicit authorization in this file.
