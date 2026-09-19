# Telegram MTProto RF1 readiness record

This record accompanies `ops/production/release_manifest_rf1.json`. RF1 is a
freeze and validation gate only; it performs no production cutover.

## Candidate and migration boundary

- Validated product base SHA: `e503f680543d2eeafbfbb9b641b1b1942d7990ca`
- This is not an M3 release SHA. The deployable `release_sha` is deliberately
  unassigned until Architect records it in `CURRENT_TASK.md` /
  `PROJECT_STATE.md` after RF1R review.
- RF1 head `a90716602d35cf5525554a1005a543dd8dda5491` is superseded by the
  accepted RF1R head; that RF1R head becomes the only M3 candidate eligible
  after Architect review.
- Production starting runtime/ref: `5cce4b57b14e0052a038acae1354a2821a2bb77b`
- Production starting Alembic: `0041`
- Required repository head: `0046`
- Allowed chain: `0041 -> 0042 -> 0043 -> 0044 -> 0045 -> 0046`
- `0047` is not authorized.
- `TELEGRAM_MTPROTO_AI_ENABLED` defaults to `false`.
- Bot API retirement is excluded.
- RF1 does not deploy or move a production ref.

## Required evidence

RF1 evidence is produced from isolated/disposable local resources only:

1. Incremental migration validation starts at `0041`, upgrades exactly through
   `0046`, checks the direct database revision and one Alembic head, and runs
   the standard backend readiness path.
2. A separate fresh-install database reaches exactly `0046` and passes the
   same readiness proof.
3. Backend, Telegram, source-sync/worker, notification, and client release
   regression suites are run without production credentials or provider calls.
4. Flutter analyzer output is compared against the accepted RF1 base when the
   repository baseline is non-empty; no new head-only diagnostics are allowed.

## Configuration contract

The candidate uses the existing Compose contract. Required production presence
checks are `POSTGRES_PASSWORD`, `SECRETARY_CREDENTIAL_KEY`,
`TELEGRAM_API_ID`, and `TELEGRAM_API_HASH`; values are never stored or printed.
`TELEGRAM_API_ID` must be positive and the API ID/hash must agree between api
and worker. `TELEGRAM_MTPROTO_AI_ENABLED` is optional with a default of
`false`; `SOURCE_SYNC_TELEGRAM_MTPROTO_INTERVAL_SECONDS` is optional and keeps
the candidate default/override semantics. Existing provider credentials remain
optional unless their provider is configured.

No release artifact, test fixture, or log may contain credential values,
session strings, provider references, access hashes, tokens, or secret hashes.

## Future authorized M3 path

RF1 reuses the accepted Production Deploy Contract v2 and M1/M2 tooling. A
future M3 task must use `ops/production/migrate_deploy.py` with exact release
and rollback SHAs, `0041` as the starting revision, and `0046` as the target.
The harness must verify repository/ref identity, clean checkout, explicit
Compose environment, credential presence/equality, DB TCP authentication,
container/volume/environment preservation, and health before destructive
progress. It must build api/worker before downtime, stop only api/worker,
upgrade once to `0046`, verify the direct DB revision, then start only api and
worker and verify health and runtime readiness.

Any ref mismatch, dirty checkout, migration delta outside `0042..0046`,
credential mismatch, DB/auth failure, migration failure, unexpected revision,
health failure, or preservation invariant failure aborts the cutover. No
direct SSH or ad-hoc Compose path is permitted.

## Future M3 failure plan

- Before migration: abort and restore the rollback application only if the
  existing harness proves that no destructive step occurred.
- Before application cutover, with api/worker stopped and no runtime MTProto
  data possible, downgrade `0042..0046 -> 0041` is permitted only under the
  disposable proof recorded for RF1R. Between `0041` and `0046`, preserve the
  database and use only that proven writers-stopped path.
- After application cutover at `0046`, downgrade is permitted only after the
  harness proves current api/worker are stopped, the DB is exactly `0046`, and
  all guarded MTProto tables are empty. If rows exist, or revision,
  emptiness, or container state cannot be proven, downgrade is blocked and
  break-glass/forward-fix/backup-restore planning is required.
- After `0046` with unhealthy application: preserve schema/data and use the
  accepted rollback guard; if MTProto data exists or emptiness is uncertain,
  do not downgrade and require break-glass/forward-fix or restore planning.
- MTProto-only runtime failure with a healthy core application: keep schema and
  data intact, disable/contain the affected feature through an authorized
  forward fix, and do not mutate production credentials or rows ad hoc.
- Client release failure: roll back the client artifact independently; do not
  downgrade the backend schema or alter production data for a client-only
  failure.

This record does not authorize any of those future actions.
