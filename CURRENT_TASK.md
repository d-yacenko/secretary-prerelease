# Current task — HOLD

REL1-R0.1 failed-migration recovery correction is complete.

- Corrective implementation: `a7dfe35e68ea6c2af5328cc00c6724b1c0c5963d`
- Product release remains `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- Rollback remains `2314bf72101fbd83d50a7b264154d73740e28db1`
- Alembic contract remains `0052 -> 0054`

Recovery classification after a failed `alembic upgrade 0054`, before release runtime is accepted:

- actual revision `0052` and both role tables absent: restore the rollback runtime, no downgrade, revision stays `0052`;
- actual revision `0052` and either role table present: no drop, no downgrade, no runtime restore, `BREAK_GLASS_REQUIRED=true`;
- actual revision `0053` or `0054` with both tables present and empty: downgrade to `0052`, then require both tables absent, then restore the rollback runtime;
- actual revision `0053` or `0054` with a missing, non-empty, or unreadable role table: no downgrade, `BREAK_GLASS_REQUIRED=true`;
- unreadable, ambiguous, or any other revision: no downgrade, no runtime restore, `BREAK_GLASS_REQUIRED=true`.

Post-cutover recovery still stops `api` and `worker`, requires Alembic `0054`, and downgrades only when both role tables are empty. The idempotent release plus Alembic `0054` path stays non-mutating and may contain role rows.

Checks: `test_person_roles_0054_migration_harness.py` and `test_rel1a_person_roles.py` together 76 passed, 0 failed. Ruff passed. `py_compile` of both role rollout helpers passed. `git diff --check` clean.

Production was not changed and remains `2314bf72101fbd83d50a7b264154d73740e28db1`, Alembic `0052 / 0052`. No SSH, deploy, migration, client install, or model/provider call.

Architect source review is required before REL1-R1. Do not execute the live rollout from this HOLD.
