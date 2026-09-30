# Current task — PL1-G4.1 keep unanchored strip outside anchored spread

Authorized base: `8635f74f3208f6584d22483f04d2bdf070cf067b`.
Production/runtime remains `666683134797948871266e84fd105f0ca0c43476`.
Repository Alembic head is `0052`; production Alembic remains `0051 / 0051`.

PL1-G4 core behavior is architect-reviewed and accepted. One bounded client geometry gap must be fixed before rollout/human gate.

## Problem

The unanchored People strip currently starts from the right edge of the full canonical Task world only.

Anchored People are then locally spread to avoid overlap. With a sufficiently dense same/near-anchor cluster, a final anchored marker can extend farther right than the Task bounds and theoretically enter the unanchored strip.

This violates the explicit invariant that the strip means only “no current Task anchor” and anchored People never enter it.

## Required correction

In the unrooted canonical People projection:

1. Keep canonical Task bounds based on the full persisted Task-center world.
2. Finish deterministic anchored Person placement first.
3. Compute the rightmost edge of all final anchored Person markers.
4. Place the unanchored strip strictly to the right of both:
   - the full canonical Task bounds; and
   - the final anchored Person marker bounds.
5. Preserve a deterministic non-semantic clearance. Reuse the existing landscape gap unless a smaller named constant is clearly justified.
6. Keep the strip vertical, deterministic, and ordered by Person id.
7. Do not move anchored People merely because unanchored People exist.
8. If there are no canonical Tasks and no anchored People, preserve the neutral strip origin.
9. Preserve all PL1-G4 anchor/centroid/fail-closed/camera behavior unchanged.

## Tests

Add a focused stress regression that would fail on PL1-G4:

- create enough People with the same or near-identical Task anchor to force deterministic local spread beyond the canonical Task-card right edge / multiple rings;
- include at least one unanchored Person;
- assert every anchored marker's right edge is strictly left of the strip X;
- assert strip ordering remains deterministic across input permutations/rebuilds;
- assert adding/removing unanchored People does not move anchored positions.

Also rerun the existing PL1-G4 focused People landscape/screen/world-camera tests, G3 task-layout tests, changed-file `flutter analyze`, and `git diff --check`.

## Explicitly out of scope

- No backend/API/migration changes.
- No production deploy/migration.
- No camera redesign.
- No marker redesign beyond what G4 already implemented.
- No combined Tasks+People mode.
- No human-gate bundle.
- Do not start rollout or later slices.

## Completion contract

When complete:

- record implementation SHA and exact test/analyze/diff results in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-G4.1 summary;
- commit/push to `main`;
- STOP.

Do not deploy or begin any later slice without a new explicit authorization.
