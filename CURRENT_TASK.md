# Current task — Telegram Depth A4.3T final acceptance coverage

## Status

Telegram Depth A4.1 — ACCEPTED through `43944ca47b407889f87eb891b898a1c55097f7f0`.

Telegram Depth A4.2 — ACCEPTED through `5de67b6a6cf746c9af911ddfcc671833d1d3d62e`.

Telegram Depth A4.3 implementation candidate `a66fc167044ff3be7c1c207938b03367cea05dd8` introduced the shared query-time MTProto active-retrieval predicate.

Telegram Depth A4.3R correction `84efe88d31e10acd6852acf59a85636834582026` — RUNTIME FIX ACCEPTED / A4.3 PHASE ACCEPTANCE STILL PENDING TEST COVERAGE.

The retained-history defect is fixed correctly: `ContextService` alone may call `GraphService.get_neighbors(..., require_active_seed=False)` for an explicit retained-history target, while ordinary neighbor discovery keeps `require_active_seed=True` and inactive returned neighbors remain hidden.

A4.3 is NOT yet accepted because the dedicated A4.3 file still contains only five tests and does not explicitly exercise most of the acceptance matrix required by A4.3/A4.3R.

A4.3T is a TEST-ONLY final acceptance pass. Do NOT begin A4.4.

## Fixed branch and baseline

- Repository: `d-yacenko/secretary-prerelease`.
- Work only in `review/telegram-depth-a4-folder-scope`.
- Fetch and fast-forward only to current `origin/review/telegram-depth-a4-folder-scope`, including Architect bookkeeping.
- Preserve `a66fc167044ff3be7c1c207938b03367cea05dd8` and `84efe88d31e10acd6852acf59a85636834582026` in ancestry.
- No reset/rebase/squash/rewrite.
- Alembic remains `0046`; no migration.
- Production code is FROZEN unless a new required regression exposes a concrete defect. If so, make only the smallest same-phase fix and report it explicitly.

## Existing coverage to keep/reuse

The current five A4.3 tests already cover:

- canonical active/inactive toggle for one private peer;
- `manual_selected=true` does not restore visibility;
- same Object/Representation identity survives reactivation;
- one Retrieval/ObjectQuery/RecentSource happy-path visibility case;
- legacy Telegram row without `metadata.transport=mtproto` remains visible;
- one malformed metadata case;
- other-user isolation case;
- inactive graph neighbor hidden;
- explicit inactive ContextService target remains readable after A4.3R;
- ordinary `GraphService.get_neighbors(inactive_seed)` still rejects active discovery from an inactive seed.

Do not rewrite these merely to increase test count.

## Required missing regressions

Use real PostgreSQL-backed A4 MTProto rows. Prefer extending `backend/tests/test_telegram_mtproto_a4_3.py`; focused additions to the existing service test files are allowed when they better prove the public service/tool path.

### 1. All supported peer kinds

Exercise private, basic group and supergroup rows with matching Objects. For each kind prove:

- `scope_active=true` => active visibility;
- `scope_active=false` => hidden from active query;
- `manual_selected=true` while inactive does not restore visibility;
- reactivation returns the same Object id.

### 2. Complete fail-closed metadata/ownership matrix

Add explicit cases for A4 MTProto Objects with:

- missing `account_id`;
- missing `peer_id`;
- malformed/non-scalar `account_id`;
- malformed/non-scalar `peer_id`;
- syntactically valid but nonexistent account id;
- existing account with no matching peer selection;
- peer selection under a different account;
- active matching selection owned by another Secretary user.

Every case must be excluded without SQL cast/query error.

### 3. RetrievalService candidate families + SearchService facade

Use distinguishable content so each path is actually exercised, not merely the common final rank step.

Prove inactive exclusion and active re-entry for:

- body/object FTS or lexical candidate path;
- title trigram candidate path;
- Representation-backed candidate path;
- retrieval with `provider="telegram"` and `kind="chat_message"` filters.

Also exercise `SearchService` for its supported ordering modes (relevance/newest/oldest or the exact current API equivalents) and prove inactive MTProto rows cannot reappear through the facade.

