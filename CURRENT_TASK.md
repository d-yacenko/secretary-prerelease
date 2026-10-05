# CURRENT_TASK

ACTIVE

## REL1D-HG2C4 — isolated bounded Microsoft Teams sender-kind repair primitive

REL1D-HG2C3 is ARCHITECT SOURCE-ACCEPTED.

HG2C1 established that ordinary Teams sync is forward/overlap-oriented and cannot safely revisit the older rows that predate explicit `sender_kind`.

Historical source review also established why missing legacy `sender_kind` is intrinsically ambiguous:

- before `92aef7e6c9fb2e5acd6afc7056b26ea67ea99d07`, Graph `from.user` and `from.application` both persisted only sender id/display shape;
- therefore missing kind MUST NOT be interpreted heuristically as `user`;
- current `sender_identity_from_message(...)` correctly distinguishes `user` from `application` from a freshly fetched Graph message.

This task builds ONLY an isolated source primitive that refetches the exact stored Teams message and fills the missing discriminator.

Do not run normal Teams sync.
Do not add API/worker/CLI/ops/production wiring.

Production/backend/client remain:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Alembic remains:

`0054 / 0054`

Human REL1D acceptance remains paused.

## Architectural contract

The repair primitive exists only to add:

`metadata.sender_kind`

to a legacy Teams Object whose exact provider provenance and stored sender identity are already present.

It must NOT:

- guess a missing kind;
- treat missing kind as `user`;
- update title/body/occurred_at/deleted_at/status/external_id;
- rewrite full normalized metadata;
- update `sender_id` or `sender_display_name`;
- move Teams chat watermarks or sync state;
- create/renew subscriptions;
- acquire/refresh OAuth tokens;
- enqueue jobs or notifications;
- commit.

The fetched kind must come ONLY from the existing canonical:

`backend/app/connectors/teams/normalize.py::sender_identity_from_message`

Closed repair values are exactly:

- `user`
- `application`

Unknown/missing sender shape => no mutation.

## Important auth/transaction boundary

Do NOT use `TeamsTokenService.acquire_access_token` inside this repair primitive.

Current Teams token refresh can update token state and perform `session.commit()`. That is outside this source primitive's transaction contract.

Instead, the repair service must receive a ready `TeamsTransport` (or equivalent injected transport factory that does not own token acquisition/refresh).

A future separately authorized orchestration/ops layer will own token acquisition and transaction boundaries.

