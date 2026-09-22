# Current task — Deploy Telegram MTProto ordinary Inbox UX release

## Authorization

Human explicitly authorized schema-neutral production deploy of:

`f31f8f5b704159b7ec903da4c26a590d23f86e78`

Rollback/current production before deploy:

`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Expected Alembic:

`0046`

Canonical `production` branch has been fast-forwarded non-force to the exact release.

## Execute exactly once

From canonical repo:

```bash
python3 ops/production/deploy.py \
  --release-sha f31f8f5b704159b7ec903da4c26a590d23f86e78 \
  --rollback-sha bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b \
  --expected-alembic 0046
```

## Expected deployment invariants

- schema-neutral preflight passes;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- only API/worker recreated;
- health PASS;
- Alembic exact `0046`;
- no DB/schema/data cleanup;
- no MTProto AI enablement.

## Failure handling

If deploy fails:
- do not retry automatically;
- do not use direct SSH;
- return complete sanitized deploy output and STOP.

## Post-deploy human acceptance

Using already-installed current clients:

1. refresh/reopen Inbox;
2. verify old routine Telegram `message_created` cards disappear from `Требует внимания`;
3. send one fresh inbound message in an active configured folder;
4. refresh/wait for normal sync;
5. verify the message appears under ordinary Inbox / `Последние входящие`;
6. verify no corresponding new attention card appears.

No client rebuild required.

`CURRENT_TASK.md` is the source of active authorization.
