# CURRENT_TASK

ACTIVE

## REL1D-HG2C5 — isolated bounded Gmail named-recipient repair primitive

REL1D-HG2C4 is ARCHITECT SOURCE-ACCEPTED.

HG2C1 established that ordinary Gmail sync/history is unsuitable for legacy HG2B2 repair because:

- already-stored Gmail external ids are skipped rather than refetched;
- ordinary history/backfill mutates Gmail sync state;
- some legacy rows do not contain enough account provenance for safe refetch.

HG2B2 already defines the accepted additive recipient contract:

- legacy `metadata.recipients` and `metadata.cc` remain unchanged;
- named To recipients live in additive `metadata.to_participants`;
- named Cc recipients live in additive `metadata.cc_participants`;
- each structured item is exactly `{address, display_name}`;
- bare addresses without a human display do not create structured participants;
- current Gmail structured parsing uses stdlib multi-address parsing and preserves the pre-existing bare-recipient behavior separately.

This task builds ONLY an isolated source primitive that refetches an exact stored Gmail message and fills MISSING HG2B2 structured recipient fields.

Do not run Gmail sync/history.
Do not acquire/refresh OAuth tokens inside this primitive.
Do not wire to API/worker/CLI/ops/production.

Production/backend/client remain:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Alembic remains:

`0054 / 0054`

Human REL1D acceptance remains paused.

## Architectural contract

The repair may add only:

- `metadata.to_participants`
- `metadata.cc_participants`

It must NOT rewrite or remove:

- `recipients`
- `cc`
- `sender`
- `headers`
- `subject`
- `thread_id`
- `timestamp`
- `labels`
- `source_account_email`
- any unrelated metadata
- title/body/occurred_at/deleted_at/status/external_id

The repair is additive-only:

- if a structured key already exists on the stored Object, preserve its current value exactly and do not overwrite it;
- if a structured key is absent and current provider headers yield one or more qualifying named participants, add that key;
- if current provider headers yield no qualifying named participant for a missing key, leave that key absent;
- do not add empty lists merely as a completion marker.

A caller-owned cursor provides one-time sweep progress. Do not create a persistent repair/version marker in message metadata.

## Shared HG2B2 parser requirement

Do not independently reimplement To/Cc parsing in the repair service.

Expose/reuse a small pure helper from:

`backend/app/connectors/google/gmail_normalize.py`

so BOTH ordinary Gmail normalization and HG2C5 use the exact same HG2B2 structured recipient parser.

A preferred shape is a public helper that accepts the Gmail provider message or provider headers and returns the current To/Cc structured participants.

The helper refactor must not change:

- `_parse_addresses` legacy bare-list semantics;
- normal Gmail message title/body/timestamp/attachments;
- HG2B2 structured parsing behavior.

The repair service should not need to parse/decode body content or attachments.

## Auth/transaction boundary

Do NOT call `GoogleTokenManager.get_valid_access_token` from the repair primitive.

That path can refresh credentials and uses transaction boundaries outside this narrow source service.

The repair method must receive from its caller:

- a ready Gmail transport;
- a ready access token string.

The future explicitly authorized orchestration layer will own OAuth refresh and transaction boundaries.

