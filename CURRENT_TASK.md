# Current task — HOLD

PL1-G4.4 offscreen unanchored-shelf edge cue is implemented. No further Executor work is authorized.

- Implementation: `5c0d13099588df686462861c580e242a511cecd0`.
- Healthy unrooted People keep the real unanchored shelf in world-space. When that entire shelf is outside the graph viewport, one 36×40 edge tab shows a Person glyph and the count, with the text «Люди без привязки к задачам · N».
- The tab is on the nearer horizontal edge, outside the camera child. A tap preserves scale and pans the real shelf into view. It does not Fit, select a Person, or open a panel.
- The tab is hidden while any shelf marker is visible, when nobody is unanchored, and in Tasks mode, rooted Person mode, and the fallback People grid.
- Known limitation: a shelf taller than the viewport is centered, so the tab hides once any part is visible; it is one count on the left or right edge only.
- Production/runtime remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, Alembic `0052 / 0052`.
- Focused Flutter tests: 59 passed. Smoke and large-canvas: 5 passed. Analyze: 0 errors, 6 pre-existing infos. `git diff --check` clean.
- No deploy and no human-gate bundle.
