# Project state

- Active development repository: `d-yacenko/secretary-prerelease`.
- Production canonical Git repository: `d-yacenko/secretary-prerelease`.
- Architect encrypted recovery context is stored in the same repository as `secretary_architect_context_encrypted.md`; plaintext is not committed.
- Production application/runtime: `5cce4b57b14e0052a038acae1354a2821a2bb77b`.
- Production Alembic: `0041 / 0041`.
- Production health: PASS.
- Google Sync Resilience A: COMPLETE / DEPLOYED / RUNTIME VERIFIED.
- Production Deploy Contract v2: MERGED / MANDATORY FOR NORMAL PRODUCTION DEPLOYMENT.
- Yandex transient retry hotfix: DEPLOYED / RUNTIME VERIFIED.
- Telegram A1/A2: MERGED TO MAIN / NOT PRODUCTION DEPLOYED.
- Telegram A3: ACCEPTED and included in accepted integration history; not production deployed.
- Telegram A4.1–A4.4: ACCEPTED; A4.4 exact accepted SHA `153f663a1ca0f787ec0be2cbb90d28758e539d39`.
- Telegram Integration Gate I1: ACCEPTED.
- I1C exact correction SHA: `3e5c271c61f911e9d28c375fc43ad473e7f304a6`; exactly six stale migration-head test assertions changed from `0044` to `0046`; no application/runtime/migration changes.
- Production Line Reconciliation R1: ACCEPTED at exact SHA `f55bc1f9360384f403e9791f863b9b104d9c6d42`.
- R1 merge parents are prior main `1ff97b66d96ec7a82eb62cb9e1c813e1ebdd4866` and production `5cce4b57b14e0052a038acae1354a2821a2bb77b`; Architect independently verified zero first-parent/content diff (`0 additions / 0 deletions / no files`).
- Therefore deployed Yandex/Google hotfix lineage is now in main ancestry while the previously tested application tree is unchanged.
- R1 verification reported: Alembic upgrade PASS, single head `0046`; production hotfix suite `68 passed`; Telegram A1-A4.4 `137 passed`; scheduler/queue/worker/source-preference `89 passed`; full backend `2938 passed, 95 failed, 8 errors, 3 skipped` with R1-only failure/error identities `0`; Ruff R1-only violations `0`; `git diff --check` PASS; clean worktree.
- Accepted migration chain is exactly `0041 -> 0042 -> 0043 -> 0044 -> 0045 -> 0046`; no `0047` is authorized.
- Normal `ops/production/deploy.py` remains schema-neutral and must continue to reject this migration-bearing release.
- Current authorized work: **Production Migration Rollout M1 harness + local proof** only, as specified in `CURRENT_TASK.md`.
- M1 creates a separate fail-closed migration deployment path for exact production schema transition `0041 -> 0046`, with both api+worker stopped during schema write, direct DB revision verification before worker start, and guarded rollback semantics.
- `0046` downgrade can re-impose `peer_kind IN ('group','supergroup')`; therefore post-cutover automatic downgrade is forbidden unless the harness proves all new MTProto rollout tables contain zero rows. Any uncertainty/data requires break-glass instead of destructive downgrade.
- M1 is implementation/testing/documentation only. It forbids SSH to production, moving `origin/production`, production Compose/Alembic, actual deploy, production backup/restore, credential rotation, A4.5, UI/Flutter work, Bot API removal, application feature changes, and unrelated cleanup/refactor.
- Production remains at application `5cce4b57b14e0052a038acae1354a2821a2bb77b` and Alembic `0041 / 0041` until a separately authorized production execution phase succeeds.
- IMAP IDLE: NOT STARTED.

`CURRENT_TASK.md` is the source of active authorization.
