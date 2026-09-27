# Current task — Graph G2: priority/fair admission of explicit Task-Flow evidence

Release R2 and Graph G1R are ACCEPTED.

Production currently runs:
`fccc2b4c1c01430721865bd118f7eb2bbd207b38`

Alembic:
`0050`

This task authorizes one bounded Graph workspace corrective on `main` only.

NO production deploy is authorized.

Do not start S3 or H2D.

## Human evidence

The R2 human gate confirms the structural Task/Direction chain now appears immediately in overview.

A remaining problem is visible for Task <-> Flow evidence.

Example: the visible Task “Публикация статьи в Pattern Recognition” has several direct persisted relations in the right-side canonical relation inventory, including confirmed Agent relations such as `references` to message/artifact objects and another semantic relation to “Публикации в научной прессе”.

Those rows are marked:

`не на карте`

The Task itself is visible, but the related Flow endpoints and their compact map connections are absent.

This is NOT evidence of deleted data. Do not recreate relations.

## Current bounds

Keep the Graph bounded.

Current server defaults:

- seed_limit = 12;
- neighbor_limit = 12;
- node_limit = 80.

Current hard maxima:

- seed_limit = 24;
- neighbor_limit = 24;
- node_limit = 120.

Current client presentation already compresses ordinary Flow into compact satellites and has:

- satellite cap = 20 per Task;
- overflow `+N` presentation.

Do NOT solve this task by merely increasing or removing these limits.

## Product invariant

A bounded overview should prioritize semantic evidence over incidental graph neighborhood.

For Tasks already admitted to the workspace:

1. confirmed explicit Task <-> Flow relations created by the human or Secretary are high-value evidence;
2. those Flow endpoints should be admitted before incidental/source/system ordinary neighbors when node budget allows;
3. allocation must be fair across visible/admitted Tasks, so one Task cannot consume the whole remaining Flow budget;
4. the global `node_limit` remains authoritative;
5. if the global budget is genuinely exhausted, omitted relations remain visible in the direct relation inventory as `не на карте`.

The Graph should stay cognitively bounded, but at the current small data volume the user should not lose all meaningful Task evidence because unrelated older neighbors consumed the budget.

## Canonical priority relation set

For this task, priority Task <-> Flow evidence is a persisted edge satisfying all of:

- current user;
- `state == confirmed`;
- `origin in {user, agent}`;
- exactly one endpoint is `kind=task`;
- the other endpoint is a non-Task active/visible object;
- relation type is one of:
  - `references`;
  - `related_to`;
  - `depends_on`.

`part_of` remains handled by the existing structural Task closure.

Do not prioritize hidden actor/label/temporal relation types.

Do not give `source` or `system` edges this new priority; they remain eligible through the existing ordinary path.

Do not change provenance/state semantics.

## Part A — priority admission phase

Add a dedicated bounded admission phase in `GraphWorkspaceService`.

### Overview

After:
- seed Tasks are selected;
- confirmed `part_of` structural closure has completed;

and BEFORE the existing ordinary-neighbor phase:

- take ALL Task nodes currently admitted at that point, including Tasks brought in by structural `part_of` closure;
- find eligible priority Task <-> Flow relations as defined above;
- admit their non-Task endpoints subject to `node_limit`.

### Rooted workspace

For a rooted Task:

- complete existing `part_of` closure first;
- run the same priority Task <-> Flow admission across all admitted Tasks in that structural component;
- then run the existing ordinary-neighbor phase.

For a rooted non-Task object, preserve current behavior; do not invent Task evidence expansion from unrelated roots.

## Part B — fair and stable allocation

Priority Flow admission must be deterministic and fair across admitted Tasks.

Use a round-robin policy:

1. stable Task order by Task id;
2. for each Task, eligible priority edges ordered by:
   `Edge.created_at ASC, Edge.id ASC`;
3. admit at most one NEW Flow endpoint per Task per pass;
4. repeat passes while node budget remains and at least one new endpoint was admitted.

If several priority edges from the same Task point to an already-admitted Flow object:
- merge/retain the edges;
- do not spend another node slot.

If the same Flow endpoint is related to multiple Tasks:
- admit it once;
- preserve all eligible persisted edges among admitted nodes through existing G1R edge closure.

This ordering is intentionally monotonic: adding a newer explicit relation must not evict an older already-visible explicit relation solely because of UUID ordering.

## Part C — interaction with existing ordinary admission

After priority Task <-> Flow admission:

- run the existing ordinary-neighbor logic with the remaining node budget;
- keep existing G1 `created_at ASC, id ASC` ordering there;
- keep `neighbor_limit` for ordinary admission;
- priority Task <-> Flow evidence is NOT constrained by the ordinary per-center `neighbor_limit`; it is constrained by the global `node_limit` and fair round-robin policy.

