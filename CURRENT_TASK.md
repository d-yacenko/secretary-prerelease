# Current task — Telegram platform credential provisioning + M2 readiness retry

## Architectural decision

Telegram credentials are split into two layers:

1. **Platform/application credentials** — one pair for the Secretary installation:
   - `TELEGRAM_API_ID`
   - `TELEGRAM_API_HASH`

   These identify the Secretary Telegram client application and are shared by all Secretary users. They are NOT per-user profile credentials.

2. **Per-user Telegram authorization** — each Secretary user connects their own Telegram account through the MTProto login flow:
   - phone number;
   - Telegram login code;
   - 2FA password when required;
   - resulting user-specific MTProto session/auth key.

   The existing backend stores the resulting Telegram session encrypted and bound to the Secretary user. Users must not be asked to create their own Telegram developer application or enter `api_id/api_hash` in their personal profile.

This preserves the same conceptual separation as platform OAuth/app credentials versus personal user tokens/sessions.

## Status

- M1 migration harness: ACCEPTED.
- M2 readiness: BLOCKED only by `RELEASE_TELEGRAM_CREDENTIALS=FAIL`.
- Production runtime/ref remains `5cce4b57b14e0052a038acae1354a2821a2bb77b`.
- Production Alembic remains `0041`.
- Candidate release remains `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`.
- No deployment has occurred.

## Authorized phase

A human/operator may now obtain one Telegram application credential pair from Telegram and provision only these two entries in:

`/opt/secretary/.env`

Allowed keys:

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`

No other environment entry may change.

## How the operator obtains the credentials

Use Telegram's official application registration:

1. Sign in to `https://my.telegram.org` with an active Telegram account controlled by the installation operator.
2. Open **API development tools**.
3. Create/register the Secretary application if no application exists for that operator account.
4. Record the returned `api_id` and `api_hash` securely.
5. Do not paste those values into Git, chat, issue trackers, logs, shell history, or documentation.

The registered Telegram account is the operator/developer identity for the application; it is not the Telegram identity used by every Secretary end user.

## Production .env mutation contract

Before editing:

- production repository/runtime/ref must still be exact rollback SHA;
- services remain running;
- capture file ownership/mode and an internal checksum of `/opt/secretary/.env`;
- do not print the checksum or any secret values.

Edit only the two Telegram application credential variables.

Requirements:

- `TELEGRAM_API_ID` numeric and > 0;
- `TELEGRAM_API_HASH` nonblank;
- no quotes or whitespace artifacts that would alter Compose parsing;
- preserve all existing non-Telegram lines exactly;
- preserve file owner/group/mode.

Prefer an interactive editor or another non-echoing path. Do not use a command line containing the secret value because it may enter shell history/process listings.

## Forbidden during provisioning

Do NOT:

- restart/recreate/stop api, worker, or db;
- run `docker compose up/restart/stop`;
- run Alembic upgrade/downgrade;
- change DB rows/schema;
- move `production` or any rollout ref;
- run `migrate_deploy.py`;
- change `SECRETARY_CREDENTIAL_KEY`;
- change PostgreSQL settings;
- print Telegram credential values or hashes.

The currently running rollback containers do not need these variables; therefore no service restart is required just to provision them.

## Verification after edit

Without restarting services:

1. prove `/opt/secretary/.env` owner/group/mode unchanged;
2. prove only the two authorized Telegram keys changed;
3. resolve candidate release Compose against the same production `.env`;
4. require usable Telegram credentials for release api+worker;
5. require api/worker Telegram values match without printing values;
6. require release DB and credential-key settings still exactly equal rollback settings;
7. rerun the full M2 readiness checks;
8. prove production runtime/ref/container IDs/DB volume/DB Alembic remain unchanged.

If all checks pass, report:

`PRODUCTION_MIGRATION_ROLLOUT_M2_READINESS_READY`

Otherwise:

`PRODUCTION_MIGRATION_ROLLOUT_M2_READINESS_BLOCKED`

Then STOP.

## Product/UI follow-up

The intended user-facing model is a profile/settings action such as **Connect Telegram** that performs per-user phone/code/2FA authorization and stores the resulting encrypted per-user session.

Do not add `TELEGRAM_API_ID` or `TELEGRAM_API_HASH` as ordinary user-profile fields. If a future self-hosting/admin UI is added, these may be exposed only as installation/admin-level platform settings backed by secure server-side secret storage, not as user-scoped credentials.

`CURRENT_TASK.md` is the source of active authorization.
