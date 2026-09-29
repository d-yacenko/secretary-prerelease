# Current task — PL1-HG1 exact-release human-gate client bundle

Authorized production release: `666683134797948871266e84fd105f0ca0c43476`.

People PL1 A-E is deployed and source-reviewed. This task authorizes only preparation of an exact-release Linux debug client bundle for the human People Landscape gate.

## Preconditions

1. Bootstrap from the canonical repository.
2. Verify `origin/production == 666683134797948871266e84fd105f0ca0c43476`.
3. Build from a clean detached checkout of that exact release SHA.
4. Do not modify product source, backend source, migrations, production runtime, production data, or the installed desktop client.

## Required bundle validation

Before handing the bundle to the human tester, prove from the exact-release checkout that:

- the unrooted People overview uses `projectPeopleLandscapeOverview` when usable;
- unusable/incomplete landscape projection falls back to the existing whole `projectPeopleOverview` grid;
- genuinely unanchored People remain on the deterministic shelf;
- Task context is not rendered as Task cards on the People canvas;
- manual Fit and automatic fit use the same effective People positions;
- rooted Person view remains unchanged.

Run at least the focused PL1 screen/projection tests from the exact release, including:

- `people_landscape_screen_test.dart`;
- `people_landscape_overview_test.dart`;
- `people_landscape_test.dart`;
- relevant existing People overview/workspace regression tests needed to prove no screen regression.

Run `flutter analyze` for the touched People/Graph screen files and `git diff --check`.

## Build artifact

Build a Linux debug bundle from the exact release.

Record in `PROJECT_STATE.md`:

- exact source SHA;
- bundle executable path;
- build mode;
- build timestamp;
- SHA-256 of the launcher executable;
- SHA-256 of `data/flutter_assets/kernel_blob.bin`;
- focused test results;
- analyze result;
- `git diff --check` result;
- confirmation that source files were unchanged;
- confirmation that production/runtime/ref remains the exact release;
- confirmation that the installed client was not replaced;
- confirmation that no production application data were written.

Create an adjacent `BUILD_INFO.txt` containing the same provenance and checksums.

## Human gate boundary

Do not perform the human visual/interactive acceptance yourself. The human tester will run the bundle.

Do not replace the installed client, do not deploy anything, do not mutate production Person/Task/Task↔Person/promotion/consolidation data, and do not begin PL1-F or any later slice.

## Completion contract

When the bundle and technical validation are complete:

- record the result in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-HG1 bundle summary;
- commit/push to `main`;
- STOP.
