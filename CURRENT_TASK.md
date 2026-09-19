# Current task — Telegram rollout RF1R: release identity, rollback proof, and baseline corrective

## Status

Telegram MTProto C3B is ACCEPTED / INTEGRATED TO MAIN.

RF1 implementation under review:
`a90716602d35cf5525554a1005a543dd8dda5491`

RF1 is **REJECTED pending this narrow RF1R corrective**.

Accepted RF1 evidence/direction:
- incremental disposable PostgreSQL upgrade `0041 -> 0046` passed;
- fresh-install disposable PostgreSQL reached `0046`;
- focused Telegram/Q1/C1/C2, notification/worker, source-sync, and C3A/C3B client suites passed;
- Flutter analyzer introduced zero head-only diagnostics;
- production remained untouched;
- `SOURCE_SYNC_TELEGRAM_MTPROTO_INTERVAL_SECONDS` Compose propagation was correctly identified as release-config debt.

Production remains untouched:
- runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- Alembic `0041 / 0041`;
- M3 production cutover is NOT AUTHORIZED;
- Bot API retirement is NOT AUTHORIZED.

Repository Alembic head must remain exactly `0046`.
No `0047` is authorized.

## Blocking issue 1 — release SHA identity is ambiguous

RF1 branch head is:
`a90716602d35cf5525554a1005a543dd8dda5491`

But both:
- `ops/production/release_manifest_rf1.json`; and
- `docs/telegram-mtproto-rf1-readiness.md`

declare the candidate SHA as:
`e503f680543d2eeafbfbb9b641b1b1942d7990ca`.

That cannot be accepted because `a907...` adds runtime-relevant release configuration to `infra/compose.yaml`, specifically propagation of:
`SOURCE_SYNC_TELEGRAM_MTPROTO_INTERVAL_SECONDS`.

A future M3 must have exactly one unambiguous release SHA.

### Required correction

Do NOT attempt to embed the final RF1R commit SHA inside a file that is part of that same commit. A Git commit cannot safely self-reference its own final SHA.

Instead make the repository artifact semantics explicit:

- replace ambiguous `candidate_sha` with a field such as:
  `validated_product_base_sha` = `e503f680543d2eeafbfbb9b641b1b1942d7990ca`;
- add an explicit machine-readable field stating that the deployable `release_sha` is bound by Architect authorization after RF1R review, not inferred from `validated_product_base_sha`;
- state clearly that the accepted RF1R branch head, once reviewed, is the only SHA eligible for M3;
- state clearly that `e503...` is a validated product-code base, NOT the M3 release SHA;
- state clearly that `a907...` is superseded by RF1R once the corrective is accepted;
- future M3 must receive its exact `--release-sha` from `CURRENT_TASK.md` / `PROJECT_STATE.md` Architect authorization.

The final RF1R SHA will be recorded by Architect after review.

No alternate release ref/tag convention is authorized in this corrective.

## Blocking issue 2 — documented rollback policy contradicts the accepted migration harness

RF1 readiness documentation currently says that a failure while DB is between `0041` and `0046` must not rely on automatic downgrade.

But accepted `ops/production/remote_migrate_deploy.py` does this when migration has started and cutover has not completed:
`alembic downgrade 0041`.

This contradiction must be resolved with evidence, not wording alone.

### Required disposable rollback proof

Using isolated/disposable PostgreSQL only, prove the structural downgrade path while application writers are stopped and before any MTProto runtime data can be created.

At minimum, for EACH intermediate revision:
- start from exact `0041`;
- upgrade to `0042`, then downgrade to `0041`;
- repeat independently for `0043`;
- repeat independently for `0044`;
- repeat independently for `0045`;
- repeat independently for `0046`;
- after each downgrade verify direct DB Alembic revision is exactly `0041`;
- verify a pre-existing core sentinel row/data item created at `0041` remains intact;
- verify no unexpected Alembic heads.

Also run a full empty-runtime round trip:
`0041 -> 0046 -> 0041 -> 0046`
and finish at exactly `0046`.

This proof is only for the **pre-live / writers-stopped / no-runtime-MTProto-data** downgrade path.

For the post-live path, reuse and cite the existing fail-closed guards in:
`backend/tests/test_production_migration_deploy.py`
that prove:
- MTProto non-empty blocks downgrade;
- MTProto emptiness uncertainty blocks downgrade;
- stopped current api/worker is required before emptiness proof;
- revision uncertainty blocks downgrade.

