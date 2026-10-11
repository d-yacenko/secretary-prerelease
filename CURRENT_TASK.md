# CURRENT_TASK

ACTIVE

## REL1D-HG5A — read-only audit for shared Task/People semantic-window topology

### Context

Human acceptance confirms HG4E/HG4F are working in production.

The next architecture issue is the previously recorded mismatch between Task and People overview partitioning.

Current accepted product model:

- Tasks and People live in one canonical Task-world coordinate system;
- People placement is derived from confirmed active Task actor anchors;
- Tasks overview is partitioned into semantic windows of complete Task constellations;
- People overview is currently paged independently by salience/title order.

This means Task window 1 and People page 1 do not necessarily represent the same part of the world, even though People are positioned using canonical Task coordinates.

Before changing the topology contract, quantify real production cases that affect the design:

- People with no active Task anchors;
- People whose anchors all belong to one Task semantic window;
- People whose anchors span multiple Task semantic windows;
- incomplete/unresolvable anchor sets.

Do not choose a home-window/duplication policy without this evidence.

### Goal

Build and run one narrowly scoped, fail-closed, read-only production audit that describes how active People map onto the current canonical Task semantic windows.

No product mutation or topology implementation is authorized.

### Authorization

This task authorizes only:

1. source-only review of current Task semantic-window and People landscape-anchor contracts;
2. construction/tests of one dedicated aggregate-only production audit harness under `ops/production/`;
3. exactly one live read-only invocation of that harness after all fail-closed checks pass.

No deploy, ref movement, restart, schema change, provider/model call, or data mutation is authorized.

### Pinned production

Production release must be exactly:

`50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`

Alembic must be exactly:

`0054 (head)`

Require the same canonical target/path/origin/clean-worktree/health/DB/host-key contracts used by accepted production audit tooling.

All DB/service inspection must run inside a transaction proven `READ ONLY`.

If any pinned invariant differs, STOP and report one sanitized blocker. Do not repair or probe alternatives.

### User selection

Do not guess the application user.

- If production has exactly one application user, audit that user internally.
- Otherwise emit a sanitized blocker and STOP before Person-specific facts.

Never print the user id.

### Canonical semantics to reuse

The audit must use production application semantics rather than reimplementing topology:

1. Task semantic windows:
   - instantiate current production `GraphWorkspaceService`;
   - use unrooted `get_workspace(window_index=N)` with production defaults;
   - derive `window_count` from the service response;
   - enumerate each valid semantic window exactly once;
   - use Task objects returned by those windows as canonical Task→window membership.

2. People overview/anchors:
   - instantiate current production `PersonGraphWorkspaceService`;
   - enumerate all current unrooted People overview pages using the service's own `window_count`;
   - every active Person must be encountered exactly once across current HG4C People pages;
   - use each Person presentation's existing `landscape_task_ids` and `landscape_task_ids_complete`;
   - do not query/derive alternate social/task links.

3. Only confirmed active Task actor anchors represented by current `landscape_task_ids` participate in this audit.

Do not count generic Person↔Task graph relations as landscape anchors.

### Required aggregate facts

Emit only strict machine-parseable numeric/boolean facts.

#### Runtime/safety

- `AUDIT_PREFLIGHT=pass`
- `AUDIT_READ_ONLY=on`
- `PRODUCTION_SHA_OK=true`
- `ALEMBIC_0054_OK=true`
- `USER_COUNT=1`
- `PROVIDER_NETWORK_CALLS=0`

#### Task semantic windows

- `TASK_SEMANTIC_WINDOW_COUNT`
- `TASK_SEMANTIC_TASK_TOTAL`
- for each window index 0..N-1, sanitized count keys such as:
  - `TASK_WINDOW_0_TASK_COUNT`
  - `TASK_WINDOW_1_TASK_COUNT`
  - etc.

The parser may allow dynamic `TASK_WINDOW_<integer>_TASK_COUNT` keys only when indexes exactly cover 0..N-1 without gaps.

Also emit:

- `TASK_IDS_DUPLICATED_ACROSS_WINDOWS` — expected 0
- `TASK_WINDOW_UNION_UNIQUE_COUNT`

#### People anchor topology

For all active People:

- `ACTIVE_PERSON_TOTAL`
- `PEOPLE_PAGES_ENUMERATED`
- `PEOPLE_ENUMERATED_UNIQUE`
- `PEOPLE_DUPLICATED_ACROSS_CURRENT_PAGES` — expected 0

Classify each Person using only existing landscape anchors:

- **unanchored**: complete anchor set and zero `landscape_task_ids`;
- **single-window anchored**: complete, non-empty anchors, all canonical anchor Tasks belong to exactly one semantic Task window;
- **multi-window anchored**: complete, non-empty anchors span two or more semantic Task windows;
- **incomplete anchors**: `landscape_task_ids_complete == false`;
- **unmapped anchors**: complete, non-empty anchor set contains at least one active anchor Task not found in any Task semantic window.

