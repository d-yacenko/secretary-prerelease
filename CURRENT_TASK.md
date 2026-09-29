# Current task — PL1-HG2 exact-source client bundle for second human gate

Authorized client source: `35c6a0a4ad6768307d1a55f8d996edcd89d9cef4`.
Current production/runtime: `666683134797948871266e84fd105f0ca0c43476`.
Alembic remains `0051 / 0051`.

PL1-F is source-reviewed and accepted for retest. This task authorizes only preparation of a Linux debug client bundle from the exact PL1-F implementation SHA for the second human People Landscape gate.

No production server rollout is required for this task: relative to current production, PL1-F changes only client code/tests plus ledger files; backend/API/schema are unchanged.

## Preconditions

1. Bootstrap from the canonical repository.
2. Verify:
   - `origin/production == 666683134797948871266e84fd105f0ca0c43476`;
   - `35c6a0a4ad6768307d1a55f8d996edcd89d9cef4` is a descendant of production;
   - merge-base with production equals the production SHA;
   - there are no backend, API schema, migration, or deployment-code changes in the PL1-F product diff.
3. Build from a clean detached checkout of exact source `35c6a0a4ad6768307d1a55f8d996edcd89d9cef4`.
4. Do not modify product source, production runtime, production data, or the installed desktop client.

## Required technical validation

Run the focused PL1-F tests from the exact source, including at least:

- `people_landscape_overview_test.dart`;
- `people_landscape_screen_test.dart`;
- `people_landscape_test.dart`;
- `people_overview_test.dart`.

The validation must cover:

- exact Person-id -> projected-position stability across input order/rebuild;
- deterministic right-edge vertical strip for complete-empty-anchor People;
- anchored People never entering that strip;
- compact 156x56 unrooted overview cards;
- local deterministic anti-overlap for identical/near anchors;
- whole-grid fail-closed fallback for incomplete/missing landscape truth;
- no Task cards rendered on the People canvas;
- manual and automatic Fit using final compact positions/sizes;
- rooted Person presentation remaining unchanged.

Run `flutter analyze` for the changed Dart files and `git diff --check`.

## Build artifact

Build a Linux debug bundle from the exact PL1-F source.

Record in `PROJECT_STATE.md`:

- exact client source SHA;
- production/runtime SHA used by the test environment;
- executable path;
- build mode and timestamp;
- SHA-256 of the launcher executable;
- SHA-256 of `data/flutter_assets/kernel_blob.bin`;
- focused test results;
- analyze result;
- diff-check result;
- confirmation that source files were unchanged;
- confirmation that production/runtime/ref remained unchanged;
- confirmation that the installed client was not replaced;
- confirmation that no production application data were written.

Create adjacent `BUILD_INFO.txt` with the same provenance and checksums.

## Human gate boundary

Do not perform visual/interactive acceptance yourself. The human tester will run the bundle against the existing production backend.

Do not deploy anything, do not advance `production`, do not replace the installed client, do not mutate production Person/Task/Task↔Person/promotion/consolidation data, and do not begin PL1-G or any later slice.

## Completion contract

When bundle preparation and technical validation are complete:

- record the result in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-HG2 bundle summary;
- commit/push to `main`;
- STOP.
