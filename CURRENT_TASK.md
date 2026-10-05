# CURRENT_TASK

ACTIVE

## REL1D-HG2C6 — isolated bounded Yandex Mail named-recipient repair primitive

REL1D-HG2C5 is ARCHITECT SOURCE-ACCEPTED.

This is the final provider-specific HG2 repair source primitive in the current sequence.

HG2C1 established that Yandex Mail legacy repair is safe only when the stored IMAP identity is still exact:

- connected account is known from stored `source_account_email`;
- mailbox is the canonical synced `INBOX`;
- stored `imap_uid` is positive;
- stored `imap_uidvalidity` still equals the CURRENT UIDVALIDITY returned by selecting that INBOX;
- `Object.external_id` matches `build_external_id(INBOX, uidvalidity, uid)`.

An IMAP UID under a different UIDVALIDITY is NOT the same message.

Rows outside that contract remain:

`NOT_REPAIRABLE_FROM_CURRENT_PROVENANCE`

for this repair mechanism.

HG2B2 additive recipient semantics remain:

- legacy `metadata.recipients` and `metadata.cc` remain unchanged;
- named To recipients use additive `metadata.to_participants`;
- named Cc recipients use additive `metadata.cc_participants`;
- each item is `{address, display_name}`;
- bare addresses do not create structured participants.

This task builds ONLY an isolated Yandex Mail recipient repair primitive.

Do not run ordinary Yandex Mail sync/history.
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

It must NOT rewrite/remove:

- `recipients`
- `cc`
- `sender`
- `headers`
- `subject`
- `message_id`
- `timestamp`
- `folder`
- `imap_uid`
- `imap_uidvalidity`
- `source_account_email`
- unrelated metadata
- title/body/occurred_at/deleted_at/status/external_id

The repair is additive-only:

- preserve an existing structured key/value exactly;
- add a missing key only when current fetched message headers yield a non-empty named list;
- do not add empty lists as a completion marker;
- do not persist a repair-version marker.

Caller-owned Object-id cursor provides sweep progress.

## Shared HG2B2 parser requirement

Do not reimplement Yandex To/Cc parsing in the repair service.

Expose/reuse one small pure helper from:

`backend/app/connectors/yandex/mail_normalize.py`

so ordinary `normalize_imap_message` and HG2C6 use the SAME HG2B2 structured-recipient parser.

Preferred shape:

- public helper accepts the already-parsed stdlib email Message object and returns `(to_participants, cc_participants)`;
- ordinary normalizer calls it;
- repair parses fetched RFC822 bytes with the same stdlib email policy and calls it.

The helper refactor must not change:

- existing Yandex bare `recipients`/`cc` semantics;
- sender/title/body/timestamp/header behavior;
- attachment handling;
- HG2B2 named-recipient semantics.

## Provider/auth boundary

The repair method must receive a caller-supplied ready `ImapTransport`.

Do not construct `ImaplibTransport` inside the repair primitive.
Do not decrypt/store/log the app password inside the repair primitive.

A future separately authorized orchestration layer will own account credential loading and transport lifecycle.

