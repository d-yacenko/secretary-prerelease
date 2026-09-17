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
- Telegram integration merge `origin/main` -> review completed at `2a4da0cf7d1bb1cfd2e83c39b3b4dd1e24a938b4`; Architect verified expected parents and zero first-parent content diff.
- I1R baseline attribution completed: pytest had 105 common failure/error identities, 6 review-only, 0 main-only; Ruff had 107 common violations, 0 review-only, 1 main-only.
- Architect inspected the six review-only pytest failures and confirmed all are stale test guards asserting latest migration `0044`; the accepted migration chain is `0044 -> 0045 -> 0046`.
- Current authorized work: **Telegram Integration Gate I1C migration-guard correction only**.
- I1C authorizes exactly six one-line test changes from `versions[-1].startswith("0044")` to `versions[-1].startswith("0046")` in the six identified legacy migration guard tests. No runtime/application/migration change is authorized.
- I1 remains PENDING until I1C proves zero review-only pytest failure/error identities and zero review-only Ruff violations against exact baseline `1be75b6d4329e25baaf158b9c61dafa3029b0184`.
- Review Alembic head remains `0046`; no new migration is authorized.
- Main fast-forward is not authorized yet.
- Production remains at application `5cce4b57b14e0052a038acae1354a2821a2bb77b` and Alembic `0041 / 0041`.
- No A4.5/product work, UI/Flutter changes, generic Telegram source-preference expansion, legacy Bot API removal, production deployment/migration, SSH, production Compose, provider-side mutation, or unrelated cleanup/refactor is authorized.
- Eventual Telegram production rollout remains migration-bearing and requires a separate explicit migration deployment plan after main integration is accepted.
- IMAP IDLE: NOT STARTED.

`CURRENT_TASK.md` is the source of active authorization.
