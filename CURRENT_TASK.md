# Current task — PL1-G4.3 compact readable Person marker polish

Authorized base: `6da8eb42a0d9a6cd79392bd6fdac2171ab168b78`.
Production/runtime remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`.
Production Alembic remains `0052 / 0052`.

The PL1-HG4 human check accepts the single-world geography/camera behavior. This slice is a bounded unrooted People-marker readability polish only.

## Product intent

People markers must remain clearly smaller than Task cards because many People may surround one Task, but they must be easier to read at the same shared-world zoom.

The compact marker should spend its limited area on identity, not provider metadata.

## Required marker design

For unrooted People overview only:

- change the marker from the current 140x44 shape to a compact **128x56** marker;
- keep it smaller than the 186x100 Task card in both dimensions;
- use a larger Person glyph on the left, target **26–28 logical px**;
- use the right side for the Person title only;
- render the title in up to **2 lines** with ellipsis after line 2;
- use a text style at least as readable as `bodyMedium`, bold/semibold, rather than the current `bodySmall`;
- allow natural word wrapping; do not parse or guess first-name/surname order;
- remove the provider cue from the compact overview marker;
- keep identity-conflict indication if present, but it must not force the name back to one tiny line;
- click/tap selection and existing inspector behavior stay unchanged.

The desired visual rhythm is: one larger identity glyph + a two-line name/title. No metrics and no provider label inside this small marker.

## Geometry

Update the canonical compact-marker width/height constants so all People landscape geometry uses the new 128x56 size consistently:

- same-anchor cluster packing;
- 6 px intra-cluster gap;
- collision checks;
- unanchored strip placement;
- bounds/manual Fit;
- camera parity tests.

Do not change Task centers, Person anchor/centroid semantics, shared world origin, or Tasks<->People camera behavior.

## Human vs organization/team icon

Do **not** add a heuristic icon distinction in this slice.

The current Person presentation contract has no explicit grounded human/organization display type. Do not infer one from title text, provider, email domain, or names.

Record as deferred product direction: when an explicit entity/display type is introduced, unrooted markers should use different identity glyphs for an individual vs an organization/team while preserving the same Person/actor semantics as appropriate.

## Tests

Add/update focused tests proving at least:

- compact marker size is 128x56;
- Person title may render on two lines and uses the larger overview text style;
- provider cue is absent from the compact overview marker;
- identity-conflict marker remains available;
- two same-anchor People remain a tight deterministic cluster with 6 px edge gap and cluster center on the Task anchor;
- 3+ same-anchor packing stays deterministic and non-overlapping with the new marker size;
- unanchored strip remains right of final anchored marker bounds;
- Tasks->People->Tasks global-pixel parity and scale preservation remain unchanged;
- Task cards remain absent in People-only mode;
- rooted Person/inspector rendering remains unchanged.

Run the focused People landscape/screen/world-camera suites, G3 task-layout regressions, relevant smoke/large-canvas tests, `flutter analyze` for changed Dart files, and `git diff --check`.

## Explicitly out of scope

- No backend/API changes.
- No Alembic changes.
- No production ref movement/deploy.
- No organization/person classification field.
- No title/provider/email heuristics for entity type.
- No combined Tasks+People view.
- No new human-gate bundle in this slice.
- Do not change rooted Person presentation.

## Completion contract

When complete:

- record implementation SHA, changed files, exact checks, final marker dimensions/text behavior, and the deferred explicit entity-type icon direction in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-G4.3 summary;
- commit/push to `main`;
- STOP.

Do not deploy or begin later work without a new explicit authorization.
