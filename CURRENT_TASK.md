# Current task — Telegram Depth A4.3 active retrieval-scope enforcement

## Status

Telegram Depth A4.1 — ACCEPTED through `43944ca47b407889f87eb891b898a1c55097f7f0`.

Telegram Depth A4.2 — ACCEPTED through final SHA `5de67b6a6cf746c9af911ddfcc671833d1d3d62e` on `review/telegram-depth-a4-folder-scope`.

A4.2 established the canonical durable peer state in `telegram_mtproto_chat_selections`: `manual_selected` is legacy compatibility, while `scope_active` is the A4 dynamic Telegram-folder scope gate. A4.2 also reuses the A3 history engine for private/group/supergroup peers and retains imported history/cursors when a peer becomes inactive.

Telegram Depth A4.3 — ACTIVE / IMPLEMENTATION AUTHORIZED.

A4.3 enforces `scope_active` at active read/retrieval time. A peer leaving the configured Telegram folders or becoming muted must immediately disappear from normal Secretary discovery/retrieval surfaces, while its already imported Objects/Representations remain stored. Re-entry must make those same stored Objects retrievable again without re-import, re-embedding, or object mutation.

Do NOT begin scheduler/bulk synchronization. That is a later phase.

## Fixed branch and baseline

- Repository: `d-yacenko/secretary-prerelease`.
- Work only in the existing review branch/worktree: `review/telegram-depth-a4-folder-scope`.
- Required accepted code baseline is A4.2 final SHA `5de67b6a6cf746c9af911ddfcc671833d1d3d62e` plus Architect bookkeeping commits already pushed to the review branch.
- Exact accepted A3 SHA `4777c32deb055f5024f3dbced125b4dd6db97e85` must remain in ancestry.
- Fetch and fast-forward only to current `origin/review/telegram-depth-a4-folder-scope` before implementation.
- Do not rebase or rewrite accepted commits.
- Alembic head remains `0046`; A4.3 requires NO schema migration.

## Canonical visibility rule

The authoritative dynamic-read gate is the existing durable `telegram_mtproto_chat_selections.scope_active` flag.

A stored Object is an A4 MTProto Telegram object only when it is the materialized Telegram message shape, including:

- `provider == "telegram"`;
- `kind == "chat_message"`;
- `metadata.transport == "mtproto"`.

For such an MTProto Object to participate in ACTIVE discovery/retrieval, there must be a matching durable row where:

- the Telegram MTProto account belongs to the same Secretary `user_id` as the Object;
- Object `metadata.account_id` matches the account id;
- Object `metadata.peer_id` matches the durable peer id;
- `telegram_mtproto_chat_selections.scope_active = true`.

`manual_selected` MUST NOT grant retrieval visibility. It is irrelevant to A4 active retrieval.

For MTProto Objects, missing/malformed `account_id`, missing/malformed `peer_id`, missing account/selection row, wrong-user account association, or inactive durable row must fail closed from active retrieval.

Do not perform unsafe JSON-to-UUID/bigint casts that can make a malformed metadata value crash a query. String/text comparison against canonical database ids is acceptable and preferred if it preserves fail-closed behavior.

Objects that are NOT A4 MTProto messages are unaffected by this new rule. In particular, do not accidentally hide legacy Telegram/Bot API objects merely because their provider is `telegram`; the `metadata.transport == "mtproto"` discriminator matters.

## Architectural implementation

Create one shared/canonical implementation of the Telegram MTProto active-retrieval predicate rather than hand-copying subtly different rules into each service.

It is acceptable for the shared implementation to expose both:

- a SQLAlchemy predicate/helper for ORM queries; and
- a raw-SQL fragment/helper for `RetrievalService`, whose candidate branches currently use textual SQL.

Both forms MUST encode the same semantics above and be regression-tested against each other through service behavior.

Do NOT add an `active` flag to every Telegram Object. Do NOT rewrite stored Objects when scope changes. The query-time durable scope row is canonical.

