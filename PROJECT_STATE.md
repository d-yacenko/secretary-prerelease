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
- Telegram A3: CODE ACCEPTED / NOT PRODUCTION DEPLOYED at `4777c32deb055f5024f3dbced125b4dd6db97e85`.
- Telegram A4.1–A4.4: ACCEPTED; A4.4 exact accepted SHA `153f663a1ca0f787ec0be2cbb90d28758e539d39`.
- Telegram integration merge `origin/main` -> review completed at `2a4da0cf7d1bb1cfd2e83c39b3b4dd1e24a938b4`.
- Architect independently verified merge parents `db8c0d196666f3ffb2a32db6e60c284fda31d12a` + `1be75b6d4329e25baaf158b9c61dafa3029b0184`, and zero first-parent content diff; the merge itself changed no file content.
- Post-merge Telegram A1-A4.4 focused suite: `137 passed`.
- Post-merge full backend suite reported `2935 passed, 98 failed, 8 errors, 3 skipped`; Ruff reported `107` violations. These were asserted as baseline but have not yet been identity-compared against exact pre-integration main SHA.
- Integration Gate I1 is PENDING, not rejected. Main fast-forward is not authorized yet.
- Current authorized work: **Telegram Integration Gate I1R baseline attribution only**.
- I1R compares exact failure/error node identities and Ruff `path:line:column code` signatures between integrated review candidate `2a4da0cf...` and exact main baseline `1be75b6d...` using the same local development environment.
- I1R is evidence-only: no application/runtime/test/migration edits, no commits for test evidence, no branch rewrite, no production work.
- If review-only pytest/Ruff issues exist, they are blockers pending a separately authorized minimal correction. If review failures are all baseline or fewer, Architect will decide I1 acceptance and main fast-forward.
- Review Alembic head remains `0046`; no new migration is authorized.
- Production remains at application `5cce4b57b14e0052a038acae1354a2821a2bb77b` and Alembic `0041 / 0041`.
- No A4.5/product work, UI/Flutter changes, generic Telegram source-preference expansion, legacy Bot API removal, production deployment/migration, SSH, production Compose, provider-side mutation, or cleanup/refactor is authorized.
- Eventual Telegram production rollout remains migration-bearing and requires a separate explicit migration deployment plan after main integration is accepted.
- IMAP IDLE: NOT STARTED.

`CURRENT_TASK.md` is the source of active authorization.
