# CURRENT_TASK

ACTIVE

## REL1D-HG2D4 — one-shot live read-only production HG2 repair preflight census

REL1D-HG2D3 and HG2D3.1 are ARCHITECT SOURCE-ACCEPTED.

Accepted harness source:

- D3: `2d98c4a85a4d0825bddb62b1da9bfbfed2201791`
- D3.1: `32909509864050c3289702d8ba2dbb1aedebf002`

Production/backend runtime and production ref must remain exactly:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Expected Alembic:

`0054`

This task authorizes exactly ONE live invocation of the committed read-only aggregate HG2 preflight census.

It authorizes:
- the harness's pinned SSH connection;
- production runtime/DB guard checks;
- one READ ONLY production DB census through the committed streamed helper;
- aggregate integer/boolean output only.

It does NOT authorize:
- any provider network call;
- any repair primitive;
- any sync/backfill/reconcile;
- any DB mutation;
- any credential/token/session decryption;
- any production ref/runtime change;
- any deploy/rollback;
- any client action;
- human REL1D acceptance.

## Mandatory bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- `ops/production/hg2_repair_preflight.py`
- `ops/production/remote_hg2_repair_preflight.py`
- `ops/production/tests/test_hg2_repair_preflight.py`
- `ops/production/target.json`

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE D4 task.

Verify before invocation:

1. `origin/production == f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`;
2. production SHA resolves and is still in `origin/main` history;
3. local canonical worktree is clean;
4. D3/D3.1 harness files on current main are byte-identical to their accepted post-D3.1 content:
   - no diff from `32909509864050c3289702d8ba2dbb1aedebf002` to current `origin/main` for:
     - `ops/production/hg2_repair_preflight.py`
     - `ops/production/remote_hg2_repair_preflight.py`
     - `ops/production/tests/test_hg2_repair_preflight.py`
5. no later `ops/production/target.json` change invalidates the pinned deployment target contract.

If any pre-invocation invariant fails:
- do not run SSH;
- record sanitized blocker;
- HOLD;
- STOP.

## Exactly one authorized command

From the canonical repository root, run exactly once:

`python3 ops/production/hg2_repair_preflight.py`

Do not pass extra arguments.
Do not wrap it in a retry loop.
Do not rerun it in the same task, even if it fails.

The committed harness owns:
- host-key pinning;
- remote repository/ref/runtime guards;
- API/DB/worker health checks;
- exact single Alembic `0054 (head)` check;
- READ ONLY transaction setup/verification;
- strict output parsing and identity leakage rejection.

Do not bypass the harness with direct SSH or SQL.

## Required successful protocol

A successful run must contain exactly the committed protocol shape, including:

- `HG2_PREFLIGHT_MARKER=started`
- `HG2_PREFLIGHT_GUARDS=pass`
- `HG2_PREFLIGHT_READ_ONLY=on`
- the fixed ordered aggregate facts;
- `YANDEX_PROVIDER_UIDVALIDITY_KNOWN=false`
- `PROVIDER_NETWORK_CALLS=0`
- `HG2_PREFLIGHT_TERMINAL=success`

The process exit code must be 0.

If the protocol is malformed, blocked, incomplete, non-zero, or reports anything except `PROVIDER_NETWORK_CALLS=0`:
- no retry;
- HOLD;
- STOP.

## Evidence handling

The output is intentionally aggregate-only and may be recorded in the repo.

Create exactly one new evidence artifact:

`docs/rel1d_hg2_production_preflight_census.md`

Record:

### Identity / guards
- live invocation date/time;
- production SHA;
- current main SHA;
- expected Alembic;
- exact command;
- exit code;
- terminal protocol status;
- READ ONLY status;
- `PROVIDER_NETWORK_CALLS=0`;
- `YANDEX_PROVIDER_UIDVALIDITY_KNOWN=false`.

### Aggregate facts
Record every fixed fact emitted by the accepted harness, exactly by key/value.

Do NOT add identities or reverse-engineer them from counts.

### Derived repair planning facts
You MAY derive only arithmetic totals from emitted integer facts, for example:
- whether a provider has zero/non-zero local repairable rows;
- total local repairable count across providers;
- per-provider number of batches implied by existing source primitive hard limits, using CEILING arithmetic only;
- providers with provenance gaps/hidden rows that should remain untouched.

Do NOT infer identities, message contents, account emails, peer ids, or provider-current Yandex UIDVALIDITY.

### Boundary
State explicitly:
- this census is read-only local production DB evidence;
- no provider was contacted;
- no repair ran;
- no DB mutation ran;
- Yandex current provider UIDVALIDITY is still unknown;
- results do not authorize repair;
- fresh Architect authorization is required before any provider call or mutation.

Do not record remote stderr, environment values, tokens, credentials, host secrets, raw rows, raw metadata, IDs, emails, usernames, display names, or provider payloads.

## Post-run decision rules

Do not start repair in this task.

After success:
- if all `*_LOCAL_REPAIRABLE == 0`, record that no locally repairable cohort exists; do not invent repair work;
- if one or more providers have local repairable rows, record their aggregate counts and leave provider ordering/repair authorization to Architect;
- Yandex `YANDEX_LOCAL_REPAIRABLE` is ONLY local structural eligibility. Never convert it to provider-safe eligibility because `YANDEX_PROVIDER_UIDVALIDITY_KNOWN=false`.

## Completion protocol

### On successful census

1. add `docs/rel1d_hg2_production_preflight_census.md`;
2. append compact factual `REL1D-HG2D4` entry to `PROJECT_STATE.md` with:
   - exact command;
   - production SHA;
   - exit 0 / terminal success / READ ONLY;
   - `PROVIDER_NETWORK_CALLS=0`;
   - aggregate local-repairable counts by provider;
   - aggregate provenance-gap/hidden counts relevant to planning;
   - Yandex current-provider UIDVALIDITY unknown;
   - explicit no repair/mutation/provider/client action;
3. replace `CURRENT_TASK.md` with HOLD stating:
   - D4 census completed;
   - artifact path;
   - production remains `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`;
   - Alembic remains `0054 / 0054`;
   - no repair/provider call/next phase without fresh Architect authorization;
4. commit + push to `main`;
5. STOP.

### On blocked/failed census

1. record only the sanitized blocked stage/exit/protocol status;
2. do not retry;
3. do not create alternate SQL/SSH path;
4. return HOLD;
5. commit ledger/evidence only if appropriate;
6. STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