This task does not build that orchestration layer.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/rel1d_hg2_provider_repair_audit.md`
- `backend/app/connectors/teams/normalize.py`
- `backend/app/connectors/teams/transport.py`
- `backend/app/connectors/teams/account_store.py`
- `backend/app/connectors/teams/token_service.py`
- `backend/app/connectors/teams/materialize.py`
- `backend/app/connectors/teams/sync.py`
- `backend/app/domain/role_import_participants.py`
- relevant Teams tests around sender metadata and commit `92aef7e6c9fb2e5acd6afc7056b26ea67ea99d07`

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.
Do not move `production`.

## Preferred source shape

Add an isolated service, preferably:

`backend/app/services/teams_sender_kind_repair_service.py`

Add focused tests, preferably:

`backend/tests/test_rel1d_hg2c4_teams_sender_kind_repair.py`

No normalizer semantic change should be required: reuse the existing public `sender_identity_from_message`.

Do not route repair through `TeamsObjectMaterializer.upsert_message`, because that path can replace full metadata/title/body/occurred_at and attach media/jobs.

## Candidate contract

The batch method must take at least:

- `user_id`
- `account_id`
- a caller-supplied ready `TeamsTransport`
- optional caller-owned continuation cursor

Use deterministic ascending `Object.id` continuation or an equivalently explicit deterministic cursor.

Select/inspect only rows that are:

- owned by `user_id`;
- `provider == "teams"`;
- `kind == "chat_message"`;
- not tombstoned/deleted;
- metadata `account_id` exactly equals requested account id;
- metadata `tenant_id` exactly corresponds to that account tenant;
- metadata `teams_user_id` exactly corresponds to that account Microsoft user;
- metadata `direction == "inbound"`;
- metadata has no `sender_kind`.

A row is provider-repairable only when all of these stored provenance values are present and valid:

- non-empty `chat_id`;
- non-empty `message_id`;
- non-empty `sender_id`;
- non-empty `sender_display_name`;
- external id exactly corresponds to current `build_external_id(account.tenant_id, account.microsoft_user_id, chat_id, message_id)`.

Rows with missing/invalid/mismatched provenance:

- consume no provider lookup;
- are not mutated;
- advance the caller cursor.

Why require stored sender id/display:

- this repair is only the discriminator repair for the known legacy shape;
- it must not silently expand into reconstruction of missing sender identity or display;
- rows missing those fields remain a separate provenance gap, not repaired here.

Respect hidden/passive-sync protection. Hidden rows must not mutate.

Already-kind-tagged rows must not be selected/repaired.

## Bounds

Hard bounds per call:

- candidate Object scan: maximum 100 rows;
- provider `get_chat_message` calls: maximum 20;
- provider calls per `chat_id`: maximum 5.

The service must stop cleanly when a provider-call bound is reached and return the last fully inspected Object cursor.

Return a structured summary including at minimum:

- candidates_scanned
- provider_calls
- updated
- fetched_without_kind
- identity_mismatch
- invalid_provenance
- hidden_skipped
- next_cursor
- exhausted

Equivalent clearer names are acceptable.

## Fetch and validation contract

For each repairable row:

1. call ONLY:
   `transport.get_chat_message(chat_id, message_id)`;
2. do not call `list_chats`, `list_chat_messages`, `get_chat`, subscription methods, send/reply methods or token methods;
3. require the returned payload to be a dict;
4. require returned message `id` to match the stored `message_id`;
5. if returned `chatId` is present and non-empty, require it to match stored `chat_id`;
6. fail closed on deleted Graph messages (`deletedDateTime` present);
7. fail closed on an explicit non-`message` `messageType`;
8. call existing `sender_identity_from_message(payload)`;
9. require fetched sender kind to be exactly `user` or `application`;
10. require fetched sender id to represent the SAME stored sender identity:
    - compare using the repository's existing Microsoft GUID canonicalization semantics where applicable;
    - do not accept a different sender id merely because display names match;
11. fetched display name is NOT a repair field in this task and must not replace the stored display;
12. when all checks pass:
    - copy the existing metadata;
    - set only `sender_kind`;
    - assign the copied metadata back to the same Object.

If fetched sender is missing/unknown, id mismatches, message provenance mismatches, message is deleted, or payload is non-message:

- leave the Object unchanged;
- record the appropriate skip;
- advance cursor.

Provider/config/rate-limit/reconnect exceptions must propagate. Do not convert them into successful skips.

## Transaction / state isolation

The service must:

- perform no `commit()`;
- perform no `rollback()`;
- mutate no `TeamsAccount.sync_state`;
- mutate no access/refresh token fields;
- mutate no auth status;
- call no token refresh/OAuth service;
- create/renew/delete no subscription;
- enqueue no jobs;
- emit no notifications;
- call no materializer;
- call no normal sync.

On exception, caller owns rollback.

## Required tests

Prove at minimum:

1. only matching inbound Teams chat rows for requested user/account and missing kind are candidates;
2. other user, other account, wrong tenant, wrong `teams_user_id`, outbound, other provider/kind, tombstoned/deleted, already-kind-tagged and hidden rows remain unchanged;
3. missing/blank chat id, message id, sender id or sender display causes no provider call and advances cursor;
4. external-id mismatch causes no provider call;
5. candidate scan is bounded at 100;
6. total `get_chat_message` calls are bounded at 20;
7. calls per chat are bounded at 5;
8. cursor advances past invalid/missing-kind/mismatch rows so bad rows cannot pin a sweep;
9. fake transport proves ONLY `get_chat_message` is used;
10. returned message-id mismatch does not mutate;
11. returned non-empty chatId mismatch does not mutate;
12. deleted Graph message does not mutate;
13. explicit non-message Graph payload does not mutate;
14. missing/unknown `from` shape does not mutate;
15. fetched sender-id mismatch does not mutate even when display matches;
16. fetched `from.user` with same sender id writes only `sender_kind=user`;
17. fetched `from.application` with same sender id writes only `sender_kind=application`;
18. stored `sender_id`, `sender_display_name`, direction, provenance and unrelated/nested metadata remain unchanged;
19. title/body/occurred_at/deleted_at/status/external_id remain unchanged;
20. role-import participant becomes qualifying after repaired `user` kind when existing strong sender id/display is present;
21. repaired `application` kind remains non-qualifying;
22. existing self-identity filtering still excludes an inbound row whose stored sender identity is exact self identity, if such a fixture is valid under current participant semantics;
23. no Teams sync_state/watermark/token/auth/subscription state changes;
24. no job is enqueued and no commit/rollback occurs;
25. provider/config/rate-limit/reconnect exception propagates;
26. service source/test fake proves no `TeamsTokenService`, OAuth, normal sync or materializer execution path is introduced;
27. existing Teams sender-kind tests and role-import participant tests remain green.

Use fake/local transport only. No live Microsoft Graph.

## Required checks

Run at minimum:

- new HG2C4 focused tests;
- relevant Teams normalization/sync tests around sender identity and `sender_kind`;
- `backend/tests/test_rel1d_role_import_participants.py`;
- directly affected Teams transport/account tests if touched;
- Ruff on touched Python;
- `git diff --check`.

Record exact totals.

## Explicit non-goals

Do not:

- acquire or refresh Teams tokens;
- add token-refresh helper to the repair primitive;
- run normal Teams sync;
- list chats/messages;
- mutate chat watermarks or sync state;
- add API/worker/CLI/ops invocation;
- call live Graph;
- inspect or mutate production;
- update sender display/id/body/title/full metadata;
- add schema/migrations/dependencies;
- deploy backend;
- build/install client;
- start Gmail/Yandex repair tooling;
- select or move a production release SHA;
- start human REL1D acceptance.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG2C4` entry to `PROJECT_STATE.md` with:
   - implementation SHA;
   - changed files;
   - exact candidate/provenance contract;
   - exact 100/20/5 bounds;
   - exact `user|application` fetched discriminator behavior;
   - explicit caller-supplied transport / no token-refresh ownership;
   - explicit no sync-state/token/subscription/job/commit behavior;
   - exact test totals;
   - Ruff/diff-check result;
   - explicit no provider-production/deploy/schema action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2C4 implementation SHA;
   - source ready for Architect review;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - no rollout/repair/live provider call/next provider task without fresh Architect authorization.

3. commit + push to `main`.

4. STOP.

On blocker:

- record the exact bounded blocker;
- do not widen into normal sync/token refresh/full message rematerialization;
- return HOLD;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