The source primitive must neither persist nor log the access token.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/rel1d_hg2_provider_repair_audit.md`
- `backend/app/connectors/google/gmail_normalize.py`
- `backend/app/connectors/google/gmail_transport.py`
- `backend/app/connectors/google/gmail_sync.py`
- `backend/app/connectors/google/credentials.py`
- `backend/app/connectors/google/api_errors.py`
- `backend/app/connectors/google/errors.py`
- `backend/app/domain/role_import_participants.py`
- `backend/tests/test_rel1d_hg2b2_mail_recipients.py`
- directly relevant Gmail sync/history tests

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.
Do not move `production`.

## Preferred source shape

Add an isolated service, preferably:

`backend/app/services/gmail_recipient_repair_service.py`

Add focused tests, preferably:

`backend/tests/test_rel1d_hg2c5_gmail_recipient_repair.py`

A small pure-helper exposure/refactor in `gmail_normalize.py` is allowed and expected solely to share the HG2B2 structured parser.

No sync/transport/account schema semantic change is expected.

## Candidate / provenance contract

The batch method must take at least:

- `user_id`
- `account_id`
- ready Gmail transport
- ready access token
- optional caller-owned continuation cursor

Use deterministic ascending `Object.id` continuation or an equivalently explicit deterministic cursor.

A row may be considered for this account only when it is:

- owned by `user_id`;
- `provider == "gmail"`;
- `kind == "email"`;
- not tombstoned/deleted;
- metadata `source_account_email` is a non-empty string EXACTLY equal to the connected `GoogleAccount.email`.

Rows without `source_account_email`, or whose source account email does not match the requested account, MUST NOT be attributed to this account and MUST NOT be refetched by this repair.

This preserves the HG2C1 finding that missing account provenance is:

`NOT_REPAIRABLE_FROM_CURRENT_PROVENANCE`

A row is provider-refetchable only when:

- metadata `message_id` is a non-empty string;
- `Object.external_id` is a non-empty string;
- `Object.external_id == metadata.message_id`.

If message id provenance is missing or mismatched:

- no provider call;
- no mutation;
- advance caller cursor.

A row needs a provider call only if at least one of these keys is absent:

- `to_participants`
- `cc_participants`

If both keys already exist, do not call Gmail; leave the row unchanged and advance cursor.

Respect hidden/passive-sync protection. Hidden Objects must not mutate.

## Bounds

Hard bounds per call:

- candidate Object scan: maximum 100 rows;
- provider `get_message` calls: maximum 20.

No list/history call is allowed.

Stop cleanly at provider-call bound and return the last fully inspected Object cursor.

Return a structured summary including at minimum:

- candidates_scanned
- provider_calls
- updated
- already_structured
- invalid_provenance
- provider_missing
- message_mismatch
- no_named_recipients
- hidden_skipped
- next_cursor
- exhausted

Equivalent clearer names are acceptable.

## Fetch contract

For each provider-refetchable row needing repair:

1. call ONLY:
   `transport.get_message(access_token, "me", message_id)`;
2. do not call list-message, history, attachment, send or profile endpoints;
3. require returned payload to be a dict;
4. require returned provider `id` to exactly equal stored `message_id`;
5. use only the shared HG2B2 To/Cc structured-recipient helper;
6. do not parse recipient names from stored body/subject or old bare recipient arrays;
7. do not use stored bare `recipients` / `cc` to synthesize human names;
8. do not refetch attachments.

### Explicit 404 handling

If `get_message` raises `GoogleApiError` with `status_code == 404`:

- count `provider_missing`;
- leave Object unchanged;
- advance cursor;
- continue within the batch.

Any other Google/provider/config/OAuth/transient/rate-limit error must propagate to the caller.

Do not swallow non-404 errors.

## Mutation contract

Given fetched structured participants:

- start from a copy of existing metadata;
- if `to_participants` is ABSENT and fetched To named-participant list is non-empty, add exactly the fetched structured list;
- if `cc_participants` is ABSENT and fetched Cc named-participant list is non-empty, add exactly the fetched structured list;
- preserve an existing `to_participants` value exactly, even if provider now differs;
- preserve an existing `cc_participants` value exactly, even if provider now differs;
- if neither missing key receives a non-empty structured list, do not assign new metadata and count a no-named/no-change outcome;
- when at least one missing key is added, assign the copied metadata back to the SAME Object and increment updated once.

Do not run the Object through normal Gmail materialization/sync creation logic.
Do not enqueue embed work.

## Transaction / state isolation

The service must:

- perform no `commit()`;
- perform no `rollback()`;
- mutate no `GoogleAccount.gmail_sync_state`;
- mutate no access/refresh token or token expiry;
- call no OAuth/token manager;
- enqueue no jobs;
- emit no notifications;
- create no attachments;
- change no ordinary Gmail history/backfill state.

Caller owns rollback on propagated error.

## Required tests

Prove at minimum:

1. only Gmail email rows for requested user and exact `source_account_email` are considered;
2. other user, other provider/kind, other source-account email, tombstoned/deleted and hidden rows are unchanged;
3. a row with missing `source_account_email` gets zero provider calls;
4. missing/blank/mismatched metadata message id or external id gets zero provider calls;
5. rows with BOTH structured keys already present get zero provider calls and preserve values exactly;
6. candidate scan is bounded at 100;
7. provider `get_message` calls are bounded at 20;
8. cursor advances past invalid/already-structured/404/no-name/mismatch rows so a bad row cannot pin a sweep;
9. fake transport proves only `get_message` is used;
10. exact Google API 404 is counted as provider-missing and does not mutate;
11. non-404 Google API/OAuth/config/transient errors propagate and service does not commit/rollback;
12. returned non-dict payload does not mutate;
13. returned provider message id mismatch does not mutate;
14. quoted commas and Unicode names produce the same HG2B2 structured participants as ordinary Gmail normalization;
15. bare To/Cc addresses add no structured entries;
16. valid fetched To names fill a missing `to_participants` only;
17. valid fetched Cc names fill a missing `cc_participants` only;
18. when both are missing and both have named participants, both are added in one Object metadata update;
19. pre-existing structured To or Cc is never overwritten;
20. legacy `recipients` and `cc` arrays remain exactly unchanged, including Gmail's existing comma-split quirks;
21. sender, headers, subject, thread id, timestamp, labels, source account and unrelated/nested metadata remain unchanged;
22. title/body/occurred_at/deleted_at/status/external_id remain unchanged;
23. role-import sees repaired named participants and exact self filtering still removes the connected account identity;
24. no Gmail sync/history state changes;
25. no token fields change;
26. no jobs/attachments are created;
27. source inspection/test fake proves no `GoogleTokenManager`, OAuth refresh, Gmail sync/history/list/attachment/send path is introduced;
28. existing HG2B2 mail-recipient tests remain green;
29. relevant role-import participant tests remain green.

Use fake/local transport only. No live Google API.

## Required checks

Run at minimum:

- new HG2C5 focused tests;
- `backend/tests/test_rel1d_hg2b2_mail_recipients.py`;
- `backend/tests/test_rel1d_role_import_participants.py`;
- directly relevant Gmail normalizer/sync tests affected by the helper refactor;
- Ruff on touched Python;
- `git diff --check`.

Record exact totals.

## Explicit non-goals

Do not:

- infer account ownership for rows missing `source_account_email`;
- acquire/refresh Google tokens;
- run Gmail live sync/history/backfill;
- list messages;
- refetch attachments;
- rewrite legacy bare recipients/cc;
- overwrite existing structured participants;
- add persistent repair markers;
- add API/worker/CLI/ops invocation;
- call live Google;
- inspect/mutate production;
- add schema/migrations/dependencies;
- deploy backend;
- build/install client;
- start Yandex repair tooling;
- select/move a production release SHA;
- start human REL1D acceptance.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG2C5` entry to `PROJECT_STATE.md` with:
   - implementation SHA;
   - changed files;
   - exact source-account/message provenance contract;
   - exact 100/20 bounds;
   - shared HG2B2 helper behavior;
   - exact 404 behavior;
   - explicit ready transport/access-token boundary;
   - explicit no sync/history/token/job/attachment/commit behavior;
   - exact test totals;
   - Ruff/diff-check result;
   - explicit no provider-production/deploy/schema action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2C5 implementation SHA;
   - source ready for Architect review;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - no rollout/repair/live provider call/Yandex task without fresh Architect authorization.

3. commit + push to `main`.

4. STOP.

On blocker:

- record exact bounded blocker;
- do not widen into ordinary Gmail sync/history/token refresh/full rematerialization;
- return HOLD;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
