# Current task — Production Line Reconciliation R1

## Status

- Telegram A4.1–A4.4: ACCEPTED.
- Telegram Integration Gate I1: ACCEPTED.
- Current `main` / accepted Telegram integration HEAD before this task: `c0d7e18bfbef553f7a14107060651fecfbd0841c`.
- Production branch/runtime remains `5cce4b57b14e0052a038acae1354a2821a2bb77b`, Alembic `0041 / 0041`.
- Production rollout is NOT authorized yet.

## Why R1 is required

Architect compared current `main` with `origin/production` and found the histories diverged from merge-base `6d69d936a7e5e08c427598bc8d659d3c7fe6b4ae`.

`origin/production` has exactly three production-only commits that are not in `main` ancestry:

1. `2c19512d11428920932ffec2267780699ae39d3b` — `Fix Yandex transient retry latency`;
2. `6a3ec041692b07fcc203906057b2823eb70f6b6b` — `Google Sync Resilience A: bound retryable source failures`;
3. `5cce4b57b14e0052a038acae1354a2821a2bb77b` — `Fix Google OAuth transient retry classification`.

These production fixes touch recurring queue/finalization/worker paths that Telegram A4.4 also extends. A migration-bearing release must preserve both the deployed production retry behavior and the accepted Telegram recurring-sync behavior.

## Objective

Create a release-candidate integration branch from current `main`, merge `origin/production` into it with a normal merge commit, resolve any conflicts by preserving BOTH production retry invariants and accepted Telegram A4.4 invariants, and prove no regression before anything is merged back to `main`.

This task does NOT deploy and does NOT execute production migrations.

## Branch

Create and work only on:

`review/production-line-reconcile-telegram-rollout`

starting from the exact current `origin/main` after this task authorization is present.

Do not work directly on `main` or `production`.

## History rules

Before work:

- `git fetch --prune origin`;
- local main must fast-forward to exact `origin/main`;
- worktree clean;
- create `review/production-line-reconcile-telegram-rollout` from that exact main;
- record starting main SHA and `origin/production` SHA.

Then perform:

`git merge --no-ff origin/production`

Do NOT:

- rebase;
- squash;
- cherry-pick the production hotfixes instead of merging the production lineage;
- reset/rewrite history;
- force push;
- move `production`;
- merge back to `main` yourself.

## Required preserved production behavior

The merged tree must retain the behavior from all three production-only commits.

### Yandex retry invariant (`2c19512...`)

- Yandex recurring retryable transient failures use short bounded retry tiers `10 / 30 / 60` seconds rather than normal failed cooldown;
- the recurring job remains pending, lock clears, transient metadata is preserved;
- stale max-attempt transient Yandex jobs re-arm through the same bounded path;
- non-transient/non-retryable failures remain conservative failed/cooldown behavior;
- successful recurring runs clear transient metadata and resume normal interval.

### Google Sync Resilience invariant (`6a3ec041...`)

- Google API errors carry structured retryability/classification;
- `Retry-After` is parsed and propagated for retryable failures;
- Gmail read transport uses structured Google error handling;
- Google recurring Gmail/Calendar retryable transient failures use bounded short retry rather than generic exhaustion;
- worker/finalizer propagate Google failure kind, retryability and Retry-After;
- permission/authentication failures remain fail-closed and non-retryable unless explicitly classified transient.

### Google OAuth hotfix invariant (`5cce4b57...`)

- `GoogleOAuthError` carries status/retryable/retry-after fields;
- OAuth refresh `429`, `5xx`, and transient provider error codes are retryable transient;
- invalid-grant/default OAuth failures remain authentication/non-retryable;
- `PERMISSION_DENIED` Google API status classifies as permission failure.

## Required preserved Telegram A4.4 behavior

Do not regress accepted Telegram behavior while resolving shared queue/worker/finalizer conflicts:

