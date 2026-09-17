# Current task — Telegram Depth A4.3U remaining acceptance gaps

## Status

- Telegram A4.2: ACCEPTED through `5de67b6a6cf746c9af911ddfcc671833d1d3d62e`.
- Telegram A4.3 candidate `a66fc167044ff3be7c1c207938b03367cea05dd8`: implementation direction retained.
- Telegram A4.3R `84efe88d31e10acd6852acf59a85636834582026`: retained-history runtime fix accepted.
- Telegram A4.3T candidate `d9007c2d5a717d26428df8056b3d6d2734fd99dc`: direct child of Architect bookkeeping `cdd7a53a6c67f9d5317a2e5160a6a4f31f4d1166`; code/test direction valid, acceptance still pending a small explicit regression set.
- `d9007c2...` added peer-kind, metadata matrix, Retrieval/Search, ObjectQuery/RecentSource, and conversation-anchor coverage. It also exposed/fixed one minimal production defect in `conversation_member_read.py`: `NotFoundError` now uses the canonical `NotFoundError("object", object_id)` constructor.
- A4.3 is NOT yet accepted.
- A4.3U is TEST-FOCUSED final remaining acceptance work only. Do NOT begin A4.4.

## Fixed branch and baseline

- Repository: `d-yacenko/secretary-prerelease`.
- Work only in `review/telegram-depth-a4-folder-scope`.
- Fetch and fast-forward only to current `origin/review/telegram-depth-a4-folder-scope`, including Architect bookkeeping.
- Preserve in ancestry: `a66fc167...`, `84efe88d...`, and `d9007c2...`.
- No reset/rebase/squash/rewrite.
- Alembic remains `0046`; no migration.
- Production code is FROZEN unless one of the remaining tests exposes a concrete A4.3 defect. Any such fix must be minimal and reported exactly.

## Already adequate — do not rewrite

Keep/reuse the existing A4.3 tests for:

- private/group/supergroup active -> inactive -> reactivated visibility;
- `manual_selected=true` not granting visibility;
- same Object/Representation identity across visibility toggles;
- missing account/peer metadata, malformed scalar shapes, nonexistent account/peer, and other-user isolation currently covered by the metadata matrix;
- legacy Telegram row without `metadata.transport=mtproto` remaining visible;
- body/representation retrieval and Search facade baseline;
- provider/kind/state/date ObjectQuery baseline;
- list-page/get-inbox/list-review RecentSource baseline;
- query-driven Context baseline;
- inactive explicit conversation anchor rejection and active anchor success;
- inactive graph neighbor hiding;
- explicit inactive retained-history Context target remaining readable.

## Remaining required regressions

### 1. Same-user wrong-account selection isolation

The current metadata matrix uses foreign/other-user accounts for its "different account" cases. Add one explicit same-Secretary-user case:

- create two MTProto accounts owned by the same Secretary `user_id`;
- Object metadata points to account A + peer X;
- the active peer-X selection exists only under account B;
- Object must remain hidden;
- adding/activating the matching selection under account A restores visibility.

This proves account identity is part of the scope key, not only user+peer.

### 2. Isolate the title-trigram candidate + filtered retrieval + all Search sorts while inactive

Strengthen the retrieval test so it proves the title trigram branch rather than an exact title/body FTS match. Use a fuzzy/misspelled title query that is expected to qualify through the existing trigram behavior but not exact FTS wording.

Also explicitly prove:

- `RetrievalService.retrieve(..., provider="telegram", kind="chat_message")` excludes the inactive Object;
- `SearchService` with each supported sort used by the current API (`relevance`, `newest`, `oldest`) excludes the inactive Object, not only the default sort;
- reactivation restores the same Object id.

Do not change Retrieval/Search production code unless the regression exposes a real defect.

### 3. ObjectQuery `statuses` and `label_ids`

The current `ObjectQueryService.query()` supports both `statuses` and `label_ids`; they were not covered by `d9007c2...`.

Add an MTProto Object that legitimately matches:

- a non-empty `statuses` filter; and
- an active label via the normal `labeled_with` path and `label_ids` filter.

For each filter (or one combined test), prove:

- active scope => same Object returned;
- `scope_active=false` => hidden;
- reactivation => same Object returned.

Use normal label service/graph helpers where practical; do not bypass label invariants by inventing an unsupported object shape.

### 4. RecentSource review count paths

The current test covers `list_page`, `get_inbox_eligible`, and `list_review_window` but not the count helpers.

