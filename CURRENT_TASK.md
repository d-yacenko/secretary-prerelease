# Current task — PL1-HG6 exact-source offscreen-shelf cue human-gate bundle

Authorized base: `a5bdd727183db16b9ae0c3dd3d80cd87eff172c6`.
Exact client candidate source: `5c0d13099588df686462861c580e242a511cecd0`.
Current production/runtime backend source: `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`.
Production Alembic: `0052 / 0052`.

PL1-G4.4 is accepted for a final human spot-check. This task prepares an exact-source Linux debug artifact only. The Executor does not perform human acceptance and does not deploy the candidate.

## Goal

Build a clean Linux debug bundle from detached source `5c0d13099588df686462861c580e242a511cecd0` so the user can verify the new offscreen unanchored-shelf cue without reopening already accepted PL1 geography/readability behavior.

## Source/provenance

1. Build from a clean detached checkout of exactly the candidate SHA above, not from `main`.
2. Verify the candidate descends from current production source.
3. Compare production -> candidate and fail closed on unexpected runtime/backend/schema/config delta.
   - `backend/app/**` unchanged.
   - `backend/alembic/**` unchanged.
   - production dependency/runtime configuration unchanged.
   - already-reviewed ledger and 0052 migration-harness/test files do not block the client bundle.
   - reviewed client changes through G4.2/G4.3/G4.4 are expected.
4. Do not cherry-pick or synthesize a client-only commit.
5. Record exact source SHA, production backend SHA, build mode, UTC timestamp, executable path, launcher SHA-256, kernel SHA-256 if present, and adjacent plain-text `BUILD_INFO.txt`.

## Verification before bundle

Run release-critical Flutter checks covering:

- unanchored shelf cue helper/widget tests;
- right-edge and left-edge cue placement;
- cue visibility/hiding as real shelf leaves/enters viewport;
- cue count/tooltip;
- click preserves scale and pans to real shelf without selection changes;
- manual Fit includes real shelf and excludes cue;
- 128x56 People marker/readability;
- same-anchor clustering;
- Tasks<->People world-camera parity;
- task-layout world regressions;
- graph screen smoke and large-canvas fit.

Run `flutter analyze` for changed G4.4 Dart files and `git diff --check`.

## Bundle

Produce one self-contained Linux debug bundle under a clearly named temporary directory, e.g.:

`/tmp/pl1-hg6-5c0d130-artifact/`

Do not install it over the user's current client.

Do not deploy anything.

Do not move `refs/heads/production`.

Do not create/edit production Task, Person, or layout data during bundle preparation.

## Human-gate notes

Record a short checklist:

1. In People mode, use Fit: the real unanchored shelf should be visible at the far right and **no cue** should be present.
2. Pan/zoom toward anchored People until the entire unanchored shelf leaves the viewport:
   - one small edge tab should appear on the nearest horizontal edge;
   - it should show a Person glyph + correct unanchored count;
   - no fake Person card should be pinned to the edge.
3. Click the tab:
   - current zoom scale should remain unchanged;
   - camera should pan to the actual shelf;
   - cue should disappear when any real shelf marker becomes visible;
   - no Person should become selected and no panel should open.
4. Pan past the shelf so it lies left of the viewport and verify the cue can appear on the left edge.
5. Spot-check that Tasks<->People world alignment, same-anchor cluster, and readable 128x56 markers remain unchanged.

Known limitation: if the real shelf is taller than the viewport, the one cue hides once any part is visible even if some ends remain offscreen.

## Explicitly out of scope

- No product source changes.
- No backend/API changes.
- No Alembic changes.
- No production deploy/ref movement.
- No installed-client replacement.
- No automated human acceptance.
- No second drawer/panel.
- No organization/person entity-type work.
- No combined Tasks+People view.
- No later slice.

## Completion contract

When complete:

- record artifact path, provenance, hashes, exact checks, and confirmation of no production/client mutation in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-HG6 bundle summary;
- commit/push ledger changes to `main`;
- STOP.

Do not perform the human gate yourself and do not begin later work.
