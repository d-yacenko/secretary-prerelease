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
- Telegram A4.3 implementation candidate: `a66fc167044ff3be7c1c207938b03367cea05dd8`.
- Telegram A4.3R retained-history correction: `84efe88d31e10acd6852acf59a85636834582026`; runtime fix accepted.
- Telegram A4.3T candidate: `d9007c2d5a717d26428df8056b3d6d2734fd99dc`; direct child of Architect bookkeeping `cdd7a53a6c67f9d5317a2e5160a6a4f31f4d1166`; no history rewrite.
- A4.3T added explicit regressions for supported peer kinds, a broad metadata/ownership matrix, Retrieval/Search, ObjectQuery/RecentSource, query-driven Context, and conversation-anchor discovery. It also made a minimal test-exposed correction in `conversation_member_read.py` to use canonical `NotFoundError("object", object_id)` construction.
- A4.3 is NOT YET ACCEPTED. Remaining proof is narrow: same-user wrong-account selection isolation; isolated title-trigram + filtered retrieval/all Search sorts; ObjectQuery status/label paths; RecentSource review-count helpers; Context pinned/folder automatic expansion + representation leakage; inactive conversation member with active anchor; explicit no-side-effect visibility toggle.
- Current authorized work: Telegram Depth A4.3U remaining acceptance gaps only, on `review/telegram-depth-a4-folder-scope`.
- A4.3U is test-focused. Production code is frozen unless a remaining regression exposes a concrete same-phase defect.
- Canonical A4.3 rule remains: only MTProto Telegram chat-message Objects with same-user account/peer durable row and `scope_active=true` participate in active discovery/retrieval. `manual_selected` does not grant visibility.
- Explicit exact by-id retained-history access remains allowed; automatic inactive MTProto discovery/expansion remains hidden.
- Review Alembic head remains `0046`; A4.3U requires no migration.
- No scheduler/recurring Telegram jobs, bulk sync-all, UI, merge to main, production work, or A4.4 is authorized.
- Main code still does not contain A3/A4 Telegram migrations `0044+`; production remains at Alembic `0041`.
- Telegram eventual production rollout remains migration-bearing and requires a separate explicit migration deployment plan.
- IMAP IDLE: NOT STARTED.

Do not invent or authorize additional roadmap items. `CURRENT_TASK.md` is the source of active authorization.
