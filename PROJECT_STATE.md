# Project state

- Active development repository: `d-yacenko/secretary-prerelease`.
- Production canonical Git repository: `d-yacenko/secretary-prerelease`.
- Architect encrypted recovery context is stored in the same repository as `secretary_architect_context_encrypted.md`; plaintext is not committed.
- Production application/runtime: `5cce4b57b14e0052a038acae1354a2821a2bb77b`.
- Production Alembic: `0041 / 0041`.
- Production health: PASS.
- Google Sync Resilience A: COMPLETE / DEPLOYED / RUNTIME VERIFIED.
- Production Deploy Contract v2: MERGED / MANDATORY FOR NORMAL PRODUCTION DEPLOYMENT.
- Yandex transient retry hotfix: DEPLOYED / RUNTIME VERIFIED.
- Telegram A1/A2: MERGED TO MAIN / NOT PRODUCTION DEPLOYED.
- Telegram A3: CODE ACCEPTED / NOT MERGED TO MAIN / NOT DEPLOYED at `4777c32deb055f5024f3dbced125b4dd6db97e85`.
- Telegram A4.1: ACCEPTED through `43944ca47b407889f87eb891b898a1c55097f7f0`.
- Telegram A4.2: ACCEPTED through `5de67b6a6cf746c9af911ddfcc671833d1d3d62e`.
- Telegram A4.3: ACCEPTED through `6e6120d38cc3b1e3b677b1ca16cf97a002ea91d3`.
- Telegram A4.4: ACCEPTED at `153f663a1ca0f787ec0be2cbb90d28758e539d39`.
- Review branch accepted bookkeeping HEAD before integration gate: `990cfaa1f515992c4d83e601f02f08c3eb178a7a`.
- Main/review diverge from merge-base `5ca5f93a3f88d1a17e2060319f6826766f2ff119`.
- Architect comparison confirmed the commits unique to main since that merge-base modify only `CURRENT_TASK.md`, `PROJECT_STATE.md`, and `secretary_architect_context_encrypted.md`; there are no main-only application/runtime code changes to reconcile.
- Current authorized work: **Telegram Integration Gate I1** only.
- I1 objective: normal merge of current `origin/main` into `review/telegram-depth-a4-folder-scope`, preserving accepted history, then local PostgreSQL migration verification and full backend regression before any merge of review into main.
- I1 forbids rebase/squash/reset/cherry-pick/force-push and forbids resolving any application/runtime/test/migration conflict without stopping for Architect review.
- Expected post-merge Alembic head remains exactly `0046`; no new migration is authorized.
- I1 requires full `pytest -q`, focused Telegram A1-A4.4 suite, `ruff check app tests`, and `git diff --check`.
- Executor must not merge review into main; Architect will independently review the integration merge and only then decide whether main may fast-forward.
- No A4.5/product work, UI/Flutter changes, generic Telegram source-preference expansion, legacy Bot API removal, production deployment/migration, SSH, production Compose, provider-side mutation, or cleanup/refactor is authorized.
- Production remains at application `5cce4b57b14e0052a038acae1354a2821a2bb77b` and Alembic `0041 / 0041`.
- Eventual Telegram production rollout remains migration-bearing and requires a separate explicit migration deployment plan after main integration is accepted.
- IMAP IDLE: NOT STARTED.

`CURRENT_TASK.md` is the source of active authorization.
