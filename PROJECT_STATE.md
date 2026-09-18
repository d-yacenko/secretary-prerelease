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
- Production Migration Rollout M1 harness: **ACCEPTED** at exact final SHA `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`.
- M1 accepted fixes include: release-Compose Telegram preflight before downtime; captured-ID initial stop proof; direct DB `alembic_version` checks; bounded health retry; post-cutover current-writer quiescence proof via stopped-aware lookup + inspect; exact `0046` revision gate before MTProto emptiness check; destructive downgrade forbidden on data or uncertainty.
- M1 was fast-forward integrated into `main`.
- M1 local evidence reported: harness `32 passed`; critical regression suite `292 passed`; full backend `2968 passed, 97 failed, 8 errors, 3 skipped`; Ruff baseline `107`, changed-file Ruff PASS; disposable `0041 -> 0046 -> 0041 -> 0046` PASS; nonempty MTProto rollback guard PASS; `git diff --check` PASS.
- The one additional full-suite identity reported during M1R4 was `tests/test_phase_29a_r1_corrective.py::test_revision_change_invalidates_before_worker`; M1R4 changed only the production migration helper and its tests, and independent review found no causal code overlap. Treat it as environment/order-sensitive baseline evidence unless independently reproduced against M1 scope.
- GitHub commit statuses for the M1 correction SHAs were empty; M1 acceptance is based on exact independent code/diff review plus local verification evidence.
- Current authorized work: **Production Migration Rollout M2 readiness gate** as specified in `CURRENT_TASK.md`.
- M2 is production read-only/readiness inspection only. It authorizes strict verified SSH and non-mutating checks needed to prove candidate release Compose/runtime readiness while `origin/production` and running production remain on rollback SHA.
- M2 explicitly forbids moving `production`, stopping/recreating services, running production Alembic writes, changing DB rows/schema, changing `.env`, rotating credentials, or executing the deployment harness.
- Candidate release code for M2 readiness: `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`.
- Rollback/runtime SHA: `5cce4b57b14e0052a038acae1354a2821a2bb77b`.
- M2 must prove production Telegram runtime credential presence/validity through the candidate release Compose using the existing production `.env`, without printing values and without moving the production ref.
- Only after M2 readiness acceptance may a separate M3 authorize the actual production ref move + exact migration deployment + runtime verification.
- IMAP IDLE: NOT STARTED.

`CURRENT_TASK.md` is the source of active authorization.
