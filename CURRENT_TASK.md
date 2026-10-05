# CURRENT_TASK

ACTIVE

## REL1D-HG2D3 — source-only fail-closed production HG2 repair preflight census harness

REL1D-HG2D2 is ARCHITECT ACCEPTED.

Production/backend runtime and production ref are now exactly:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Alembic is:

`0054 / 0054`

Installed client remains:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

HG2 provider repair primitives are deployed in backend source/runtime, but NO production repair has been executed.

This task prepares ONLY a fail-closed, read-only, aggregate production census harness for the next Architect-reviewed live preflight.

DO NOT run the harness against production in this task.

Do not call any provider.
Do not mutate production.
Do not run any HG2 repair service.

## Goal

Create a committed one-shot census protocol that can later prove, using production DB data only:

- how many locally repairable legacy rows exist for each HG2 provider;
- how many rows are already enriched;
- how many rows are hidden;
- how many rows fail local provenance requirements and therefore must not generate provider calls;
- how many connected accounts exist and how many accounts have local candidates;
- for Yandex, how many rows are only conditionally repairable pending a future provider-current UIDVALIDITY check.

The census must never emit:

- user ids;
- account ids;
- emails;
- usernames;
- server URLs;
- peer/chat/message ids;
- sender/author ids;
- display names;
- raw metadata;
- tokens/credentials;
- raw provider payloads;
- raw SQL rows.

Only fixed-name integer/boolean facts are allowed.

## Architectural pattern

Use the existing fail-closed production census pattern as the reference shape:

- `ops/production/people_p1_person_census.py`
- `ops/production/remote_people_p1_person_census.py`
- `ops/production/tests/test_people_p1_person_census.py`

Do NOT modify those historical files.

The HG2 census should similarly:

1. pin the exact production SHA;
2. require canonical origin;
3. require clean remote production worktree;
4. require remote HEAD == pinned production SHA;
5. require `origin/production == pinned production SHA`;
6. require DB/API/worker running;
7. require DB healthy;
8. require API health;
9. require Alembic exactly `0054`;
10. begin/verify a READ ONLY database transaction before reading repair facts;
11. expose a strict closed output protocol;
12. use the pinned target/host-key contract;
13. sanitize all errors to bounded stage/class values;
14. make zero provider network calls.

This task is SOURCE-ONLY. It builds and tests the harness but does not invoke SSH.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `docs/rel1d_hg2_provider_repair_audit.md`
- all HG2C2–HG2C6 repair services;
- `app.domain.object_visibility`;
- the existing Person census local/remote/test files above.

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Do not move `production`.

## Required source shape

Prefer exactly these new files:

- `ops/production/hg2_repair_preflight.py`
- `ops/production/remote_hg2_repair_preflight.py`
- `ops/production/tests/test_hg2_repair_preflight.py`

No backend runtime source change is authorized.

No migration/dependency/client change is authorized.

The local entrypoint must hard-pin:

`PRODUCTION_SHA = "f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6"`

and expected Alembic:

`0054`

Do not make the production SHA a broad arbitrary CLI argument.

## Remote execution model

The future live invocation must stream the committed remote helper, like the existing Person census.

The helper may run its read-only child logic inside the existing API container so it can import:

- current SQLAlchemy models;
- `is_object_hidden_from_active_reads`;
- exact pure/local provenance helpers from HG2 repair services where useful.

It must NOT instantiate or call provider transports.

It must NOT decrypt credentials.

It must NOT instantiate the repair services in a way that can perform provider I/O.

Prefer direct read-only SQLAlchemy/model inspection of the exact local provenance contracts.

Before any Object/account census query:

- open a DB transaction;
- set it READ ONLY;
- query/verify `transaction_read_only == on`.

Any failure to prove read-only mode is terminal.

No `commit()`.
No `flush()`.
No `rollback()` as an application mutation path; normal session close/transaction cleanup is fine.

## Exact provider census semantics

All counts must be across the full production dataset, grouped internally by owning user/account as needed, but output only global aggregate integers and aggregate per-account maxima/counts.

Respect the exact deployed HG2 repair contracts.

### Telegram MTProto

Count:

- connected MTProto accounts;
- inbound MTProto chat rows with missing `sender_kind` that fall into the repair service's coarse account filter;
- locally repairable rows:
  - positive non-bool `message_id`;
  - valid stored peer id according to the deployed repair helper semantics;
  - peer has an ACTIVE stored selection for that exact account;
  - Object is not hidden;
