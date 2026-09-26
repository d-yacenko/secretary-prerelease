# Current task — Visual Task Map V8C1: proposed relation visibility

V8B2 global packing is accepted on real data.

Client presentation only. No backend/API/schema changes. No layout changes. No production deploy. Do not start detail-pane work.

## Product invariant

Relation type and relation state are independent.

Type continues to define:
- arrow/no arrow;
- canonical source -> target direction;
- dashed/solid;
- structural/light emphasis.

State defines whether the relation is confirmed or proposed.

A proposed relation must keep the exact semantics of its type:
- proposed related_to: no arrow;
- proposed references: source -> target arrow;
- proposed depends_on: dashed source -> target arrow;
- proposed part_of: child/source -> parent/target arrow and still layout-neutral until confirmed.

## Strong proposed cue

The current tertiary-color-only cue is too subtle.

For every visible proposed relation, use both:
1. a strong theme tertiary/attention line treatment;
2. a small hollow diamond marker at the line midpoint.

Do not rely on color alone.

Full-card edge target:
- stroke >= 2.5 px;
- high-opacity proposal color;
- hollow midpoint diamond about 8 px;
- optional low-alpha wider under-stroke if useful.

Compact hairline target:
- stroke about 1.8–2.0 px;
- same proposal color family;
- hollow midpoint diamond about 5–6 px.

A proposed relation should remain discoverable in focus mode; do not reduce it below roughly 0.65 effective opacity.

## Preserve semantic vocabulary

Keep existing map semantics unchanged:
- related_to: solid, symmetric, no arrow;
- references: light solid, directed;
- depends_on: dashed, directed;
- part_of: structural solid, child -> parent;
- legacy contains: preserve current canonical direction.

Proposal styling overlays these semantics and must not replace them.

## Full flower

Update the full edge painter:
- strong proposed styling;
- midpoint proposal diamond;
- preserve semantic dashed/solid;
- preserve semantic arrow/no-arrow;
- preserve canonical direction.

## Collapsed dandelion

Current HybridHairline loses relation state.

Extend its presentation metadata to carry at least:
- proposed;
- dashed;
- existing directed/arrow placement.

Refactor the canonical hairline decoration so the chosen anchor edge supplies these values.

Compact painter requirements:
- confirmed references stays thin directed;
- symmetric stays undirected;
- depends_on stays dashed and directed;
- proposed gets strong proposal color + midpoint diamond;
- no geometry change.

Synthetic +N overflow stays neutral and undirected.

## Audit panel

Keep canonical source/type/target and current confirm/reject controls.

Make a proposed row a little easier to scan using an existing small label/chip/icon convention, without redesigning the panel.

## Confirmation transition

On confirm:
- proposed styling disappears immediately;
- semantic type/direction remains unchanged;
- Task movement = 0 px, except confirmed part_of may reproject via existing V8B2 hierarchy behavior.

On reject:
- current removal behavior remains.

## Tests

Prove at minimum:
1. proposed related_to is visibly proposed and undirected;
2. proposed references is visibly proposed and directed source -> target;
3. proposed depends_on is visibly proposed, dashed, directed;
4. proposed part_of is visibly proposed, child -> parent, and remains layout-neutral before confirm;
5. full proposed edge has midpoint marker;
6. compact proposed hairline carries proposal state;
7. compact proposed references arrow is correct;
8. compact proposed related_to is undirected;
9. compact proposed depends_on is dashed/directed;
10. confirmed hairline has no proposal cue;
11. proposal cue survives normal focus dimming;
12. overflow stays neutral;
13. pure styling changes move Tasks 0 px;
14. V8B2 packing tests remain unchanged;
15. V8A-R direction tests remain unchanged;
16. People mode unchanged.

Run:
- graph workspace/relation presentation tests;
- hybrid dandelion/local flower tests;
- V8B2 hierarchy tests;
- Task Profile relation regressions;
- Flutter analyze touched files;
- flutter build linux --debug;
- git diff --check.

## Completion

Record implementation SHA and exact proposal styling in PROJECT_STATE.md.
Return CURRENT_TASK.md to HOLD.
Do not start detail-pane work.
Do not deploy production.
Push to origin/main and STOP.

Human review decides whether proposal visibility is sufficient.
