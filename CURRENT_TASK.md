# Current task — HOLD

GR1.1 search-filter scope isolation is Architect-reviewed and ACCEPTED FOR HUMAN GATE.

Accepted implementation:
- `4ca65eb54b9f3218a861e9db0106b89250938bde`
- Executor HOLD: `ee4044a11146e6a52bebcf73ececf66152d8ce1b`

Architect review confirmed:

- Graph search kind/provider facets are search-only;
- `visibleNodes`, `visibleEdges`, and `visiblePositions` no longer depend on search facets;
- changing a search facet does not clear the current Graph selection;
- Graph no longer enters the canvas state “Нет объектов по выбранным фильтрам” from a search facet;
- Graph toolbar reruns search with the selected kind/provider but does not mutate canvas membership;
- Graph-specific semantics clarify `Тип в поиске` / `Источник в поиске`;
- shared `CompactObjectFilters` keeps previous wording when no Graph-specific scope label is supplied;
- the incident-shaped regression keeps the hybrid `Program_DYSC.pdf` glyph visible while `kind=task` is active and after a Task-topology refresh;
- canonical Task centers, `task-map-v2.2`, SW2-A semantic windows, GR1 relation behavior, and completed-Task lifecycle semantics are unchanged;
- no backend/schema/Alembic/production changes occurred.

Recorded checks:
- Flutter client suite: 165 passed;
- changed client analysis: 0 errors; 9 pre-existing infos;
- `git diff --check`: clean.

Human-check bundle, not installed:
- source: `4ca65eb54b9f3218a861e9db0106b89250938bde`
- executable: `/home/d.yacenko/tmp/gr11-4ca65eb-artifact/bundle/personal_secretary`
- build UTC: `2026-10-01T08:32:04Z`
- adjacent BUILD_INFO present per Executor ledger
- launcher SHA-256: `7ea6dfb25340029beddba20d31e5997a2d8ef27a3dd66f8dfa2c4365d70b9352`
- kernel SHA-256: `169beda7a225c9f7e2245fa3c511ec9db96d325010843bb48fe5f700f7837d5e`

The bundle is workstation-local; Architect review verified the recorded provenance against the exact implementation SHA but did not independently re-hash the workstation bytes through GitHub.

Production remains:
- `0719e9bf5af75a8065a9916d8e27c0247a3921ec`
- Alembic `0052 / 0052`

No production rollout is required for GR1.1 because this slice is client-only.

## Human gate

Run manually:

`/home/d.yacenko/tmp/gr11-4ca65eb-artifact/bundle/personal_secretary`

Use existing live data and verify:

1. Publications/other Task flowers show their hybrid “dandelion” file/email/note glyphs normally.
2. Search for a completed Task such as the ICDM publication task.
3. Set the Graph search kind facet to `Задача`.
4. Search results are filtered to Tasks, but all existing hybrid glyphs across the current canvas remain visible.
5. With that facet still active, reconnect/create the intended Task relation if needed; after the resulting topology refresh, hybrid glyphs still remain visible.
6. Changing provider facet likewise affects search results only.
7. Changing facets does not clear the currently selected Graph object.
8. GR1 relation repair still works: confirmed removable agent relations can be removed/rejected and wrong directed relations can be recreated correctly.
9. Proposed attached endpoints such as `Program_DYSC.pdf` remain visible automatically.
10. TL2.2 flower geometry and SW2-A whole-component pagination remain coherent.

GR1 / GR1.1 are NOT HUMAN-ACCEPTED until the user reports this check.

Do not redeploy production, run Alembic, install/replace the desktop client automatically, start SW2-B, or begin another Graph-cleanup slice until the human-gate result is recorded. STOP.