- hidden coarse candidates;
- invalid-provenance coarse candidates;
- already-enriched inbound MTProto rows with non-missing `sender_kind`;
- number of accounts with at least one locally repairable row;
- maximum locally repairable rows in any one account.

Do NOT inspect Telegram sessions.
Do NOT contact Telegram.

### Mattermost

Count:

- connected Mattermost accounts;
- coarse candidate rows matching exact account id + normalized server URL and missing/blank `author_display_name`;
- locally repairable rows with non-empty string `author_user_id` and not hidden;
- hidden coarse candidates;
- invalid-provenance coarse candidates with missing/blank author id;
- already-enriched matching Mattermost chat rows with non-empty `author_display_name`;
- accounts with at least one locally repairable row;
- maximum locally repairable rows in one account.

Do NOT decrypt Mattermost tokens.
Do NOT call profiles/posts/history.

### Microsoft Teams

Count:

- connected Teams accounts;
- inbound Teams chat rows matching exact account/tenant/Teams-user provenance and missing `sender_kind`;
- locally repairable rows satisfying the deployed HG2C4 local target contract:
  - non-empty chat id;
  - non-empty message id;
  - non-empty sender id;
  - non-empty sender display;
  - exact external id from current `build_external_id`;
  - not hidden;
- hidden coarse candidates;
- invalid-provenance coarse candidates;
- already-kind-tagged inbound Teams rows matching exact account provenance;
- accounts with at least one locally repairable row;
- maximum locally repairable rows in one account.

Do NOT load/refresh OAuth tokens.
Do NOT call Graph.

### Gmail

Count:

- connected Google/Gmail accounts;
- Gmail email rows attributable to an account by exact `source_account_email == account.email`;
- rows attributable to an account and missing at least one structured key;
- locally repairable rows among them:
  - non-empty string `message_id`;
  - exact `Object.external_id == message_id`;
  - not hidden;
- hidden candidate rows;
- invalid-provenance candidate rows;
- attributable rows already containing BOTH structured keys;
- Gmail rows with missing/blank `source_account_email` as a separate global `UNATTRIBUTABLE` count;
- accounts with at least one locally repairable row;
- maximum locally repairable rows in one account.

Rows whose non-empty source email matches NO connected account may be counted separately as `UNMATCHED_SOURCE_ACCOUNT`, but do not emit the email.

Do NOT load/refresh Google tokens.
Do NOT call Gmail.

### Yandex Mail

Count:

- connected Yandex Mail accounts;
- attributable canonical-INBOX rows missing at least one structured key;
- hidden candidate rows;
- local invalid-provenance rows:
  - invalid/non-positive/bool UID;
  - invalid/non-positive/bool stored UIDVALIDITY;
  - external-id mismatch under the STORED row UIDVALIDITY;
- locally structurally refetchable rows whose UID/UIDVALIDITY/external id are internally consistent and not hidden;
- among structurally refetchable rows, count how many have stored row UIDVALIDITY equal to the account's stored `sync_state.inbox_uidvalidity`, if that stored account state is a valid positive integer;
- count rows where row UIDVALIDITY differs from the stored account sync-state UIDVALIDITY;
- attributable INBOX rows already containing BOTH structured keys;
- rows missing/blank `source_account_email` as `UNATTRIBUTABLE`;
- non-INBOX rows missing structured fields as a separate `NON_INBOX_OUTSIDE_REPAIR` count;
- accounts with at least one structurally refetchable row;
- maximum structurally refetchable rows in one account.

The output/protocol MUST clearly name this as LOCAL/STORED-STATE evidence only.

It MUST NOT call `select_folder`.

It MUST NOT claim current provider UIDVALIDITY is known.

Future Yandex live repair still requires provider-current UIDVALIDITY validation before any message fetch.

## Output protocol

Use a fixed ordered fact list.

Every emitted repair fact must be:

- boolean, or
- non-negative base-10 integer.

No free-form strings except fixed protocol markers/classifications.

At minimum include for each provider:

- `*_ACCOUNTS`
- `*_COARSE_CANDIDATES` (where the provider contract has a meaningful coarse set)
- `*_LOCAL_REPAIRABLE`
- `*_HIDDEN`
- `*_INVALID_PROVENANCE`
- `*_ALREADY_ENRICHED`
- `*_ACCOUNTS_WITH_LOCAL_REPAIRABLE`
- `*_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT`