The repair service itself may query the requested `YandexMailAccount` row only to validate ownership and exact account email/provenance.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/rel1d_hg2_provider_repair_audit.md`
- `backend/app/connectors/yandex/constants.py`
- `backend/app/connectors/yandex/imap_transport.py`
- `backend/app/connectors/yandex/mail_normalize.py`
- `backend/app/connectors/yandex/mail_sync.py`
- `backend/app/connectors/yandex/credentials.py`
- `backend/app/connectors/yandex/mail_history_state.py`
- `backend/app/connectors/yandex/errors.py`
- `backend/app/domain/role_import_participants.py`
- `backend/tests/test_rel1d_hg2b2_mail_recipients.py`
- directly relevant Yandex Mail sync/history/UIDVALIDITY tests

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.
Do not move `production`.

## Preferred source shape

Add isolated service, preferably:

`backend/app/services/yandex_mail_recipient_repair_service.py`

Add focused tests, preferably:

`backend/tests/test_rel1d_hg2c6_yandex_mail_recipient_repair.py`

A small helper exposure/refactor in `mail_normalize.py` is allowed solely to share HG2B2 parsing.

No sync/history/transport/account schema semantic change is expected.

## Candidate / provenance contract

The batch method must take at least:

- `user_id`
- `account_id`
- ready `ImapTransport`
- optional caller-owned continuation cursor

A row may belong to this repair only when:

- owned by `user_id`;
- `provider == "yandex_mail"`;
- `kind == "email"`;
- not tombstoned/deleted;
- metadata `source_account_email` is a non-empty string EXACTLY equal to requested `YandexMailAccount.email`;
- metadata `folder` is exactly `DEFAULT_MAIL_FOLDER` (`INBOX`);
- at least one of `to_participants` / `cc_participants` is absent.

Rows with missing account provenance or non-INBOX folder are outside this repair and MUST NOT be attributed/refetched.

Before any message fetch in a non-empty candidate batch:

1. call `transport.select_folder(DEFAULT_MAIL_FOLDER)` exactly once;
2. require a positive integer CURRENT UIDVALIDITY;
3. use that one returned value for all candidate validation in the batch.

A row is provider-refetchable only when:

- metadata `imap_uid` is a positive integer (bool is invalid);
- metadata `imap_uidvalidity` is a positive integer (bool is invalid);
- stored `imap_uidvalidity == current_uidvalidity`;
- `Object.external_id == build_external_id(DEFAULT_MAIL_FOLDER, current_uidvalidity, imap_uid)`.

If any condition fails:

- no `fetch_message` for that row;
- no mutation;
- advance caller cursor;
- record invalid/stale provenance appropriately.

Do NOT repair a UID under a changed UIDVALIDITY even if another field such as Message-ID looks familiar.

## Bounds

Hard bounds per call:

- candidate Object scan: maximum 100 rows;
- folder selection: at most ONE `select_folder(INBOX)` call;
- message fetches: maximum 20 `fetch_message(INBOX, uid)` calls.

No IMAP search/list/history/internaldate call is allowed.

If there are zero coarse candidate rows, make zero provider calls including zero `select_folder`.

Stop cleanly at 20 message fetches and return the last fully inspected Object cursor.

Return structured summary containing at minimum:

- candidates_scanned
- folder_select_calls
- message_fetches
- updated
- already_structured (if rows with both keys are included in scan; otherwise this may be omitted)
- invalid_provenance
- uidvalidity_mismatch
- message_malformed
- no_named_recipients
- hidden_skipped
- current_uidvalidity (nullable when no select occurred)
- next_cursor
- exhausted

Equivalent clearer names are acceptable.

## Fetch / parse contract

For each exact refetchable row:

1. call ONLY:
   `transport.fetch_message(DEFAULT_MAIL_FOLDER, imap_uid)`;
2. do not call search/list/history/fetch_internaldate;
3. require returned value to be non-empty `bytes`;
4. parse RFC822 bytes with the same stdlib email policy used by current Yandex normalization;
5. derive named To/Cc only through the shared HG2B2 helper;
6. do not use stored body/subject/bare recipient arrays to synthesize names;
7. do not use Message-ID as a substitute for UID + UIDVALIDITY identity;
8. do not process/refetch attachments.

If returned payload is not non-empty bytes:

- leave Object unchanged;
- count malformed;
- advance cursor.

### Provider error handling

Current `ImapTransport.fetch_message` exposes provider absence/failure through `YandexImapError` without a reliable distinct "message missing" status contract.

Therefore HG2C6 MUST NOT guess whether a `YandexImapError` means deleted message versus transient/auth/unknown failure.

Any `YandexConnectorError` / `YandexImapError` from `select_folder` or `fetch_message` must propagate to the caller.

Do not swallow provider errors.

Caller owns rollback.

## Mutation contract

From the fetched structured lists:

- copy existing metadata;
- if `to_participants` is ABSENT and fetched To named list is non-empty, add exactly that list;
- if `cc_participants` is ABSENT and fetched Cc named list is non-empty, add exactly that list;
- preserve any existing To/Cc structured value exactly;
- if neither missing key receives a non-empty named list, do not assign metadata;
- when one or both fields are added, assign copied metadata back to the SAME Object and increment updated once.

Do not route through normal Yandex sync/materialization.
Do not create attachments or embedding jobs.

## Transaction / state isolation

The service must:

- perform no `commit()`;
- perform no `rollback()`;
- mutate no `YandexMailAccount.sync_state`;
- mutate no `inbox_uidvalidity`, `inbox_last_uid` or `history_backfill`;
- mutate no credential/account fields;
- enqueue no jobs;
- emit no notifications;
- create no attachments;
- call no ordinary sync/history path.

## Required tests

Prove at minimum:

1. only Yandex email rows for requested user, exact `source_account_email`, canonical INBOX and missing structured field(s) are candidates;
2. other user/provider/kind/account email, non-INBOX, tombstoned/deleted and hidden rows remain unchanged;
3. missing `source_account_email` gets zero message fetches;
4. zero candidate rows causes zero `select_folder` and zero fetches;
5. a non-empty batch calls `select_folder(INBOX)` at most once;
6. non-positive/non-integer/bool `imap_uid` gets zero fetch;
7. invalid/non-positive/bool stored `imap_uidvalidity` gets zero fetch;
8. stored UIDVALIDITY different from current selected UIDVALIDITY gets zero fetch and increments mismatch count;
9. external-id mismatch gets zero fetch;
10. candidate scan is bounded at 100;
11. message fetches are bounded at 20;
12. cursor advances past invalid/stale/malformed/no-name rows so a bad local row cannot pin a successful sweep;
13. fake transport proves only `select_folder` and `fetch_message` are used;
14. provider `select_folder` error propagates and no mutation occurs;
15. provider `fetch_message` error propagates; service does not classify it as provider-missing;
16. non-bytes/empty fetched payload does not mutate;
17. quoted commas and Unicode names match ordinary Yandex HG2B2 normalization;
18. bare To/Cc addresses add no structured entries;
19. valid fetched To names fill only missing `to_participants`;
20. valid fetched Cc names fill only missing `cc_participants`;
21. both missing named lists can be added in one metadata update;
22. existing structured To or Cc is never overwritten;
23. legacy `recipients`/`cc` remain exactly unchanged;
24. sender/headers/subject/message_id/timestamp/folder/uid/uidvalidity/source account/unrelated metadata remain unchanged;
25. title/body/occurred_at/deleted_at/status/external_id remain unchanged;
26. role-import sees repaired named participants and exact self filtering still excludes connected account identity;
27. no sync/history checkpoint changes;
28. no account credential changes;
29. no job/attachment is created;
30. no commit/rollback occurs;
31. service source/test fake proves no search/history/internaldate/ordinary sync path is introduced;
32. existing HG2B2 Yandex recipient tests remain green;
33. relevant Yandex UIDVALIDITY/history tests remain green;
34. relevant role-import participant tests remain green.

Use fake/local transport only. No live Yandex IMAP.

## Required checks

Run at minimum:

- new HG2C6 focused tests;
- `backend/tests/test_rel1d_hg2b2_mail_recipients.py`;
- `backend/tests/test_rel1d_role_import_participants.py`;
- directly relevant Yandex normalizer tests;
- relevant Yandex UIDVALIDITY/history tests needed to prove the identity contract;
- Ruff on touched Python;
- `git diff --check`.

Record exact totals.

## Explicit non-goals

Do not:

- repair rows missing `source_account_email`;
- repair non-INBOX rows;
- repair rows under stale/different UIDVALIDITY;
- infer identity from Message-ID;
- run IMAP searches/history/live sync;
- fetch internaldate or attachments;
- construct live transport/decrypt credentials inside the service;
- add persistent repair markers;
- add API/worker/CLI/ops invocation;
- call live Yandex;
- inspect/mutate production;
- add schema/migrations/dependencies;
- deploy backend;
- build/install client;
- select/move production release SHA;
- start rollout/data repair;
- start human REL1D acceptance.

## Completion protocol

On success:

1. append compact factual `REL1D-HG2C6` entry to `PROJECT_STATE.md` with:
   - implementation SHA;
   - changed files;
   - exact account/INBOX/UID/UIDVALIDITY/external-id provenance contract;
   - exact 100 / 1 select / 20 fetch bounds;
   - shared HG2B2 helper behavior;
   - explicit provider-error propagation;
   - explicit ready-transport boundary;
   - explicit no sync/history/credential/job/attachment/commit behavior;
   - exact test totals;
   - Ruff/diff-check result;
   - explicit no provider-production/deploy/schema action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2C6 implementation SHA;
   - source ready for Architect review;
   - provider-specific repair primitive sequence HG2C2..HG2C6 is complete pending Architect acceptance;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - no rollout/data repair/live provider call/release selection without fresh Architect authorization.

3. commit + push to `main`.

4. STOP.

On blocker:

- record exact bounded blocker;
- do not widen into ordinary sync/history or alternate mailbox identity heuristics;
- return HOLD;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