- recurring job type `sync_telegram_mtproto` remains in existing source-sync lane/handler registry;
- one recurring job per MTProto account;
- 300-second interval;
- reconciliation before history;
- failed scope reconciliation means zero history calls;
- only `scope_active=true` peers considered;
- max 10 peers per run;
- durable `telegram_peer_cursor` round-robin;
- peer-local failures continue; provider/account-wide failures stop;
- Telegram Retry-After remains propagated;
- Telegram Job errors remain sanitized;
- A3/A4 history cursors/materializer remain reused;
- no generic Telegram source-preference/history-days exposure.

If a conflict is ambiguous relative to these invariants, STOP and report instead of guessing.

## Migration boundary

R1 must not change migration files.

The accepted chain remains exactly:

`0041 -> 0042 -> 0043 -> 0044 -> 0045 -> 0046`

Expected single Alembic head: `0046`.

No new migration is authorized.

## Required verification

Use local development PostgreSQL only.

### 1. History/tree

After merge verify:

- starting `origin/main` is ancestor of final R1 HEAD;
- `origin/production` / `5cce4b57...` is ancestor of final R1 HEAD;
- no migration file changed by conflict resolution;
- report all conflict files and exact resolution logic.

### 2. Migration

From `backend`:

`alembic upgrade head`

`alembic heads`

Expected exactly `0046 (head)`.

### 3. Production hotfix regression

Run at minimum:

`pytest -q tests/test_yandex_transient_retry_hotfix.py tests/test_google_sync_retry_resilience.py tests/test_google_oauth.py`

All tests in these files must pass.

### 4. Telegram regression

Run:

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py tests/test_telegram_mtproto_a4_3.py tests/test_telegram_mtproto_a4_4.py`

Expected current collection: 137 passed. Report exact result.

### 5. Shared queue/worker regression

Run the focused scheduler/queue/worker/source-preference suites that cover recurring finalization and source sync. Include any directly relevant files discovered from the conflict set. Report exact command and counts.

### 6. Full backend regression + attribution

Run:

`pytest -q`

Capture full output outside the repository.

Compare FAILED/ERROR identities against the pre-R1 current-main baseline already established during I1C. Acceptance condition:

- R1-only FAILED/ERROR identities: 0;
- remaining failures/errors must be contained in the pre-R1 baseline set (or fewer).

If environment/nondeterminism changes one baseline identity, report it explicitly; do not silently fix unrelated debt.

### 7. Ruff attribution

Run:

`ruff check app tests --output-format concise`

Compare against pre-R1 main baseline. Acceptance condition: no R1-only Ruff violations.

Do not clean baseline Ruff debt.

### 8. Hygiene

`git diff --check`

Final `git status --short` must be clean.

## Scope prohibitions

R1 does NOT authorize:

- production SSH;
- moving `production`;
- production Compose;
- Alembic migration on production;
- application deployment;
- DB backup/restore actions;
- migration harness implementation;
- A4.5;
- UI/Flutter work;
- Bot API removal;
- unrelated refactor/cleanup.

## Completion report

Push only the R1 branch and return:

- starting `origin/main` SHA;
- starting `origin/production` SHA;
- merge commit SHA;
- final remote R1 HEAD;
- conflict file list;
- exact conflict-resolution summary showing production + Telegram invariants both preserved;
- confirmation both starting refs are ancestors of final HEAD;
- confirmation migration files unchanged;
- `alembic upgrade head` / `alembic heads` results;
- production hotfix focused suite result;
- Telegram suite result;
- shared queue/worker suite result;
- full pytest result and R1-only identity count;
- Ruff result and R1-only violation count;
- `git diff --check`;
- clean worktree;
- confirmation no production action occurred;
- final marker exactly:

`PRODUCTION_LINE_RECONCILIATION_R1_READY`

Then STOP.

## After R1

Architect will independently review the exact merge/diff/test evidence. Only after R1 acceptance may Architect merge the reconciled lineage into `main` and authorize a separate migration-deployment harness/plan for production `0041 -> 0046`.
