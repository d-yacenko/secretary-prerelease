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
- Telegram A4.1 implementation:
  REVIEWED / CHANGES REQUIRED / NOT ACCEPTED
  reviewed SHA `814f75c330e9876ca9ee7f2da692c5d39d51ba40`.
- A4.1 durable migration/configuration direction remains valid; review Alembic head remains expected `0045`.
- Blocking provider-semantics findings:
  custom Telegram `DialogFilter` IDs are not peer-folder IDs for `iter_dialogs(folder=...)`; `messages.getDialogFilters` current result is a wrapper with `.filters`; effective mute must be derived from raw notify settings rather than a presumed `Dialog.muted` property.
- Current authorized work:
  Telegram Depth A4.1R provider-semantics correction only, on `review/telegram-depth-a4-folder-scope`.
- A4.1R must evaluate custom filter membership from live dialog facts + Telegram filter definitions, keep final Secretary rule `member of configured filter AND currently not muted`, preserve stable filter-ID configuration, and remain read-only with respect to history/materialization/queue/scheduler.
- A4.2 is NOT STARTED / NOT AUTHORIZED.
- Main code still does not contain A3/A4 Telegram migrations 0044/0045; production remains at Alembic 0041.
- Telegram eventual production rollout remains migration-bearing and requires a separate explicit migration deployment plan.
- IMAP IDLE:
  NOT STARTED

Do not invent or authorize additional roadmap items. `CURRENT_TASK.md` is the source of active authorization.
