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
- Telegram A4.3 implementation candidate: `a66fc167044ff3be7c1c207938b03367cea05dd8`; direct child of Architect bookkeeping `8298f7b0c6ce94873b17eff94d6670a7006ca23b`.
- Telegram A4.3R retained-history correction: `84efe88d31e10acd6852acf59a85636834582026`; runtime fix accepted. `ContextService` may bypass the active-seed gate only for an explicit retained-history target while normal neighbor discovery remains active-scope gated.
- A4.3 is NOT YET ACCEPTED because explicit MTProto-scope acceptance coverage remains incomplete. The dedicated A4.3 test file still contains only five tests.
- Current authorized work: Telegram Depth A4.3T final acceptance coverage only, on `review/telegram-depth-a4-folder-scope`.
- A4.3T is test-only. Production code is frozen unless a required regression exposes a concrete same-phase defect.
- Required remaining proof: all peer kinds; complete fail-closed metadata/account matrix; Retrieval/Search candidate families; ObjectQuery filter combinations; RecentSource review/count paths; Context pinned/folder/query expansion and representation leakage; actual conversation-member discovery; no-side-effect reactivation.
- Canonical A4.3 rule remains: only MTProto Telegram chat-message Objects with same-user account/peer durable row and `scope_active=true` participate in active discovery/retrieval. `manual_selected` does not grant visibility.
- Explicit exact by-id retained-history access remains allowed; automatic inactive MTProto discovery/expansion remains hidden.
- Review Alembic head remains `0046`; A4.3T requires no migration.
- No scheduler/recurring Telegram jobs, bulk sync-all, UI, merge to main, production work, or A4.4 is authorized.
- Main code still does not contain A3/A4 Telegram migrations `0044+`; production remains at Alembic `0041`.
- Telegram eventual production rollout remains migration-bearing and requires a separate explicit migration deployment plan.
- IMAP IDLE: NOT STARTED.

Do not invent or authorize additional roadmap items. `CURRENT_TASK.md` is the source of active authorization.