## Active-read surfaces that MUST enforce the gate

### 1. RetrievalService / SearchService

All lexical/FTS/trigram/representation candidate branches in `RetrievalService` must exclude inactive MTProto Telegram Objects before they become candidates.

Because `SearchService` delegates to `RetrievalService`, normal relevance/newest/oldest search must inherit the same gate. A caller specifying `provider=telegram` must not bypass it.

### 2. ObjectQueryService / `query_objects`

Structured object queries used by assistant/MCP must apply the same active gate. Provider/kind/date/status/label filters must not make an inactive MTProto object visible.

### 3. RecentSourceService / inbox review

`RecentSourceService` active inbox/feed eligibility must apply the same scope gate so a peer that leaves scope or becomes muted cannot continue appearing in recent-source/inbox-review discovery.

This includes the frozen review-window/count paths because they all derive from the service eligibility predicate.

### 4. ContextService automatic expansion

Query-driven ContextService retrieval already passes through SearchService, but automatic context expansion can also add pinned/contained/graph-neighbor Objects directly.

Apply the active Telegram scope gate to automatically discovered/expanded Objects so an inactive MTProto Telegram message cannot leak into assistant context as a pinned/folder/neighbor expansion.

The explicit target Object supplied by an exact `object_id` is different: retained imported history is intentionally not deleted. A direct, explicit by-id target may remain readable/auditable. Do not turn A4.3 into a physical access-control/delete mechanism.

Representations belonging to an inactive automatically discovered MTProto Object must likewise not be added to context.

### 5. Assistant/MCP neighbor discovery

`list_neighbors` is an active discovery tool. It must not return inactive MTProto Telegram neighbor Objects. Prefer enforcing the shared predicate before/inside the query so filtering does not accidentally create a cross-user leak.

Direct `get_object(object_id)` remains intentionally unchanged for exact explicit historical access.

### 6. Conversation-member discovery

If `list_conversation_members` can be called for a Telegram MTProto conversation, inactive MTProto members/conversations must not become an assistant/MCP discovery bypass. Apply the same active rule to the seed/member read path where needed.

Do not redesign conversation stacking; make only the minimal visibility integration.

## Reactivation semantics

Changing the durable row from `scope_active=false` back to `scope_active=true` must make already stored matching Objects visible again immediately on the next read.

Reactivation MUST NOT require or trigger:

- Telegram history fetch;
- materialization/upsert;
- Object update;
- Representation rewrite;
- embedding/re-embedding job;
- queue/scheduler activity.

The Object id, external id, body, metadata, timestamps and representations remain the same.

## Deliberate boundaries

Do NOT implement in A4.3:

- recurring Telegram scheduler/job registration;
- automatic/bulk `sync all active peers`;
- new history fetching;
- provider-side Telegram mutations;
- physical purge/delete of imported messages;
- rewriting Object state/status/deleted_at to encode Telegram scope;
- mass Object metadata updates;
- embedding or representation invalidation on scope transitions;
- UI/Flutter changes;
- removal of legacy A2/A3 endpoints;
- merge to `main`;
- production deployment or production migrations.

A4.4 or later will address automatic synchronization only after active-read semantics are accepted.

## Required tests

Prefer a dedicated `backend/tests/test_telegram_mtproto_a4_3.py` plus focused additions to existing retrieval/context/inbox/tool tests where that is the natural home.

Use real PostgreSQL-backed rows for the core scope behavior. Cover at minimum:

1. **Canonical active predicate**
   - active MTProto row is retrievable;
   - same Object becomes non-retrievable when only `scope_active` changes to false;
   - setting `manual_selected=true` while `scope_active=false` does NOT restore visibility;
   - restoring `scope_active=true` restores the SAME Object without changing the Object row or its representations.

2. **Supported peer kinds**
   - private, group and supergroup MTProto Objects obey the same active gate.

