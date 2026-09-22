# Current task — no active Telegram Bot production task

## Status

Telegram Bot API retirement is COMPLETE / PRODUCTION ACCEPTED through Stage C.

Final accepted production runtime/ref:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Alembic:
`0046`

Final live read-only acceptance proved:
- exact production HEAD/ref and clean worktree;
- DB/API/worker running and DB healthy;
- application health PASS;
- retired Bot runtime env absent;
- MTProto/protected credentials preserved;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- retired Bot routes absent;
- required MTProto route present;
- active Settings contains no retired Bot fields;
- exactly one MTProto account;
- active scope count 28;
- 431 preserved legacy non-MTProto Telegram chat objects;
- at least one preserved legacy Bot-derived object remains Inbox-readable;
- Telegram/provider calls = 0;
- DB writes = 0;
- env writes = 0;
- service recreations = 0;
- terminal success.

External/runtime retirement state:
- Bot account destroyed;
- webhook deleted;
- Bot credentials cleared;
- Bot runtime/code/config surfaces retired;
- historical Bot-derived objects and legacy Bot schema intentionally retained;
- MTProto is the sole live Telegram transport.

## Authorization

NO NEW IMPLEMENTATION OR PRODUCTION ACTION IS AUTHORIZED BY THIS FILE.

Do not:
- deploy;
- mutate production;
- clean up legacy schema/data;
- alter MTProto;
- enable Telegram MTProto AI;
- perform provider calls;
- move refs.

Await the next architect task.

`CURRENT_TASK.md` remains the source of active authorization.
