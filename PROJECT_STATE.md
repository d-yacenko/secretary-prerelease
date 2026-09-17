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
- The A4 baseline merge preserves exact A3 SHA in ancestry and had no manual conflict-resolution changes.
- A4 baseline verification reported:
  targeted A1/A2/A3 tests `65 passed`; review Alembic head `0044`; clean primary and review worktrees.
- Telegram Depth A4.1 — folder configuration and eligibility resolver:
  ACTIVE / IMPLEMENTATION AUTHORIZED on `review/telegram-depth-a4-folder-scope`.
- A4.1 scope is backend-only durable folder configuration + read-only dynamic eligibility preview using stable folder IDs and the canonical rule `configured folder membership AND not muted`.
- A4.1 does not authorize history import, materialization into active history scope, scheduler work, UI, merge to main, or production work.
- Main code still does not contain A3/A4 Telegram migration 0044+; production remains at Alembic 0041.
- Telegram eventual production rollout remains migration-bearing and requires a separate explicit migration deployment plan.
- IMAP IDLE:
  NOT STARTED

Do not invent or authorize additional roadmap items. `CURRENT_TASK.md` is the source of active authorization.