Against one inbox-eligible MTProto chat message, prove active/inactive/reactivated behavior for the current APIs:

- `count_review_window`;
- `count_older_in_review_window`;
- `count_newer_in_review_window`.

Use stable anchor/snapshot tuples so the expected count change is deterministic. Reactivation must restore the previous count.

### 5. Context pinned + folder-contained expansion and representation leakage

The existing test covers graph-neighbor and query-driven paths, but not the explicit pinned/folder automatic expansion paths required by A4.3.

Add focused ContextService regressions using existing repository conventions/helpers:

- an inactive MTProto Object referenced as user-pinned context is NOT automatically added;
- a matching active Object IS added;
- an inactive MTProto Object contained in a folder is NOT automatically added through folder expansion;
- a matching active contained Object IS added;
- give the inactive automatic Object a unique Representation text and assert that text is absent from resulting context;
- explicit exact inactive target behavior remains unchanged: the target itself and its own retained Representation remain readable.

Do not weaken the shared visibility predicate or the A4.3R explicit-target exception.

### 6. Conversation-member inactive-member bypass with an active anchor

`d9007c2...` proves an inactive MTProto anchor is rejected, but does not prove an inactive member cannot leak when reconstruction starts from an otherwise active/visible anchor.

Add an actual `list_conversation_members_page` / reconstruction regression where the active visible anchor can form the same presentation conversation with another candidate member, but that candidate member is an inactive MTProto Object. A practical shape is allowed to use a legacy/non-MTProto Telegram anchor with the same conversation grouping key if two MTProto messages cannot differ in scope for the same durable peer.

Assert:

- inactive MTProto member is absent;
- active/legacy visible anchor remains usable;
- after activating the matching durable peer scope, the same MTProto member may participate according to normal conversation grouping.

Do not test only RecentSource as a proxy.

### 7. No-side-effect visibility toggle

Add one explicit regression around the real read paths that snapshots persistent state before and after `scope_active` false/true transitions and active reads.

Prove:

- same Object row/id/body/metadata/timestamps;
- same Representation row/id/text;
- neither row deleted;
- no new Job row/enqueue appears;
- no Telegram history/materialization call occurs;
- no embedding/re-embedding call occurs.

Use lightweight existing test instrumentation/monkeypatching. It is acceptable to patch history/materialization/embedding methods to raise if called, provided those patches target real existing methods and no production hooks are added solely for testing.

## Acceptance rule

A4.3U is complete only when sections 1–7 above each map to one or more concrete test names. Passing unrelated old focused suites is compatibility evidence, not a substitute.

Do not add new scope requirements beyond these remaining gaps.

## Verification

Use only local development PostgreSQL:

`docker compose -f infra/compose.yaml -f infra/compose.dev.yaml up -d db`

Wait for healthy.

From `backend`:

`alembic upgrade head`

Run the complete Telegram suite:

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py tests/test_telegram_mtproto_a4_3.py`

Also rerun the existing focused regression suites for the A4.3 production surfaces: retrieval/search, object query/labels, recent-source/inbox review, context, graph/tools/workspace, and conversation-member reconstruction. Report exact test files/commands and results.

Then:

`alembic heads`

Run `ruff check` over all A4.3 production files plus every modified/new test file.

Run:

`git diff --check`

## Completion report

Commit and push only to `review/telegram-depth-a4-folder-scope`.

Return:

- starting Architect bookkeeping HEAD;
- confirmation `a66fc167...`, `84efe88d...`, `d9007c2...` remain in ancestry;
- A4.3U commit SHA(s);
- final remote HEAD;
- changed files;
- mapping sections 1–7 -> concrete test names;
- production defect found? `none` or exact minimal fix;
- exact DB startup/alembic/Telegram-suite/focused-suite/ruff/diff-check results;
- `alembic heads` result;
- confirmation no migration and head remains `0046`;
- confirmation retained-history exact target remains readable;
- confirmation no active-read bypass remains through Retrieval/Search/ObjectQuery/RecentSource/Context/neighbor/conversation-member paths covered above;
- confirmation visibility reactivation returns the same persisted Object/Representation with no history/materialization/embedding/job side effect;
- confirmation no A4.4/scheduler/bulk/UI/production work started;
- `git status --short`;
- final marker exactly: `TELEGRAM_A4_3_REMAINING_TESTS_READY`.

Then STOP.

## Production boundary

No production deployment, production migration, rollback, SSH, production Compose, runtime probing, credential changes, or provider-side Telegram mutation is authorized.
