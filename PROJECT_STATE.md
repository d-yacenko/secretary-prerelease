# Project state

- Active development repository: `d-yacenko/secretary-prerelease`.
- Production canonical Git repository: `d-yacenko/secretary-prerelease`.
- Architect encrypted recovery context is stored in the same repository as `secretary_architect_context_encrypted.md`; plaintext is not committed.
- Production application/runtime: `5cce4b57b14e0052a038acae1354a2821a2bb77b`.
- Production branch: `5cce4b57b14e0052a038acae1354a2821a2bb77b`.
- Production Alembic: `0041 / 0041`.
- Production health: PASS.
- Google Sync Resilience A: COMPLETE / DEPLOYED / RUNTIME VERIFIED.
- Production Deploy Contract v2: MERGED / MANDATORY FOR NORMAL SCHEMA-NEUTRAL PRODUCTION DEPLOYMENT.
- Yandex transient retry hotfix: DEPLOYED / RUNTIME VERIFIED.
- Telegram A1/A2: MERGED TO MAIN / NOT PRODUCTION DEPLOYED.
- Telegram A3: ACCEPTED / MAIN / NOT PRODUCTION DEPLOYED.
- Telegram A4.1–A4.4: ACCEPTED / MAIN / NOT PRODUCTION DEPLOYED.
- Telegram Integration Gate I1: ACCEPTED.
- Production Line Reconciliation R1: ACCEPTED.
- Accepted migration chain is exactly `0041 -> 0042 -> 0043 -> 0044 -> 0045 -> 0046`.
- Production Migration Rollout M1 harness: ACCEPTED at exact SHA `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`.
- Telegram platform credentials are provisioned in production `/opt/secretary/.env`; values/hashes are not committed or logged.
- M2 production readiness retry: READY.
- Production runtime/ref remains `5cce4b57b14e0052a038acae1354a2821a2bb77b`; no deployment/ref move occurred.
- M3 migration-bearing production cutover is NOT AUTHORIZED.
- Telegram Bot API retirement is NOT AUTHORIZED.
- Current work state: HOLD for Telegram API Terms clarification before any further Telegram code/design task.
- Intended scenario under review is private personal-assistant processing of messages already accessible to the authenticated user, with no training/fine-tuning/dataset/public indexing/global search/resale/investigation.
- Current Telegram official terms contain broad AI/ML restrictions including "deployment" and an exception language requiring explicit, informed, affirmative and continued consent from all relevant users for specific content/context.
- It is not yet resolved whether that language permits the intended private inference/summarization scenario.
- No agent task is authorized during this HOLD.
- No production ref move, deploy, service mutation, Alembic write, DB mutation, env mutation, production MTProto login/history import, bot disable/delete, or destructive cleanup is authorized.
- IMAP IDLE: NOT STARTED.

`CURRENT_TASK.md` is the source of active authorization.
