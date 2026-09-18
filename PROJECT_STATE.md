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
- M2 production readiness inspection: **BLOCKED**.
- M2 evidence passed: local main alignment/cleanliness; SSH fingerprint; production runtime/ref identity; health; DB TCP auth; direct Alembic `0041`; rollback Compose DB/key invariants; candidate release Compose resolution; release DB/key equality; no-mutation proof; temporary worktree cleanup.
- M2 blocking result: `RELEASE_TELEGRAM_CREDENTIALS=FAIL`.
- Candidate release code remains `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`.
- Production runtime/ref remains `5cce4b57b14e0052a038acae1354a2821a2bb77b`; no deployment/ref move occurred.
- The existing production `/opt/secretary/.env` does not currently resolve usable candidate-release `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` values.
- No credential values or credential hashes were exposed by M2.
- Current authorization is STOP: no production ref move, service mutation, Alembic write, DB mutation, env mutation, credential mutation, or M3.
- Next prerequisite is human/operator availability of valid Telegram MTProto application credentials through a secure channel.
- After operator confirmation, Architect may authorize a separate narrow credential-provisioning phase that updates only Telegram credential entries in production `.env`, preserves all other env values/ownership/mode, performs no service restart/ref/DB/schema mutation, and then reruns full M2 readiness.
- Only after M2 returns READY may M3 authorize the actual migration-bearing cutover.
- IMAP IDLE: NOT STARTED.

`CURRENT_TASK.md` is the source of active authorization.
