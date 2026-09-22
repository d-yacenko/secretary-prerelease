# Current task — Fix live production rehearsal path and remote execution wrapper

## Context

Helper commit:
`02ea29f58c36ff629cb5c6fc00f225d65f035ede`

Local fake-provider path is useful and accepted.

Architect live-path review found blocking issues. Do not execute the production rehearsal yet.

## Accepted facts

- production runtime/ref remains:
  `8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`;
- production API/worker Telegram AI remains false;
- no second product deploy is desired merely to run the rehearsal;
- user authorization already covers one live synthetic rehearsal after this correction/review;
- live rehearsal must use real production ML/LLM adapters, synthetic Telegram content only, zero Telegram transport calls.

## Blocker 1 — live CLI exit code

Current `main(--live)` calls `execute_live(...)` and then unconditionally returns exit code 2.

Fix:
- return the actual `execute_live()` code;
- add a regression proving live success => 0 and live refusal/failure => nonzero.

## Blocker 2 — fail-closed live exception handling

Real provider/LLM failures can raise exceptions outside `RehearsalRefused`.

Current live path can then:
- emit a traceback/provider error;
- leave already-committed rehearsal jobs parked as `running`;
- violate sanitized-output and no-dangling-job guarantees.

Required:
- catch broad runtime/provider exceptions at the live boundary;
- never print raw exception message, traceback, prompt, response, credentials, ids, or provider payload;
- emit one fixed sanitized failure marker/class;
- rollback current transaction;
- load the synthetic rehearsal user by run id;
- mark every rehearsal `pending/running` job failed with a fixed safe error such as `rehearsal_aborted`;
- commit that failure cleanup;
- leave synthetic objects/artifacts intact for audit;
- restore process-local AI setting in all paths;
- prove dangling pending/running = 0 after injected provider failure.

Do not change generic worker semantics.

## Clarification — embedding live adapter

Do NOT add a special live embedding adapter merely because the helper passes `None` into job handlers.

This is intentional and correct: `handle_embed_object` resolves the real configured embedding service when `embedding_service is None`.

Preserve this canonical production behavior.

## Blocker 3 — helper is not in production checkout

The helper is on `main`; production checkout intentionally remains `8ad52f06...`.

Do not deploy/recreate API/worker just to place an ops helper on production.

Create a canonical local production wrapper under `ops/production/`, following the trust model used by `deploy.py`:

- validate canonical local repo/origin/main/clean worktree;
- validate `target.json`;
- host-key pinning / BatchMode / strict known-hosts;
- authoritative production ref must remain exact `8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`;
- remote production checkout HEAD exact same release and tracked worktree clean;
- verify API and worker long-running env flag are false on the host BEFORE launching the rehearsal;
- stream the reviewed helper code to the production environment rather than requiring it to exist in the production Git checkout;
- run the helper in an isolated one-shot backend process/container with production DB/network/config available;
- do not modify .env and do not recreate/restart long-running API/worker;
- process-local AI=true only in the rehearsal process;
- no Telegram transport access;
- return only helper sanitized stdout.

Preferred execution model:
- host-side remote driver performs the long-running service flag probes;
- run a temporary `docker compose run --rm --no-deps` backend/api process for the rehearsal, or equivalent isolated one-shot container;
- pass the verified long-running false state into the helper through fixed non-secret rehearsal-only markers/environment;
- do not mount Docker socket into the rehearsal container;
- do not use an ad-hoc manual SSH command.

If a different design is simpler and equally safe, document why.

## Live provider wiring

For `providers=live`:
- embedding handler receives `None` and resolves configured real embedding service normally;
- auto-label, temporal, correlation, summary handlers use their normal production effective-settings factories;
- no fake provider patches may be active.

Add an explicit test proving the live code path does not enter `_fake_providers`.

## Queue safety

Preserve:
- canonical enqueue/signature logic;
- jobs parked running before commit;
- synchronous in-process execution;
- no ordinary false worker consumption;
- success => no pending/running synthetic jobs;
- failure => cleanup to failed => no pending/running synthetic jobs.

## Tests

At minimum:
1. live success exit code propagates 0;
2. live refusal propagates nonzero;
3. injected real-provider-style exception produces sanitized failure only;
4. failure cleanup marks rehearsal pending/running jobs failed and leaves zero dangling;
5. settings AI flag restored after failure;
6. environment unchanged after failure;
7. live path uses no fake providers;
8. wrapper refuses wrong local origin/branch/dirty tree;
9. wrapper refuses wrong production ref/head/worktree;
10. wrapper refuses API or worker AI=true;
11. wrapper uses host-key pinning and no raw stderr leakage;
12. wrapper launches isolated one-shot backend process and does not restart/recreate API/worker;
13. helper code is streamed; production checkout need not contain helper;
14. Telegram transport remains blocked;
15. local fake-provider rehearsal remains green.

Run compile, Ruff, bash syntax if shell wrapper, and `git diff --check`.

## Authorization

AUTHORIZED:
- local helper/wrapper/test correction;
- commit/push canonical `main`.

NOT AUTHORIZED:
- live production rehearsal execution in this task;
- another product deploy;
- production ref movement;
- global AI=true;
- Telegram transport calls;
- migration;
- cleanup of synthetic rows.

## Required report

Return:
- commit SHA;
- files changed;
- corrected live exit behavior;
- failure cleanup design;
- isolated remote execution design;
- proof no second deploy is needed;
- tests/compile/Ruff/Bash/diff-check;
- live rehearsal executed=0.

Final marker:

`TELEGRAM_PRODUCTION_REHEARSAL_LIVE_PATH_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
