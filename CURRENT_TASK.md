# Current task — HOLD

TL2 Task Layout v2 is Architect-reviewed and ACCEPTED FOR HUMAN GATE.

Accepted implementation:
- `e98435fa492b3f362122f752df08bb81b573e423`
- executor HOLD: `b895699d4966154cc98a212883ad0a89f33e7fa7`

Canonical Task layout algorithm is now `task-map-v2`.

Architect review confirmed:
- confirmed `part_of` remains child/source -> parent/target and defines the structural forest;
- each structural parent owns a recursive local subtree/flower rather than placing descendants on a global root-centered ring;
- child subtrees are treated as modules with bounded envelopes;
- confirmed secondary Task relations can reduce avoidable edge length through deterministic orientation without detaching children from their `part_of` parents;
- Flow/People do not drive canonical Task centers;
- a usable `task-map-v1` snapshot is not reused; complete topology is resolved and one complete `task-map-v2` replacement is persisted through the existing optimistic contract;
- usable v2 snapshots are reused on ordinary entry;
- no backend/schema/Alembic/production change occurred.

Known implementation limits accepted for this human gate:
- sibling modules currently share a conservative ring clearance, so a large sibling subtree can push a small sibling farther from their common parent than the minimum single-child distance;
- orientation uses a bounded discrete search, not a global optimizer;
- old Task coordinates are not hard-pinned;
- semantic-window/page locality is intentionally not addressed in TL2 and belongs to Semantic Windows v2.

Human-check bundle:
- executable: `/tmp/tl2-e98435f-artifact/bundle/personal_secretary`
- BUILD_INFO: `/tmp/tl2-e98435f-artifact/BUILD_INFO.txt`
- launcher SHA-256: `56d876bbd202a979034eefcb4836127eb9d7f2e6552202b65a4f7bc519ee97f4`
- kernel SHA-256: `e7e22670bba7c1bad6ecc0bdc8891582108addb66a9e5063a708b84b34c4f096`

Human gate checklist:
1. On the real Academic tree, Publications should remain a compact local flower.
2. Teaching should have its own compact local flower instead of spreading leaves around the whole Academic tree.
3. Courses should behave as its own local branch as it grows.
4. Secondary Task links should avoid obviously unnecessary long lines where orientation can shorten them.
5. Task cards/subtree clusters should not overlap.
6. Tasks and People should still use the same canonical world/camera.
7. Quick regression: duplicate-title suffixes, rename, scrollable relation picker, and drag-created existing `part_of`.

Do not start Semantic Windows v2 until the user completes this human gate and the Architect records the result.

Production remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, Alembic `0052 / 0052`. STOP.
