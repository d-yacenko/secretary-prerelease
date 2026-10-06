# CURRENT_TASK

ACTIVE

## REL1D-HG2D5 — source-only fail-closed Mattermost one-batch repair canary harness

REL1D-HG2D4 is ARCHITECT ACCEPTED.

Production/backend runtime and production ref remain:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Alembic remains:

`0054 / 0054`

D4 aggregate evidence for Mattermost:

- `MATTERMOST_ACCOUNTS=1`
- `MATTERMOST_COARSE_CANDIDATES=2515`
- `MATTERMOST_LOCAL_REPAIRABLE=2515`
- `MATTERMOST_HIDDEN=0`
- `MATTERMOST_INVALID_PROVENANCE=0`
- `MATTERMOST_ALREADY_ENRICHED=102`
- `MATTERMOST_ACCOUNTS_WITH_LOCAL_REPAIRABLE=1`
- `MATTERMOST_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT=2515`

Mattermost is selected as the FIRST repair canary because HG2C3:
- mutates only `metadata.author_display_name`;
- never refetches posts;
- uses one `get_users_by_ids` batch for at most 100 unique authors;
- does not mutate sync/history/edit-sweep state;
- does not enqueue jobs;
- does not commit internally.

This task builds ONLY the production canary harness.

DO NOT run it against production in D5.
DO NOT call Mattermost.
DO NOT mutate production.

A future separate Architect task will authorize at most one live canary invocation after source review.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- `docs/rel1d_hg2_production_preflight_census.md`
- `ops/production/hg2_repair_preflight.py`
- `ops/production/remote_hg2_repair_preflight.py`
- `backend/app/services/mattermost_author_repair_service.py`
- `backend/app/connectors/mattermost/credentials.py`
- `backend/app/connectors/mattermost/transport.py`
- `backend/app/connectors/mattermost/normalize.py`
- `backend/app/domain/object_visibility.py`
- `backend/app/core/config.py`
- relevant HG2C3 tests

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE D5 task.

Do not move `production`.

## Required source shape

Prefer exactly:

- `ops/production/mattermost_hg2_repair_canary.py`
- `ops/production/remote_mattermost_hg2_repair_canary.py`
- `ops/production/tests/test_mattermost_hg2_repair_canary.py`

No backend runtime/test source change is authorized.
No migration/dependency/client/deploy-target change is authorized.

Pin exactly:

`PRODUCTION_SHA = "f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6"`

and:

`EXPECTED_ALEMBIC = "0054"`

Do not expose a broad arbitrary release/account/user/cursor CLI.

## Future live execution shape

The harness must be designed for one future invocation only.

The local entrypoint must:
- require canonical clean local repo;
- require `origin/production == PRODUCTION_SHA`;
- use the existing pinned `ops/production/target.json` host-key contract;
- stream the committed remote helper;
- reject remote stderr-dependent evidence;
- parse only a fixed aggregate protocol.

The remote helper must:
- require canonical production cwd/origin;
- require clean remote worktree;
- require remote HEAD and `origin/production` exactly `PRODUCTION_SHA`;
- require DB/API/worker running and DB healthy;
- require API health;
- require Alembic output to be exactly one non-empty line `0054 (head)`;
- execute the mutation child only inside the existing API container.

Do not use direct SQL from the local machine.
Do not use ad-hoc SSH outside the harness.

## Exact canary scope

The future live canary may invoke:

`MattermostAuthorRepairService.repair_author_display(..., cursor=None)`

EXACTLY ONCE.

No continuation cursor is allowed in the canary.
No loop is allowed.
No second service invocation is allowed.

Therefore the maximum source-service scope is:

- <=100 candidate Object rows;
- <=100 unique author ids;
- <=1 Mattermost `get_users_by_ids` provider call.

Do not widen the canary to all 2515 rows.

## Account gate

Inside the API-container child, before decrypting credentials or opening any provider transport:

1. open one SQLAlchemy session/transaction;
2. query Mattermost accounts;
3. require EXACTLY ONE account, matching D4's aggregate account count;
4. acquire a row lock on that account using PostgreSQL `FOR UPDATE NOWAIT` or an equivalently fail-closed non-waiting lock;
5. if account cardinality is not exactly one or the lock cannot be acquired:
   - zero provider calls;
   - zero commit;
   - blocked terminal.

Do not emit account/user/server/username/email ids or values.

## Candidate row lock gate

Before decrypting the Mattermost token or making a provider call:

- select the exact first page that HG2C3 can scan for this account:
  - matching user;
  - provider `mattermost`;
  - kind `chat_message`;
  - `deleted_at IS NULL`;
  - exact metadata account id;
  - exact normalized server URL;
  - missing/blank `author_display_name`;
  - ascending `Object.id`;
  - limit 100;