Do not make the workspace unbounded.

Do not alter seed selection in this task.

## Part D — truncation semantics

Set/keep `truncated=true` when eligible priority Flow endpoints remain hidden because the global node budget is exhausted.

Do not claim an exact hidden count unless computed correctly.

If all priority Flow fits but incidental ordinary neighbors are hidden, existing truncation behavior remains valid.

The direct relation inventory remains the canonical full direct relation read and must continue to mark endpoints outside the current workspace as `не на карте`.

## Part E — client behavior should already be sufficient

No client product change is expected unless a regression proves otherwise.

Existing client behavior should:

- compact admitted Flow around related Tasks;
- draw Task <-> Flow anchor edges using existing relation grammar;
- expand selected Flow where current LOD already permits;
- use `+N` after the existing 20-satellite presentation cap.

Add/extend focused client tests only as necessary to prove that an admitted priority Flow node + edge is actually rendered as existing compact evidence.

Do NOT raise `kFocusLodSatelliteCap` in this task.

## Backend regressions

Add a focused G2 test file covering at least:

1. **priority beats incidental**
   - one admitted Task has >neighbor_limit older incidental/source/system neighbors;
   - it also has several confirmed user/agent `references` Flow neighbors;
   - explicit confirmed Flow endpoints are admitted before incidental endpoints.

2. **fairness across Tasks**
   - several admitted Tasks each have explicit confirmed Flow;
   - with a deliberately small node_limit, allocation is round-robin rather than one Task consuming the entire budget.

3. **part_of-added Task gets evidence**
   - parent/child Task enters workspace through confirmed `part_of`, not as a seed;
   - its confirmed user/agent Task <-> Flow evidence is still eligible for priority admission.

4. **shared Flow**
   - one Flow object is explicitly related to two visible Tasks;
   - it occupies one node slot and both persisted edges survive final G1R closure.

5. **provenance/state guard**
   - rejected edge is excluded;
   - source/system edge does not receive priority;
   - proposed edge does not receive confirmed-priority treatment;
   - existing ordinary behavior remains available where applicable.

6. **global bound**
   - priority evidence never exceeds node_limit;
   - truncated is true when additional priority Flow remains outside because of node_limit.

7. **stability**
   - appending a newer confirmed explicit relation does not evict an older admitted explicit relation while the same budget applies.

## Existing regression protection

Run relevant backend suites at minimum:

- `backend/tests/test_graph_workspace_g1.py`;
- `backend/tests/test_graph_workspace_g1r.py`;
- `backend/tests/test_graph_workspace_part_of_closure.py`;
- `backend/tests/test_graph_workspace.py`;
- `backend/tests/test_graph_workspace_caps.py`;
- `backend/tests/test_relations_api.py`;
- new G2 tests.

Run Ruff on touched backend files.

Run:
`git diff --check`

Run relevant client Graph/focus LOD tests proving existing compact rendering still works.

Linux debug build required only if client product files are changed. If no client product file changes, do not rebuild solely for this backend admission corrective; record that fact.

Known pre-existing/bootstrap-user test failures already documented in PROJECT_STATE are not authorization to change unrelated code.

## Scope guard

Do NOT:

- inspect or mutate production user data;
- recreate the user's missing-looking relations;
- use bearer tokens;
- deploy backend/client;
- move `origin/production`;
- change Alembic/schema;
- remove or raise global Graph limits;
- raise the client satellite cap;
- change Task/Direction ontology;
- change the four canonical relation types;
- modify G1R final edge closure except where needed to integrate priority admission safely;
- add AI/salience ranking;
- change seed selection;
- add graph pagination;
- fold in `SECRETARY_API_BASE_URL` precedence;
- start S3;
- start H2D;
- fix unrelated failures.

If tests show the direct Flow relations are actually deleted/rejected rather than merely not admitted, STOP and report the exact integrity path instead of implementing this admission policy.

## Completion

On completion:

1. update `PROJECT_STATE.md` with root cause, admission policy, implementation SHA, exact tests/results, and rollout requirement;
2. return `CURRENT_TASK.md` to HOLD;
3. push normal implementation/HOLD commits to `main`;
4. do not deploy;
5. STOP.

Final report must state:

- confirmed root cause;
- exact priority relation predicate;
- fairness algorithm;
- behavior for part_of-added Tasks;
- behavior for shared Flow endpoints;
- node_limit/truncated behavior;
- whether any client product code changed;
- backend tests;
- client tests if applicable;
- implementation SHA;
- HOLD/main SHA;
- whether G2 can be deployed schema-neutrally from current production.

Then STOP. Do not choose the next task yourself.
