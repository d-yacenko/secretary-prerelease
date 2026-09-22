# Current task — Telegram Bot API M4BW1: make Stage 2 failures diagnostic without weakening read-only safety

## Executor handoff

Continue as implementation executor in the canonical repo.

Read first:
- `AGENTS.md`
- `CURRENT_TASK.md`
- latest `PROJECT_STATE.md`
- `DECISIONS.md`
- `ops/production/verify_telegram_bot_stage_c.py`
- `ops/production/verify_telegram_bot_stage_c.sh`
- focused Stage C verifier tests

This task is CODE/TEST ONLY. No production SSH or live verifier.

## Live fact to preserve

The authorized M4BV1 live read-only run reached production and emitted:

```
M4BR1_BEGIN=true
REMOTE_HEAD_PASS=true
REMOTE_PRODUCTION_REF_PASS=true
REMOTE_WORKTREE_CLEAN=true
DB_RUNNING_PASS=true
API_RUNNING_PASS=true
WORKER_RUNNING_PASS=true
DB_HEALTH_PASS=true
ALEMBIC_0046_PASS=true
APP_HEALTH_PASS=true
BOT_CONTAINER_ENV_ABSENT_PASS=true
MTPROTO_CREDENTIALS_PRESERVED_PASS=true
TELEGRAM_MTPROTO_AI_DISABLED_PASS=true
FAILURE_STAGE=STAGE_2_READ_ONLY_STATE
RAW_EXCEPTION_CLASS=RuntimeError
TELEGRAM_NETWORK_CALLS=0
DB_WRITES=0
ENV_WRITES=0
SERVICE_RECREATIONS=0
M4BR1_TERMINAL=failure
M4BR1_BLOCKED=ssh_failed
```

Interpretation:
- all Stage 0 and Stage 1 production invariants passed;
- remote Stage 2 child failed before returning structured values;
- zero mutation/provider counters passed;
- the trailing `ssh_failed` is misleading: SSH succeeded and returned the valid remote transcript; remote verifier exit code was nonzero.

Do not guess which Stage 2 check failed.

## Problem 1 — Stage 2 collapses too many causes

Current child combines:
- app route checks;
- active Settings model check;
- DB session/query setup;
- MTProto account count;
- active scope count;
- legacy Bot object aggregate;
- bounded candidate scan;
- canonical `RecentSourceService.get_inbox_eligible()` calls.

Any uncaught child exception makes `docker compose exec ... python -c` exit nonzero, and outer `_run()` reduces it to generic `RuntimeError`.

The live transcript therefore cannot distinguish a product/data issue from verifier code/query/import issues.

## Goal

Make Stage 2 fail with a deterministic sanitized substage, with no secret/data leakage, while preserving strict read-only behavior.

Do not fix a guessed production cause in this task unless code review identifies a deterministic verifier bug that can be proven locally.

## Required Stage 2 design

Use fixed allowlisted failure codes/stages. Exact naming may vary, but distinguish at minimum:

1. child bootstrap/import failure;
2. legacy Bot route surface failure;
3. required MTProto route failure;
4. active Settings model still contains Bot fields;
5. DB/session bootstrap failure;
6. MTProto account query/check;
7. active scope query/check;
8. legacy Bot aggregate query/check;
9. legacy candidate query;
10. canonical Inbox eligibility evaluation;
11. bounded candidate exhaustion.

Preferred pattern:
- child catches exceptions internally;
- child emits only a strict sanitized result protocol;
- no exception messages, SQL, IDs, titles, bodies, env values, or traceback;
- outer helper validates the child protocol strictly;
- remote failure becomes a precise `FAILURE_STAGE=STAGE_2_...` value.

A child process crash or malformed output that bypasses the internal protocol must have its own fixed safe Stage 2 code.

Do not weaken the top-level strict parser.

## Important data-check semantics

