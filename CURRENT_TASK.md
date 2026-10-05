# CURRENT_TASK

ACTIVE

## REL1D-HG2C2 — isolated bounded Telegram MTProto sender-metadata repair primitive

REL1D-HG2C1 provider repair audit is ARCHITECT ACCEPTED.

Accepted audit artifact:

`docs/rel1d_hg2_provider_repair_audit.md`

HG2C1 established that ordinary `reconcile_recent_messages(...)` is NOT safe to reuse directly for a controlled legacy sender-metadata repair because:

- it shares cursor/rotation payload with recurring sync;
- it can tombstone an Object when `fetch_message` returns no message;
- it mixes message reconciliation semantics with the narrower HG2B3 repair goal.

This task builds ONLY an isolated source primitive for later explicitly authorized MTProto repair.

Do not wire it to production.
Do not add API/worker/recurring/CLI/ops invocation.
Do not call Telegram outside fake/local tests.

Production/backend/client remain:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Alembic remains:

`0054 / 0054`

Human REL1D acceptance remains paused.

## Architectural contract

The repair primitive exists only to enrich legacy stored MTProto Objects with the HG2B3 sender identity fields obtained from the CURRENT canonical single-message fetch path.

It must NOT become a general message reconcile.

It must NOT:

- tombstone provider misses;
- update title/body/occurred_at/deleted_at;
- rewrite arbitrary metadata;
- advance Telegram history cursors;
- use recurring-job payload state;
- call `get_sender` / `get_entity`;
- synthesize human display from username, phone, peer title, group title, or selection title.

Only these metadata keys may be added/replaced by this repair:

- `sender_kind`
- `sender_display_name`

The fetched sender contract remains HG2B3:

