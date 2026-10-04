# CURRENT_TASK

ACTIVE

## REL1D-HG-D2 — read-only production diagnosis of missing Teams participant evidence

Human REL1D acceptance on fully aligned release:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

shows:

- HG1.5 mention-backed fallback works visibly for `Шабаршина Ирина Сергеевна`;
- grounding shows 12 stored communication mentions;
- client correctly states contact identity is unknown and would create a name-only Person;
- however the human supplied a Microsoft Teams screenshot showing `Шабаршина Ирина Сергеевна` as an actual sender in a Teams conversation on 2026-09-18/19.

D1 previously reported:
- normal Person resolution = `none`;
- zero identity-backed participant candidates;
- 12 Gmail mention-only Objects;
- no Teams participant evidence in the bounded scan;
- the 90-day scan was truncated.

Source review now confirms:
- `MAX_PERSON_SCAN_ROWS = 400`;
- role-import participant and mention scans order all active `email` + `chat_message` Objects by newest timestamp and then take only the newest 400 across all providers;
- Teams normalizer, when a message is stored, preserves `sender_id`, `sender_display_name`, `sender_kind`, and tenant metadata;
- new Teams accounts initialize `sync_start_at` to the account connection time, so pre-connection history may legitimately be absent from stored Objects.

This task is a **BREAK-GLASS READ-ONLY production diagnostic only**.

Goal: determine which factual case explains the discrepancy.

Do not change source code.
Do not deploy.
Do not move `production`.
Do not build/install the client.
Do not migrate.
Do not trigger sync.
Do not call Microsoft Graph or any provider API.
Do not call a model.
Do not create/update/delete product data.

## Exact expected live state

```
PRODUCTION_RELEASE=bc69c6fa5c0735db9509d12dd5f77e6285e45901
EXPECTED_ALEMBIC=0054
SOURCE_TITLE=Снимок экрана от 2026-10-04 13-47-27.png
TARGET_DISPLAY_NAME=Шабаршина Ирина Сергеевна
TARGET_TEAMS_DATE_UTC_RANGE=2026-09-18..2026-09-20
MAX_PERSON_SCAN_ROWS=400
```

Production branch/ref, backend runtime, and installed Linux client are expected to be the same release.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `ops/production/target.json`
- `backend/app/domain/person_assistant.py`
- `backend/app/services/person_promotion_service.py`
- `backend/app/services/person_role_import_mention_service.py`
- `backend/app/connectors/teams/account_store.py`
- `backend/app/connectors/teams/sync.py`
- `backend/app/connectors/teams/normalize.py`
- `backend/app/connectors/teams/materialize.py`
- `backend/app/domain/role_import_participants.py`

Verify:

1. fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task;
2. fresh `origin/production == PRODUCTION_RELEASE`;
3. production runtime exact release remains `PRODUCTION_RELEASE`;
4. health PASS;
5. Alembic `0054 / 0054`.

If any differ, return HOLD and STOP.

## BREAK-GLASS SSH contract

Use only the committed canonical production target and pinned host-key fingerprint.

Require one strict pinned public-key-only SSH no-op according to `AGENTS.md` / `docs/executor_bootstrap.md`:

- `PasswordAuthentication=no`
- `KbdInteractiveAuthentication=no`
- `PreferredAuthentications=publickey`
- strict pinned host-key checking

Do not probe another host.
Do not create/copy/request credentials.
Do not print credentials or environment values.

This task explicitly permits direct production SSH and read-only `docker compose exec` solely for this diagnosis.

## Read-only execution boundary

Run one bounded Python diagnostic inside the existing API container using canonical Compose files/environment from `docs/deploy.md`.

Use application `SessionLocal` and application models/helpers where practical.

The diagnostic must:

- open a DB session;
- perform SELECT/read-only service calls only;
- not call `commit()`;
- finish with explicit rollback/close;
- not enqueue jobs;
- not call provider transports;
- not refresh tokens;
- not change sync state;
- not manufacture test data.

No secrets or raw endpoint identities in output.

## Identify the exact Secretary user safely

Find active current-production Object rows whose title exactly equals:

`Снимок экрана от 2026-10-04 13-47-27.png`

Require exactly one user owner.

Do not print:
- user UUID;
- source Object UUID.

If not unique, stop with:

`DIAGNOSTIC_BLOCKED=source_owner_not_unique`

## Diagnostic A — shared global scan shape

Reproduce the exact 90-day communication query shape used by role-import scans:

- current user only;
- active, non-rejected;
- kinds `email`, `chat_message`;
- Telegram AI predicate where applicable;
- order by `coalesce(occurred_at, created_at) desc, Object.id`;
- fetch `MAX_PERSON_SCAN_ROWS + 1`.

Report only:

- total number of qualifying communication Objects in the full 90-day DB query;
- whether the 400-row window is truncated;
- timestamp of the oldest Object inside the first 400;
- per-provider counts inside first 400;
- per-provider counts across the full 90-day qualifying set, but only aggregate counts;
- whether 2026-09-18/19 lies older than the top-400 cutoff timestamp.