Emit:

- `PEOPLE_UNANCHORED`
- `PEOPLE_SINGLE_WINDOW_ANCHORED`
- `PEOPLE_MULTI_WINDOW_ANCHORED`
- `PEOPLE_INCOMPLETE_ANCHORS`
- `PEOPLE_UNMAPPED_ANCHORS`

These categories must be mutually exclusive and sum exactly to `ACTIVE_PERSON_TOTAL`.

#### Per-window Person relevance

For each semantic Task window, count People whose complete anchor set includes at least one Task in that window:

- `PEOPLE_RELEVANT_TO_WINDOW_0`
- `PEOPLE_RELEVANT_TO_WINDOW_1`
- etc.

A multi-window Person may contribute to more than one of these counts. This is intentional for the audit only and does **not** pre-decide UI duplication policy.

Also emit:

- `PEOPLE_WINDOW_RELEVANCE_MEMBERSHIPS` — total memberships across all windows;
- `PEOPLE_MULTI_WINDOW_MAX_SPAN` — max distinct Task windows touched by one Person, 0 when none;
- `PEOPLE_WITH_ONE_TASK_ANCHOR`;
- `PEOPLE_WITH_MULTIPLE_TASK_ANCHORS`.

#### Current independent People paging comparison

To quantify the mismatch, emit:

- `CURRENT_PEOPLE_PAGE_COUNT`;
- `CURRENT_PEOPLE_PAGE_WINDOW_ALIGNED_COUNT`:
  count of active People whose current HG4C People page index equals their only semantic Task window index; only single-window anchored People are eligible for this fact;
- `CURRENT_PEOPLE_PAGE_WINDOW_MISMATCH_COUNT`:
  single-window anchored People whose independent People page differs from their Task semantic window.

Do not emit Person ids/names/page memberships.

### Audit invariants

The live audit must fail closed if:

1. a Task appears in more than one semantic Task window;
2. People HG4C page enumeration returns the same Person twice;
3. People HG4C page union count differs from active Person count;
4. mutually exclusive Person topology categories do not sum to active Person count;
5. any dynamic window-count keys are missing/gapped;
6. service responses disagree on declared window counts while enumerating;
7. read-only transaction proof is absent.

### Output safety

Do not print or commit:

- Person names/titles;
- Person/Task/edge UUIDs;
- emails or identity values;
- role labels;
- raw message content;
- provider payloads;
- raw DB rows;
- raw production stderr.

The local parser must reject unapproved keys and identity-like/raw fields.

No live-data artifact containing identifiers may be committed.

### Required tests

At minimum prove:

1. wrong production SHA blocks before live audit;
2. wrong cwd/origin/production ref/health/Alembic blocks fail closed;
3. transaction must prove `transaction_read_only=on`;
4. user count !=1 blocks Person-specific audit;
5. parser accepts fixed aggregate keys and only contiguous dynamic window count keys;
6. parser rejects identifiers/names/raw rows/unapproved keys;
7. deterministic fixture with:
   - one unanchored Person;
   - one single-window Person;
   - one multi-window Person;
   - one incomplete Person;
   - one unmapped Person;
   produces mutually exclusive counts correctly;
8. per-window relevance allows multi-window Person membership in multiple windows without changing exclusive category totals;
9. duplicate Task membership across semantic windows fails;
10. duplicate Person across HG4C People pages fails;
11. People page union != active Person total fails;
12. current People-page vs semantic-window mismatch counts are computed only for single-window anchored People;
13. no provider/model call path exists;
14. `git diff --check` and Ruff/appropriate Python checks pass.

### Live invocation

After source tests are green, execute exactly one live audit.

The live authorization is consumed only once the remote audit marker is reached. Local/bootstrap/pre-SSH failure does not consume it.

If live audit succeeds:

1. update `PROJECT_STATE.md` with only sanitized aggregate facts and conclusions;
2. replace this file with `HOLD`, recording harness SHA/live result/checks;
3. commit + push canonical `main`;
4. STOP.

If it blocks/fails after the remote marker:

1. record only the sanitized blocker/result;
2. set `CURRENT_TASK.md` to `HOLD`;
3. do not repair or retry live production without fresh authorization;
4. commit + push;
5. STOP.

### Explicitly out of scope

Do NOT:

- change Task semantic window packing;
- change People page membership;
- change shared topology;
- choose home-window vs duplicate-Person policy;
- change People placement coordinates;
- change Task actor semantics;
- change identity-candidate/email discovery;
- change salience;
- deploy production;
- move production refs;
- modify schema/Alembic;
- call providers/models;
- mutate People/Tasks/edges;
- modify role-import image extraction;
- resume historical HG2 repair.

This task is evidence gathering only.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
