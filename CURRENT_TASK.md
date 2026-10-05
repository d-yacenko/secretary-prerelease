# CURRENT_TASK

ACTIVE

## REL1D-HG2C3 — isolated bounded Mattermost author-display repair primitive

REL1D-HG2C2 is ARCHITECT SOURCE-ACCEPTED.

The next provider-specific source slice is Mattermost.

HG2C1 established that ordinary Mattermost history/backfill is unsuitable for controlled repair because it mutates ordinary sync/history state and does not revisit already-covered windows.

For HG2B1, however, legacy stored Mattermost Objects already carry stable `author_user_id` provenance. The missing field is the human `author_display_name`, which can be derived from the current Mattermost user profile contract without refetching historical posts.

This task therefore builds ONLY a metadata-only, profile-based repair primitive.

Do not refetch posts.
Do not call ordinary Mattermost sync/history.
Do not wire the repair to API/worker/CLI/ops/production.

Production/backend/client remain:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Alembic remains:

`0054 / 0054`

Human REL1D acceptance remains paused.

## Architectural contract

The primitive repairs only:

`metadata.author_display_name`

for legacy Mattermost chat Objects that already have a stored `author_user_id`.

It must reuse the EXACT HG2B1 human-display semantics already implemented in:

`backend/app/connectors/mattermost/normalize.py`

Those semantics are:

- non-empty profile `display_name` qualifies only when it is not equivalent to `username` after current collapse/casefold behavior;
- otherwise collapsed `first_name + last_name` qualifies only when BOTH are present;
- username alone does NOT qualify;
- nickname/email/single first/single last do NOT qualify;
- no channel/team/post title fallback;
- no arbitrary mention/name fallback.

Do not duplicate or subtly rewrite this logic.

