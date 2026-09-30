# Current task — PL1-G4.4 offscreen unanchored-shelf edge cue

Authorized base: `c27ae419c856fb7b05f877ab96daf2488c06271e`.
Production/runtime remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`.
Production Alembic remains `0052 / 0052`.

PL1-HG5 readability is accepted. This is one bounded People-only usability polish: keep awareness of the far-right unanchored Person shelf after zoom/pan without moving those People into Task geography and without adding another panel.

## Product rule

The real unanchored People remain exactly where they are now in world-space: one deterministic non-semantic strip outside the canonical Task/anchored geography.

Do **not** clamp, pin, duplicate, or relocate actual Person markers to the viewport edge.

When that entire real shelf is off-screen, show one small viewport-space **edge cue** that means “unanchored People exist off-screen”.

## Edge cue

For healthy unrooted People mode only:

- if `unanchoredPersonIds` is non-empty and the complete unanchored shelf is outside the current graph viewport, show one compact edge handle/tab;
- preferred presentation: narrow rounded tab visually reading like the edge of a People marker, with a Person glyph and the count of unanchored People;
- keep it visually much smaller than a Person marker and clearly distinct from a real node;
- tooltip/semantics: “Люди без привязки к задачам · N”;
- place it on the horizontal viewport edge nearest the real shelf:
  - normally right edge;
  - if the user has panned beyond the shelf so it lies left of the viewport, use the left edge;
- vertically clamp the handle into the visible graph viewport near the transformed shelf center so it remains reachable;
- if any part of the real shelf is already visible, hide the cue;
- hide the cue in Tasks mode, rooted Person mode, degraded/fallback People grid, when there are no unanchored People, or while the required projection/viewport geometry is unavailable.

Render the cue outside the transformed `InteractiveViewer` child, in screen/viewport space. It must not alter shared-world coordinates, canvas bounds, Fit, or Tasks<->People camera parity.

## Interaction

Click/tap on the cue:

- preserve the current zoom scale;
- pan the existing shared camera so the real unanchored shelf becomes visible/centered enough to inspect;
- do not auto-Fit;
- do not open a second panel;
- do not change Person selection merely because the cue was clicked.

Once the real shelf enters the viewport, the cue disappears.

No extra persistent frame/drawer is allowed.

## Implementation boundary

Prefer a small helper for:

- transforming the real unanchored shelf bounds into viewport coordinates;
- deciding visible/off-screen/left/right state;
- computing cue vertical placement.

Do not infer shelf state from names or from approximate world-right constants. Use the actual final unanchored marker positions produced by the healthy People projection.

If necessary, expose the healthy `PeopleLandscapeOverview` projection result from the screen helper path so the renderer can access `unanchoredPersonIds` and their actual positions without recomputing a different geography.

## Preserve existing behavior

Keep unchanged:

- canonical Task centers;
- shared world frame/origin;
- Tasks<->People global-pixel parity;
- 128x56 Person markers;
- same-anchor 6 px clustering;
- unanchored shelf world positions/order/gap;
- manual Fit behavior;
- rooted Person/inspector;
- whole-grid fallback semantics.

## Tests

Add focused tests proving at least:

- cue absent when no unanchored People;
- cue absent while any real unanchored marker intersects the viewport;
- cue appears on right edge when the full shelf is right-offscreen;
- cue appears on left edge when camera is panned beyond the shelf;
- cue shows the correct unanchored count and accessibility/tooltip text;
- clicking cue preserves scale and pans until the real shelf is visible;
- cue then disappears;
- cue is absent in Tasks mode, rooted People mode, and degraded/fallback People layout;
- cue does not change canonical positions or Person selection;
- manual Fit still includes the real shelf and does not fit the cue;
- existing Tasks<->People parity, clustering, strip, marker-readability, task-layout, smoke, and large-canvas tests remain green.

Run focused Flutter People/screen/world-camera tests, task-layout regressions, smoke/large-canvas tests, `flutter analyze` for changed Dart files, and `git diff --check`.

## Explicitly out of scope

- No backend/API changes.
- No Alembic changes.
- No production ref movement/deploy.
- No second inspector/drawer/panel.
- No individual offscreen duplicate cards.
- No organization/person entity-type work.
- No combined Tasks+People view.
- No new human-gate bundle in this slice.

## Completion contract

When complete:

- record implementation SHA, changed files, edge-cue behavior, exact checks, and known limitations in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-G4.4 summary;
- commit/push to `main`;
- STOP.

Do not deploy or begin later work without a new explicit authorization.
