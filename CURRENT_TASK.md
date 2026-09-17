# Current task — Telegram Depth A4.3R retained-history correction

## Status

- Telegram A4.2: ACCEPTED through `5de67b6a6cf746c9af911ddfcc671833d1d3d62e`.
- Telegram A4.3 candidate `a66fc167044ff3be7c1c207938b03367cea05dd8`: REVIEWED / CHANGES REQUIRED / NOT ACCEPTED.
- `a66fc167...` is a direct child of Architect bookkeeping `8298f7b0c6ce94873b17eff94d6670a7006ca23b`; preserve it in ancestry. No reset/rebase/rewrite.
- A4.3R is the only authorized work. Do not begin A4.4.

## Confirmed defect

A4.3 correctly introduced shared query-time MTProto visibility in `backend/app/domain/telegram_mtproto_visibility.py`, but it made `GraphService.get_neighbors()` require the seed object itself to be active.

That breaks the A4.3 retained-history contract: `ContextService.build_context(object_id=<inactive MTProto object>)` explicitly loads the exact target through ordinary `get_object()`, then calls `get_neighbors()`, which rejects that inactive seed. Exact by-id retained history must remain readable; only automatic discovery/expansion must be hidden.

## Required correction

Implement the smallest correction that preserves both rules:

1. `ContextService.build_context(object_id=<inactive MTProto object>)` must succeed and include the explicit target.
2. The explicit target's own stored representations may remain readable.
3. Automatically discovered objects — pinned, folder-contained, graph neighbors, query/search results — must still require active MTProto scope.
4. Representations of inactive automatically discovered MTProto objects must not leak.
5. `list_neighbors`/normal GraphService neighbor discovery remains an active-discovery surface: inactive returned neighbors stay hidden.
6. `get_object(object_id)` remains unchanged for exact retained-history access.
7. No schema change, purge, object rewrite, re-embedding, history fetch, queue work, scheduler, bulk sync, UI, main merge, or production work.

A small internal seed-policy/helper is acceptable if necessary. Do not weaken returned-neighbor filtering.

## Missing acceptance coverage to add

Use real PostgreSQL-backed tests and extend `backend/tests/test_telegram_mtproto_a4_3.py` (plus focused existing test files where natural) to cover explicitly:

- private, group, supergroup active/inactive scope behavior;
- `manual_selected=true` with `scope_active=false` remains invisible;
- missing account_id; missing peer_id; malformed/non-scalar values; nonexistent account; no matching selection; wrong account; other-user active selection — all fail closed without cast errors;
- RetrievalService object/body FTS, trigram/title, representation-backed retrieval, and `provider=telegram` filter;
- SearchService relevance/newest/oldest behavior cannot bypass scope;
- ObjectQueryService provider/kind/date/status/label filters cannot bypass scope;
- RecentSourceService list/page, `get_inbox_eligible`, review-window list and count paths exclude inactive MTProto and restore on reactivation;
- query-driven ContextService excludes inactive MTProto and its representations;
- explicit inactive exact target through `ContextService.build_context(object_id=...)` remains readable;
- pinned/folder/graph automatic expansion excludes inactive MTProto while active counterparts work;
- GraphService/list_neighbors excludes inactive neighbors;
- actual conversation-member reconstruction/list path cannot expose inactive MTProto anchor/member and works for active counterparts;
- non-Telegram objects and legacy Telegram/Bot API rows without `metadata.transport == "mtproto"` keep prior behavior;
- toggling `scope_active` changes visibility only: same Object/Representation rows, no history/materialization/embedding/job/delete side effects;
- Alembic remains single head `0046`.

The shared helper introduced in `backend/app/domain/telegram_mtproto_visibility.py` should remain canonical unless a regression proves a concrete issue.

## Verification

Use only local development PostgreSQL:

`docker compose -f infra/compose.yaml -f infra/compose.dev.yaml up -d db`

From `backend`:

`alembic upgrade head`

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py tests/test_telegram_mtproto_a4_3.py`

Also run all existing focused regression files for every A4.3/A4.3R service touched: retrieval/search, object-query, recent-source/inbox, context, graph/workspace/tools, conversation-member reconstruction. Report the exact commands and results.

Then:

`alembic heads`

Run `ruff check` for every changed Python/test file from A4.3/A4.3R.

`git diff --check`

## Completion report

Push only to `review/telegram-depth-a4-folder-scope` and report:

- starting Architect bookkeeping HEAD;
- confirmation `a66fc167044ff3be7c1c207938b03367cea05dd8` remains in ancestry;
- A4.3R commit SHA(s) and final remote HEAD;
- changed files;
- exact retained-history fix;
- mapping of the acceptance bullets above to concrete test names;
- exact DB/alembic/pytest/focused-suite/ruff/diff-check results;
- confirmation no migration and head `0046`;
- confirmation exact inactive by-id context works while automatic inactive expansion remains hidden;
- confirmation reactivation exposes the same stored Object/Representation with no history/materialization/embedding/queue side effect;
- confirmation no A4.4/scheduler/bulk/UI/production work;
- `git status --short`;
- final marker exactly: `TELEGRAM_A4_3_CORRECTION_READY`.

Then STOP.
