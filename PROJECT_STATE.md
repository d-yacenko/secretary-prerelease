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
- Telegram A4 integration baseline: ACCEPTED on `review/telegram-depth-a4-folder-scope` at `4f1a9012145faa66baf499ad4fc9c08b759e9a5f`.
- Telegram A4.1: ACCEPTED through `43944ca47b407889f87eb891b898a1c55097f7f0`.
- Telegram A4.2: ACCEPTED through `5de67b6a6cf746c9af911ddfcc671833d1d3d62e`.
- Telegram A4.3: ACCEPTED through `6e6120d38cc3b1e3b677b1ca16cf97a002ea91d3`.
- Telegram A4.4: ACCEPTED at `153f663a1ca0f787ec0be2cbb90d28758e539d39` on `review/telegram-depth-a4-folder-scope`.
- A4.4 accepted recurring architecture: existing Postgres `SourceSyncScheduler` / `JobQueueService` / recurring source-sync worker lane; one `sync_telegram_mtproto` Job per MTProto account; 300-second deployment interval; reconcile-before-history; fail-closed reconcile means zero peer sync; only current `scope_active=true` rows considered; max 10 peers per run; safe `telegram_peer_cursor` round-robin in Job payload; peer-local failures continue; provider/account-wide failures stop; Telegram Retry-After is propagated; Job errors are sanitized; existing `sync_scope_peer()` and A3/A4 cursors/materializer are reused without reset.
- Generic Telegram `UserSourcePreference` / `history_days` exposure remains intentionally deferred because MTProto retains the accepted fixed 14-day durable cutoff.
- A4.4 added no migration; review Alembic head remains `0046`.
- Executor A4.4 verification reported: `alembic upgrade head` PASS; Telegram A1-A4.4 `137 passed`; A4.4 focused `12 passed`; scheduler/queue/worker/source-preference `89 passed`; Ruff PASS; `git diff --check` PASS; clean worktree. Architect independently reviewed exact ancestry/diff and runtime paths before accepting.
- Current authorized work: **none**. Executor must STOP. No A4.5 or other Telegram phase is authorized.
- No UI/Flutter changes, generic Telegram source-preference expansion, legacy Bot API removal, merge to main, production deployment, production migration, SSH, production Compose, provider-side Telegram mutations, or independent cleanup is authorized.
- Main code still does not contain A3/A4 Telegram migrations `0044+`; production remains at Alembic `0041`.
- Telegram eventual production rollout remains migration-bearing and requires a separate explicit migration deployment plan.
- IMAP IDLE: NOT STARTED.

Do not invent or authorize additional roadmap items. `CURRENT_TASK.md` is the source of active authorization.
