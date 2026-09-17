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
- Google runtime retry-policy assertions:
  PASS
- Google recurring jobs at runtime verification:
  Gmail pending: 1
  Calendar pending: 1
  Failed: 0
- Natural six-minute Google aggregate observation:
  COMPLETED / NO AGGREGATE STATUS-COUNT TRANSITION OBSERVED
- Rollback after Google rollout:
  NOT REQUIRED
- Production Deploy Contract v2:
  MERGED / MANDATORY FOR NORMAL PRODUCTION DEPLOYMENT
- Canonical Google runtime verifier:
  `ops/production/verify_google_sync.py`
- Canonical explicit application rollback:
  `ops/production/rollback.py`
- Production Compose execution requires explicit:
  `/opt/secretary/.env`
- Explicit DB authentication from resolved production env:
  VERIFIED
- File-backed DB password transport:
  CANCELLED / NOT REQUIRED
- Yandex transient retry hotfix:
  DEPLOYED / RUNTIME VERIFIED
- Production Yandex Mail synchronized successfully after rollout and returned to normal scheduling.
- Telegram A1/A2:
  MERGED / NOT PRODUCTION DEPLOYED
- Telegram A3:
  CODE ACCEPTED / UNMERGED / NOT DEPLOYED
  `4777c32deb055f5024f3dbced125b4dd6db97e85`
- Telegram A4 — Folder-scoped dialog ingestion:
  ACTIVE / PREPARATION-INTEGRATION BASELINE AUTHORIZED
- Current A4 preparation goal:
  synchronize Executor `main` and construct `review/telegram-depth-a4-folder-scope` with exact accepted A3 preserved in ancestry; no folder-scope implementation yet.
- Telegram production remains migration-bearing; production Alembic is still 0041, while Telegram development includes 0042/0043 and accepted A3 adds 0044.
- IMAP IDLE:
  NOT STARTED

Do not invent or authorize additional roadmap items. `CURRENT_TASK.md` is the source of active authorization.
