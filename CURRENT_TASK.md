# CURRENT_TASK

ACTIVE

## REL1D-HG6C — read-only diagnosis of role-authoring degradation after progressive hydration

### Context

HG6B is Architect-accepted.

Current main before this task authorization contains:
- HG6A progressive Person detail;
- HG6B global context palette / compact packing.

Production remains:
`0031f531d1215970093bea7add44fcd2259ec71b`

Alembic:
`0054 / 0054`

Human runtime finding from a freshly rebuilt client:

- role assignment worked quickly for several People;
- later, the role dialog stopped showing role-term suggestions;
- role assign/retract surfaced only `Не удалось обновить роль`;
- selected Person detail could show `Нет ролей` while heavy rooted sections were still loading.

Source facts already established by Architect:

1. Backend has no global 5–6-Person role limit.
   `MAX_ACTIVE_ASSIGNMENTS=16` is per Person.

2. Role-search failures are currently swallowed by the client dialog: a failed `GET /graph/person-role-terms` can leave no suggestions/create action without the concrete API error.

3. Assign/retract failures are reduced to the generic client text `Не удалось обновить роль`.

4. HG6A starts a heavy rooted `GET /graph/people-workspace?root_id=...` for every newly selected Person. Token/generation logic rejects stale **responses**, but does not cancel or serialize the underlying requests.

Leading hypothesis: rapid Person traversal accumulates concurrent heavy rooted reads and temporarily starves lighter role requests.

This is a hypothesis only. Do not implement a fix until this task gathers evidence.

### Goal

Perform one bounded diagnostic cycle that distinguishes:

A. client/background rooted-request concurrency starvation;
B. a concrete backend role-service/database error;
C. a role-cap/data-state issue;
D. insufficient evidence.

No production mutation and no product-code fix are authorized.

### A. Local/client concurrency evidence

1. Bootstrap from canonical current `main` and verify refs exactly.

2. Re-read the current implementations of:

- `_trackPersonSelection`;
- `_loadRootedPerson`;
- role-term search dialog;
- role assign/retract UI;
- `SecretaryApiClient.getPeopleWorkspace`.

3. Create a temporary diagnostic harness/test outside committed product scope, or minimally instrument an existing test in an uncommitted scratch copy, to measure the current behavior.

Required scenario:

- at least 8 distinct overview People;
- each rooted People request is gated and remains unresolved;
- rapidly select all 8;
- record:
  - number of rooted GETs started;
  - peak simultaneous unresolved rooted GETs;
  - whether selection-token logic stops the requests themselves or only rejects their eventual responses.

The diagnostic must not call production.

4. Then release all gates and prove the client returns to zero in-flight rooted requests.

5. Inspect role search/mutation error handling and record exactly:

- whether `GET /graph/person-role-terms` ApiException detail is currently visible to the user;
- whether POST/DELETE role ApiException detail is currently visible;
- whether a failed role-term search can suppress both suggestions and explicit create action.

Do not change these paths in HG6C.

### B. One BREAK-GLASS read-only production diagnostic

This task explicitly authorizes BREAK-GLASS **read-only** production inspection only.

Before SSH:

- read `docs/deploy.md`, `ops/production/target.json`, and named runtime files;
- verify canonical pinned target/host-key contract;
- verify GitHub `production` is exactly `0031f531d1215970093bea7add44fcd2259ec71b`;
- perform the required pinned public-key-only no-op.

If bootstrap/SSH invariant fails, record sanitized blocker and STOP.

Do not modify deployment files.

Do not move refs.

Do not restart/recreate any service.

Do not use provider/model/network APIs.

#### B1. Runtime identity

Read-only verify:

- runtime HEAD;
- runtime `origin/production`;
- API health;
- Alembic current.

All must remain the accepted production values.

#### B2. Recent API logs

Inspect only the recent diagnostic window, preferably the last 2 hours at run time.

Use the existing committed runtime/Compose service names; do not guess alternate hosts/paths.

Extract only sanitized facts for these route families:

- `GET /graph/people-workspace`;
- `GET /graph/person-role-terms`;
- `POST /graph/people/*/roles`;
- `DELETE /graph/people/*/roles/*`.

Report aggregate/sanitized:

- request counts;
- HTTP status counts;
- visible latency/timing if the current logs provide it;
- timeout / connection-pool / SQLAlchemy / PostgreSQL wait/error class if present;
- exception class and source function/line for relevant 5xx traces.

Do NOT report:

- Person IDs;
- role/context text;
- emails;
- request bodies;
- auth headers/tokens;
- raw SQL values;
- names or communication content.

If logs do not contain timing or route-level evidence, state that fact rather than inventing it.

#### B3. DB read-only aggregates

Using read-only SQL only, collect:

- total active PersonRoleAssignment rows for the current user;
- total PersonRoleTerm rows for the current user;
- maximum active role assignments on any one active Person;
- count of active People currently at the `MAX_ACTIVE_ASSIGNMENTS=16` cap;
- aggregate `pg_stat_activity` counts by `state`, `wait_event_type`, and `wait_event` for the application database at diagnostic time.

Do not return IDs, names, context strings, role strings, query text, or raw rows.

If permitted safely, also report count of sessions with transaction age buckets (for example <5s, 5–30s, >30s) without PIDs/query text.

Do not terminate sessions.

Do not VACUUM/ANALYZE/LOCK.

#### B4. Runtime resource snapshot

Read-only capture one sanitized no-stream snapshot for application runtime services:

- API container running state;
- API CPU/memory if readily available from the committed runtime environment;
- DB container health only.

No restarts.

### C. Interpretation

Classify the result into exactly one primary finding:

1. `CLIENT_CONCURRENCY_SUPPORTED`
   - local harness proves several concurrent heavy rooted reads;
   - production evidence is compatible with starvation/timeouts/waits or transient route degradation;
   - no role-cap/data error explains the symptom.

2. `BACKEND_ROLE_ERROR_SUPPORTED`
   - relevant 4xx/5xx/trace identifies a concrete role-service/DB failure independent of rooted-read concurrency.

3. `ROLE_CAP_OR_DATA_SUPPORTED`
   - aggregate data or relevant 422 proves the documented per-Person cap/data validation is the actual cause.

4. `INCONCLUSIVE`
   - source concurrency exists but production evidence cannot tie it to the observed failure and no separate error is proven.

Secondary findings may be recorded, especially:
- hidden client error detail;
- unbounded rooted background concurrency as an architectural risk even if not proven as this incident's primary cause.

### Explicitly out of scope

Do NOT:

- change client/backend product code;
- add cancellation/single-flight yet;
- change HTTP timeout/pool settings;
- change role limits;
- add retry logic;
- expose new errors yet;
- mutate Person roles;
- run POST/DELETE role calls against production;
- create test People/roles in production;
- deploy;
- move production refs;
- restart services;
- kill DB sessions;
- add schema/Alembic;
- optimize rooted backend evidence scans;
- change identity-candidate/email discovery;
- add embeddings/OpenSearch/cache;
- call providers/models;
- modify Agent/harness contracts.

### Completion protocol

1. Record only sanitized diagnostic facts in `PROJECT_STATE.md`.
2. Replace this file with `HOLD`, recording:
   - diagnostic classification;
   - local peak rooted concurrency;
   - sanitized production log/status facts;
   - aggregate role-cap facts;
   - aggregate DB wait/activity facts;
   - runtime identity/health;
   - exact commands/check categories, without secrets.
3. Commit + push ledger-only changes to canonical `main`.
4. STOP.

Do not implement the corrective automatically.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
