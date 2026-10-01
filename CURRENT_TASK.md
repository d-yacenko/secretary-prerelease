# Current task — HOLD

RP1 dense relation-target picker is Architect-reviewed and ACCEPTED FOR HUMAN GATE.

Accepted implementation:
- `83920bcfc31bc67fb21c0f0d8693d91b0b71e778`
- Executor HOLD: `f76559e06dc0c070d74e5166958ac4c621ecc7d9`

Architect review confirmed:

- duplicate Task disambiguation is display-only and uses normalized title keys: trim, collapse internal whitespace, lowercase;
- stored titles and object identity are unchanged; there is no fuzzy merge;
- visually equivalent Task titles receive confirmed `part_of` parent suffixes, or `(без родителя)`;
- proposed/rejected parents do not count as established disambiguation context;
- relation target rows are single-line and dense;
- finite Tasks use the normal Task glyph;
- ongoing Tasks/Directions use the existing infinity cue;
- provider identity reuses the existing provider icon system;
- assigned bookmark colors reuse the existing read-only bookmark glyph;
- bookmark colors are reconciled for the search-result batch in one request, not one request per row;
- bookmark-load failure is fail-soft and does not block row selection;
- long result sets remain bounded/scrollable inside the relation dialog;
- `part_of` candidate filtering, relation direction semantics, target identity, create payload, and post-create topology refresh are unchanged;
- no backend/API/schema/Alembic/production changes occurred;
- canonical Task layout remains `task-map-v2.2`.

Recorded checks:
- focused RP1 widget tests: 5 passed;
- preserved relation-picker / label / Graph regression tests: 19 passed;
- total recorded RP1-related tests: 24 passed;
- analyzer: no errors; 7 pre-existing infos in Graph screen;
- `git diff --check`: clean.

Human-check bundle, not installed:
- source: `83920bcfc31bc67fb21c0f0d8693d91b0b71e778`
- executable: `/home/d.yacenko/tmp/rp1-83920bc-artifact/bundle/personal_secretary`
- BUILD_INFO: `/home/d.yacenko/tmp/rp1-83920bc-artifact/BUILD_INFO.txt`
- build UTC: `2026-10-01T10:14:39Z`
- launcher SHA-256: `334f6a6d3c6efba5e73c9d6a6ee6b1690d04e4e48e3ec5d458d111d48ea707b8`
- kernel SHA-256: `403a70a95d6a8c014f4537da70b479f2983f7e92dbc624e43802a7fc08eb9450`

The bundle is workstation-local; Architect review verified the recorded provenance against the exact implementation SHA but did not independently re-hash the workstation bytes through GitHub.

Production remains:
- `0719e9bf5af75a8065a9916d8e27c0247a3921ec`
- Alembic `0052 / 0052`

No production rollout is required for RP1 because it is client-only.

## Human gate

Run manually:

`/home/d.yacenko/tmp/rp1-83920bc-artifact/bundle/personal_secretary`

Verify with live relation-target searches:

1. `Создание курсов` and `создание курсов` are immediately distinguishable by their confirmed parent context.
2. Each target occupies one compact line rather than title + textual kind subtitle.
3. Finite Task and ongoing/Direction are visually distinguishable.
4. Google/Yandex provider identity is visible where applicable.
5. Colored bookmark cues are visible for bookmarked targets.
6. A long result set remains scrollable and usable without dialog overflow.
7. Selecting a target and creating the relation behaves exactly as before.
8. Existing GR1/GR1.1/GR1.2 relation behavior remains intact.

RP1 is not HUMAN-ACCEPTED until the user reports this check.

Do not deploy production, run Alembic, install/replace the desktop client automatically, start relation-editor work, agent-audit work, SW2-B, GUX1, or another slice until the human-gate result is recorded. STOP.
