# Current task — HOLD after Quick UX bugfix pack acceptance

## Architect acceptance

Commit:

`2a5d76ae80d53c13a6581852ef1a0362ad1a3e38`

is ACCEPTED / DEPLOY-READY / NOT DEPLOYED.

Production currently remains:

`d22c6cf78945c8f92934a46431b2bcc1887fd8c8`

Alembic remains:

`0046`

The accepted bugfix pack is schema-neutral.

## Accepted changes

### Google OAuth diagnostics

Accepted:
- normal automatic access-token refresh remains unchanged;
- refresh responses preserve only a sanitized OAuth error code such as `invalid_grant`;
- permanent/non-retryable refresh failures remain authentication failures;
- transient/server/rate-limit OAuth failures remain retryable;
- job/source-sync diagnostics do not expose refresh tokens, access tokens, authorization codes, client secrets, or raw provider response bodies;
- user-facing authentication diagnostics instruct the user to reconnect;
- `docs/google_oauth.md` documents that Testing publishing status cannot provide persistent non-basic authorization and that continuous operation requires `In Production` or an appropriate Internal mode.

Operational note:
- this code does NOT and cannot silently renew an already expired/revoked refresh token;
- the currently broken Google account will require one new OAuth authorization after the Google Cloud publishing mode is corrected;
- changing Google Cloud OAuth publishing status and performing real reauthorization are separate operator actions and are NOT authorized by this HOLD.

### Hands-free Assistant

Accepted:
- voice-origin Assistant request failures remain in `AssistantVoiceState.error`;
- the existing sanitized backend error text remains visible, including `assistant_round_limit`;
- exactly one local failure cue is played for a failed voice-origin turn;
- typed Assistant failures do not play the voice failure cue;
- failures are not converted into chat success messages;
- existing retry mechanics remain in use;
- next voice invocation clears the prior voice-turn error.

### Desktop Inbox delete

Accepted:
- desktop Inbox source cards now expose a trash quick action after Ask Secretary and Open in Graph;
- existing delete API and confirmation policy are reused;
- successful delete removes the card locally without a full Inbox reload;
- failed delete keeps the card;
- Android/touch swipe-to-remove behavior is unchanged.

### Exact Assistant object citations

Accepted:
- Assistant may emit `secretary://object/<uuid>` internal object citations;
- server validates cited ids against object ids actually exposed during the current turn;
- unseen/invented/foreign ids are neutralized and are not clickable;
- exact cited ids are prioritized ahead of generic references and survive the ordinary generic reference cap;
- duplicate citations/references are deduplicated;
- client opens validated internal citations through existing `openObjectDetail()`;
- http/https Markdown links remain external;
- unsupported/malformed schemes are ignored.

## Verification reported on exact accepted commit

- backend citation/OAuth/sync focused tests: 25 passed;
- `py_compile`: passed;
- Ruff check on changed modules: passed;
- Ruff format --check on focused/new files: passed;
- Flutter voice/Markdown/source-sync/Inbox delete focused tests: passed;
- `flutter analyze` on touched libraries: no new errors;
- `git diff --check`: clean.

## Deferred backlog

Still deferred and not part of this accepted pack:
- cross-provider temporal `already_evidenced` / idempotency nuance;
- eventual historical cleanup/compaction of `PROJECT_STATE.md`.

## Authorization state

NO deploy is currently authorized.

Do not:
- move production ref;
- deploy/restart/recreate production;
- change production env;
- change Google Cloud OAuth publishing status;
- perform real Google OAuth reauthorization;
- run provider diagnostics/calls;
- run direct production SSH/manual Docker/Compose;
- perform production DB writes.

STOP and wait for explicit human authorization to deploy exact commit `2a5d76ae80d53c13a6581852ef1a0362ad1a3e38`.

Google Cloud publishing-mode correction and one-time Google reauthorization remain separate operator steps.
