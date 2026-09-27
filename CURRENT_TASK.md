# Current task — Client C1: exact G3A-R1 Linux bundle for human relayout gate

Graph G3A-R1 is architect-accepted.

Client product implementation:
`dc7bde42cc1a382c911fb968f35518f69356193c`

Current main/documentation SHA:
`d74b399e574ec50bc59ec035fd0d0e81ec359bc2`

Production backend/runtime and `origin/production` remain:
`489741540e30a775e2ea086f3976d7305512afe2`

Alembic remains:
`0050`

This task authorizes only an exact-current-main Linux debug client build and startup smoke for the human G3A-R1 gate.

NO backend deploy is authorized.
Do not move `origin/production`.
Do not implement prompt/ontology changes in this task.
Do not start `Скрыть связи`, G3B, S3, or H2D.

## 1. Clean exact checkout

Use the canonical repository and a clean checkout of exact:

`d74b399e574ec50bc59ec035fd0d0e81ec359bc2`

Verify:
- local commit is exact;
- client product diff from G3A-R1 implementation contains no later client product changes;
- production remains exact `489741540e30a775e2ea086f3976d7305512afe2`.

If refs moved or checkout is dirty/ambiguous, STOP.

## 2. Focused client gate

Run at minimum:

- `client/test/graph/graph_workspace_controller_test.dart`;
- `client/test/graph/graph_part_of_dialog_test.dart`;
- `client/test/graph/graph_map_relation_test.dart`;
- `client/test/graph/graph_direct_relation_inventory_test.dart`;
- relevant G3A semantic-window tests;
- G1R;
- proposed-relation tests;
- hierarchy/hybrid/focus LOD tests.

Run Flutter analyze on the G3A-R1 touched client files.

Run:
`git diff --check`

The three documented object-detail finders for `Удалить` / `Спросить секретаря` are not authorization for unrelated fixes.

## 3. Exact Linux build

From exact current-main SHA:

```bash
cd client
flutter build linux --debug
```

Record the ABSOLUTE path ending in:

`build/linux/x64/debug/bundle/personal_secretary`

Verify adjacent `lib` and `data` are present.

Do NOT install over the user's existing client.

Do NOT modify saved API URL, preferences, secure storage, or token.

A single startup-only launch on the existing graphical session is allowed. Do not interact with product data.

## 4. Human gate — executor does not perform

The human launches the exact bundle.

The next real Task<->Task/Direction topology edit is sufficient; do not create fake production data solely for the test.

Expected behavior after a successful visible Task<->Task relation mutation:

- relation persistence succeeds;
- current overview/rooted workspace refreshes authoritatively;
- Task cards receive fresh geometry immediately;
- old long rays/stale coordinates do not remain;
- one fit occurs after geometry changes;
- semantic-window metadata reflects any `part_of` constellation merge/split;
- Task<->Flow additions continue to preserve stable Task geography.

The previously observed case was linking “Публикации в научной прессе” into Direction “Академ”.

No need to undo/recreate that relation just for testing. The next natural structural edit can serve as the gate.

## 5. Completion

On success:

1. update `PROJECT_STATE.md` with exact source SHA, test/analyze/build result, absolute bundle path, startup result, and note that production backend stayed unchanged;
2. return `CURRENT_TASK.md` to HOLD;
3. push documentation completion to `main`;
4. STOP.

Final report:

1. SUCCESS or BLOCKED;
2. exact client source SHA;
3. production backend SHA;
4. focused test result;
5. analyze result;
6. absolute Linux bundle path;
7. startup result;
8. documentation/HOLD SHA.

Then STOP. Do not start the ontology prompt corrective yourself.
