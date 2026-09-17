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
- Telegram Integration Gate I1: ACCEPTED.
- I1C exact correction SHA: `3e5c271c61f911e9d28c375fc43ad473e7f304a6`; exactly six test assertion lines changed from latest migration `0044` to `0046`; no application/runtime/migration changes.
- Main/review integration bookkeeping finalized through `c0d7e18bfbef553f7a14107060651fecfbd0841c`; integrated Alembic head is `0046`.
- Architect compared `main` with `origin/production` and found they diverge from merge-base `6d69d936a7e5e08c427598bc8d659d3c7fe6b4ae`.
- `origin/production` contains exactly three production-only commits absent from main ancestry: `2c19512d11428920932ffec2267780699ae39d3b` (Yandex short transient retry), `6a3ec041692b07fcc203906057b2823eb70f6b6b` (Google Sync Resilience A), and `5cce4b57b14e0052a038acae1354a2821a2bb77b` (Google OAuth transient retry classification).
- Those production-only changes overlap queue/worker/recurring-finalization paths also modified by Telegram A4.4, so production lineage must be reconciled before any migration-bearing release.
- Current authorized work: **Production Line Reconciliation R1** only, as specified in `CURRENT_TASK.md`.
- R1 must create `review/production-line-reconcile-telegram-rollout` from current main, merge `origin/production` normally, preserve both deployed Google/Yandex retry behavior and accepted Telegram recurring-sync behavior, and run focused + full regression attribution.
- R1 forbids production SSH, moving production, production Compose, production migration execution, deployment, A4.5, UI/Flutter work, Bot API removal, new migration, and unrelated cleanup/refactor.
- Accepted migration chain remains exactly `0041 -> 0042 -> 0043 -> 0044 -> 0045 -> 0046`; no new migration is authorized.
- Normal `ops/production/deploy.py` intentionally rejects migration-bearing releases, so after R1 acceptance a separate migration deployment harness/plan will be required.
- Production remains at application `5cce4b57b14e0052a038acae1354a2821a2bb77b` and Alembic `0041 / 0041` until a separately authorized migration rollout succeeds.
- IMAP IDLE: NOT STARTED.

`CURRENT_TASK.md` is the source of active authorization.
