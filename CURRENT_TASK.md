# CURRENT_TASK

ACTIVE

## REL1D-HG4E.1 — decouple Person rename stale-read generation from Task-actor reconciliation

### Context

HG4E implementation `1cb1269b019a7ea829766445268fbea201e5d4b1` is directionally correct:

- Person rename uses dedicated `PATCH /graph/people/{person_id}`;
- no embedding/provider dependency;
- rename errors are visible/retryable;
- returned title is applied immediately;
- canonical Task actor relations are removed from generic `Связи` presentation.

Architect review found one narrow concurrency regression.

Current successful rename does:

`_personTaskGeneration += 1`

to invalidate stale People responses.

But `_personTaskGeneration` is also the generation used by the accepted HG3.2/HG4B Task-actor reconciliation contract.

Failure scenario:

1. Person Task actor mutation succeeds.
2. Local actor row is updated immediately.
3. Background actor reconciliation starts with task generation N.
4. Before it returns, Person rename succeeds.
5. Rename increments `_personTaskGeneration` to N+1.
6. The actor reconciliation response is discarded as stale.
7. Rename does not queue a replacement actor reconciliation.
8. Final authoritative Task-derived Person state (for example `openTaskCount`) may remain stale until an unrelated later refresh.

### Goal

Keep rename stale-response protection without repurposing the Task-actor generation.

A Person rename must never restore an old title from a stale read, and it must never cancel the accepted guarantee that a successful Task actor mutation eventually receives one latest authoritative reconciliation.

### Required behavior

1. Keep `_personTaskGeneration` exclusively for Task actor mutation/reconciliation semantics.

2. Introduce one narrow Person-presentation/read generation (name may differ) used to invalidate stale Person detail/reconciliation reads after a successful rename.

3. A successful Person rename must:
   - increment the Person-presentation/read generation;
   - immediately apply the authoritative returned title exactly as HG4E already does;
   - NOT increment `_personTaskGeneration`.

4. `_loadRootedPerson` must capture and validate both:
   - existing rooted token / Person identity checks;
   - Task mutation generation where relevant;
   - Person-presentation/read generation.

A detail response started before a successful rename must not restore the old title.

5. Background `_PersonReconcileTarget` must carry enough generation state to distinguish:
   - stale actor state;
   - stale Person presentation/title state.

Do not collapse both concepts back into one integer.

6. If an actor reconciliation is already in flight when rename succeeds:
   - its pre-rename response must not apply as a whole Person presentation;
   - queue/coalesce exactly one follow-up reconciliation for the same current Person using the latest Task generation and latest Person-presentation generation;
   - max concurrent People-workspace reconciliation requests remains 1.

7. If multiple renames happen while one reconciliation is in flight, keep only the latest pending reconciliation target/generations. Do not start unbounded requests.

8. If rename succeeds while there is no reconciliation in flight, do not introduce a mandatory heavy People-workspace GET merely for rename correctness. The returned Person object remains authoritative for the title.

9. Existing Task actor behavior must remain:
   - foreground mutation result applies immediately;
   - authoritative `openTaskCount` is preserved locally until reconciliation;
   - final latest reconciliation can update it;
   - stale actor generations do not overwrite newer actor mutations;
   - A→B Person switch protection remains;
   - at most one reconciliation in flight.

10. Existing rename behavior must remain:
    - dedicated Person endpoint;
    - no embedding/provider dependency;
    - dialog waits for server;
    - failure remains visible/retryable;
    - unrooted rename does not re-root;
    - rooted/unrooted title updates immediately;
    - no full workspace reload blocks visible success.

11. Existing actor relation presentation filtering remains unchanged.

### Explicitly out of scope

Do NOT:

- change backend Person rename API semantics;
- modify generic object PATCH/embedding;
- change Task actor backend semantics;
- change People paging;
- change shared Task/People topology;
- change identity-candidate scan depth/email discovery;
- change PersonRole semantics;
- add schema/Alembic changes;
- deploy production;
- build/install the user's client;
- call providers/models;
- modify role-import image extraction;
- resume historical HG2 repair.

Prefer a client-only corrective.

### Expected files

Likely only:

- `client/lib/graph/graph_workspace_screen.dart`;
- `client/test/graph/person_rename_test.dart`;
- possibly existing Person task bridge tests.

Do not refactor unrelated controller state.

### Required tests

At minimum add/update focused Flutter tests proving:

1. Actor mutation succeeds; its reconciliation is held in flight.
2. Rename then succeeds while that reconciliation is held.
3. The pre-rename reconciliation response cannot restore the old title.
4. The rename does not advance the Task mutation generation / does not cause the actor mutation to lose convergence.
5. After releasing the stale reconciliation, exactly one fresh reconciliation runs for the same Person with latest generations.
6. That fresh reconciliation may update authoritative derived Task state such as `openTaskCount` while preserving the renamed title.
7. Max concurrent People-workspace reconciliation requests remains 1.
8. Multiple renames while reconciliation is in flight coalesce to one latest follow-up.
9. Rename with no reconciliation in flight performs no extra People-workspace GET.
10. Existing stale rooted-detail-after-rename test remains green.
11. Existing HG3.2/HG4B actor reconciliation tests remain green.
12. Existing HG4E rename failure/success and actor relation filtering tests remain green.

Run the smallest focused Flutter suite covering these contracts.

Run Dart format/analyze for touched files and `git diff --check`.

### Completion protocol

When implementation/checks are green:

1. update `PROJECT_STATE.md` with concise HG4E.1 facts;
2. replace this file with `HOLD`, recording implementation SHA and exact checks;
3. commit + push canonical `main`;
4. STOP.

Do not deploy or start topology/email-candidate work automatically.

Production remains:
`a9221699b4b725888213ff38e6673495a512042c`

Alembic remains:
`0054 / 0054`

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
