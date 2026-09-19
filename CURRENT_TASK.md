# Current task — Telegram rollout RF1: freeze new migration-bearing release candidate

## Status

Telegram MTProto user-facing chain is now complete through C3B:

- C2B/C2BR/C2BR2 deterministic transport notifications: ACCEPTED / MAIN
- C3A/C3AR/C3AR2 Flutter account/auth/scope UX: ACCEPTED / MAIN
- C3B Inbox transport-event presentation: ACCEPTED / MAIN

C3B reviewed implementation tip:
`ef27577b61b5762e00c5f96183f9abec05e64e36`

C3B integration merge:
`e503f680543d2eeafbfbb9b641b1b1942d7990ca`

The previous migration-bearing release candidate:
`917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`
MUST NOT be deployed as-is because it predates Q1/C1/C2/C3 Telegram messenger work.

This task authorizes only **RF1 — freeze and validate a new release candidate**.

Production remains untouched:
- production runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- production Alembic `0041 / 0041`;
- production health currently PASS;
- M3 production migration-bearing cutover is NOT AUTHORIZED;
- Bot API retirement is NOT AUTHORIZED.

Repository migration head must remain exactly:
`0046`

No `0047` is authorized.

## Goal

Produce a single exact Git SHA that is suitable to become the next migration-bearing release candidate, together with reproducible readiness evidence.

RF1 is NOT a deployment task.

Do not connect to production SSH.
Do not mutate production DB, env, services, containers, refs, or runtime.

## Base / branch

Create branch:
`review/telegram-mtproto-rf1-release-freeze`

Start from exact:
`RF1_BASE_SHA=e503f680543d2eeafbfbb9b641b1b1942d7990ca`

If main later moves only because Architect updates task/state/recovery documentation, do NOT rebase merely for those documentation commits.

## Required work

### 1. Release candidate inventory

Produce a machine-readable or clearly structured release manifest in the repository containing at minimum:

- exact candidate Git SHA;
- migration range:
  `0041 -> 0042 -> 0043 -> 0044 -> 0045 -> 0046`;
- repository Alembic head;
- production starting Alembic revision: `0041`;
- production starting runtime/ref: `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- accepted Telegram feature milestones included in this candidate:
  A1/A2, A3, A4.1-A4.4, Q1, C1A, C1B, C2A, C2B, C3A, C3B;
- canonical MTProto AI quarantine default:
  `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- explicit statement that Bot API retirement is not part of this candidate;
- explicit statement that production cutover is not performed by RF1.

Prefer extending an existing release/readiness artifact if the repository already has one. Do not create competing deployment conventions.

### 2. Migration-chain validation

Against an isolated/disposable PostgreSQL database, validate the exact accepted chain:

`0041 -> 0042 -> 0043 -> 0044 -> 0045 -> 0046`

Required proof:
- database starts at exactly `0041`;
- upgrade to head succeeds;
- resulting revision is exactly `0046`;
- application/backend can start or execute its standard DB readiness path at `0046`;
- no unexpected extra Alembic heads;
- no `0047`;
- migration scripts are deterministic/re-runnable in the accepted harness sense.

If the existing M1 migration harness already proves part of this, reuse it and extend only where necessary for the new candidate.

Do NOT test against production.

### 3. Fresh-install validation

Using an isolated/disposable PostgreSQL database:
- create/upgrade schema from repository-supported fresh-install path to `0046`;
- prove one head only;
- run the backend smoke/readiness test expected by the existing project conventions.

This is to catch dependencies that only work on an incremental 0041->0046 path.

### 4. Application regression gate

Run the broadest practical regression suites relevant to the release candidate, including:

Backend:
- core backend test suite or the repository's accepted release regression subset;
- Telegram A1-A4.4;
- Q1;
- C1A/C1B;
- C2A/C2B;
- source-sync/worker recurring;
- existing notification suite on isolated DB where required.