Preserve:
- MTProto account count must equal 1;
- active scope count must equal 28;
- legacy non-MTProto Telegram chat object count must be >= 1;
- at least one legacy object must be Inbox-readable through canonical `RecentSourceService.get_inbox_eligible()`;
- bounded scan remains fail-closed if the bound is exceeded without proof.

Do not output any count unless already permitted by the existing success protocol.
On failure, prefer stage code only rather than production data values.

## Problem 2 — misleading wrapper `ssh_failed`

Current wrapper:
- receives a valid sanitized remote failure transcript;
- validates it;
- prints it;
- then labels the nonzero remote verifier exit as `M4BR1_BLOCKED=ssh_failed`.

That is semantically wrong.

## Required wrapper behavior

Distinguish:
- SSH transport/protocol failure; versus
- valid sanitized remote verifier terminal failure.

For a valid remote verifier failure:
- print the remote sanitized transcript once;
- terminate nonzero locally;
- do NOT append `ssh_failed`.

It is acceptable to emit one fixed local marker such as:
`M4BR1_REMOTE_VERIFIER_FAILED=true`
only if it is useful and fully covered by the wrapper protocol/tests. Prefer no redundant marker if the remote `M4BR1_TERMINAL=failure` is sufficient.

For actual SSH transport failure with no valid remote protocol, retain a deterministic transport-specific blocker.

Do not surface stderr from SSH/remote commands.

## Required regressions

Add end-to-end tests proving:

1. each fixed Stage 2 internal failure class maps to its expected sanitized `FAILURE_STAGE`;
2. child exception messages/IDs/content never reach stdout;
3. malformed/unknown child output fails closed to a fixed safe Stage 2 protocol code;
4. successful Stage 2 still yields exactly the existing success fields/order;
5. account != 1 maps to account-specific Stage 2 failure without outputting the count;
6. scope != 28 maps to scope-specific failure without outputting the count;
7. legacy count < 1 maps to aggregate-specific failure without outputting the count;
8. no eligible legacy object within complete bounded set maps to Inbox-read-specific failure;
9. legacy_count > bound with no proof maps to bound-exhausted-specific failure;
10. actual child process nonzero/crash maps to child-execution-specific failure;
11. a valid remote `M4BR1_TERMINAL=failure` causes wrapper exit nonzero without `M4BR1_BLOCKED=ssh_failed`;
12. actual SSH transport failure remains distinguishable and sanitized;
13. strict top-level success/failure parser remains unchanged in safety properties;
14. all prior canonical Git bootstrap, protocol-order, Bot-env absence, zero-mutation/provider tests remain green.

## Preserve exactly

Do not change:
- production release `bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`;
- Alembic `0046`;
- canonical Git bootstrap;
- route/config expectations;
- MTProto account=1 and active scope=28 requirements;
- historical Bot preservation requirement;
- bounded health retry;
- Bot runtime env absence contract;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- zero Telegram/provider calls;
- zero DB writes;
- zero env writes;
- zero service restart/recreate;
- no production identifiers/content output.

## Validation

Run:
- all focused Stage C verifier tests;
- Python compile;
- bundled helper compile;
- Bash syntax;
- Ruff;
- `git diff --check`.

Self-review actual failure transcripts produced by tests, not only helper functions.

## Authorization

AUTHORIZED:
- local verifier/wrapper/test diagnostic correction only;
- update `PROJECT_STATE.md`;
- commit/push canonical `main`.

NOT AUTHORIZED:
- production SSH;
- live verifier retry;
- provider calls;
- DB/env writes;
- service restart/recreate;
- deploy/rollback/ref movement;
- schema/data cleanup;
- MTProto behavior/config changes;
- AI enablement.

## Required report

Return:
- commit SHA;
- files changed;
- Stage 2 sanitized substage map;
- child protocol design;
- wrapper remote-failure vs SSH-failure behavior;
- regression/test results;
- compile/Ruff/Bash/diff-check results;
- production SSH=0;
- provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BW1_STAGE2_DIAGNOSTIC_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
