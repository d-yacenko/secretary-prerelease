# Current task — PL1-HG5 exact-source marker-readability human-gate bundle

Authorized base: `fd8b52774f3cda405d39328fce14b0f1cb4d7723`.
Exact client candidate source: `f3b6fdb04455a27c234ee2b0e1f728daf5d35f64`.
Current production/runtime backend source: `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`.
Production Alembic: `0052 / 0052`.

PL1-G4.3 is accepted for a final visual readability check. This task prepares an exact-source Linux debug artifact only. The Executor does not perform human acceptance and does not deploy the candidate.

## Goal

Build a clean Linux debug bundle from detached source `f3b6fdb04455a27c234ee2b0e1f728daf5d35f64` so the user can verify the final compact Person marker against the already-compatible production backend.

## Source/provenance

1. Build from a clean detached checkout of exactly the candidate SHA above, not from `main`.
2. Verify the candidate descends from current production source.
3. Compare production -> candidate and fail closed on any unexpected runtime/backend/schema/config delta.
   - `backend/app/**` must be unchanged.
   - `backend/alembic/**` must be unchanged.
   - production dependency/runtime configuration must be unchanged.
   - already-reviewed ledger, migration-harness/test files from earlier PL1 rollout do not block the client bundle.
   - reviewed client changes through G4.2/G4.3 are expected.
4. Do not cherry-pick or synthesize a client-only commit. Build the Flutter client from the exact detached candidate.
5. Record exact source SHA, production backend SHA, build mode, UTC build timestamp, executable path, launcher SHA-256, kernel SHA-256 if present, and adjacent plain-text `BUILD_INFO.txt`.

## Verification before bundle

Run the release-critical Flutter checks covering:

- People overview marker rendering;
- 128x56 marker dimensions;
- two-line semibold title and 28 px glyph;
- absence of compact provider cue;
- identity-conflict badge;
- same-anchor 6 px cluster packing;
- People landscape/strip behavior;
- Tasks<->People world-camera parity;
- task-layout world regression;
- graph screen smoke and large-canvas fit.

Run `flutter analyze` for the changed G4.3 Dart libraries and `git diff --check`.

Record exact results.

## Bundle

Produce one self-contained Linux debug bundle in a clearly named temporary directory, e.g.:

`/tmp/pl1-hg5-f3b6fdb-artifact/`

Do not install it over the user's current client.

Do not deploy anything.

Do not move `refs/heads/production`.

Do not create or edit production Task, Person, or layout data during bundle preparation.

## Human-gate notes

Record that the user should primarily judge readability, while spot-checking that the already accepted spatial behavior has not regressed:

- People marker is clearly smaller than a Task card but materially easier to read than HG4;
- marker visually reads as one larger identity glyph plus name/title;
- a two-word name can naturally occupy two lines rather than being squeezed into one tiny line;
- provider labels such as Email are absent from the compact marker;
- same-anchor People remain a tight local cluster;
- Tasks -> People does not shift the shared world;
- Task cards remain absent in People-only mode;
- rooted Person/inspector remains unchanged.

Organization/team vs individual icon differentiation is intentionally not part of this gate because the model still lacks an explicit grounded entity/display type.

## Explicitly out of scope

- No product source changes.
- No backend/API changes.
- No Alembic changes.
- No production deploy/ref movement.
- No installed-client replacement.
- No automated human acceptance.
- No entity-type heuristics.
- No combined Tasks+People view.
- No later slice.

## Completion contract

When complete:

- record artifact path, provenance, hashes, exact tests/analyze/diff results, and confirmation of no production/client mutation in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-HG5 bundle summary;
- commit/push ledger changes to `main`;
- STOP.

Do not perform the human gate yourself and do not begin later work.
