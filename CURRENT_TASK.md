# Current task — Telegram Bot API M4BQ1: Stage C cleanup deploy awaiting explicit human authorization

## Status

M4BP1 + M4BP1R Stage C non-destructive cleanup is CODE ACCEPTED.

Accepted release candidate:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Current production / rollback:
`fe151f12f64886505253e765b82458710a949e34`

Expected Alembic:
`0046`

The production -> candidate comparison is a fast-forward and contains no Alembic/migration changes.

## Accepted candidate semantics

- retired Bot link/webhook routes are removed;
- Bot HTTP transport/webhook service/webhook CLI are removed;
- active Bot settings are removed from Settings, Compose, and `.env.example`;
- legacy Bot connection/link client DTOs are removed;
- live Bot send execution code is removed;
- historical Bot-derived canonical objects remain readable;
- historical Bot send/reply remains fail-closed and never reroutes to MTProto;
- legacy Bot DB models/tables/migrations remain preserved;
- MTProto transport/session/scope/sync/send/mutation behavior remains;
- no migration / no `0047`.

Production `.env` currently contains only already-empty legacy Bot lines from Stage B. Candidate Settings ignores unknown env entries and candidate Compose no longer passes those lines into API/worker, so no production env edit is required for this deploy.

## Authorization state

PRODUCTION DEPLOY IS NOT YET AUTHORIZED.

Do not:
- move `production` ref;
- run `ops/production/deploy.py`;
- edit production `.env`;
- delete legacy DB rows/tables;
- perform any Telegram/provider call;
- change MTProto configuration;
- enable MTProto AI.

Await explicit human authorization such as:

`Разрешаю production deploy M4BP1 Stage C`

After explicit authorization, Architect will promote the exact accepted candidate to `production` and authorize one schema-neutral canonical deploy.

## Client note

The canonical production deploy harness updates API + worker, not a Flutter artifact. Backend cleanup is backward-compatible with old clients because the previous client parser tolerates the missing legacy Telegram connection field. Any distribution/rebuild of the cleaned Flutter client is a separate packaging/client-release concern and is not a blocker for server Stage C safety.

`CURRENT_TASK.md` is the source of active authorization.
