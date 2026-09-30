# Current task — HOLD

TL2.1.1 canonical confirmed-edge filtering is Architect-reviewed and ACCEPTED FOR HUMAN GATE.

Accepted implementation:
- `e77a2bbc3d3e91e0380820ddb4557429a20a8f29`
- executor HOLD: `ca5b59c80061e17000e84c07428f2a94526f498e`

Canonical Task layout algorithm is `task-map-v2.1.1`.

Architect review confirmed:
- confirmed `part_of` remains child/source -> parent/target and defines the structural forest;
- only confirmed visible non-`part_of` Task↔Task relations enter canonical baseline/order/component/free-Task layout inputs;
- proposed/rejected `depends_on`, `references`, and `related_to` no longer move Task centers or merge canonical components;
- proposed relation rendering semantics are unchanged;
- TL2.1 sibling reordering remains active for confirmed secondary links;
- a usable `task-map-v2.1` snapshot is replaced once by a complete v2.1.1 snapshot;
- usable v2.1.1 snapshots are reused;
- no backend/schema/Alembic/production change occurred.

Human-check bundle:
- executable: `/tmp/tl211-e77a2bb-artifact/bundle/personal_secretary`
- BUILD_INFO: `/tmp/tl211-e77a2bb-artifact/BUILD_INFO.txt`
- launcher SHA-256: `8dfeaa1e83108a9eb1d51bb5471ef3a4915dcfa79a266c02c69b1f5294a03ff2`
- kernel SHA-256: `9abe30181afe8d3c862afe47fe2e9de2ce7914712e260024d1546f6e7136edeb`

Human gate checklist:
1. On the real Academic map, compare «Трудоустройство в МФТИ» ↔ «Преподавание Java в МФТИ»: the dashed secondary relation should be clearly shorter if sibling reordering can achieve it.
2. Teaching/Publications/Courses should remain coherent compact local flowers.
3. No Task cards/subtree clusters should overlap.
4. Quick regression: duplicate-title suffixes, rename, scrollable relation picker, drag-created existing `part_of`.
5. Do not evaluate page tearing yet: Semantic Windows v2 has not started, so petals may still be split across areas.

Do not start Semantic Windows v2 until the user completes this human gate and the Architect records the result.

Production remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, Alembic `0052 / 0052`. STOP.
