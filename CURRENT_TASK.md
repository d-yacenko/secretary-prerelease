# CURRENT_TASK

ACTIVE

## REL1D-HG2D1 — offline qualification of the frozen HG2 backend release candidate

REL1D-HG2C2 through REL1D-HG2C6 are ARCHITECT SOURCE-ACCEPTED.

The provider-specific bounded repair primitives are complete at source level.

This task does NOT deploy anything and does NOT run any provider repair.

The frozen backend release candidate for qualification is:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

The current production/rollback SHA is:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Expected Alembic revision:

`0054`

This task determines whether that exact candidate is safe to authorize later as a schema-neutral backend release.

It does NOT itself authorize:
- moving `production`;
- running `ops/production/deploy.py`;
- SSH;
- production access;
- provider calls;
- data repair;
- client rollout;
- human REL1D acceptance.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/deploy.md`
- `ops/production/deploy.py`
- `docs/rel1d_hg2_provider_repair_audit.md`

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Verify exact SHAs resolve locally:

- release candidate: `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`
- rollback/production: `bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Do not move any ref.

## Frozen-candidate invariants

Prove all of the following locally from Git before running qualification:

1. `bc69c6fa5c0735db9509d12dd5f77e6285e45901` is an ancestor of `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`.
2. Candidate is present in the canonical `main` history.
3. The current task/ledger commits after candidate do not change backend code or tests:
   - `git diff --quiet f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6 origin/main -- backend`
   must succeed before qualification.
4. Candidate versus rollback changes NO migration infrastructure covered by the normal deploy harness:
   - `backend/alembic/versions/`
   - `backend/alembic/env.py`
   - `backend/alembic.ini`
   - `backend/alembic/script.py.mako`
5. Candidate versus rollback changes NO `ops/production/` file.
6. Repository Alembic graph has exactly one head and it is `0054`.
7. Production branch is still exactly:
   `bc69c6fa5c0735db9509d12dd5f77e6285e45901`.

If any invariant fails:
- do not reinterpret or pick a different release SHA;
- return HOLD with exact blocker;
- STOP.

## Execution environment

Qualification is LOCAL/OFFLINE only.

Do not:

- run production deploy/rollback/migration harnesses;
- connect by SSH;
- call external providers;
- use production DB;
- run tests marked `live`;
- set live-provider environment flags merely to make tests run;
- use real provider credentials.

Existing local/fake/unit/integration tests are allowed.

## Required regression qualification

From the backend project environment, run the full non-live backend suite:

`pytest -m "not live"`

Do not substitute only the focused HG2 tests.

If the suite has existing collection/runtime configuration that requires the repository's documented local test invocation wrapper, use that exact local wrapper only if it is already committed and source-grounded; record the exact command.

Do NOT fix unrelated failures in this task.

A full-suite failure is a qualification blocker and must return HOLD for Architect review.

## Required HG2 focused union

Even if the full suite passes, also run an explicit HG2 qualification union covering at minimum:

- `backend/tests/test_rel1d_hg2a_scan_window.py`
- HG2B1 Mattermost tests used for source acceptance;
- `backend/tests/test_rel1d_hg2b2_mail_recipients.py`
- `backend/tests/test_rel1d_hg2b3_mtproto_sender.py`
- `backend/tests/test_rel1d_hg2c2_mtproto_sender_repair.py`
- `backend/tests/test_rel1d_hg2c3_mattermost_author_repair.py`
- `backend/tests/test_rel1d_hg2c4_teams_sender_kind_repair.py`
- `backend/tests/test_rel1d_hg2c5_gmail_recipient_repair.py`
- `backend/tests/test_rel1d_hg2c6_yandex_mail_recipient_repair.py`
- `backend/tests/test_rel1d_role_import_participants.py`

Also include the exact MTProto A3/A4/A4.2 tests whose stale Alembic assertions were corrected during HG2B3.1/HG2B3.2R.

Record exact totals.

## Static checks

Run:

- `ruff check app tests` from the backend project directory;
- `git diff --check bc69c6fa5c0735db9509d12dd5f77e6285e45901 f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`.

Do not auto-fix Ruff findings in this task.

Any failure is a qualification blocker.

## Release-delta evidence

Create exactly one qualification artifact:

`docs/rel1d_hg2_release_qualification.md`

It must record factual evidence only:

### Identity

- candidate SHA;
- rollback/production SHA;
- expected Alembic revision;
- current `origin/main` SHA at qualification time;
- current `origin/production` SHA.

### Git safety

- ancestor check result;
- number of commits candidate is ahead of rollback;
- total changed files rollback -> candidate;
- count/list of migration-infrastructure changes (must be zero);
- count/list of `ops/production/` changes (must be zero);
- confirmation that candidate -> current main changes no `backend/` files.

### Test evidence

- exact full non-live pytest command and total passed/failed/skipped/xfailed as emitted;
- exact focused HG2 union command and totals;
- exact Ruff result;
- exact `git diff --check` result;
- Alembic single-head result.

### Release boundary

State explicitly:

- candidate is QUALIFIED only if every required check is green;
- qualification is not deployment authorization;
- `production` was not moved;
- no SSH/provider/production DB access occurred;
- no data repair occurred;
- no client rollout occurred;
- human REL1D acceptance remains paused;
- release authorization must come from a fresh Architect decision after review.

Do not include credentials, account identifiers, raw provider payloads, production secrets or private/local Architect context.

## Source-mutation prohibition

This task is qualification/documentation only.

Do not change:
- `backend/app/`
- `backend/tests/`
- `backend/alembic/`
- `ops/production/`
- client source
- dependency files

The only non-ledger file allowed to change is:

`docs/rel1d_hg2_release_qualification.md`

If a test/static check fails, do not patch it under HG2D1. Return HOLD.

## Completion protocol

### On fully green qualification

1. add/update `docs/rel1d_hg2_release_qualification.md`;
2. append a compact factual `REL1D-HG2D1` entry to `PROJECT_STATE.md` containing:
   - candidate SHA;
   - rollback SHA;
   - schema-neutral evidence;
   - exact full-suite totals;
   - exact focused-union totals;
   - Ruff/diff-check/Alembic results;
   - explicit no ref move/deploy/provider/production/data-repair/client action;
3. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2D1 qualification artifact path;
   - candidate `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6` is ready for Architect release review;
   - production remains `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - no deploy/ref move/data repair/client rollout/human acceptance without fresh Architect authorization;
4. commit + push to `main`;
5. STOP.

### On any blocker

1. write a concise blocker section in `docs/rel1d_hg2_release_qualification.md` with exact local evidence;
2. append blocker facts to `PROJECT_STATE.md`;
3. return `CURRENT_TASK.md` to HOLD;
4. do not change runtime/tests to make qualification green;
5. commit + push ledger/artifact only;
6. STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
