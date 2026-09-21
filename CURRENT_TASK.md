# Current task — Telegram MTProto folder-derived scope complete: await next product authorization

## Status

Telegram MTProto folder-derived scope onboarding with shallow bootstrap is COMPLETE / PRODUCTION ACCEPTED.

Current production runtime/ref:
`c69d2353c19c4958e1fb60aac69466fcf6ac1482`

Alembic:
`0046`

Accepted production evidence:
- complete configured-folder scope = 28 peers;
- active scope = 28;
- manual-active = 0;
- folder-only active = 28;
- latest cursor present = 28;
- history complete = 28;
- backfill cursor present = 0;
- persisted history cutoff present = 0;
- active folder-only peers with >20 stored objects = 0;
- maximum active-peer object count = 20;
- MTProto embeddings = 0;
- current MTProto embedding provenance = 0;
- pending/running MTProto embed jobs = 0;
- folder-derived Telegram items are visible in the normal Inbox UI.

## Transport coexistence

Bot API remains enabled and is a separate transport from MTProto.

Current architecture intentionally does not treat Bot API and MTProto as interchangeable transports. Their canonical external-id schemes are distinct, so cross-transport duplicate representation is possible while both are active.

No Bot API retirement, cross-transport deduplication change, or transport migration is authorized by this task.

## Authorization state

No production mutation is currently authorized.

Do NOT:
- disable Bot API;
- change Telegram Bot API configuration;
- enable MTProto AI;
- change folder configuration;
- trigger manual Sync/Apply Scope;
- deploy/rollback/move production refs;
- alter cross-transport deduplication semantics.

Await explicit human product authorization for the next phase.

`CURRENT_TASK.md` is the source of active authorization.