Do not print Object ids or message text.

Purpose:
prove or disprove **shared_scan_cap_starvation**.

## Diagnostic B — exact stored Teams sender evidence across the full 90-day range

Search **stored DB rows only**, not Graph.

Within the full 90-day qualifying active Teams `chat_message` set for the target user:

find rows where collapsed/casefolded `metadata.sender_display_name` exactly equals:

`Шабаршина Ирина Сергеевна`

Report only:

- count of exact-display Teams sender rows;
- count where `sender_kind == user`;
- count where tenant id is present;
- count where sender id is present;
- earliest and latest occurrence timestamps;
- count falling inside the global top-400 window;
- count falling outside the global top-400 window;
- whether at least one exact sender row exists on 2026-09-18..2026-09-20.

Do not print:
- sender id;
- tenant id;
- chat id;
- message id;
- account id;
- raw body/title.

If rows exist, also run the existing `participant_identities(...)` logic in-process and report only:

- how many exact target rows yield a Teams normalized identity;
- how many are filtered as self;
- how many are already owned by an active Person;
- how many are suppressed;
- how many would be eligible if the shared top-400 cap were removed.

Purpose:
distinguish **stored-but-starved** from parser/guard mismatch.

## Diagnostic C — target-name Search-like stored evidence classification

Across stored Objects in the same 90-day interval, find exact-name occurrences for the target and classify only by provider/kind and field category.

Report aggregate counts for:

- Teams sender-display exact match;
- Teams title/body exact-name mention without sender-display match;
- Gmail/Yandex title/body/subject mention;
- Mattermost author-display exact match;
- Telegram sender/peer-display exact match;
- other communication providers if present.

Do not print raw text snippets.

This is only to reconcile why Search can visibly surface the name while role-import strong evidence may not.

## Diagnostic D — Teams account sync boundary

Read the current user's TeamsAccount row, if present.

Do not print:

- account id;
- tenant id;
- Microsoft user id;
- UPN;
- display name;
- token/scopes/secrets.

Report only:

- Teams account present: yes/no;
- auth status category;
- whether `sync_start_at` exists;
- relation of `sync_start_at` to 2026-09-18T00:00Z:
  - `before_target_date`
  - `on_target_date`
  - `after_target_date`
- whether chats sync state contains at least one chat entry;
- count of stored Teams chat_message Objects before `sync_start_at`;
- count after `sync_start_at`.

Purpose:
prove or disprove **teams_history_not_ingested_before_sync_start**.

Do not modify sync state.

## Diagnostic E — root-cause classification

Choose only from evidence-backed classifications:

- `shared_scan_cap_starvation`
  - exact Teams sender identity is stored in DB within 90 days;
  - but all target rows lie outside the shared newest-400 scan.

- `teams_history_not_ingested_before_sync_start`
  - no stored target Teams sender row;
  - Teams account sync boundary begins after the external message date;
  - stored data pattern is consistent with no historical backfill.

- `stored_teams_target_present_but_identity_parser_mismatch`
  - exact sender-display Teams rows are stored inside scan scope;
  - required sender/tenant/user metadata is present;
  - but `participant_identities` fails to emit the expected identity.

- `stored_teams_target_present_but_filtered`
  - identity is emitted but blocked as self/owned/suppressed.

- `teams_sender_metadata_missing`
  - target Teams row is stored but required sender identity fields are absent.

- `search_result_not_from_teams_storage`
  - Search-visible target evidence is only Gmail/other stored text;
  - no stored Teams target row exists;
  - sync boundary does not by itself explain absence.

- `mixed:<classification1>+<classification2>`

- `other_structural_mismatch:<short sanitized description>`

Do not speculate beyond observed data.

## No mutation proof

Before and after the diagnostic, verify counts for the target user's:

- Object rows;
- Person Objects;
- PersonIdentity rows;
- PersonIdentityEvidence rows;
- PersonRoleTerm rows;
- PersonRoleAssignment rows;
- PendingActionPlan rows;
- TeamsAccount rows

are unchanged.

Rollback and close the session.

No provider/model call.

## Completion protocol

On success:

1. append a compact sanitized `REL1D-HG-D2` entry to `PROJECT_STATE.md`, including:
   - production/runtime release;
   - top-400 cutoff/truncation facts;
   - aggregate provider counts;
   - exact target Teams sender stored-row count;
   - inside/outside-top-400 classification;
   - Teams sync-start relation to target date;
   - final root-cause classification;
   - explicit no provider/model call;
   - explicit no product-data/sync-state mutation;
   - no raw ids/addresses/tokens.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - D2 completed;
   - exact root-cause classification;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - do not implement a corrective until Architect review.

3. commit + push ledger updates to `main`.

4. STOP.

On blocker:

- no mutations;
- record only sanitized blocker;
- return HOLD;
- commit/push accurate ledger if appropriate;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