Use precise provider-specific extra facts for Gmail/Yandex provenance gaps.

Also emit:

- `HG2_PREFLIGHT_MARKER=started`
- `HG2_PREFLIGHT_GUARDS=pass`
- `HG2_PREFLIGHT_READ_ONLY=on`
- `PROVIDER_NETWORK_CALLS=0`
- terminal `HG2_PREFLIGHT_TERMINAL=success`

On error emit only a closed/sanitized blocked stage and exception class plus `PROVIDER_NETWORK_CALLS=0`.

The local parser must reject:

- unknown extra fields;
- missing fields;
- duplicates;
- negative/non-integer counts;
- any line containing an email-like `@`;
- UUID-like values;
- unexpected free-form output;
- stderr-dependent secret/debug handling.

Do not echo remote stderr.

## Read-only and no-provider proof

Tests must prove, by source inspection and behavior, that remote helper/child contains no reachable path to:

- HTTP/Graph/Gmail/Mattermost network transports;
- Telethon/Telegram client construction or connect;
- IMAP `select_folder` or `fetch_message`;
- OAuth/token refresh;
- credential decryption;
- any HG2 repair method call;
- `INSERT`, `UPDATE`, `DELETE`, `ALTER`, `DROP`, `TRUNCATE`;
- Alembic upgrade/downgrade;
- Compose `up`, `restart`, `stop`;
- job enqueue;
- commit.

It is acceptable to import pure helpers/constants that do not perform I/O.

## Required tests

Add focused local tests proving at minimum:

1. wrong release SHA / wrong production ref fails closed;
2. wrong cwd/origin/HEAD/worktree/Alembic fails closed;
3. parser accepts one exact complete success protocol;
4. parser rejects missing/extra/duplicate/reordered/malformed fields;
5. parser rejects identity-like/raw-value leakage;
6. remote helper requires and verifies read-only transaction state;
7. zero provider network calls are hard-coded/proven in all success/failure terminals;
8. read-only source contains no mutation SQL / provider-I/O path;
9. candidate classification fixtures correctly separate local repairable vs hidden vs invalid provenance for all five providers;
10. Gmail missing source-account provenance is counted only as unattributable and never assigned heuristically;
11. Teams missing `sender_kind` is never assumed to mean user;
12. Yandex stale/different stored UIDVALIDITY is not called current-provider-valid;
13. Yandex non-INBOX rows are outside repair;
14. per-account aggregate maximum/account-count facts do not reveal identifiers;
15. output never contains fixture email/UUID/id/display strings;
16. existing production census/deploy tests remain green if affected by imports.

Prefer deterministic local SQLite/Postgres-independent fixture tests for classification logic where possible. If JSONB query semantics require PostgreSQL, test the pure classification helpers directly and keep remote DB query construction source-reviewed.

No live SSH/provider test is authorized.

## Required checks

Run at minimum:

- `python3 -m pytest -q ops/production/tests/test_hg2_repair_preflight.py`
- `python3 -m pytest -q ops/production/tests/test_people_p1_person_census.py`
- directly relevant deploy/parser production tests if imports/shared helpers are touched;
- Ruff on the three new Python files;
- `git diff --check`.

Record exact totals.

## Explicit non-goals

Do not:

- execute the new census against production;
- connect by SSH in this task;
- query production DB;
- call any provider;
- run any repair service;
- mutate `backend/app` or `backend/tests`;
- change migrations/schema;
- change production ref/runtime;
- build/install client;
- start human REL1D acceptance;
- design the provider execution harness beyond what is needed for read-only census evidence.

## Completion protocol

On success:

1. append compact factual `REL1D-HG2D3` entry to `PROJECT_STATE.md` containing:
   - implementation SHA;
   - new files;
   - pinned production SHA and Alembic;
   - aggregate-only/no-identity protocol;
   - read-only transaction enforcement;
   - zero-provider-call contract;
   - exact test totals;
   - Ruff/diff result;
   - explicit no SSH/production DB/provider/repair/runtime/client action;
2. replace `CURRENT_TASK.md` with HOLD stating:
   - D3 census harness source SHA;
   - harness is ready for Architect review;
   - production remains `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`;
   - Alembic remains `0054 / 0054`;
   - no live census/repair/provider call without fresh Architect authorization;
3. commit + push to `main`;
4. STOP.

On blocker:

- record exact bounded source/test blocker;
- do not run production;
- return HOLD;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
