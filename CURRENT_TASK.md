# Current task — HOLD

REL1-R0 harness preparation is complete and waiting for Architect source review. Do not execute the live rollout, deploy, migrate production, install the client, or start REL1B, REL1C, or REL1D from this HOLD.

## REL1-R0 — 0052 -> 0054 rollout harness

- Harness implementation: `ed287ed115dda037f94b509b79f76c8ffba2e2ea`
- Product release: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- Rollback: `2314bf72101fbd83d50a7b264154d73740e28db1`
- Revision pair: `0052 -> 0054`
- Production was not mutated
- Production Alembic remains `0052 / 0052`

## Changed files

- `ops/production/migrate_person_roles_0054.py`
- `ops/production/remote_migrate_person_roles_0054.py`
- `backend/tests/test_person_roles_0054_migration_harness.py`
- `docs/deploy.md`

## Rollback

The harness accepts only rollback plus Alembic `0052`, or the exact release plus Alembic `0054`. The second path verifies schema and identity without migrating again and does not require empty role tables.

Before `0054` is applied, failure restores the rollback runtime with the database still at `0052`. After migration and before the release runtime is accepted, downgrade to `0052` is allowed only when `person_role_terms` and `person_role_assignments` are both proven empty. After the release runtime starts, the harness stops `api` and `worker` and may downgrade only when the revision is still `0054` and both tables are still empty. If either table has rows, emptiness cannot be proven, or a safety query fails, automatic downgrade is forbidden, role rows are not deleted, and the harness emits `BREAK_GLASS_REQUIRED=true`.

## Checks

- `test_person_roles_0054_migration_harness.py` and `test_rel1a_person_roles.py`: 55 passed, 0 failed
- Ruff on the new Python files: passed
- `py_compile` of both helpers: passed
- `git diff --check`: clean

No production SSH. No production migration. No deploy. No client install. No model or provider call.

## HOLD

Architect source review is required before REL1-R1 live execution.
