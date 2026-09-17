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
- Telegram A4.1:
  ACCEPTED through review SHA `43944ca47b407889f87eb891b898a1c55097f7f0`.
- Telegram A4.2 implementation:
  REVIEWED / CHANGES REQUIRED / NOT ACCEPTED at `e4202d1171f9a6552d2b276093cd39d6692d6e05`.
- A4.2 architecture retained:
  migration `0046`, independent durable `manual_selected` and `scope_active`, dynamic-scope reconciliation, and shared A3 bounded history engine.
- A4.2 blocking review findings:
  scoped per-peer endpoint does not catch `TelegramMtprotoGroupUnavailableError` from the shared history transport, risking an unsanitized internal failure; dedicated A4.2 acceptance coverage contains only four tests and does not prove the required cursor preservation/re-entry, legacy manual compatibility, private scoped history/idempotency, complete-empty/missing-folder reconciliation, and API/error boundaries.
- A4.2 required DB-backed suite was not completed because the Executor reported no PostgreSQL on `localhost:5432`; repository `infra/compose.dev.yaml` explicitly publishes the local development DB on host port 5432 for pytest.
- Current authorized work:
  Telegram Depth A4.2R correction + acceptance completion only, on `review/telegram-depth-a4-folder-scope`.
- A4.2R must minimally fix scoped unavailable-peer error mapping, add the full required regression coverage, start the repository local development PostgreSQL, run `alembic upgrade head`, and successfully run the required A1/A2/A3/A4/A4.2 DB-backed suite before requesting acceptance.
- No scheduler/recurring jobs, bulk sync-all, assistant/retrieval filtering, UI, merge to main, or production work is authorized.
- Main code still does not contain A3/A4 Telegram migrations `0044+`; production remains at Alembic `0041`.
- Telegram eventual production rollout remains migration-bearing and requires a separate explicit migration deployment plan.
- IMAP IDLE:
  NOT STARTED

Do not invent or authorize additional roadmap items. `CURRENT_TASK.md` is the source of active authorization.