### Required documentation correction

Bring `docs/telegram-mtproto-rf1-readiness.md` into exact agreement with the harness:

- before app goes live, with api/worker stopped and no runtime MTProto data possible, downgrade `0042..0046 -> 0041` is permitted only because RF1R disposable tests prove the path;
- after app has gone live at `0046`, downgrade is allowed only if the existing harness first proves current api/worker are stopped, DB is exactly `0046`, and all guarded MTProto tables are empty;
- if MTProto rows exist OR emptiness/revision/container-state cannot be proven, downgrade is blocked and break-glass/forward-fix/backup-restore planning is required;
- never imply arbitrary downgrade safety outside these proven conditions.

If any required intermediate downgrade proof fails, STOP and report RF1R blocker. Do NOT modify migration `0042..0046` in this task.

## Blocking issue 3 — full backend baseline claim is not proven

RF1 reports:
- 3073 passed;
- 93 failed;
- 8 errors;
- 3 skipped;

and says failures are existing baseline debt/fixture issues.

That claim needs exact evidence.

Run the same full backend-suite command in the same isolated environment at:

Base:
`e503f680543d2eeafbfbb9b641b1b1942d7990ca`

RF1R head:
`<new head>`

Return:
- base passed/failed/error/skipped counts;
- head passed/failed/error/skipped counts;
- exact set of base failed/error test node IDs;
- exact set of head failed/error test node IDs;
- common failed/error IDs;
- base-only failed/error IDs;
- head-only failed/error IDs.

Acceptance requires:
`HEAD_ONLY_FAILED_OR_ERROR = 0`

If head adds any new failure/error, RF1R is blocked.

Do not fix unrelated baseline debt.

## Config completeness corrective

RF1 correctly added:
`SOURCE_SYNC_TELEGRAM_MTPROTO_INTERVAL_SECONDS=60`
to `.env.example` and Compose.

Also add the canonical installation flag explicitly to `.env.example`:
`TELEGRAM_MTPROTO_AI_ENABLED=false`

Add/extend focused Compose-config tests proving:
- api resolves `TELEGRAM_MTPROTO_AI_ENABLED=false` by default;
- worker resolves the same;
- api resolves `SOURCE_SYNC_TELEGRAM_MTPROTO_INTERVAL_SECONDS=60` by default;
- worker resolves the same;
- explicit overrides propagate equally to api and worker;
- no secret values are printed by the test.

Do not change application defaults; this is contract/documentation/Compose verification only.

## Required revalidation

Re-run:
- incremental disposable `0041 -> 0046`;
- fresh install -> `0046`;
- new intermediate downgrade matrix;
- full empty-runtime `0041 -> 0046 -> 0041 -> 0046`;
- `backend/tests/test_production_migration_deploy.py`;
- focused Compose-config tests;
- Telegram/Q1/C1/C2 regression subset;
- isolated notification/worker/source-sync release subsets;
- C3A/C3B client release subset;
- full Flutter analyze baseline comparison;
- `git diff --check`;
- Ruff for changed Python files only;
- Dart format only if Dart changes unexpectedly;
- Alembic head exactly `0046`.

RF1R should not change product behavior.

## Branch / deliverable

Continue existing branch:
`review/telegram-mtproto-rf1-release-freeze`

Continue from exact:
`RF1R_BASE_SHA=a90716602d35cf5525554a1005a543dd8dda5491`

Create exactly one corrective commit on top.
Do not rewrite/squash RF1.

Return:
- `RF1R_BASE_SHA`;
- `RF1R_SHA`;
- changed files;
- corrected manifest semantics;
- proof that `e503...` is only the validated product base and not the future M3 release SHA;
- intermediate downgrade matrix results;
- `0041 -> 0046 -> 0041 -> 0046` result;
- exact existing post-live downgrade guard tests cited;
- full backend base/head comparison with exact failed/error node-ID sets and head-only count;
- Compose-config default/override tests;
- release regression results;
- analyzer comparison;
- Ruff/static results;
- Alembic `0046`;
- clean worktree;
- remote branch SHA;
- production untouched.

Final marker:
`TELEGRAM_MTPROTO_RF1R_RELEASE_FREEZE_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
