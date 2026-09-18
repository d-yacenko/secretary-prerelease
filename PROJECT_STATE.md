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
- Telegram platform credentials are provisioned in production `/opt/secretary/.env`; values/hashes are not committed or logged.
- M2 production readiness retry: **READY**. Sanitized evidence: local main/origin-main exact, production runtime/ref exact rollback SHA, SSH fingerprint PASS, health PASS, DB TCP auth PASS, direct Alembic `0041`, rollback Compose env PASS, candidate release resolves/configures PASS, candidate Telegram credentials PASS, api/worker Telegram credential match PASS, release DB/key equality PASS, production state unchanged PASS, temporary worktree removed PASS.
- Exact pre-edit owner/group/mode evidence for `.env` was not available and was not fabricated.
- Production runtime/ref remains `5cce4b57b14e0052a038acae1354a2821a2bb77b`; no deploy/ref move occurred.
- M3 migration-bearing production cutover is **NOT AUTHORIZED** due Telegram external compliance blocker.
- Current Telegram API Terms prohibit using/accessing/aggregating Telegram-platform data to train, fine-tune, develop, enhance, or deploy AI/ML systems.
- Current Bot Platform terms permit use of data submitted directly and voluntarily by users to a bot only with clear intended-use disclosure and individual explicit active revocable consent; broader scraping/aggregation for AI products is prohibited.
- Accepted MTProto A3/A4 automatic history/folder ingestion currently feeds Telegram-derived objects into assistant/search/retrieval/embedding/proactive paths and therefore must not be production-deployed unchanged.
- Telegram Bot API retirement is **DEFERRED**. Bot code/config/webhook/schema must remain until a compliant Telegram architecture is selected and implemented.
- Current authorized work: Telegram Compliance Re-scope C1 design/code-impact analysis as specified in `CURRENT_TASK.md`.
- C1 must define a single clear user-facing Telegram model, consent/revocation semantics, exact AI-visible data boundary, and whether MTProto is retained only for non-AI functions or removed.
- Until C1 acceptance: no production ref move, no production deploy, no service restart/recreate, no Alembic write, no DB mutation, no further `.env` mutation, no production MTProto login/history import, no bot disable/delete, no destructive Telegram cleanup.
- IMAP IDLE: NOT STARTED.

`CURRENT_TASK.md` is the source of active authorization.
