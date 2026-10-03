# Current task — ACTIVE

## REL1-R1 — execute exact REL1A production migration + backend rollout

The user explicitly authorized the controlled REL1A production rollout on 2026-10-03.

REL1-R0 harness `ed287ed115dda037f94b509b79f76c8ffba2e2ea` plus recovery corrective `a7dfe35e68ea6c2af5328cc00c6724b1c0c5963d` are **ARCHITECT SOURCE-ACCEPTED**.

This task is the live production migration/backend stage only.

Do not install or replace the local Linux client in this task. Client rollout will be a separate follow-up stage after backend/migration success.

## Exact authorized contract

- product release SHA: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- current production / rollback SHA: `2314bf72101fbd83d50a7b264154d73740e28db1`
- current production Alembic: `0052`
- target production Alembic: `0054`
- exact live harness:
  - `ops/production/migrate_person_roles_0054.py`
  - streamed helper `ops/production/remote_migrate_person_roles_0054.py`
- harness source/corrective accepted from current `main`;
- exact production release remains the fixed SHA above, not current `main`.

Authorized migration chain is exactly:

- `0053_person_role_vocabulary.py`: `0053 -> 0052`
- `0054_person_role_key_width.py`: `0054 -> 0053`

Do not substitute another release SHA, rollback SHA, migration pair, or deployment method.

## Mandatory bootstrap

Follow `docs/executor_bootstrap.md`.

Use only the canonical repository:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh from `origin/main`:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- the exact role migration harness files.

Use the committed production target and pinned host-key contract only.

Do not create/copy/request new production key material. Do not probe alternate hosts or credentials.

## Preflight before any production-ref mutation

From a clean canonical local `main == origin/main`:

1. Verify current `origin/production` is exactly:
   `2314bf72101fbd83d50a7b264154d73740e28db1`.
2. Verify exact release and rollback SHAs resolve locally.
3. Verify rollback is an ancestor of release.
4. Verify rollback -> release is ahead-only.
5. Verify the Alembic delta is exactly the two authorized additive files and no Alembic infra/earlier migration is changed.
6. Verify exact revision chain `0052 -> 0053 -> 0054`.
7. Verify repository Alembic head at the release is `0054`.
8. Re-run the accepted focused rollout checks before mutation:
   - `backend/tests/test_person_roles_0054_migration_harness.py`;
   - `backend/tests/test_rel1a_person_roles.py`;
   - Ruff for role rollout helpers;
   - `py_compile` for local + remote role rollout helpers;
   - `git diff --check`.
9. Verify the actual public-key SSH path to the pinned production target according to bootstrap/runbook.

If any preflight fails before production mutation:

- do not move `production`;
- do not SSH for rollout;
- do not migrate/deploy;
- record one sanitized blocker;
- return ledger to HOLD;
- STOP.

## Production ref gate

Immediately before invoking the harness:

- fast-forward `refs/heads/production` from exact rollback SHA
  `2314bf72101fbd83d50a7b264154d73740e28db1`
  to exact release SHA
  `6f802d6959aca40758376a83d5bdfcbbd77fc537`;
- no force push;
- verify `origin/production` equals the exact release SHA.

Do not point `production` at the R0/R0.1 harness commits or at current `main`.

If the production branch is no longer exactly at the rollback SHA before this move, STOP for Architect review. Do not reconcile an unexpected ref.

## Execute only the accepted migration harness

Run the canonical entrypoint with exactly:

`python3 ops/production/migrate_person_roles_0054.py --release-sha 6f802d6959aca40758376a83d5bdfcbbd77fc537 --rollback-sha 2314bf72101fbd83d50a7b264154d73740e28db1 --from-alembic 0052 --to-alembic 0054`

Do not substitute:

- `ops/production/deploy.py`;
- direct SSH;
- direct Docker Compose;
- direct Alembic;
- manual SQL;
- ad-hoc remote commands.