3. **Fail closed metadata/ownership**
   - MTProto Object with missing account id, missing peer id, malformed values, missing selection, or mismatched account/user is excluded without query error;
   - another user's active selection cannot make the Object visible.

4. **Legacy/non-MTProto compatibility**
   - non-Telegram Objects are unchanged;
   - legacy Telegram/Bot API Object without `metadata.transport == "mtproto"` remains governed by its previous visibility rules.

5. **Retrieval/Search**
   - FTS/lexical candidate discovery excludes inactive MTProto Object;
   - representation-backed retrieval also excludes it;
   - `provider="telegram"` filter does not bypass the gate;
   - reactivation restores it with the same Object id.

6. **Structured query**
   - `ObjectQueryService` / `query_objects` excludes inactive MTProto Object and returns it after reactivation;
   - kind/provider/date filters cannot bypass the gate.

7. **Recent source / inbox**
   - inactive MTProto chat message is absent from `RecentSourceService` list/count/review eligibility;
   - reactivation restores it without rematerialization;
   - non-MTProto chat providers remain unaffected.

8. **Context expansion**
   - query-driven context does not include inactive MTProto Object;
   - inactive MTProto Object linked/pinned/contained as an automatically expanded neighbor is not included;
   - direct exact `object_id` target remains readable as retained history;
   - inactive object's representations are not leaked through automatic context expansion.

9. **Neighbor/conversation tool bypasses**
   - `list_neighbors` does not return inactive MTProto neighbors;
   - `list_conversation_members` cannot surface an inactive MTProto conversation/member as an active discovery bypass;
   - active counterparts still work.

10. **No side effects**
   - toggling scope visibility causes no history transport call, no Job enqueue, no Object/Representation mutation and no deletion;
   - Alembic remains single head `0046`.

Preserve all existing A1/A2/A3/A4.1/A4.2 tests.

## Required verification

Use only the local development PostgreSQL:

`docker compose -f infra/compose.yaml -f infra/compose.dev.yaml up -d db`

Wait until healthy.

From `backend` run:

`alembic upgrade head`

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py tests/test_telegram_mtproto_a4_3.py`

Also run the existing focused suites for every active-read service changed by this task (retrieval/search, object query, recent source/inbox, context, graph/tool/conversation-member as applicable). Do not silently skip an existing relevant suite because it is not named in the Telegram-only command above; report the exact additional test files selected and results.

Run:

`alembic heads`

Run `ruff check` over every changed Python file and every new/modified A4.3 test file.

Run:

`git diff --check`

## Completion report

Commit and push only to `review/telegram-depth-a4-folder-scope`. Do not merge to `main`.

Return:

- starting branch HEAD after Architect bookkeeping fast-forward;
- A4.3 implementation commit SHA(s);
- final pushed branch HEAD;
- changed files;
- confirmation no migration and Alembic remains `0046`;
- exact local DB startup + `alembic upgrade head` result;
- exact Telegram suite command/result;
- exact additional active-read regression suites and results;
- exact ruff and `git diff --check` results;
- location/design of the shared MTProto active-retrieval predicate;
- explicit evidence that Retrieval/Search, ObjectQuery, RecentSource, Context automatic expansion, neighbor discovery and conversation-member discovery cannot bypass inactive scope;
- confirmation direct exact by-id retained-history access remains available;
- confirmation reactivation exposes the same stored Object without history fetch, object/representation mutation, embedding job or queue work;
- confirmation `manual_selected` alone does not grant retrieval visibility;
- confirmation no scheduler/bulk sync/UI/production/next-phase work was started;
- `git status --short` for the review worktree;
- final marker exactly: `TELEGRAM_A4_3_RETRIEVAL_SCOPE_READY`.

Then STOP. Do not begin A4.4.

## Production boundary

No production deployment, production migration application, rollback, SSH, production Compose, runtime probing, credential changes, or provider-side Telegram mutation is authorized.
