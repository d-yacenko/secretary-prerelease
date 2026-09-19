# Current task — Telegram MTProto M4A: production account activation and first controlled sync

## Status

Production Migration Rollout M3 is **SUCCESSFUL**.

Exact production release/runtime/ref:
`8091736337689b68b4510126e74d9e409397f696`

Production Alembic:
`0046`

Production health:
PASS.

M3 preserved:
- DB container;
- DB volume;
- production `.env`;
- `SECRETARY_CREDENTIAL_KEY`;
- Telegram runtime configuration;
- Bot API integration.

No migration `0047` exists or is authorized.

Telegram MTProto personal-account login and history import were intentionally NOT performed during M3.

This task authorizes only **M4A — activate one production Telegram MTProto user account through the existing application contract and perform the first controlled sync**.

No deploy or schema change is authorized.

## Security boundary

Sensitive Telegram authentication values MUST be entered only by the human user through the existing application UI/input path:
- phone number;
- login code;
- 2FA password.

The Executor must NOT:
- ask the user to paste Telegram code/password into terminal/chat logs;
- print, capture, persist, screenshot, echo, or inspect code/password/session data;
- inspect raw encrypted Telegram session material;
- read or print `TELEGRAM_API_HASH`, credential key, or other production secrets;
- use raw Telethon scripts or direct Telegram SDK calls outside the application;
- create an alternative auth endpoint or login path.

The Executor may launch/use the existing Flutter client and existing Secretary API only.

If human input is required, stop at the UI/input boundary and report:
`TELEGRAM_MTPROTO_M4A_USER_AUTH_REQUIRED`

The human can complete the sensitive fields locally, then the Executor may continue only after the application reports authorization success.

## No-code expectation

M4A is a production runtime activation/smoke task.

Expected repository changes:
NONE.

Do not create a branch or commit unless a genuine product defect is discovered. If a defect is found, STOP and report it for a separately authorized corrective. Do not fix it inside M4A.

## Production preflight

Read:
- `docs/deploy.md`;
- relevant accepted production runtime/readiness helpers under `ops/production/`;
- existing MTProto client/backend contract files only as needed.

Before any account activation:
- verify `origin/production == 8091736337689b68b4510126e74d9e409397f696`;
- verify production runtime/checkout exact same SHA using accepted read-only verification path;
- verify DB Alembic exact `0046`;
- verify health PASS;
- verify api + worker running;
- verify production worktree clean;
- verify Bot API remains present/untouched;
- verify MTProto backend status is configured through the existing application status endpoint/UI;
- do not print config secret values.

If production runtime/config is not healthy/configured, STOP:
`TELEGRAM_MTPROTO_M4A_BLOCKED`

## Existing application auth flow only

Use existing Flutter/API flow:
- `GET /telegram/mtproto/status`
- `POST /telegram/mtproto/auth/start`
- `POST /telegram/mtproto/auth/code`
- `POST /telegram/mtproto/auth/password` when required.

Do not call those endpoints with sensitive values from shell history or logged command lines.

Preferred path:
1. open existing Account/Settings Telegram MTProto section;
2. human enters phone;
3. human enters Telegram code;
4. if Telegram requests 2FA, human enters password in the obscured field;
5. app reaches connected state.

If user interaction cannot be completed in the Executor environment, report `TELEGRAM_MTPROTO_M4A_USER_AUTH_REQUIRED` and STOP with only non-sensitive UI steps.

## Post-auth verification

After the application reports authorization success, verify only non-sensitive facts:

- `GET /telegram/mtproto/status` reports configured + connected;
- connected identity fields are present as allowed by UI contract;
- no auth challenge remains active in the user-visible flow;
- no secret/session values are exposed;
- `TELEGRAM_MTPROTO_AI_ENABLED=false` remains the effective production setting;
- no AI/embed jobs are created merely by transport activation.

Do not print Telegram account/user identifiers in the completion report unless needed for troubleshooting; prefer boolean/sanitized identity-present markers.

## Scope setup

Use the existing UI/API only.

### Folders

Load:
- available folders;
- current sync folders;
- current `ignore_muted`.

Do NOT invent defaults.

For the first controlled sync, keep scope bounded.

If the human has not explicitly selected folders/groups yet:
- do not silently select everything;
- show available choices;
- require a human selection before syncing broad history.

Zero folders is valid.

### Manual groups / scope preview

Use existing:
- folders;
- scope preview;
- reconcile;
- manual groups;
- peer sync endpoints.

Before first history materialization:
- preview scope;
- report only counts/titles safe for UI display;
- do not expose provider/access references;
- do not automatically broaden scope.

## First controlled sync

After human-approved scope exists:

1. Prefer one explicitly selected peer/group for the first manual sync.
2. Use only the existing scope-peer or manual-group sync endpoint/UI action.
3. Do not run an unbounded all-account history import.
4. Record sanitized result counters only:
   - scanned;
   - materialized;
   - created;
   - updated;
   - unchanged;
   - skipped;
   - history_complete.
5. Verify resulting Telegram source objects appear in the normal Inbox.
6. Verify no duplicate Telegram-only feed exists.
7. Verify deterministic transport notifications appear for new forward events only; historical initial/backfill materialization must not spam notifications.
8. Verify MTProto-derived content remains outside AI/LLM processing while `TELEGRAM_MTPROTO_AI_ENABLED=false`.

Do not alter production sync interval during M4A.

## Recurring source-sync smoke

After first controlled manual sync:
- verify the worker remains healthy;
- verify the Telegram recurring source-sync lane can schedule/run under the accepted 60-second default or existing production override;
- do not wait for or force a broad historical crawl;
- verify no failing Telegram source-sync job storm is created.

Report sanitized counts/state only.

## Bot API coexistence

M4A does NOT authorize Bot API retirement.

Verify:
- existing Bot API configuration/integration is untouched;
- no disable/delete/revoke action occurred.

Do not compare or expose token values.

## Stop conditions

STOP immediately and report `TELEGRAM_MTPROTO_M4A_BLOCKED` if:
- production health degrades;
- auth flow returns an unexpected server error requiring code changes;
- credential/session persistence fails;
- connected status cannot be established after successful human auth;
- first bounded sync causes unexpected DB/runtime errors;
- AI/embedding jobs are produced despite the disabled MTProto AI flag;
- migration/schema mismatch is observed;
- a fix would require code/deploy/schema mutation.

Do not repair these inside M4A.

## Completion report

Return one of three markers.

### If human auth is still required

Return:
- production ref/runtime verified;
- Alembic/health verified;
- MTProto configured readiness;
- exact non-sensitive UI step awaiting human action;
- no production mutation beyond normal read-only checks.

Final marker:
`TELEGRAM_MTPROTO_M4A_USER_AUTH_REQUIRED`

### If blocked

Return:
- sanitized blocker;
- stage;
- production ref/runtime;
- Alembic;
- health;
- confirmation no unauthorized repair/deploy was attempted.

Final marker:
`TELEGRAM_MTPROTO_M4A_BLOCKED`

### If successful

Return:
- production ref/runtime SHA;
- Alembic;
- health;
- MTProto configured + connected booleans;
- auth path used: code-only or code+2FA (never values);
- human-approved scope summary;
- first bounded sync result counters;
- normal Inbox materialization verification;
- historical notification anti-spam verification;
- AI quarantine verification;
- recurring source-sync smoke;
- Bot API untouched;
- production worktree clean;
- confirmation no secrets/auth values/session material were printed;
- confirmation no code/schema/deploy changes occurred.

Final marker:
`TELEGRAM_MTPROTO_M4A_ACTIVATION_SUCCESS`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
