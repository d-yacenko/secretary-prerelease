# Current task — Telegram Integration Gate I1

## Status

- Telegram A4.1: ACCEPTED.
- Telegram A4.2: ACCEPTED.
- Telegram A4.3: ACCEPTED through `6e6120d38cc3b1e3b677b1ca16cf97a002ea91d3`.
- Telegram A4.4: ACCEPTED at `153f663a1ca0f787ec0be2cbb90d28758e539d39`.
- Product feature work is paused. The active task is integration only.

## Why this gate exists

`main` and `review/telegram-depth-a4-folder-scope` currently diverge from merge-base `5ca5f93a3f88d1a17e2060319f6826766f2ff119`.

Architect comparison confirmed that the commits unique to `main` since that merge-base change only:

- `CURRENT_TASK.md`;
- `PROJECT_STATE.md`;
- `secretary_architect_context_encrypted.md`.

No main-only application/runtime code changes need to be reconciled.

The review branch contains the accepted A3/A4 implementation and migrations through Alembic `0046`.

## Objective

Create a normal merge commit bringing current `origin/main` into `review/telegram-depth-a4-folder-scope`, preserve all accepted history, resolve bookkeeping files to the current Integration Gate state, and prove the merged review branch is safe to fast-forward into `main`.

This is not a rebase and not a product implementation phase.

## Branch / history rules

Work only in:

`review/telegram-depth-a4-folder-scope`

Before work:

- `git fetch origin`;
- worktree must be clean;
- fast-forward local review branch to current `origin/review/telegram-depth-a4-folder-scope`;
- confirm accepted A4.4 SHA `153f663a1ca0f787ec0be2cbb90d28758e539d39` remains in ancestry;
- record exact `origin/main` and review starting SHAs.

Then merge current `origin/main` into review with a normal merge commit.

Do NOT:

- rebase;
- squash;
- cherry-pick accepted Telegram commits;
- reset/rewrite history;
- force push;
- merge review into `main` yourself;
- change product/runtime code merely to clean up style.

If conflicts occur, they are expected only in bookkeeping/recovery-context files. Resolve `CURRENT_TASK.md` and `PROJECT_STATE.md` to this Integration Gate authorization. Preserve the current canonical encrypted recovery context file; do not decrypt or rewrite it locally unless explicitly required by Architect.

If any application/runtime/test/migration file conflicts, STOP and report before resolving it.

## Expected code result

After merge:

- application/runtime code must remain exactly the accepted review implementation except for merge metadata;
- migrations remain `0042/0043` already on main plus accepted Telegram `0044/0045/0046` from review;
- `alembic heads` must report exactly one head: `0046`;
- no new migration is allowed;
- no UI/Flutter changes;
- no source-preference expansion;
- no legacy Bot API removal;
- no production changes.

## Required verification

Use local development PostgreSQL only.

From repository root:

`docker compose -f infra/compose.yaml -f infra/compose.dev.yaml up -d db`

Wait for DB healthy.

From `backend`:

1. Migration verification:

`alembic upgrade head`

`alembic heads`

Expected head: `0046` only.

2. Full backend regression gate:

`pytest -q`

This full-suite run is required for the main integration gate. Report pass/fail/deselected counts exactly. If the repository has a documented unavoidable environment-only exclusion, do not silently omit it; report it explicitly.

3. Telegram focused regression must also remain green:

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py tests/test_telegram_mtproto_a4_3.py tests/test_telegram_mtproto_a4_4.py`

4. Static checks:

`ruff check app tests`

`git diff --check`

5. History/tree verification:

- verify `origin/main` is an ancestor of final review HEAD after merge;
- compare final review HEAD against the pre-merge review HEAD and confirm the only content changes from the merge are bookkeeping/recovery-context resolution, not application/runtime/test/migration code;
- compare final review against `origin/main` and report the remaining files that would enter `main` on fast-forward.

## Completion report

Commit/push only the merge result to:

`review/telegram-depth-a4-folder-scope`

Return:

- starting review SHA;
- starting `origin/main` SHA;
- merge commit SHA;
- final remote review SHA;
- confirmation A4.4 accepted SHA remains in ancestry;
- conflict list and exact resolution summary;
- confirmation no application/runtime/test/migration conflict was manually resolved;
- `alembic upgrade head` result;
- `alembic heads` result;
- full `pytest -q` result;
- Telegram focused suite result;
- Ruff result;
- `git diff --check` result;
- final `git status --short`;
- confirmation `origin/main` is ancestor of final review HEAD;
- final review-vs-main file summary;
- confirmation no production/main/UI/A4.5 work was performed;
- final marker exactly: `TELEGRAM_INTEGRATION_GATE_I1_READY`.

Then STOP.

## After I1

Architect will independently review the merge commit and test evidence. Only after acceptance will Architect fast-forward `main` to the integration HEAD. Production migration/deployment remains a separate later authorization.