- `user`
- `bot`
- `channel`
- `chat`
- unknown/missing => no kind
- human User display only from provider first/last name fields via the existing canonical fetch conversion.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/rel1d_hg2_provider_repair_audit.md`
- `backend/app/services/telegram_mtproto_history_service.py`
- `backend/app/connectors/telegram/mtproto_transport.py`
- `backend/app/connectors/telegram/mtproto_account_store.py`
- `backend/app/connectors/telegram/materialize.py`
- `backend/app/domain/role_import_participants.py`
- `backend/tests/test_rel1d_hg2b3_mtproto_sender.py`

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.
Do not move `production`.

## Source shape

Prefer a new isolated service module:

`backend/app/services/telegram_mtproto_sender_repair_service.py`

Do not add a public API, worker handler, recurring job hook, CLI, or production ops script in this task.

The service may reuse:

- `TelegramMtprotoAccountStore`;
- the existing transport factory / credential decryption pattern;
- `TelethonMtprotoTransport.fetch_message` through the existing transport protocol/factory.

Do not duplicate Telethon sender classification logic.

## Candidate contract

The batch method must be explicit and bounded. It must take at least:

- `user_id`
- `account_id`
- optional explicit continuation cursor owned by the CALLER, not stored in sync/job state.

A simple Object-id cursor is acceptable if deterministic and tested.

Select only existing Objects that are all of:

- owned by `user_id`;
- `provider == "telegram"`;
- `kind == "chat_message"`;
- not tombstoned/deleted;
- metadata `transport == "mtproto"`;
- metadata `account_id` exactly matches `account_id`;
- metadata `direction == "inbound"`;
- metadata has a positive integer `message_id`;
- metadata has a valid peer id matching an ACTIVE stored MTProto selection for that account;
- metadata is missing `sender_kind`.

Why missing-kind is the repair selector:

- pre-HG2B3 legacy rows lack the explicit discriminator;
- after a successful current fetch, even a bot/channel/chat or a username-only human can receive a closed `sender_kind`, allowing the repair sweep to make deterministic forward progress;
- `sender_display_name` may legitimately remain absent for a `user` with no first/last provider name and must not cause endless reselection.

Respect existing hidden/passive-sync protection. A hidden Object must not be mutated.

## Batch bounds

Keep the source primitive hard-bounded:

- maximum provider lookups per call: 20;
- maximum lookups per peer per call: 5;
- candidate scan read: maximum 100 Objects per call.

These are the existing reconcile safety magnitudes and are the maximums for this task.

The method must return a structured summary containing enough facts for a later ops harness, including at minimum:

- candidates_scanned
- provider_calls
- updated
- provider_missing
- fetched_without_kind
- invalid_or_mismatch
- hidden_skipped
- next_cursor
- exhausted

Names may differ slightly if clearer, but semantics must be explicit and tested.

## Fetch and validation contract

For each selected candidate:

1. decrypt/use the stored ACTIVE selection reference for that exact peer;
2. call the existing transport `fetch_message(..., peer_id=..., message_id=...)`;
3. do not perform any extra entity/profile lookup;
4. if provider returns `None`:
   - increment provider-missing result;
   - DO NOT tombstone;
   - DO NOT change the Object;
5. require returned `peer_id` and `message_id` to match the stored target;
6. use only returned `sender_kind` and `sender_display_name`;
7. accept `sender_kind` only from the closed set `user|bot|channel|chat`;
8. if kind is absent/unknown:
   - leave Object unchanged;
   - record fetched-without-kind / invalid result;
9. when kind is valid:
   - copy the existing metadata dict;
   - set `sender_kind`;
   - set `sender_display_name` only when the returned value is a non-empty string after the SAME normalization already guaranteed by canonical fetch;
   - if returned display is absent, remove neither unrelated metadata nor synthesize a display;
   - write back only the metadata dict;
   - do not alter title/body/occurred_at/deleted_at/external_id.

For legacy `sender_display_name` already present with missing kind:

- valid current fetched display may replace it;
- if current fetch has no display, leave the existing display untouched rather than deleting it;
- role-import remains fail-closed because kind is authoritative.

## Transaction / state isolation

The service must:

- perform no `commit()` internally;
- mutate no `TelegramMtprotoChatSelection` history fields;
- mutate no recurring job payload;
- mutate no sync cursor/state;
- enqueue no jobs/notifications;
- invoke no tombstone path.

On provider/auth/transient exception, propagate the bounded connector error and let the caller transaction decide rollback.

Do not swallow provider errors as successful skips.

## Required tests

Add a focused test module, preferably:

`backend/tests/test_rel1d_hg2c2_mtproto_sender_repair.py`

Prove at minimum:

1. only matching inbound MTProto rows for the requested user/account are candidates;
2. outbound, Telegram Business, other account, other user, deleted/tombstoned, invalid message id, inactive peer, and already-kind-tagged rows are not repaired;
3. hidden/passive-sync protected Object is not mutated;
4. batch makes at most 20 provider calls;
5. batch makes at most 5 provider calls per peer;
6. candidate scan is bounded at 100;
7. explicit continuation cursor advances past rows even when provider returns missing/unknown, so one bad row does not pin the sweep;
8. provider `None` does not tombstone or mutate;
9. peer/message mismatch does not mutate;
10. `sender_kind=user` + provider display updates only the two authorized metadata fields;
11. `sender_kind=user` with no display stores kind but does not invent or erase display;
12. bot/channel/chat kinds are stored and remain non-qualifying in `participant_identities(...)`;
13. unknown/missing kind leaves Object unchanged;
14. pre-existing unrelated metadata is byte-for-byte/value-for-value preserved;
15. title, body, occurred_at, deleted_at, external_id remain unchanged;
16. no selection history field changes;
17. no job/notification/tombstone call occurs;
18. provider/auth/transient exception propagates and service does not commit;
19. transport fake proves no `get_sender` / `get_entity` path is introduced;
20. HG2B3 focused tests remain green.

Use fake/local transport only.

## Required checks

Run at minimum:

- new HG2C2 focused tests;
- `backend/tests/test_rel1d_hg2b3_mtproto_sender.py`;
- `backend/tests/test_rel1d_role_import_participants.py`;
- directly affected MTProto account/store/history tests;
- Ruff on touched Python;
- `git diff --check`.

Record exact totals.

## Explicit non-goals

Do not:

- add CLI/API/worker/recurring invocation;
- call live Telegram;
- inspect or mutate production;
- run sync/reconcile/backfill;
- tombstone messages;
- change current reconcile behavior;
- change MTProto history sync;
- change HG2B3 sender classification;
- change role-import parser semantics;
- change schema/migrations/dependencies;
- deploy backend;
- build/install client;
- start Mattermost/Gmail/Yandex/Teams repair tooling;
- select or move a production release SHA;
- start human REL1D acceptance.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG2C2` entry to `PROJECT_STATE.md` including:
   - implementation SHA;
   - changed files;
   - exact candidate contract;
   - exact 100/20/5 bounds;
   - explicit no tombstone/no sync-state/no job/no commit behavior;
   - exact focused test totals;
   - Ruff/diff-check result;
   - explicit no provider/production/deploy/schema action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2C2 implementation SHA;
   - source ready for Architect review;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - no rollout/repair/provider call/next provider task without fresh Architect authorization.

3. commit + push to `main`.

4. STOP.

On blocker:

- record exact bounded blocker;
- do not widen into ordinary reconcile or production ops;
- return HOLD;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