Client:
- relevant Flutter account/API/Inbox suites including C3A/C3B;
- existing client smoke/regression suite used for release readiness;
- full `flutter analyze` using the accepted baseline rule if repository baseline findings remain.

Static:
- Ruff for changed Python files if RF1 changes Python;
- Dart format for changed Dart if RF1 changes Dart;
- `git diff --check`.

RF1 should ideally change only release/readiness artifacts/tests/harness code. Product behavior changes are not expected.

### 5. Environment/config readiness audit

Without reading or printing production secret values, verify the candidate's required configuration contract.

At minimum enumerate and classify:
- required existing production variables;
- newly required variables introduced between production runtime and candidate;
- optional variables/defaults;
- `TELEGRAM_MTPROTO_AI_ENABLED=false` default;
- Telegram API ID/hash presence requirement;
- credential-encryption key requirement;
- source-sync Telegram interval default/override;
- no secret values in logs/artifacts/tests.

Do NOT copy secret values into Git, reports, commands, or test fixtures.

If the repository already has env-example/config docs, update them only if they are incomplete for the accepted candidate.

### 6. Deployment preflight reuse

Inspect and reuse the accepted Production Deploy Contract v2 and M1/M2 readiness tooling.

Prove that the new candidate can be fed into the existing deployment process without introducing a parallel path.

RF1 must document:
- exact pre-deploy checks;
- exact migration step expected during a future authorized M3;
- exact health/readiness checks expected after migration/app start;
- exact ref verification;
- exact conditions that must abort a future cutover before destructive progress.

Do not execute production deployment.

### 7. Rollback / failure plan

Document a concrete future-M3 failure plan for this exact candidate.

At minimum distinguish:
- failure before migrations;
- migration failure while production DB is between 0041 and 0046;
- application start/health failure after DB reaches 0046;
- MTProto-specific runtime failure with otherwise healthy app;
- client release failure independent of backend migration.

Do not claim schema downgrade is safe unless existing migrations/tests actually prove it.

If downgrade is not guaranteed, state the forward-fix / restore-from-backup strategy required by existing project conventions.

### 8. Candidate immutability

At completion:
- worktree clean;
- branch pushed;
- exact remote SHA confirmed;
- no uncommitted generated artifacts;
- candidate SHA must be suitable for Architect to record as the only allowed M3 candidate.

Do not move production ref.

## Acceptance evidence

Return an RF1 matrix:
`readiness invariant -> exact test/check/artifact -> result`

Include:
- incremental 0041->0046 migration;
- fresh install ->0046;
- one Alembic head;
- no 0047;
- backend regression;
- Telegram regression;
- notification regression;
- source-sync recurring;
- client C3A/C3B regressions;
- analyzer baseline;
- env/config audit;
- deploy-contract compatibility;
- rollback plan;
- clean worktree;
- remote SHA;
- production untouched.

## Explicitly out of scope

Do NOT:
- deploy to production;
- SSH to production;
- run Alembic against production;
- change production env;
- restart production services;
- move production branch/ref;
- log into Telegram from production;
- import production Telegram history;
- disable/delete Bot API integration;
- create migration `0047`;
- implement new product features;
- redesign deploy pipeline.

If a product or migration defect is discovered that requires code changes beyond narrow release-readiness fixes, STOP and report the blocker instead of widening RF1.

## Deliverable

Return:
- `RF1_BASE_SHA=e503f680543d2eeafbfbb9b641b1b1942d7990ca`;
- `RF1_SHA=<exact sha>`;
- changed files;
- release manifest path/content summary;
- exact migration validation results;
- fresh-install validation;
- regression results;
- env/config readiness audit;
- deploy-contract compatibility summary;
- rollback/failure plan;
- analyzer/static results;
- Alembic head `0046`;
- clean worktree;
- remote branch SHA;
- production untouched.

Final marker:
`TELEGRAM_MTPROTO_RF1_RELEASE_FREEZE_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
