# Current task — HOLD after Quick UX bugfix production deployment

## Production status

Production runtime/ref:

`2a5d76ae80d53c13a6581852ef1a0362ad1a3e38`

Deployment status:

PASS.

Deployment evidence:
- `RELEASE_HEAD=2a5d76ae80d53c13a6581852ef1a0362ad1a3e38`
- `HEALTH=PASS`
- `ALEMBIC=0046`
- `DB_CONTAINER_UNCHANGED=true`
- `DB_VOLUME_UNCHANGED=true`
- `ENV_FILE_UNCHANGED=true`
- `API_RECREATED=true`
- `WORKER_RECREATED=true`
- `DEPLOYMENT=PASS`
- exit status 0;
- stderr empty;
- rollback `d22c6cf78945c8f92934a46431b2bcc1887fd8c8` not used.

## Live behavior

The deployed Quick UX bugfix pack includes:
- Google OAuth refresh diagnostics with safe provider error codes such as `invalid_grant`;
- existing automatic access-token refresh preserved;
- hands-free Assistant failures remain visibly errored and emit one local failure cue;
- desktop Inbox source cards expose a trash quick action using the existing delete semantics;
- provenance-safe `secretary://object/<uuid>` Assistant citations open exact validated Secretary objects;
- external http/https links remain external.

## Google OAuth operational state

The deployment does NOT repair an already expired/revoked Google refresh token.

If the Google OAuth project is still in Publishing status `Testing`, continuous Gmail/Calendar/Drive authorization is not expected to persist for these scopes.

The next Google recovery steps are separate operator actions:
1. inspect Google Cloud OAuth publishing mode;
2. if appropriate, change from `Testing` to `In Production` (or appropriate Internal mode);
3. perform one fresh Google OAuth authorization in Secretary;
4. verify Gmail and Google Calendar sync recover.

None of those actions is authorized by this HOLD.

## Deferred backlog

Still deferred:
- cross-provider temporal `already_evidenced` / idempotency nuance;
- eventual historical cleanup/compaction of `PROJECT_STATE.md`.

## Authorization state

No further production or provider work is currently authorized.

Do not:
- move refs;
- deploy/restart/recreate;
- change production env;
- change Google Cloud OAuth publishing status;
- perform real Google OAuth reauthorization;
- run provider diagnostics/calls;
- change `TELEGRAM_MTPROTO_AI_ENABLED`;
- run direct production SSH/manual Docker/Compose;
- perform production DB writes.

STOP and await the next explicit human task/authorization.
