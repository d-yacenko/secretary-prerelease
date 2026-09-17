# Project state

- Active development repository: `d-yacenko/secretary-prerelease`.
- Production canonical Git repository: `d-yacenko/secretary-prerelease`.
- Architect encrypted recovery context is stored in the same repository as `secretary_architect_context_encrypted.md`; plaintext is not committed.
- Production application/runtime:
  `5cce4b57b14e0052a038acae1354a2821a2bb77b`
- Production Alembic:
  `0041 / 0041`
- Production health:
  PASS
- Google Sync Resilience A:
  COMPLETE / DEPLOYED / RUNTIME VERIFIED
- Production Deploy Contract v2:
  MERGED / MANDATORY FOR NORMAL PRODUCTION DEPLOYMENT
- Yandex transient retry hotfix:
  DEPLOYED / RUNTIME VERIFIED
- Telegram A1/A2:
  MERGED TO MAIN / NOT PRODUCTION DEPLOYED
- Telegram A3:
  CODE ACCEPTED / NOT MERGED TO MAIN / NOT DEPLOYED
  `4777c32deb055f5024f3dbced125b4dd6db97e85`
- Telegram A4 integration baseline:
  ACCEPTED on `review/telegram-depth-a4-folder-scope`
  `4f1a9012145faa66baf499ad4fc9c08b759e9a5f`
- Telegram A4.1 — folder configuration + corrected custom `DialogFilter` semantics + read-only dynamic scope preview:
  ACCEPTED through review SHA `43944ca47b407889f87eb891b898a1c55097f7f0`.
- A4.1 accepted semantics:
  stable custom filter IDs/names; exact fail-closed configuration; one bounded all-dialog scan; Telegram filter membership evaluated from live dialog facts; final eligibility `member of configured filter AND currently not muted`; private/group/supergroup supported; bot/broadcast/unsupported skipped; no history fetch in preview.
- A4.1 acceptance evidence reported by Executor:
  A1/A2/A3/A4 targeted suite `83 passed`; Alembic `0045 (head)`; ruff PASS; git diff --check PASS; clean review worktree. GitHub has no CI status checks for the acceptance SHA, so local test execution is Executor-reported while code/diff/ancestry were independently reviewed.
- Current authorized work:
  Telegram Depth A4.2 — durable active scope + explicit scoped per-peer history sync, on `review/telegram-depth-a4-folder-scope`.
- A4.2 must evolve the existing `telegram_mtproto_chat_selections` row into durable peer sync state with independent `manual_selected` and `scope_active` flags, preserve A3 cursors on deactivation/re-entry, support private/group/supergroup, fail closed on truncated scope reconciliation, and reuse the A3 bounded history engine for exactly one explicitly requested active peer.
- A4.2 does NOT authorize scheduler/recurring jobs, bulk sync-all loops, assistant/retrieval filtering, UI, merge to main, or production work.
- Review Alembic head is expected to become `0046` if A4.2 is implemented as authorized.
- Main code still does not contain A3/A4 Telegram migrations 0044+; production remains at Alembic 0041.
- Telegram eventual production rollout remains migration-bearing and requires a separate explicit migration deployment plan.
- IMAP IDLE:
  NOT STARTED

Do not invent or authorize additional roadmap items. `CURRENT_TASK.md` is the source of active authorization.
