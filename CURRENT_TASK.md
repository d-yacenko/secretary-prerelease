# Current task — HOLD

PL1-G4.3 compact readable Person marker polish is implemented. No further Executor work is authorized.

- Implementation: `f3b6fdb04455a27c234ee2b0e1f728daf5d35f64`.
- Unrooted People markers are 128×56: a 28 px Person glyph and a semibold `bodyMedium` title of up to two lines. The compact marker has no provider cue. Identity-conflict indication remains and does not collapse the title to one line.
- Same-anchor packing, the 6 px gap, the unanchored strip, Fit, and Tasks↔People camera parity use the new size. Rooted Person presentation is unchanged.
- Deferred: different individual vs organization/team glyphs after an explicit entity/display type exists. This slice does not infer that type.
- Production/runtime remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, Alembic `0052 / 0052`.
- Focused Flutter tests: 50 passed. Smoke and large-canvas: 5 passed. Analyze: 0 errors, 6 pre-existing infos. `git diff --check` clean.
- No deploy, no production mutation, and no human-gate bundle.