- acquire `FOR UPDATE NOWAIT` locks on those rows.

This pre-lock query intentionally mirrors the HG2C3 coarse page, including legacy `status='deleted'` rows if any; the service itself remains authoritative for hidden/invalid skips.

If there are zero coarse candidate rows:
- zero provider calls;
- zero commit;
- return a fixed sanitized NO_CANDIDATES terminal;
- do not invent a later page.

If any row lock cannot be acquired:
- zero provider calls;
- zero commit;
- blocked terminal.

Hold account/candidate locks until transaction completion.

Do not use `SKIP LOCKED`, because silently changing the first canary cohort is not allowed.

## Credential / provider boundary

Only after account and candidate locks are held:

- read `settings.secretary_credential_key`;
- construct encryption through the existing `MattermostAccountStore.build_encryption` contract;
- do not print/log the key or decrypted token.

Inject a GUARDED transport factory into `MattermostAuthorRepairService`.

The factory must construct the normal production `MattermostHttpTransport` from the service snapshot, but wrap it so the repair can invoke ONLY:

`get_users_by_ids(author_ids)`

The guard must:
- count provider calls before delegating;
- allow at most one `get_users_by_ids` call;
- reject any other provider method if invoked;
- expose no URL/token/profile payload in output;
- close the underlying owned HTTP transport in a `finally` path.

Do not call:
- `get_me`;
- channel/team/post/history methods;
- create/send methods;
- ordinary sync;
- any other provider.

## Service-result gate

After the ONE repair invocation returns, require all of:

- `1 <= candidates_scanned <= 100`;
- `1 <= unique_author_ids <= 100`;
- guarded provider call count == `provider_calls == 1`;
- `updated >= 0`;
- `profile_missing >= 0`;
- `no_human_display >= 0`;
- `invalid_provenance == 0`;
- `hidden_skipped == 0`;
- `updated + profile_missing + no_human_display == candidates_scanned`.

Because D4 observed zero hidden/invalid Mattermost rows, any hidden/invalid result during the canary is drift and must cause rollback/HOLD, not partial commit.

If `updated == 0`:
- rollback the transaction;
- `DB_COMMIT=0`;
- return fixed `NO_UPDATES` terminal;
- do not retry.

## Strict dirty-state gate before flush/commit

Before any flush/commit, inspect the SQLAlchemy unit-of-work.

Require:

- `session.new` empty;
- `session.deleted` empty;
- the locked Mattermost account is NOT dirty;
- no account `sync_state`, identity, credential, timestamp or other field is dirty;
- every dirty entity is an `Object`;
- dirty Object ids are a subset of the pre-locked candidate ids;
- number of dirty Objects equals `summary.updated`;
- for every dirty Object, the ONLY application attribute with history changes is `metadata_`;
- before/after metadata differs ONLY at `author_display_name`;
- new `author_display_name` is a non-empty string;
- prior `author_display_name` was absent or blank;
- every unrelated and nested metadata value is equal;
- title/body/provider/external_id/status/occurred_at/deleted_at and all other application fields remain unchanged before flush.

Do not treat normal SQLAlchemy/database-managed `updated_at` behavior caused by the Object UPDATE itself as an extra product mutation, but no harness/service code may explicitly write it.

Any dirty-state mismatch:
- rollback;
- zero DB commit;
- blocked terminal;
- no retry.

## Commit boundary

Only if:
- provider call count is exactly one;
- service result gate passes;
- `updated > 0`;
- strict dirty-state gate passes;

then:

1. flush once;
2. commit once.

No commit may occur before all gates pass.

On ANY exception before successful commit:
- rollback transaction;
- close guarded transport if opened;
- output only sanitized stage/class + aggregate call/commit facts;
- do not retry.

The harness itself must not call any sync/history/job/materializer path.

## Fixed output protocol

Success output must be identity-free and contain only fixed markers plus non-negative integer/boolean facts.

At minimum:

- `MM_CANARY_MARKER=started`
- `MM_CANARY_GUARDS=pass`
- `MM_CANARY_ACCOUNT_COUNT=1`
- `MM_CANARY_LOCKED_CANDIDATES=<n>`
- `MM_CANARY_SCANNED=<n>`
- `MM_CANARY_UNIQUE_AUTHOR_IDS=<n>`
- `MM_CANARY_PROVIDER_CALLS=1`
- `MM_CANARY_UPDATED=<n>`
- `MM_CANARY_PROFILE_MISSING=<n>`
- `MM_CANARY_NO_HUMAN_DISPLAY=<n>`
- `MM_CANARY_INVALID_PROVENANCE=0`
- `MM_CANARY_HIDDEN_SKIPPED=0`
- `MM_CANARY_DIRTY_OBJECTS=<n>`
- `MM_CANARY_DB_COMMIT=1`
- `MM_CANARY_TERMINAL=success`

