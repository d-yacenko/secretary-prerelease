# REL1D-HG2D4 live read-only production HG2 repair preflight census

This census is read-only local production DB evidence. No provider was contacted. No repair ran. No DB mutation ran. Yandex current provider UIDVALIDITY is still unknown. These results do not authorize repair. Fresh Architect authorization is required before any provider call or mutation.

## Identity / guards

- Live invocation: `2026-10-06 07:52` Europe/Moscow.
- Production SHA: `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`.
- `origin/main` at invocation: `0e111f194c8b9f230af9b856cfc833d5af5cfda2`.
- Expected Alembic: `0054`.
- Command: `python3 ops/production/hg2_repair_preflight.py`.
- Exit code: `0`.
- Terminal protocol: `HG2_PREFLIGHT_TERMINAL=success`.
- Read-only status: `HG2_PREFLIGHT_READ_ONLY=on`.
- `PROVIDER_NETWORK_CALLS=0`.
- `YANDEX_PROVIDER_UIDVALIDITY_KNOWN=false`.
- After the run, `origin/production` was still `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`.

## Aggregate facts

- `TELEGRAM_ACCOUNTS=1`
- `TELEGRAM_COARSE_CANDIDATES=315`
- `TELEGRAM_LOCAL_REPAIRABLE=96`
- `TELEGRAM_HIDDEN=0`
- `TELEGRAM_INVALID_PROVENANCE=219`
- `TELEGRAM_ALREADY_ENRICHED=327`
- `TELEGRAM_ACCOUNTS_WITH_LOCAL_REPAIRABLE=1`
- `TELEGRAM_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT=96`
- `MATTERMOST_ACCOUNTS=1`
- `MATTERMOST_COARSE_CANDIDATES=2515`
- `MATTERMOST_LOCAL_REPAIRABLE=2515`
- `MATTERMOST_HIDDEN=0`
- `MATTERMOST_INVALID_PROVENANCE=0`
- `MATTERMOST_ALREADY_ENRICHED=102`
- `MATTERMOST_ACCOUNTS_WITH_LOCAL_REPAIRABLE=1`
- `MATTERMOST_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT=2515`
- `TEAMS_ACCOUNTS=1`
- `TEAMS_COARSE_CANDIDATES=13`
- `TEAMS_LOCAL_REPAIRABLE=13`
- `TEAMS_HIDDEN=0`
- `TEAMS_INVALID_PROVENANCE=0`
- `TEAMS_ALREADY_ENRICHED=25`
- `TEAMS_ACCOUNTS_WITH_LOCAL_REPAIRABLE=1`
- `TEAMS_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT=13`
- `GMAIL_ACCOUNTS=1`
- `GMAIL_ATTRIBUTABLE=210`
- `GMAIL_COARSE_CANDIDATES=210`
- `GMAIL_LOCAL_REPAIRABLE=210`
- `GMAIL_HIDDEN=0`
- `GMAIL_INVALID_PROVENANCE=0`
- `GMAIL_ALREADY_ENRICHED=0`
- `GMAIL_UNATTRIBUTABLE=1011`
- `GMAIL_UNMATCHED_SOURCE_ACCOUNT=0`
- `GMAIL_ACCOUNTS_WITH_LOCAL_REPAIRABLE=1`
- `GMAIL_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT=210`
- `YANDEX_ACCOUNTS=1`
- `YANDEX_COARSE_CANDIDATES=63`
- `YANDEX_LOCAL_REPAIRABLE=63`
- `YANDEX_HIDDEN=0`
- `YANDEX_INVALID_PROVENANCE=0`
- `YANDEX_ALREADY_ENRICHED=0`
- `YANDEX_STORED_UIDVALIDITY_MATCH=63`
- `YANDEX_STORED_UIDVALIDITY_DIFFER=0`
- `YANDEX_STORED_UIDVALIDITY_UNVERIFIED=0`
- `YANDEX_UNATTRIBUTABLE=606`
- `YANDEX_NON_INBOX_OUTSIDE_REPAIR=0`
- `YANDEX_ACCOUNTS_WITH_LOCAL_REPAIRABLE=1`
- `YANDEX_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT=63`

## Derived repair planning facts

Every provider has a non-zero local repairable count. The sum of the five `*_LOCAL_REPAIRABLE` facts is `2897`. Provider order and any repair authorization remain with the Architect.

Deployed repair primitives read at most `100` candidate rows per call. Ceiling of local repairable rows divided by that page size is:

- Telegram: `1`
- Mattermost: `26`
- Teams: `1`
- Gmail: `3`
- Yandex: `1`

Those ceilings are page arithmetic only. They are not a repair schedule.

Rows that must stay untouched by a later provider repair:

- Telegram invalid provenance: `219`
- Gmail missing source-account provenance: `1011`
- Yandex missing source-account provenance: `606`

Hidden counts are `0` for every provider. Gmail unmatched source accounts are `0`. Yandex non-INBOX rows outside repair are `0`.

`YANDEX_LOCAL_REPAIRABLE=63` is local structural eligibility only. All `63` of those rows match the stored account UIDVALIDITY, and `0` differ or are unverified against that stored value. Provider-current UIDVALIDITY is unknown, so this count is not provider-safe eligibility.

## Boundary

No provider network call, repair primitive, sync, backfill, reconcile, credential decryption, production ref move, deploy, rollback, or client action occurred.
