# Current task — Telegram Depth A4 preparation / integration baseline

## Status

Telegram Depth A4 — ACTIVE, preparation step authorized.

This task is intentionally limited to synchronizing Executor state and creating a clean A4 review baseline that contains the already accepted A3 commit without rewriting it. No folder-scoped product implementation is authorized yet.

## Fixed refs

- Repository: `d-yacenko/secretary-prerelease`
- Start from the current `origin/main` at task execution time.
- Accepted Telegram A3 SHA: `4777c32deb055f5024f3dbced125b4dd6db97e85`
- A3 branch: `review/telegram-depth-a3-history-import`
- A3 state: CODE ACCEPTED / UNMERGED / NOT DEPLOYED
- Intended A4 review branch: `review/telegram-depth-a4-folder-scope`

## Authorized work

1. Verify the Executor primary checkout is clean. If it is not clean, STOP and report the exact status; do not stash, discard, or repair unrelated work.
2. Fetch `origin`, switch/stay on `main`, and fast-forward only to `origin/main`. Verify exact `HEAD == origin/main`.
3. Keep the primary checkout on clean current `main`. Create a separate Git worktree for `review/telegram-depth-a4-folder-scope` from that exact `main`.
4. In the review worktree, integrate exact A3 commit `4777c32deb055f5024f3dbced125b4dd6db97e85` while preserving that exact commit in branch ancestry. Prefer a normal merge of the accepted A3 branch/commit. Do not rebase or cherry-pick A3 into a rewritten commit.
5. Resolve only conflicts strictly required by this integration. Do not implement folder configuration, muted filtering, dialog-scope redesign, UI, scheduler changes, production changes, or any other A4 functionality in this task.
6. Run targeted Telegram MTProto A1/A2/A3 tests, including `backend/tests/test_telegram_mtproto_a1.py`, `backend/tests/test_telegram_mtproto_a2.py`, and `backend/tests/test_telegram_mtproto_a3.py`, plus the migration-head checks those tests exercise. If an integration conflict requires a minimal correction, include a focused test for that correction.
7. Push `review/telegram-depth-a4-folder-scope`.

## Completion report

Return exactly:

- primary `main` HEAD and confirmation it equals `origin/main`;
- review branch HEAD SHA;
- integration/merge commit SHA;
- confirmation that exact A3 SHA `4777c32deb055f5024f3dbced125b4dd6db97e85` is an ancestor of the review branch HEAD;
- changed files introduced by integration conflict resolution, if any;
- exact test commands and results;
- `git status --short` for both primary checkout and review worktree;
- fixed completion marker: `TELEGRAM_A4_BASELINE_READY`.

Then STOP. Do not start folder-scoped ingestion until Architect reviews and explicitly authorizes the next A4 task.

## Production boundary

No production deployment, migration, rollback, SSH, Compose, runtime probing, credential changes, or provider-side mutation is authorized by this task.
