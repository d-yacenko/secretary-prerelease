# CURRENT_TASK

ACTIVE

## REL1D-HG4A — read-only production audit of recent People persistence, overview visibility, and Task actor mutations

### Context

Human acceptance on 2026-10-09 exposed two serious People issues.

Source review already confirms:

1. Person↔Task foreground mutation feedback is skipped for a Person selected from the unrooted People overview because `_personSurfaceStill(personId)` currently requires `controller.rootId == personId`. In the normal overview-selection flow `rootId == null`, so the server mutation may succeed while the local card remains stale until refresh.

2. Manual `POST /graph/people` creation persists a confirmed user-origin Person, but unrooted People overview is bounded to `DEFAULT_SEED_LIMIT=12`. Positive-salience People are selected first; remaining slots are filled by zero-salience People. A manual Person without identity/communication normally has zero salience, while an approved promotion candidate has communication-backed identity/evidence and positive salience. There is no ordinary People overview paging path.

The relevant backend source files are identical between current main and production:
`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`.

Before authorizing product fixes, confirm what was actually persisted in production.

### Goal

Build and execute one narrowly scoped, fail-closed, read-only production audit that answers:

- whether recently created Person objects exist and remain active;
- how many recent People are manual-like vs promotion/identity-backed;
- whether those recent categories are included in the current 12-Person overview;
- whether recent Task actor add/remove operations are actually persisted in `edges`;
- whether the production runtime/ref/schema still match the pinned expected state.

No production mutation of any kind is allowed.

### Authorization

This task authorizes:

1. source-only construction/tests of a dedicated one-shot production audit harness under `ops/production/`;
2. exactly one live invocation of that harness against the canonical production target after all fail-closed preflight checks pass.

This task does NOT authorize deployment, repair, data editing, provider calls, model calls, restart, migration, sync, backfill, or application configuration changes.

### Pinned production state

Production release must be exactly:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Alembic must be exactly:

`0054 (head)`

The remote checkout, `origin/production`, API/worker/db health, canonical origin/path, target host key, and read-only DB transaction must all be verified before census facts are emitted.

If any invariant differs, STOP and report a sanitized blocker. Do not repair or probe alternatives.

### Harness design

Follow the established fail-closed pattern used by existing production census tools, but do not reuse an old harness whose pinned SHA/revision is stale.

Expected files may include a new local entrypoint, streamed remote helper, and focused tests under:

- `ops/production/`
- `ops/production/tests/`

Do not modify product backend/client code in this task.

The remote helper must:

- be streamed over the pinned SSH connection; do not copy secrets;
- verify `/opt/secretary`, canonical origin, clean worktree, exact HEAD, exact `origin/production`;
- require db/api/worker running, db healthy, API health OK;
- require exactly one Alembic head line `0054 (head)`;
- run all database/service reads inside a transaction proven `READ ONLY`;
- make zero provider/model/network calls other than the existing local API health check;
- contain no mutation SQL or application mutation path.

### User scope / fail-closed selection

The audit must not guess which user's data to inspect.

Use a deterministic fail-closed rule:

- if production has exactly one application user, audit that user's People state internally without printing the user id;
- if there is not exactly one user, emit a sanitized blocker and STOP before Person-specific facts.

Do not print user ids, Person ids, Task ids, edge ids, names, emails, account identifiers, canonical identities, raw message content, provider payloads, or raw DB errors.

### Audit window

Use a fixed recent window of **48 hours** relative to production DB time for recent-person and recent-actor facts.

### Required facts

Emit only strict machine-parseable aggregate/boolean/numeric facts.

At minimum include:

#### Runtime / safety

- `AUDIT_PREFLIGHT=pass`
- `AUDIT_READ_ONLY=on`
- `PRODUCTION_SHA_OK=true`
- `ALEMBIC_0054_OK=true`
- `USER_COUNT=1`
- `AUDIT_WINDOW_HOURS=48`

#### Person persistence

For active/non-hidden, non-rejected Person objects:

- `ACTIVE_PERSON_TOTAL`
- `RECENT_PERSON_48H`
- `RECENT_PERSON_WITH_ACTIVE_IDENTITY`
- `RECENT_PERSON_WITHOUT_ACTIVE_IDENTITY`
- `RECENT_PERSON_WITH_ACTIVE_CONFIRMATION_EVIDENCE`

Define a conservative internal classification:

- **manual-like recent Person** = recent active Person with no active PersonIdentity and no active PersonIdentityEvidence;
- **identity-backed recent Person** = recent active Person with at least one active PersonIdentity.

