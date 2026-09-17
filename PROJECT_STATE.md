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
- Telegram A4.3: ACCEPTED through final SHA `6e6120d38cc3b1e3b677b1ca16cf97a002ea91d3` on `review/telegram-depth-a4-folder-scope`.
- A4.3 accepted semantics: Telegram MTProto active discovery/retrieval is query-time gated by the same-user durable account + exact account/peer selection + `scope_active=true`; `manual_selected` does not grant visibility; malformed/missing linkage fails closed; legacy non-MTProto Telegram remains unaffected; explicit exact by-id retained history remains readable while automatic inactive expansion is hidden.
- A4.3 includes retained-history correction `84efe88d31e10acd6852acf59a85636834582026`, expanded acceptance candidate `d9007c2d5a717d26428df8056b3d6d2734fd99dc`, and final test commit `6e6120d38cc3b1e3b677b1ca16cf97a002ea91d3`.
- The previously requested two-MTProto-accounts-for-one-Secretary-user scenario is structurally impossible under current schema constraint `uq_telegram_mtproto_accounts_user_id`; it is not an A4.3 blocker. The visibility predicate nevertheless matches exact account id, peer id, and same-user ownership.
- Current authorized work: Telegram Depth A4.4 recurring scope + history sync only, on `review/telegram-depth-a4-folder-scope`.
- A4.4 must extend the existing Postgres-backed `SourceSyncScheduler` / `JobQueueService` / source-sync worker lane. No Telegram-specific scheduler daemon, queue, worker, broker, or microservice is authorized.
- A4.4 recurring identity: one `sync_telegram_mtproto`-style recurring Job per connected MTProto account, not per peer.
- A4.4 deployment interval: 300 seconds through a Telegram-specific source-sync setting; generic `UserSourcePreference` / `history_days` exposure is explicitly deferred because MTProto already has the accepted fixed 14-day durable history cutoff.
- Every A4.4 run must reconcile Telegram folder/mute scope before any history work. Failed/truncated/unavailable reconciliation means zero peer history sync in that run.
- After successful reconciliation, A4.4 may attempt at most 10 currently active peers per run and must persist fair round-robin progress in safe non-secret recurring Job payload metadata. Peer-local failures must not starve later peers; provider/account-wide failures stop the run.
- A4.4 must reuse `TelegramMtprotoHistoryService.sync_scope_peer()` and all existing A3/A4 history cursors/materialization behavior; it must not reset cursors or duplicate the importer.
- A4.4 requires no schema migration. Review Alembic head remains `0046`.
- No UI/Flutter changes, generic Telegram source-preference exposure, legacy Bot API removal, merge to main, production deployment, production migration, or provider-side Telegram mutation is authorized in A4.4.
- Main code still does not contain A3/A4 Telegram migrations `0044+`; production remains at Alembic `0041`.
- Telegram eventual production rollout remains migration-bearing and requires a separate explicit migration deployment plan.
- IMAP IDLE: NOT STARTED.

Do not invent or authorize additional roadmap items. `CURRENT_TASK.md` is the source of active authorization.
