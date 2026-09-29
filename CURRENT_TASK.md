# Current task — PL1-R1 schema-neutral production rollout

Authorized source release: `666683134797948871266e84fd105f0ca0c43476`.
Current production / rollback base: `44407ed6e972a05809d55874acaa966cc7e141c8`.
Repository Alembic head and production Alembic are `0051`.

PL1 A-E is source-reviewed and accepted. This task authorizes only the production rollout required before the exact-release human People Landscape gate.

## Preconditions

1. Bootstrap from the canonical repository and verify:
   - `origin/production == 44407ed6e972a05809d55874acaa966cc7e141c8`;
   - release `666683134797948871266e84fd105f0ca0c43476` is a descendant of production with merge-base equal to production;
   - the release has no Alembic-path changes relative to production;
   - `ops/production/deploy.py` at production and release is unchanged.
2. Use only the committed canonical production target and deployment runbook. Do not discover or guess hosts, paths, credentials, Compose files, or environment values.
3. This is schema-neutral. Do not run a migration-specific harness and do not modify database data manually.

## Authorized action

Promote exact release `666683134797948871266e84fd105f0ca0c43476` to `production` using the canonical schema-neutral `ops/production/deploy.py` procedure.

Required result:

- non-force fast-forward only;
- deploy harness exits PASS;
- health check passes;
- runtime checkout and `origin/production` resolve to the exact release SHA;
- Alembic remains `0051 / 0051`;
- DB container, DB volume, and `.env` remain unchanged;
- no production Person, Task, Task↔Person, promotion, consolidation, or other application data writes are performed for validation;
- installed desktop client is not replaced;
- rollback is used only if the canonical deploy procedure requires it after a failed rollout.

## Completion contract

Record the exact preflight facts, promotion result, deploy result, health result, Alembic state, runtime/repository SHAs, unchanged-state checks, and whether rollback was used in `PROJECT_STATE.md`.

Then replace this file with `# Current task — HOLD` and a concise PL1-R1 result, commit/push to `main`, and STOP.

Do not build the human-gate client and do not begin any PL1-F/later slice. The exact-release client bundle and human People Landscape gate require a new Architect authorization.
