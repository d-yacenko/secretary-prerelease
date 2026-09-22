# Current task — Telegram Bot API M4BM1R: finalize post-retirement verifier fail-closed boundary

## Status

M4BM1 verifier implementation:
`aaa09236c57c780403d3096d410416330532d9aa`

Architect review: NOT YET ACCEPTED FOR LIVE VERIFICATION.

Current production runtime/ref remains:
`fe151f12f64886505253e765b82458710a949e34`

No live verifier execution is authorized.

## Accepted parts

The verifier is directionally correct and read-only:
- no Telegram/Bot API calls;
- no DB writes;
- no env writes;
- no service restart/recreate;
- exact production ref/HEAD/worktree checks;
- Bot settings checked empty in `.env`, Compose, and actual containers;
- MTProto/protected credentials and AI=false checked;
- health retries up to 30 attempts with 2-second spacing;
- Alembic 0046 checked.

## Required corrections

### 1. Strict failure-protocol whitelist

`parse_output()` must reject any unknown/unexpected line in failure transcripts.

The failure protocol must allow only:
- the valid ordered prefix of already-emitted known PASS markers;
- exactly one `FAILURE_STAGE=...`;
- exactly one `RAW_EXCEPTION_CLASS=...`;
- exactly:
  - `TELEGRAM_NETWORK_CALLS=0`
  - `DB_WRITES=0`
  - `ENV_WRITES=0`
  - `SERVICE_RECREATIONS=0`
- final `M4BM1_TERMINAL=failure`.

Reject:
- any unknown key such as `SECRET=...`;
- duplicate keys;
- malformed/out-of-order failure tail;
- nonzero counters;
- any text not matching the sanitized protocol.

Add an explicit regression proving a transcript containing all required failure fields PLUS an extra unknown line is rejected before the wrapper can print it.

### 2. Explicit API/worker running-state proof

After resolving API and worker container IDs, inspect each Docker container state and require `Status == running`.

Do not emit:
- `API_RUNNING_PASS=true`
- `WORKER_RUNNING_PASS=true`

based only on nonempty `compose ps -q`.

Keep DB health logic unchanged.

Add regressions for stopped API and stopped worker producing deterministic zero-mutation failure.

### 3. Noninteractive SSH

Add `-o BatchMode=yes` to the verifier shell wrapper, matching the established production harness contract.

No other wrapper behavior needs to change unless required by tests.

## Preserve

Do not weaken:
- `target.json` single-source identity;
- fresh exact production-ref fetch/check;
- read-only runtime behavior;
- zero provider/write/recreate counters;
- Bot env empty checks across file/Compose/actual containers;
- MTProto/protected credential checks;
- AI=false;
- bounded health retries;
- exact Alembic 0046 proof;
- secret-free protocol.

## Validation

Run:
- focused verifier tests;
- Python compile;
- bundled helper compile;
- Bash syntax;
- Ruff;
- `git diff --check`.

## Authorization

AUTHORIZED:
- local verifier/test changes only;
- update `PROJECT_STATE.md`;
- commit/push canonical `main`.

NOT AUTHORIZED:
- production SSH;
- live verifier;
- Telegram/Bot API/provider calls;
- DB/env mutation;
- service restart/recreate;
- deploy/rollback/ref movement;
- webhook/Bot-secret restoration;
- BotFather/account destruction;
- Stage C cleanup;
- MTProto changes;
- AI enablement.

## Required report

Return:
- corrective commit SHA;
- files changed;
- strict failure-protocol correction;
- API/worker running-state correction;
- BatchMode correction;
- focused tests/compile/Ruff/Bash/diff-check results;
- production SSH=0;
- provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BM1R_VERIFIER_HARDENED`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