The harness is the only authorized live mutation path.

## Success acceptance

Treat REL1-R1 as successful only if the harness proves all of the following:

- `PERSON_ROLE_MIGRATION_DEPLOYMENT=PASS` or the exact accepted idempotent success marker if production was already safely completed by this same rollout;
- production checkout/runtime is exact release `6f802d...`;
- Alembic is exactly `0054`;
- health PASS;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- API recreated on first rollout;
- worker recreated on first rollout;
- role schema verification PASS:
  - both role tables exist;
  - required columns/checks/FKs/indexes exist;
  - `display_text` 120;
  - `normalized_key` 360;
  - `context_text` 200;
  - `context_key` 600;
- before first release runtime start, both new role tables were proven empty;
- no role seed rows were created by rollout;
- no unrelated user/application data was intentionally mutated by Executor;
- after success, `origin/production` remains exact release SHA.

Do not call role product endpoints merely to manufacture runtime evidence.

## Failure and rollback handling

Obey the harness result exactly.

### Failure before remote mutation

If no production mutation occurred and production remains rollback + `0052`:

- restore `refs/heads/production` to rollback only if this task itself had already fast-forwarded it;
- verify rollback ref;
- STOP.

### Safe automatic rollback

If harness reports safe automatic rollback and independently verified state is:

- runtime exact rollback SHA;
- Alembic exactly `0052`;
- health PASS;
- DB container/volume/`.env` preserved;

then restore `refs/heads/production` to rollback SHA if needed and STOP.

### Break-glass / uncertain state

If the harness reports any of:

- `BREAK_GLASS_REQUIRED=true`;
- rollback blocked;
- unknown/unreadable Alembic revision;
- inconsistent role-table presence;
- cannot prove empty role tables;
- failed downgrade;
- uncertain runtime/schema identity;

then:

- do not manually downgrade;
- do not delete/truncate/drop role tables;
- do not edit `alembic_version`;
- do not restart an application against an uncertain schema;
- do not improvise SSH/Compose/SQL recovery;
- leave production/ref in the safest state dictated by harness output;
- record sanitized exact markers;
- return HOLD;
- STOP for Architect review.

No automatic or manual recovery may lose role facts.

## Runtime/external-effect limits

Authorized in this task:

- exact production branch fast-forward to the fixed release;
- exact production `0052 -> 0054` migration through the accepted harness;
- rebuild/recreate production API and worker through that harness;
- read-only/sanitized health/schema/container/ref verification required by the harness.

Not authorized in this task:

- Linux client build/install/replacement;
- real Assistant/model calls;
- provider sync/actions;
- manual product-data creation/editing;
- role assignment/retraction through product API;
- human UI acceptance;
- REL1B / REL1C / REL1D;
- Organization;
- Scheduled Activity.

## Completion protocol

After the live run, append a compact factual REL1-R1 result to `PROJECT_STATE.md` including:

- local/main SHA used to launch the harness;
- accepted harness/corrective SHAs;
- production ref before/after;
- release and rollback SHAs;
- Alembic before/after;
- exact harness result markers;
- role schema verification markers;
- health;
- DB container/volume/`.env` preservation;
- API/worker recreation state;
- rollback path: unused / safely used / blocked;
- confirmation no role rows were intentionally created;
- confirmation installed client was unchanged;
- confirmation no real model/provider call occurred.

Then replace this file with `# Current task — HOLD` and a concise result.

On success, HOLD must state:

- production backend/source = `6f802d6959aca40758376a83d5bdfcbbd77fc537`;
- production branch = same exact SHA;
- Alembic = `0054 / 0054`;
- installed client still = `2314bf72101fbd83d50a7b264154d73740e28db1`;
- next controlled rollout stage is exact-release Linux client build/install for human REL1A acceptance;
- do not perform that client stage from this task.

Commit + push ledger updates to `main`, then STOP.
