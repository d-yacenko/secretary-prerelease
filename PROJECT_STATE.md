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
- Telegram A4.4 exact accepted SHA: `153f663a1ca0f787ec0be2cbb90d28758e539d39`.
- Telegram Integration Gate I1: ACCEPTED.
- Production Line Reconciliation R1: ACCEPTED at exact merge SHA `f55bc1f9360384f403e9791f863b9b104d9c6d42`; production hotfix lineage is in main ancestry.
- Accepted migration chain is exactly `0041 -> 0042 -> 0043 -> 0044 -> 0045 -> 0046`; no `0047` is authorized.
- Normal `ops/production/deploy.py` remains schema-neutral and must reject this migration-bearing release.
- Production Migration Rollout M1 harness: ACCEPTED at exact SHA `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`.
- M1 accepted safety properties include: release-Compose Telegram preflight before downtime; captured-ID initial stop proof; direct DB `alembic_version` checks; bounded startup health retries; stopped-aware post-cutover current-writer quiescence proof; exact `0046` revision gate before MTProto emptiness check; no destructive downgrade on data or uncertainty.
- M1 is integrated into `main`.
- Initial M2 production readiness inspection was BLOCKED only by `RELEASE_TELEGRAM_CREDENTIALS=FAIL`.
- Candidate release code remains `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`.
- Production runtime/ref remains `5cce4b57b14e0052a038acae1354a2821a2bb77b`; no deployment/ref move occurred.
- Architectural credential model: `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` are installation-level Secretary platform credentials; each Secretary user receives a separate encrypted per-user MTProto session via phone/code/2FA authorization.
- Operator has now provisioned the two Telegram platform credential entries into production `/opt/secretary/.env`.
- Credential values/hashes were not shared in chat or repository and are not committed.
- Provisioning is NOT yet accepted as production-ready; full M2 readiness must be rerun and independently reviewed.
- Current authorization: rerun the M2 readiness/no-mutation gate only, as specified in `CURRENT_TASK.md`.
- During M2 retry it remains forbidden to move `production`, stop/restart/recreate services, run Alembic writes, mutate DB rows/schema, modify `.env`, rotate credentials, or execute deployment.
- M2 retry must prove candidate release Compose sees usable Telegram credentials for both api+worker, values match without disclosure, DB/key invariants remain equal, and production runtime/ref/container IDs/DB volume/Alembic remain unchanged.
- Only after M2 returns READY and Architect accepts the evidence may M3 authorize actual migration-bearing cutover.
- IMAP IDLE: NOT STARTED.

`CURRENT_TASK.md` is the source of active authorization.
