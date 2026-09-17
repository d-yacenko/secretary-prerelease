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
- Telegram A4.2 implementation: `e4202d1171f9a6552d2b276093cd39d6692d6e05`.
- Telegram A4.2R correction: `28ca11160ce2b0ffcca651bfc2058b9344c379b1`; known scoped unavailable-peer 500 risk fixed to sanitized 409; local PostgreSQL-backed suite reported `90 passed`; Alembic `0046`; ruff/diff checks PASS.
- A4.2 is NOT YET ACCEPTED because required regression coverage for the new `sync_scope_peer()` path and several durable reconciliation edge cases remains incomplete.
- Current authorized work: Telegram Depth A4.2T final acceptance coverage only, on `review/telegram-depth-a4-folder-scope`.
- A4.2T is primarily test hardening. Production code is frozen unless a required new regression test exposes a real same-phase defect.
- A4.2T must explicitly prove durable private/group/supergroup rows, full cursor preservation across deactivate/re-entry, manual deselect/reselect retention, retained-row A3 manual gate, complete-empty reconciliation, both truncation sources and missing-folder fail-closed behavior, muted-peer deactivation, inactive scoped-history gate, private scoped history through `sync_scope_peer()` with materialization/cursors/idempotency, scoped group/supergroup engine reuse, scoped API peer-ID bounds, and scoped domain/provider error mappings.
- Review Alembic head remains `0046`.
- No scheduler/recurring jobs, bulk sync-all, assistant/retrieval filtering, UI, merge to main, or production work is authorized.
- Main code still does not contain A3/A4 Telegram migrations `0044+`; production remains at Alembic `0041`.
- Telegram eventual production rollout remains migration-bearing and requires a separate explicit migration deployment plan.
- IMAP IDLE: NOT STARTED.

Do not invent or authorize additional roadmap items. `CURRENT_TASK.md` is the source of active authorization.
