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
- Telegram A4.1 initial implementation:
  NOT ACCEPTED due provider-semantics defect at reviewed SHA `814f75c330e9876ca9ee7f2da692c5d39d51ba40`.
- Telegram A4.1R provider-semantics correction:
  CODE REVIEW PASSED at `0a987bc02a16eaea5aadc859ad631510579b0743`; acceptance pending required regression-test coverage.
- Corrected A4.1 semantics:
  custom `DialogFilter` definitions come from `messages.DialogFilters.filters`; one bounded all-dialog scan is used; custom filter IDs are not passed to `iter_dialogs(folder=...)`; membership is evaluated from filter definitions; final Secretary eligibility remains `member of configured filter AND currently not muted`.
- Current authorized work:
  Telegram Depth A4.1T acceptance-test hardening only, on `review/telegram-depth-a4-folder-scope`.
- Review Alembic head remains `0045`; no new migration is authorized by A4.1T.
- A4.2 is NOT STARTED / NOT AUTHORIZED.
- Main code still does not contain A3/A4 Telegram migrations 0044/0045; production remains at Alembic 0041.
- Telegram eventual production rollout remains migration-bearing and requires a separate explicit migration deployment plan.
- IMAP IDLE:
  NOT STARTED

Do not invent or authorize additional roadmap items. `CURRENT_TASK.md` is the source of active authorization.