### 4. ObjectQueryService filter combinations

Prove inactive MTProto exclusion when query uses the supported combinations that could otherwise bypass the base predicate, including:

- provider + kind;
- date/time bounds;
- status filter if supported;
- label filter if supported.

Use the actual current method signature; do not invent unsupported filters. Reactivation must return the same Object.

### 5. RecentSource / inbox review paths

Seed an inbox-eligible MTProto chat message and prove inactive exclusion / active restoration through the actual APIs:

- `list_recent` or `list_page`;
- `get_inbox_eligible`;
- `list_review_window`;
- `count_review_window`;
- newer/older review count helpers that are part of the current service API.

At least one non-MTProto chat provider/legacy Telegram row must remain unaffected.

### 6. Context automatic expansion + representation leakage

Beyond the existing graph-neighbor check, explicitly cover automatic expansion paths that exist in current ContextService:

- query-driven SearchService result;
- pinned reference expansion;
- folder-contained expansion if supported by existing fixtures/helpers.

Inactive MTProto automatic Objects and their Representation text must not appear. Active counterparts must work.

The explicit exact inactive `object_id` target must still include the retained target and its own retained Representation.

### 7. Conversation-member discovery

Use the actual conversation-member reconstruction/page function used by assistant/MCP. Prove:

- inactive MTProto anchor cannot be used as active conversation discovery;
- inactive MTProto member is not surfaced through reconstruction/window membership;
- active counterpart works.

Do not substitute `RecentSourceService` alone for this test.

### 8. No-side-effect reactivation

Capture before/after persisted state and prove toggling only `scope_active` for visibility does not cause:

- Object mutation/deletion;
- Representation mutation/deletion;
- new Job row/enqueue;
- history transport/materialization call;
- embedding/re-embedding call.

Use the lightest reliable instrumentation available in existing tests. Do not add production hooks only for testing.

## Acceptance principle

Passing old focused suites demonstrates compatibility but does NOT substitute for the explicit MTProto-scope regressions above. Every numbered section 1–8 must map to one or more concrete test names in the completion report.

If a required current service API does not support a named sub-filter/path, document that fact in the report and test the nearest actual supported API rather than inventing behavior.

## Verification

Use only local development PostgreSQL:

`docker compose -f infra/compose.yaml -f infra/compose.dev.yaml up -d db`

Wait for healthy.

From `backend`:

`alembic upgrade head`

Run:

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py tests/test_telegram_mtproto_a4_3.py`

Also rerun the existing focused regression suites for every production service exercised by A4.3/A4.3T: retrieval/search, object-query, recent-source/inbox, context, graph/tool/workspace, and conversation-member reconstruction. Report exact commands/files and results.

Then:

`alembic heads`

Run `ruff check` over all A4.3 production files and every modified/new test file.

Run:

`git diff --check`

## Completion report

Commit and push only to `review/telegram-depth-a4-folder-scope`. Do not merge to `main`.

Return:

- starting Architect bookkeeping HEAD;
- confirmation `a66fc167...` and `84efe88d...` remain in ancestry;
- A4.3T commit SHA(s);
- final remote HEAD;
- changed files;
- mapping sections 1–8 above -> concrete test names;
- any production defect found? If none, say `none`; if yes, exact minimal fix;
- exact DB startup/alembic/Telegram-suite/focused-suite/ruff/diff-check results;
- `alembic heads` result;
- confirmation no migration and head remains `0046`;
- confirmation explicit retained-history Context target still works;
- confirmation automatic inactive MTProto objects/representations cannot bypass through Search/ObjectQuery/RecentSource/Context/neighbor/conversation-member paths;
- confirmation reactivation returns the same stored Object/Representation with no history/materialization/embedding/job work;
- confirmation no A4.4/scheduler/bulk/UI/production work was started;
- `git status --short`;
- final marker exactly: `TELEGRAM_A4_3_FINAL_TESTS_READY`.

Then STOP.

## Production boundary

No production deployment, production migration, rollback, SSH, production Compose, runtime probing, credential changes, or provider-side Telegram mutation is authorized.