Emit:

- `RECENT_MANUAL_LIKE`
- `RECENT_IDENTITY_BACKED`

Do not claim manual-like means definitely created through the manual button; it is only an audit classification.

#### Exact current People overview behavior

Use the current production application service semantics rather than inventing a second ranking algorithm.

Inside the read-only transaction, call the current production `PersonGraphWorkspaceService(...).get_workspace()` for the sole user and inspect only aggregate membership.

Emit:

- `PEOPLE_OVERVIEW_DEFAULT_LIMIT` (expected 12)
- `PEOPLE_OVERVIEW_RETURNED`
- `PEOPLE_OVERVIEW_TRUNCATED`
- `RECENT_PERSON_IN_OVERVIEW`
- `RECENT_PERSON_OUTSIDE_OVERVIEW`
- `RECENT_MANUAL_LIKE_IN_OVERVIEW`
- `RECENT_MANUAL_LIKE_OUTSIDE_OVERVIEW`
- `RECENT_IDENTITY_BACKED_IN_OVERVIEW`
- `RECENT_IDENTITY_BACKED_OUTSIDE_OVERVIEW`

Also inspect current salience ranking via the production service and emit only counts:

- `CURRENT_SALIENCE_RANKED_COUNT`
- `CURRENT_POSITIVE_SALIENCE_COUNT`
- `RECENT_MANUAL_LIKE_POSITIVE_SALIENCE`

This should test the source hypothesis without exposing identities.

#### Task actor persistence

For edge types exactly:

- `requested_by`
- `delegated_to`
- `waiting_on`
- `involves`

and `updated_at` within the last 48 hours, emit:

- `RECENT_TASK_ACTOR_UPDATED_48H`
- `RECENT_TASK_ACTOR_ACTIVE_48H`
- `RECENT_TASK_ACTOR_REJECTED_48H`
- `LATEST_TASK_ACTOR_UPDATE_AGE_SECONDS` if at least one exists, otherwise a documented sentinel such as `-1`.

These facts are only evidence that actor mutations are reaching persistence; do not infer a specific click unless timing makes that explicit in the Architect review.

### Output safety

The local parser must reject any unexpected key.

The committed harness/test output contract must make it structurally impossible to print:

- title/name;
- UUID/id;
- email/address;
- provider account identifiers;
- identity values;
- raw SQL rows;
- raw stderr from production commands.

The live final report may summarize only the approved aggregate facts.

Do not commit live user data or a production artifact containing personal values.

### Required tests

At minimum test:

1. wrong release SHA fails before SSH/runtime audit;
2. wrong `origin/production`, HEAD, cwd, origin, health, or Alembic fails closed;
3. Alembic accepts exactly one non-empty `0054 (head)` line and rejects multiple heads;
4. transaction must prove `transaction_read_only=on`;
5. user count other than exactly 1 blocks Person-specific audit;
6. output parser accepts only the approved aggregate keys/types and rejects extra/raw identity-like keys;
7. audit SQL/service helper contains no mutation path;
8. recent manual-like vs identity-backed classification works on deterministic fixtures;
9. overview membership counts are computed from the service-returned ids without emitting ids;
10. Task actor active/rejected recent counts and latest-age sentinel are parsed correctly;
11. no provider/model call path exists;
12. `git diff --check` clean and Ruff/appropriate Python checks pass.

### Live invocation

After source tests are green, execute the new audit exactly once.

The live invocation is consumed only after the remote audit marker is reached. A local/bootstrap/SSH-preflight stop does not count as a production audit result.

If live invocation succeeds:

1. update `PROJECT_STATE.md` with only sanitized aggregate conclusions/facts;
2. replace this file with `HOLD`, recording harness implementation SHA, live result, and checks;
3. commit + push;
4. STOP.

If it blocks or fails:

1. record only the sanitized blocker;
2. return `HOLD`;
3. do not repair production and do not start a second live attempt without fresh Architect authorization;
4. commit + push;
5. STOP.

### Explicitly out of scope

Do NOT:

- fix the unrooted Person mutation UI bug;
- change People overview ranking/limit/paging;
- change Person creation semantics;
- attach identities to manual People;
- create/delete/merge People;
- alter Task actor edges;
- deploy a backend/client;
- restart containers;
- change schema/Alembic;
- call providers or models;
- resume historical HG2 repair/backfill;
- modify raster role-import extraction.

No next coding phase without fresh Architect review of the live audit.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