Blocked/no-candidate/no-update outputs must:
- use only closed stage/classification names;
- include `MM_CANARY_PROVIDER_CALLS=<0|1>`;
- include `MM_CANARY_DB_COMMIT=0`;
- reveal no identities/provider response.

The local parser must reject:
- missing/extra/duplicate/reordered fields;
- negative/non-integer counts;
- success with provider calls !=1;
- success with DB commit !=1;
- success with updated <=0;
- UUID/email-like/free-form identity leakage;
- raw profile/provider output.

Do not print remote stderr.

## Source-level proof requirements

Tests/source inspection must prove the canary harness has no reachable path to:

- normal Mattermost sync;
- get/list posts;
- get/list channels or teams;
- get_me;
- create/send post;
- jobs/notifications;
- schema/migration;
- production ref move/deploy;
- more than one service call;
- more than one provider call;
- retry loop.

The only network provider operation allowed in the FUTURE live canary is one guarded `get_users_by_ids`.

D5 itself performs zero network provider operations.

## Required tests

Add focused tests proving at minimum:

1. wrong production SHA/ref/cwd/origin/worktree/Alembic fails closed;
2. multi-head Alembic fails closed;
3. wrong account cardinality blocks before credentials/provider;
4. account lock failure blocks before provider;
5. zero candidate rows returns NO_CANDIDATES, zero calls, zero commit;
6. candidate lock failure blocks before provider;
7. candidate lock query is bounded at 100 and uses NOWAIT/no SKIP LOCKED;
8. guarded transport allows exactly one `get_users_by_ids` and rejects any other method;
9. provider exception => rollback, zero commit, no retry;
10. summary provider_calls mismatch blocks;
11. hidden/invalid drift blocks and rolls back;
12. updated==0 returns NO_UPDATES and rolls back;
13. session.new/session.deleted non-empty blocks;
14. dirty MattermostAccount blocks;
15. dirty non-Object entity blocks;
16. dirty Object outside locked page blocks;
17. dirty-object count != summary.updated blocks;
18. non-metadata attribute mutation blocks;
19. metadata mutation of any key other than `author_display_name` blocks;
20. valid metadata-only mutation passes dirty gate;
21. success flushes/commits exactly once and only after all gates;
22. fixed output parser rejects identity leakage and malformed protocols;
23. source proof shows no sync/posts/jobs/retry path;
24. existing HG2C3 service tests remain green;
25. D3/D3.1 preflight tests remain green.

Use fake/local provider transport only in tests. No live Mattermost.

## Required checks

Run at minimum:

- `python3 -m pytest -q ops/production/tests/test_mattermost_hg2_repair_canary.py`
- `python3 -m pytest -q ops/production/tests/test_hg2_repair_preflight.py`
- the existing focused HG2C3 Mattermost repair test file;
- Ruff on the three new files;
- `git diff --check`.

Record exact totals.

## Explicit non-goals

Do not:

- execute the canary against production;
- connect by SSH in D5;
- query production DB in D5;
- call Mattermost in D5;
- mutate production;
- repair more than one batch in future harness design;
- add continuation/loop/all-pages behavior;
- run normal sync/history;
- change HG2C3 service;
- change backend runtime;
- change schema/migrations/dependencies;
- change production ref/runtime;
- build/install client;
- start human REL1D acceptance;
- design Teams/Gmail/Telegram/Yandex execution harnesses yet.

## Completion protocol

On success:

1. append compact factual `REL1D-HG2D5` entry to `PROJECT_STATE.md` with:
   - implementation SHA;
   - exact new files;
   - pinned production SHA/Alembic;
   - one-account/one-batch/<=100/one-provider-call contract;
   - NOWAIT account/candidate locking;
   - guarded transport contract;
   - strict dirty-state/rollback-before-commit contract;
   - exact tests/Ruff/diff results;
   - explicit no SSH/production/provider/mutation action;
2. replace `CURRENT_TASK.md` with HOLD stating:
   - D5 harness source SHA;
   - harness ready for Architect review;
   - production remains `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`;
   - Alembic remains `0054 / 0054`;
   - no live Mattermost canary/provider call/repair without fresh Architect authorization;
3. commit + push to `main`;
4. STOP.

On blocker:
- record exact bounded source/test blocker;
- do not widen scope;
- HOLD;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
