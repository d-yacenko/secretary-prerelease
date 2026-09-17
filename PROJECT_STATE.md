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
- Telegram A3: ACCEPTED and included in the accepted integration history; not production deployed.
- Telegram A4.1–A4.4: ACCEPTED; A4.4 exact accepted SHA `153f663a1ca0f787ec0be2cbb90d28758e539d39`.
- Telegram Integration Gate I1: **ACCEPTED**.
- Initial integration merge `origin/main` -> review: `2a4da0cf7d1bb1cfd2e83c39b3b4dd1e24a938b4`, verified zero first-parent content diff.
- I1R attribution found six review-only stale migration-head assertions and zero review-only Ruff violations.
- I1C exact correction SHA: `3e5c271c61f911e9d28c375fc43ad473e7f304a6`; exactly six test assertion lines changed from latest migration `0044` to `0046`; no application/runtime/migration changes.
- I1C local verification: six corrected tests `6 passed`; Alembic upgrade PASS; single head `0046`; full backend `2937 passed, 96 failed, 8 errors, 3 skipped`; identity attribution `104 common, 0 review-only, 1 main-only`; Telegram A1-A4.4 `137 passed`; Ruff `107 common, 0 review-only, 1 main-only`; `git diff --check` PASS; clean worktree.
- Architect independently reviewed the I1C exact diff and accepted it.
- Ancestry-only bookkeeping merge `54ccf1db14f635eed72e546c391081b07f68e67c` joined current main bookkeeping history to the tested review tree without content changes.
- Current authorized work: **none**. Executor must STOP.
- No A4.5/product work, UI/Flutter changes, generic Telegram source-preference expansion, legacy Bot API removal, production deployment/migration, SSH, production Compose, provider-side mutation, or unrelated cleanup/refactor is authorized.
- Integrated repository Alembic head is `0046`.
- Production remains at application `5cce4b57b14e0052a038acae1354a2821a2bb77b` and Alembic `0041 / 0041`.
- Telegram production rollout remains migration-bearing and requires a separate explicit Architect-authorized migration deployment plan before any production action.
- IMAP IDLE: NOT STARTED.

`CURRENT_TASK.md` is the source of active authorization.
