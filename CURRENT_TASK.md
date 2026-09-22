# Current task — Human UI acceptance for Telegram ordinary Inbox

## Status

Production deploy SUCCESS.

Production runtime/ref:

`f31f8f5b704159b7ec903da4c26a590d23f86e78`

Alembic:

`0046`

Deployment invariants:
- health PASS;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- API recreated;
- worker recreated.

## Human acceptance

Using an already-installed current client:

1. refresh or reopen Inbox;
2. verify historical routine Telegram `message_created` cards are no longer shown under `Требует внимания`;
3. send one fresh inbound Telegram message into a chat in an active configured folder;
4. wait for normal sync / refresh Inbox;
5. verify the fresh message appears under ordinary Inbox / `Последние входящие`;
6. verify no corresponding new `Требует внимания` card appears.

No client rebuild is required for this backend-only correction.

## If acceptance fails

Report:
- whether old Telegram attention cards disappeared;
- whether the new message appeared anywhere in Inbox;
- whether it appeared under `Требует внимания`, `Последние входящие`, both, or neither;
- approximate message/send time;
- any sanitized UI error.

Do not perform production SSH, DB cleanup, or additional deploys without a new architect task.

`CURRENT_TASK.md` is the source of active authorization.
