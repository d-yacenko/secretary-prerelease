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
- Telegram A4.2: ACCEPTED through final SHA `5de67b6a6cf746c9af911ddfcc671833d1d3d62e` on `review/telegram-depth-a4-folder-scope`.
- A4.2 accepted semantics: durable `telegram_mtproto_chat_selections` rows with independent `manual_selected` and `scope_active`; private/group/supergroup dynamic scope; fail-closed reconciliation; A3 history cursors retained across inactivity/re-entry; explicit one-peer scoped history sync reuses the A3 engine; no bulk scheduler.
- A4.2 final regression evidence: Executor reported local PostgreSQL healthy, `alembic upgrade head` PASS, Alembic `0046 (head)`, required suite `107 passed`, ruff PASS, `git diff --check` PASS, clean worktree. Architect independently reviewed ancestry/diff/coverage and accepted the phase.
- A4.2U also fixed a shared HTTP error-handler defect by preserving `HTTPException.headers`, restoring already-generated `Retry-After` headers without changing status/detail semantics.
- Current authorized work: Telegram Depth A4.3 active retrieval-scope enforcement only, on `review/telegram-depth-a4-folder-scope`.
- A4.3 canonical rule: an A4 MTProto message (`provider=telegram`, `kind=chat_message`, `metadata.transport=mtproto`) participates in active discovery/retrieval only when its same-user MTProto account + peer durable row exists and `scope_active=true`. `manual_selected` does not grant visibility.
- A4.3 must enforce the gate across Retrieval/Search, structured ObjectQuery, RecentSource/inbox review, Context automatic expansion, neighbor discovery and Telegram conversation-member discovery while preserving direct explicit by-id retained-history access.
- A4.3 is query-time only: no Object/Representation rewrite, purge, re-embedding, queue work, history fetch, schema migration, scheduler or bulk sync. Reactivation must expose the same stored Object immediately.
- Review Alembic head remains `0046`; A4.3 requires no migration.
- Scheduler/recurring Telegram jobs, bulk sync-all, UI, merge to main, and production work remain unauthorized.
- Main code still does not contain A3/A4 Telegram migrations `0044+`; production remains at Alembic `0041`.
- Telegram eventual production rollout remains migration-bearing and requires a separate explicit migration deployment plan.
- IMAP IDLE: NOT STARTED.

Do not invent or authorize additional roadmap items. `CURRENT_TASK.md` is the source of active authorization.
