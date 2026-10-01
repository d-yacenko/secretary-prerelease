# Current task — HOLD

GR1.2 collapsed multi-edge proposal visibility is Architect-reviewed and ACCEPTED FOR HUMAN GATE.

Accepted implementation:
- `88d60d8dfb6e706ade06f2dbc6c594f370b932a0`
- Executor HOLD: `ad97c2d7bbb502a8d60788d8370712149fc64070`

Architect review confirmed:

- compact Task↔Flow presentation still draws one glyph/hairline per object pair;
- the canonical representative edge continues to determine direction, dash/light styling, and arrow placement;
- proposal review state is aggregated separately through `proposalCue`;
- if any visible active proposed edge exists in the collapsed pair, one hollow proposal diamond is visible before Task selection;
- a confirmed representative line is not restyled as proposed merely because another collapsed edge is proposed;
- rejected edges do not create the cue;
- hidden actor/label/temporal relations do not create the cue;
- several proposed edges still produce only one compact cue;
- inspector semantics remain one row per real edge;
- Task/Flow positions and hairline endpoints are unchanged in the focused regressions;
- no backend/schema/Alembic/production change occurred;
- canonical Task layout remains `task-map-v2.2`.

Recorded checks:
- focused Flutter client suite: 32 passed;
- changed-library analysis: 0 issues;
- `git diff --check`: clean.

Human-check bundle, not installed:
- source: `88d60d8dfb6e706ade06f2dbc6c594f370b932a0`
- executable: `/home/d.yacenko/tmp/gr12-88d60d8-artifact/bundle/personal_secretary`
- build UTC: `2026-10-01T09:35:07Z`
- adjacent BUILD_INFO present per Executor ledger
- launcher SHA-256: `fb97380c0e2f6e68afb124956f9ba2630fea445c7ade8b1d5afb6ddfdbc75e69`
- kernel SHA-256: `bb05c6bb19d6d5b3d90d812109fd33d5eca86dc87547d3dad61f4f80d60b4e5d`

The bundle is workstation-local; Architect review verified the recorded provenance against the exact implementation SHA but did not independently re-hash the workstation bytes through GitHub.

Production remains:
- `0719e9bf5af75a8065a9916d8e27c0247a3921ec`
- Alembic `0052 / 0052`

GR1 and GR1.1 are already HUMAN-ACCEPTED.

## Human gate

Run manually:

`/home/d.yacenko/tmp/gr12-88d60d8-artifact/bundle/personal_secretary`

Verify on the real Publications Task:

1. Before selecting «Публикация тезисов на 8-й Международной конференции …», both outstanding proposals are already visually cued on their respective compact Task↔object relations.
2. Selecting the Task does not reveal a proposal that was completely invisible in compact mode.
3. Inspector still shows separate real relation rows to «Решение Программного комитета DYSC 2026»: the confirmed directed `references` and the separate agent-proposed relation.
4. Rejecting the wrong proposed relation removes its proposal cue while the confirmed `references` attachment and object remain visible.
5. A single proposed attachment such as `Program_DYSC.pdf` still shows the normal proposal diamond.
6. No Task or Flow node moves merely because proposal cue aggregation changed.
7. GR1.1 behavior remains good: search facets do not hide dandelion glyphs.

GR1.2 is not HUMAN-ACCEPTED until the user reports this check.

The future RP1 dense relation-target picker remains DEFERRED and recorded in `PROJECT_STATE.md`. Do not start it until GR1.2 human acceptance is recorded.

Do not redeploy production, run Alembic, install/replace the desktop client automatically, start relation-editor work, agent-audit work, SW2-B, or another Graph-cleanup slice until the human-gate result is recorded. STOP.
