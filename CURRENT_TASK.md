# Current task — Telegram MTProto M4BB2R: make wide preview probe compatible with current production

## Status

M4BB1 code is accepted but NOT deployed:
`c69d2353c19c4958e1fb60aac69466fcf6ac1482`

Current production remains:
`cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa`

M4BB2 probe commit:
`a41d3e11902f55858c4960b9f6b5ddc1383e0579`

is NOT authorized for live execution.

## Blockers

### 1. Probe depends on code not present in pinned production

The remote child currently imports:

`TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT`

and calls:

`TelethonMtprotoTransport.fetch_dialog_universe(...)`

But pinned production `cbd5e7d...` predates M4BB1:
- it does not contain the new 2000 scope constant;
- its `fetch_dialog_universe` still clamps to `DISCOVERY_DIALOG_LIMIT=500`;
- it still reports boundary truncation with the old semantics.

So the current probe cannot test the intended 2000+1 preview against current production.

### 2. Runtime failure reporting is not truthful

The remote child catches all exceptions in one broad handler and always reports:
- `FAILURE_STAGE=STAGE_1_DB_SESSION`;
- `TELEGRAM_NETWORK_CALLS=0`.

That is false for failures after Telegram connection/auth/folder discovery/dialog iteration starts.

The live one-shot protocol must truthfully distinguish pre-provider vs provider-started failures.

## Goal

BUILD / REVIEW ONLY.

Correct the probe so it can execute the M4BB1 2000+1 preview semantics against the OLD current production runtime without deploying M4BB1.

Do NOT run live.

## Required implementation shape

Keep the existing production pin:
`cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa`

Expected Alembic:
`0046`

Inside the API-container child:

### Reuse only helpers that already exist on current production

Allowed imports from pinned production:
- `TelethonMtprotoTransport` for folder discovery if desired;
- `TelegramClient` / `StringSession` from the transport module or Telethon;
- canonical `_dialog_from_dialog`;
- canonical `dialog_matches_filter`;
- account store/encryption/session helpers.

Do NOT import M4BB1-only constants.

Do NOT call production `fetch_dialog_universe` for the wide scan.

### Explicit wide scan

Define the probe-local constant:

`SCOPE_DIALOG_SCAN_LIMIT = 2000`

Then:
1. discover the one configured folder definition using current production-compatible code;
2. create/read-only Telegram client with the stored session;
3. connect;
4. verify `is_user_authorized()`;
5. iterate `client.iter_dialogs(limit=2001)`;
6. retain/process only first 2000;
7. if an actual 2001st dialog is yielded, set `TRUNCATED=true` and stop;
8. convert retained rows using canonical `_dialog_from_dialog`;
9. aggregate skipped reasons only across retained 2000;
10. exclude muted;
11. apply canonical `dialog_matches_filter`;
12. dedupe scope by peer.

Always disconnect in `finally`.

No history/message fetch.

## Truthful stage/accounting protocol

Track provider progress explicitly.

Recommended high-level Telegram network-call accounting:
- folder discovery: connect + authorization check + folder request = 3;
- wide dialog scan: connect + authorization check + dialog iteration = 3;
- successful run => `TELEGRAM_NETWORK_CALLS=6`.

For failure:
- before any provider operation: 0;
- after folder discovery starts: report the actual completed/attempted high-level count according to a deterministic counter;
- after wide scan starts: likewise non-zero.

At minimum distinguish stages:
- `STAGE_1_DB_SESSION`
- `STAGE_1_ACCOUNT_CARDINALITY`
- `STAGE_1_FOLDER_CARDINALITY`
- `STAGE_2_FOLDER_DISCOVERY`
- `STAGE_2_AUTHORIZED`
- `STAGE_2_FOLDER_DEFINITIONS`
- `STAGE_3_DIALOG_CONNECT`
- `STAGE_3_DIALOG_AUTHORIZED`
- `STAGE_3_DIALOG_ITERATION`
- `STAGE_3_DIALOG_CONVERSION`

Do not collapse provider failures into DB stage.

No raw exception text/traceback.

## Required tests

Tests must exercise the CHILD LOGIC, not only the transcript parser.

At minimum:

1. Current-production compatibility: child source contains no import/reference to `TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT`.
2. Current-production compatibility: child source does not call `fetch_dialog_universe`.
3. Explicit local bound is exactly 2000.
4. 499 dialogs -> not truncated.
5. exactly 500 -> not truncated.
6. exactly 2000 -> not truncated.
7. 2001 -> truncated.
8. iterator requested limit exactly 2001.
9. no more than 2001 yielded/consumed.
10. retained descriptors <=2000.
11. skipped counts only retained window.
12. muted excluded.
13. scope dedupe by peer.
14. account cardinality fail -> stage/cardinality and network calls 0.
15. folder cardinality fail -> stage/cardinality and network calls 0.
16. folder discovery provider failure -> correct provider stage and nonzero truthful call count.
17. auth-invalid during wide scan -> correct auth stage and nonzero truthful call count.
18. dialog iteration provider failure -> correct iteration stage and nonzero truthful call count.
19. dialog conversion failure -> correct conversion stage and nonzero truthful call count.
20. client disconnect attempted in success/failure.
21. no history/message fetch.
22. no reconcile.
23. no DB flush/commit/write.
24. premature EOF fail closed.
25. unsafe output fail closed.
26. Alembic host/credential + stdin isolation.
27. bash -n.
28. helper compile.
29. Ruff.
30. git diff --check.

Use fake clients/transports; no live Telegram.

## Strictly forbidden

Do NOT:
- run live probe;
- deploy M4BB1;
- move production ref;
- production SSH;
- live Telegram/provider calls;
- Apply Scope;
- Sync;
- change folders;
- login/re-login;
- DB writes;
- restart/recreate;
- migration / `0047`;
- AI enable;
- Bot API change.

## Deliverable

If corrected:
- commit/push canonical main;
- update `PROJECT_STATE.md`;
- do NOT run live probe.

Report:
- corrective commit SHA;
- files changed;
- proof of current-production compatibility;
- child-logic test results;
- protocol tests;
- lint/diff-check;
- production SSH=0;
- Telegram/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_MTPROTO_M4BB2R_SCOPE_PREVIEW_PROBE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
