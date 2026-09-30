# Current task — PL1-HG4 exact-source repeat human-gate bundle

Authorized base: `7893a8699738f18688800a6fea5fa00aced954b6`.
Exact client candidate source: `04ea802233bc2bf33fa25dc2eb18e8373715f0cd`.
Current production/runtime backend source: `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`.
Production Alembic: `0052 / 0052`.

PL1-G4.2 is accepted for a repeat user visual check. This task prepares a new exact-source Linux debug artifact only. The Executor does not perform human acceptance and does not deploy the candidate.

## Goal

Build a clean Linux debug bundle from detached source `04ea802233bc2bf33fa25dc2eb18e8373715f0cd` so the user can repeat the failed HG3 check against the already-compatible production backend.

## Source/provenance

1. Build from a clean detached checkout of exactly the candidate SHA above, not from `main`.
2. Verify the candidate is descended from current production source. The compare against production is **not required to be repository-wide client-only**: this candidate intentionally also contains already-reviewed non-runtime ledger/harness/test files created after the production release.

   The exact permitted non-client delta is:
   - `CURRENT_TASK.md`;
   - `PROJECT_STATE.md`;
   - `backend/tests/test_task_layout_0052_migration_harness.py`;
   - `ops/production/migrate_task_layout_0052.py`;
   - `ops/production/remote_migrate_task_layout_0052.py`.

   Client-side candidate changes are the reviewed G4.2 files under `client/`.

   Fail closed if the compare contains any unexpected backend application/API file, Alembic file, dependency/runtime configuration, production deployment configuration, or any other path outside the exact known compare set. In particular, `backend/app/**` and `backend/alembic/**` must be unchanged from production. The listed ops/test/ledger files are repository metadata/tooling and are not part of the Linux Flutter client runtime; their presence does not block the bundle.
3. Do not modify product source while building. Build the Flutter client from the exact detached candidate checkout; do not cherry-pick or synthesize a client-only commit.
4. Record:
   - exact candidate SHA;
   - production backend SHA;
   - build mode;
   - UTC build timestamp;
   - executable path;
   - SHA-256 of launcher;
   - SHA-256 of `data/flutter_assets/kernel_blob.bin` if present;
   - adjacent plain-text `BUILD_INFO.txt`.

## Verification before bundle

Run the release-critical Flutter suites including:

- task-layout API/world tests;
- People landscape/overview/screen tests;
- People world-camera tests;
- the multi-Task semantic-window global-pixel parity regression added in G4.2;
- same-anchor compact clustering tests;
- dense spread / unanchored strip regression;
- graph screen smoke and large-canvas fit tests.

Run `flutter analyze` on the G4.2 changed Dart libraries and `git diff --check`.

Record exact results.

## Bundle

Produce one self-contained Linux debug bundle under a clearly named temporary directory such as:

`/tmp/pl1-hg4-04ea802-artifact/`

Do not install it over the user's current client.

Do not deploy anything.

Do not move `refs/heads/production`.

Do not call production Task-layout endpoints during bundle preparation.

Do not create/edit production Task, Person, or layout rows.

## Human-gate notes

Record in `BUILD_INFO.txt` that the user should repeat the same comparison that failed HG3:

- start in Tasks and use manual Fit;
- record/screenshot the visible Task positions;
- switch to People without pan/zoom;
- the world must not shift despite the Task semantic-window banner disappearing;
- single-anchor People must occupy the same screen regions as their Tasks;
- the Person pair sharing one Task must appear as one tight two-marker cluster with a 6 px logical gap, centered on that Task region;
- switch back to Tasks and confirm scale/world position and Task semantic window are preserved;
- unanchored strip remains on the far right;
- Task cards remain absent in People-only mode;
- rooted Person/inspector behavior remains unchanged.

Known limitation to include: very large same-anchor clusters at the extreme left/top may exceed the current 80 px canvas reserve. This is not the two-Person HG3 case and does not authorize ignoring any visible clipping during the human gate.

## Explicitly out of scope

- No source changes.
- No backend/API changes.
- No Alembic changes.
- No production ref movement/deploy.
- No installed-client replacement.
- No automated visual acceptance.
- No PL1 acceptance declaration.
- No combined Tasks+People view.
- No later slice.

## Completion contract

When complete:

- record artifact path, source/provenance, hashes, exact tests/analyze/diff results, and confirmation of no production/client mutation in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-HG4 bundle summary;
- commit/push ledger changes to `main`;
- STOP.

Do not perform the human gate yourself and do not begin later work.