If needed, expose a small public pure helper from `mattermost/normalize.py` and have BOTH normal sync and repair use the same helper, with no semantic change to HG2B1.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/rel1d_hg2_provider_repair_audit.md`
- `backend/app/connectors/mattermost/normalize.py`
- `backend/app/connectors/mattermost/transport.py`
- `backend/app/connectors/mattermost/credentials.py`
- `backend/app/connectors/mattermost/sync.py`
- `backend/app/connectors/mattermost/materialize.py`
- `backend/app/domain/role_import_participants.py`
- relevant Mattermost HG2B1/tests

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.
Do not move `production`.

## Preferred source shape

Add an isolated service, preferably:

`backend/app/services/mattermost_author_repair_service.py`

Add focused tests, preferably:

`backend/tests/test_rel1d_hg2c3_mattermost_author_repair.py`

A small pure-helper exposure/refactor in:

`backend/app/connectors/mattermost/normalize.py`

is allowed ONLY to ensure sync and repair share the exact HG2B1 human-display function.

Do not change the HG2B1 rules.

No other runtime source file should need semantic modification.

## Candidate contract

The batch method must take at least:

- `user_id`
- `account_id`
- optional caller-owned continuation cursor

Use deterministic ascending `Object.id` continuation or an equivalently deterministic explicit cursor.

Select/inspect only legacy rows for that user/account that are:

- `provider == "mattermost"`
- `kind == "chat_message"`
- not tombstoned/deleted
- metadata `account_id` exactly equals the requested account
- metadata `server_url` exactly equals the connected account's normalized server URL
- metadata has no non-empty `author_display_name`

A row is provider-repairable only when metadata has a non-empty string `author_user_id`.

Rows with missing/invalid author id are local invalid/provenance skips:
- no provider lookup for that row;
- no mutation;
- cursor still advances.

Respect hidden/passive-sync protection. Hidden Objects must not be mutated.

Already display-enriched rows must not be selected/repaired.

Do not use `author_username` as the human display.

## Repair method

For the selected bounded rows:

1. collect UNIQUE non-empty `author_user_id` values;
2. request current profiles only through the existing `MattermostTransport.get_users_by_ids(...)` primitive;
3. do not call any post/history/channel/team endpoint;
4. ignore returned profiles whose `id` was not requested;
5. require each profile id to exactly match the requested author id;
6. derive human display only through the shared HG2B1 helper;
7. if profile is missing:
   - leave row unchanged;
   - count profile missing;
8. if profile exists but yields no qualifying human display:
   - leave row unchanged;
   - count no-human-display;
9. if a qualifying display exists:
   - copy existing metadata;
   - set only `author_display_name`;
   - preserve `author_user_id`, `author_username`, channel/team/post/media/mention metadata and every unrelated value;
   - do NOT change title/body/occurred_at/deleted_at/external_id/status.

Do not route the row back through full `normalize_mattermost_post` or `MattermostObjectMaterializer.upsert_post` in this repair, because those paths can rewrite title/body/full metadata and are outside the narrow repair contract.

## Bounds

Hard bounds per call:

- candidate Object scan: maximum 100 rows;
- unique author ids requested: maximum 100;
- `get_users_by_ids(...)` transport invocation: at most ONE per call.

Current transport batches IDs internally at `MATTERMOST_USERS_IDS_BATCH_SIZE = 200`, so a repair call with at most 100 ids must remain within one provider HTTP profile-batch request in the current implementation.

The service must not call `get_users_by_ids` when there are zero valid author ids.

Return a structured summary including at minimum:

- candidates_scanned
- unique_author_ids
- provider_calls
- updated
- profile_missing
- no_human_display
- invalid_provenance
- hidden_skipped
- next_cursor
- exhausted

Clear equivalent names are acceptable.

## Account / transport / transaction isolation

Use the requested `MattermostAccount` only when it belongs to `user_id`.

Use the account's stored normalized server URL and decrypted token via the existing account-store/encryption contract.

A transport-factory injection for fake/local tests is required or strongly preferred. It may mirror the existing Mattermost sync snapshot/factory pattern.

The repair service must:

- perform no `commit()` internally;
- mutate no `MattermostAccount.sync_state`;
- mutate no history/backfill/edit-sweep watermark;
- enqueue no jobs;
- emit no notifications;
- perform no post write;
- perform no post/history fetch.

If a provider/config/auth/transient profile request fails, propagate the existing bounded connector error and let the caller transaction decide rollback.

If the service opens an owned `MattermostHttpTransport`, close it in the same safe lifecycle pattern as existing sync. Injected fake transport need not be closed unless the factory contract explicitly owns it.

## Required tests

Prove at minimum:

1. only Mattermost chat rows for the requested user/account/server and missing display are considered;
2. other user, other account, wrong server, other provider/kind, tombstoned/deleted, already-enriched and hidden rows are unchanged;
3. missing/blank `author_user_id` causes no provider request for that row and advances the cursor;
4. candidate scan is bounded at 100;
5. unique author ids are deduplicated and bounded at 100;
6. only one `get_users_by_ids` transport call occurs per repair call;
7. zero valid author ids causes zero provider calls;
8. provider return for unrequested user id is ignored;
9. missing profile leaves row unchanged;
10. username-only profile does not produce `author_display_name`;
11. display_name equivalent to username does not qualify unless both first+last provide the human display;
12. first-only and last-only do not qualify;
13. first+last qualifies;
14. distinct non-technical display_name qualifies;
15. valid display updates ONLY `author_display_name`;
16. existing `author_username` and unrelated/nested metadata are preserved;
17. title/body/occurred_at/deleted_at/external_id/status remain unchanged;
18. role-import participant becomes eligible only when valid display plus stored strong identity is present, and existing exact self-filtering still excludes own identity;
19. no sync_state/history/watermark fields change;
20. no jobs are enqueued and no commit occurs;
21. provider/config/auth/transient error propagates;
22. cursor advances past missing-profile/no-human-display/invalid rows so a bad row cannot pin one sweep;
23. existing HG2B1 Mattermost normalization tests remain green;
24. existing role-import participant tests remain green.

Use fake/local transport only. No live Mattermost.

## Required checks

Run at minimum:

- new HG2C3 focused tests;
- relevant HG2B1 Mattermost tests, including the enriched-profile same-Object test;
- `backend/tests/test_rel1d_role_import_participants.py`;
- directly affected Mattermost normalization/transport tests;
- Ruff on touched Python;
- `git diff --check`.

Record exact totals.

## Explicit non-goals

Do not:

- refetch historical posts;
- call `sync_account`;
- mutate sync/history/edit-sweep state;
- update titles/bodies/full normalized metadata;
- add API/worker/CLI/ops/recurring invocation;
- call live Mattermost;
- inspect or mutate production;
- add schema/migrations/dependencies;
- deploy backend;
- build/install client;
- start Gmail/Yandex/Teams repair tooling;
- select or move a production release SHA;
- start human REL1D acceptance.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG2C3` entry to `PROJECT_STATE.md` with:
   - implementation SHA;
   - changed files;
   - exact candidate/provenance contract;
   - exact 100-row / 100-author / one-profile-call bounds;
   - shared HG2B1 helper behavior;
   - explicit no post fetch/no sync-state/no job/no commit behavior;
   - exact test totals;
   - Ruff/diff-check result;
   - explicit no provider-production/deploy/schema action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2C3 implementation SHA;
   - source ready for Architect review;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - no rollout/repair/live provider call/next provider task without fresh Architect authorization.

3. commit + push to `main`.

4. STOP.

On blocker:

- record the exact bounded blocker;
- do not widen into post-history replay or normal sync;
- return HOLD;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
