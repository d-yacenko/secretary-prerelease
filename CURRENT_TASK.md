# Current task — PL1-HG5 exact-source final Person-marker human-gate bundle

Authorized base: `9933d47b32df7b1b1df358331bfa9c86bbeaddd8`.
Exact client candidate source: `f3b6fdb04455a27c234ee2b0e1f728daf5d35f64`.
Current production/runtime backend source: `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`.
Production Alembic: `0052 / 0052`.

PL1-G4.3 is architect-reviewed and accepted for the final visual check. This task prepares the exact-source Linux debug artifact only. The Executor does not perform human acceptance and does not deploy the candidate.

## Goal

Build a clean Linux debug bundle from detached source `f3b6fdb04455a27c234ee2b0e1f728daf5d35f64` so the user can confirm the new compact readable Person marker on real production data while rechecking that already-accepted single-world geometry remains intact.

## Source / provenance gate

1. Build from a clean detached checkout of exactly the candidate SHA above, not from `main`.
2. Verify candidate descends from current production source.
3. Compare production -> candidate and fail closed on any unexpected backend runtime or schema delta:
   - `backend/app/**` must be unchanged;
   - `backend/alembic/**` must be unchanged;
   - dependency/runtime configuration must be unchanged unless already present in the reviewed post-production history;
   - the already-known ledger / migration-harness / harness-test files after production are allowed and are not part of the Flutter runtime.
4. Do not cherry-pick or synthesize a client-only commit.
5. Record exact source SHA, production backend SHA, linux-debug mode, UTC timestamp, executable path, launcher SHA-256, kernel SHA-256 if present, and adjacent `BUILD_INFO.txt`.

## Verification before bundle

Run the release-critical Flutter suites covering:

- People overview marker rendering;
- People landscape / same-anchor clustering / unanchored strip;
- People world-camera parity;
- Task-layout world/API behavior;
- graph screen smoke and large-canvas Fit.

Run `flutter analyze` on changed G4.3 Dart files and `git diff --check`.

Record exact results.

## Bundle

Produce one self-contained Linux debug bundle under a clearly named temporary directory such as:

`/tmp/pl1-hg5-f3b6fdb-artifact/`

Do not install it over the user's current client.

Do not deploy anything.

Do not move `refs/heads/production`.

Do not call production Task-layout endpoints during bundle preparation.

Do not create/edit production Task, Person, or layout rows.

## Human-gate notes to include in BUILD_INFO.txt

The user should verify:

- Tasks -> People without pan/zoom still preserves the same world/camera;
- known single-anchor People still occupy their Task regions;
- the shared-anchor pair still forms one compact local cluster;
- the new unrooted Person marker is visibly smaller than a Task card but easier to read than HG4;
- marker size is 128x56;
- the left glyph is visually prominent;
- the Person title can use two lines and is readable at the shared-world zoom;
- provider metadata is absent from the compact overview marker;
- unanchored strip remains on the far right;
- Task cards remain absent in People-only mode;
- rooted Person card and inspector remain unchanged.

Organization/team vs individual still uses the same generic Person glyph in this build. That distinction is intentionally deferred until the model exposes an explicit grounded entity/display type; do not treat it as a failed gate for this slice.

## Explicitly out of scope

- No source changes.
- No backend/API/Alembic changes.
- No production deploy or ref movement.
- No installed-client replacement.
- No automated visual acceptance.
- No organization/person inference.
- No combined Tasks+People mode.
- No PL1 acceptance declaration by Executor.
- No later slice.

## Completion contract

When complete:

- record artifact path, provenance, hashes, exact tests/analyze/diff results, and confirmation of no production/client mutation in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-HG5 bundle summary;
- commit/push ledger changes to `main`;
- STOP.

Do not perform the human gate yourself and do not begin later work.
