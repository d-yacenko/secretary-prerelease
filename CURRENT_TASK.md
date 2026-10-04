# CURRENT_TASK

ACTIVE

## REL1D-HG-D3 — cross-connector per-account participant-identity coverage audit

REL1D-HG-D2 diagnosis is ARCHITECT-ACCEPTED.

Accepted D2 classification:

`mixed:shared_scan_cap_starvation+teams_sender_metadata_missing`

D2 proved both:

- the shared role-import communication window of the newest `MAX_PERSON_SCAN_ROWS=400` is materially truncated;
- stored Teams rows can contain tenant id + sender id + human sender display while missing `sender_kind`, causing current `participant_identities(...)` to emit no Teams identity.

Human REL1D acceptance remains paused.

Before any connector-specific or scan-architecture corrective, perform one systematic **read-only per-account participant-identity coverage audit** across every communication-producing connection of the same Secretary user.

This task is DIAGNOSTIC ONLY.

Do not change source code.
Do not deploy.
Do not move `production`.
Do not build/install the client.
Do not migrate.
Do not trigger provider sync/backfill.
Do not call provider APIs.
Do not call a model.
Do not create/update/delete product data.

## Exact expected live state

```
PRODUCTION_RELEASE=bc69c6fa5c0735db9509d12dd5f77e6285e45901
EXPECTED_ALEMBIC=0054
SOURCE_TITLE=Снимок экрана от 2026-10-04 13-47-27.png
PERSON_LOOKBACK_DAYS=90
MAX_PERSON_SCAN_ROWS=400
```

Production branch/ref, backend runtime, and installed Linux client are expected to be the same release.

## Audit scope

Audit every current-user connection that can produce stored `email` or `chat_message` evidence relevant to Person/role grounding:

- every `GoogleAccount` for Gmail;
- every `YandexMailAccount`;
- every `MattermostAccount`;
- the current-user `TeamsAccount`, if present;
- every relevant Telegram communication account:
  - `TelegramMtprotoAccount`;
  - `TelegramAccount` / business transport if stored communication rows exist.

Do not include Calendar, Drive, Disk, or other non-communication connectors in this participant-identity audit.

The audit unit is:

**Secretary user × concrete connection/account × provider/kind**

Do not collapse multiple Google/Yandex/Mattermost accounts into one provider-wide result.

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
- `backend/app/db/models.py`
- `backend/app/domain/person_assistant.py`
- `backend/app/domain/role_import_participants.py`
- `backend/app/services/person_promotion_service.py`
- Google Gmail normalize/sync/materialization source;
- Yandex Mail normalize/sync/materialization source;
- Mattermost normalize/sync/materialization source;
- Teams normalize/sync/materialization source;
- Telegram MTProto/business normalize/sync/materialization source.

Verify:

1. fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task;
2. fresh `origin/production == PRODUCTION_RELEASE`;
3. production runtime exact release remains `PRODUCTION_RELEASE`;
4. health PASS;
5. Alembic `0054 / 0054`.

If any differ, return HOLD and STOP.

## BREAK-GLASS SSH contract

Use only the committed canonical production target and pinned host-key fingerprint.

Require one real strict pinned public-key-only SSH no-op according to `AGENTS.md` / `docs/executor_bootstrap.md`:

- `PasswordAuthentication=no`
- `KbdInteractiveAuthentication=no`
- `PreferredAuthentications=publickey`
- strict pinned host-key checking

Do not probe another host.
Do not create/copy/request credentials.
Do not print credentials or environment values.

This task explicitly permits direct production SSH and read-only `docker compose exec` only for this audit.

## Read-only diagnostic boundary

Run one bounded Python diagnostic inside the existing `api` container using canonical Compose files/environment from `docs/deploy.md`.

Use application `SessionLocal`, models, and current participant helpers where practical.

The diagnostic must:

- open a DB session;
- perform SELECT/read-only service/helper calls only;
- not call `commit()`;
- finish with explicit rollback/close;
- not enqueue jobs;
- not call provider transports;
- not refresh tokens;
- not change sync state;
- not manufacture test data.

No source patch or local monkeypatch may be used to reinterpret production rows.

## Identify the Secretary user safely

Find active current-production Object rows whose title exactly equals:

`Снимок экрана от 2026-10-04 13-47-27.png`

Require exactly one user owner.

Do not print:

- user UUID;
- source Object UUID.

If not unique, stop with:

`DIAGNOSTIC_BLOCKED=source_owner_not_unique`

## Anonymous connection labels

For reporting only, assign each connection a deterministic local ordinal label by provider and creation order, for example:

- `gmail#1`
- `gmail#2`
- `yandex_mail#1`
- `mattermost#1`
- `mattermost#2`
- `teams#1`
- `telegram_mtproto#1`
- `telegram_business#1`

Do not print or persist:

- account UUIDs;
- email addresses;
- usernames;
- user ids;
- tenant ids;
- server URLs;
- phone numbers;
- connection ids;
- tokens;
- scopes.

The ordinal labels are diagnostic-only and must not be treated as durable identities.

## Diagnostic A — connection inventory

For each in-scope connection, report only:

- anonymous label;
- provider;
- communication kind(s);
- account created-at date/time;
- account active/auth-status category where such a field exists;
- whether an exact self identity is configured: yes/no;
- whether sync/backfill state exists: yes/no;
- whether stored communication Objects can be unambiguously attributed back to that specific connection using stored account/realm provenance: yes/no.

If stored rows cannot be safely attributed to a specific connection, classify:

`account_attribution_missing`

Do not guess account attribution from display text or message body.

For providers with multiple configured accounts, this distinction is mandatory.

## Diagnostic B — stored coverage per connection

For every connection whose rows can be safely attributed:

report for active/non-rejected native communication Objects:

- total stored Object count;
- 90-day Object count;
- earliest stored occurrence timestamp;
- latest stored occurrence timestamp;
- count inside the shared current top-400 role-import scan;
- count outside top-400 but inside 90 days;
- whether the connection contributes at least one row to top-400;
- whether 90-day data exist but all/most strong participant rows are outside top-400.

For rows that cannot be safely attributed to a concrete connection:

- report provider-level unattributed Object count separately;
- do not assign them to one account.

Do not print Object ids or content.

## Diagnostic C — participant metadata completeness

Measure each provider using the exact metadata fields the current production parser expects.

### Gmail / Yandex Mail

For each attributable mail connection, count rows/categories:

- named parseable sender/from;
- bare sender address without human display;
- named parseable reply-to;
- recipients/to stored with a human display + address;
- recipients/to stored as bare addresses only;
- cc stored with a human display + address;
- cc stored as bare addresses only;
- rows with at least one exact identity-bearing non-self participant emitted by current `participant_identities(...)`;
- rows with communication content but zero participant identity emitted;
- rows where self identity is the only parsed participant.

Also report:

- whether the stored Object itself carries enough account provenance to distinguish multiple mail connections.

Do not print addresses.

### Mattermost

For each Mattermost account/realm, count native rows with:

- `author_user_id` present;
- `author_username` present;
- `author_display_name` present;
- stable author id + human display both present;
- stable author id/username present but human display absent;
- human display present but no stable author identity;
- current `participant_identities(...)` emits a normalized identity;
- current parser emits zero despite stable author identity fields;
- title presentation falls back to a technical username because human display is absent, when this can be inferred from stored metadata/title without printing the title.

Source-level structural note is permitted:

current normalizer reads Mattermost profile `display_name` and `username`; if `first_name`/`last_name` are not persisted, record that as a source-level coverage limitation, but do not call Mattermost to inspect live profiles.

### Microsoft Teams

For the Teams connection, count native rows with:

- `sender_display_name` present;
- tenant id present;
- sender id present;
- `sender_kind` present;
- `sender_kind == user`;
- display + tenant + sender id all present but `sender_kind` missing;
- all required current parser fields present;
- current `participant_identities(...)` emits a normalized identity;
- parser emits zero despite display + tenant + sender id being present;
- self identity filtered.

Report how many strong Teams identity-capable rows are:

- inside top-400;
- outside top-400 inside 90 days.

### Telegram MTProto

For every MTProto account, count native rows admitted by the same Assistant/Telegram gate used by Person scans, with:

- `transport == mtproto`;
- account id present;
- inbound sender peer id present;
- inbound sender display present;
- outbound private peer id present;
- outbound private peer display/title present;
- current `participant_identities(...)` emits a normalized identity;
- stable peer id present but human display absent;
- human display present but stable peer id absent;
- quarantined/non-admitted rows count.

Keep account/realm separation.

### Telegram Business / legacy Telegram

If native stored `provider=telegram` communication rows exist from non-MTProto business transport:

report:

- connection present yes/no;
- stored native row count;
- whether current role-import `participant_identities(...)` supports those rows;
- if unsupported, classify `parser_not_supported_for_transport`.

Do not broaden parser semantics in this task.

## Diagnostic D — current parser yield matrix

For each anonymous connection, calculate:

- `native_rows_90d`
- `rows_with_stable_remote_identity_fields`
- `rows_with_human_display`
- `rows_with_both_identity_and_human_display`
- `rows_current_parser_emits_identity`
- `rows_self_filtered`
- `rows_identity_ready_but_parser_blocked`
- `rows_stable_id_but_human_display_missing`
- `rows_human_display_but_stable_id_missing`
- `rows_text_only_no_identity`
- `identity_ready_rows_inside_top400`
- `identity_ready_rows_outside_top400`

Percentages may be reported, but always include counts.

Do not treat one repeated identity across many rows as many distinct people.
This matrix is row coverage, not unique-person count.

## Diagnostic E — unique participant identity coverage

Per connection, using normalized internal identity keys in-process only, report aggregate counts:

- unique non-self normalized participant identities emitted by current parser;
- unique identities with non-empty human display;
- unique identities already owned by an active Person;
- unique identities not yet owned;
- unique identities suppressed from generic promotion;
- unique identity-bearing participants that appear only outside top-400.

Do not print the keys or display names.

This section measures identity coverage, not automatic Person-merging.

Do not merge the same human across providers/accounts.

## Diagnostic F — Search/native evidence discrepancy

The human observed that Search can surface colleague names through mail notifications/summaries while native chat identity is absent or incomplete.

Without provider calls, classify the stored evidence source at aggregate level.

For each provider/connection, report:

- native communication Object count;
- native rows with strong participant identity;
- provider-notification/proxy evidence only when it can be identified structurally from stored provider/type metadata;
- do not use arbitrary subject-string heuristics as ground truth unless the source already has a deterministic notification classification.

If deterministic notification-vs-native classification is unavailable, report:

`proxy_vs_native_not_structurally_classifiable`

Do not invent a heuristic merely to satisfy this section.

## Diagnostic G — sync/history coverage

Per connection, inspect stored account sync/backfill state only.

Report safe categories:

- `history_complete`
- `history_in_progress`
- `incremental_only`
- `sync_state_present_but_completion_unknown`
- `no_sync_state`

Also report, when safely derivable without raw cursors:

- stored earliest object is after account creation: yes/no;
- explicit history cutoff exists: yes/no;
- history backfill incomplete: yes/no;
- account has 90-day stored rows older than current top-400 cutoff: yes/no.

Do not print cursor values, message ids, folder ids, chat ids, or remote ids.

## Diagnostic H — root-cause classification per connection

Assign one or more evidence-backed classifications per anonymous connection:

- `identity_healthy`
- `account_attribution_missing`
- `history_coverage_incomplete`
- `native_objects_missing`
- `human_display_missing`
- `stable_identity_missing`
- `email_recipient_display_lost`
- `teams_sender_kind_missing`
- `parser_discriminator_missing`
- `parser_not_supported_for_transport`
- `parser_mismatch_other`
- `shared_scan_cap_starvation`
- `mostly_text_only_evidence`
- `self_only`
- `mixed:<...>`

Use only classifications supported by stored production facts or directly inspected source contracts.

Do not speculate about live provider payloads that were not called.

## Diagnostic I — correction plan, no implementation

Produce a compact prioritized architecture summary grouped by defect class, not person:

1. **ingest/normalization defects**
   - fields available in stored/provider-normalized data but omitted or degraded;

2. **account provenance defects**
   - cannot tell which concrete connection produced the Object;

3. **history/backfill defects**
   - native communication not stored or incomplete;

4. **parser defects**
   - stored identity-ready metadata exists but current parser rejects it;

5. **scan architecture defects**
   - strong identity-ready rows exist but shared top-400 removes them;

6. **expected weak evidence**
   - no stable identity exists in storage, so HG1.5 mention fallback is appropriate.

For each class, report affected anonymous connection labels and row/identity counts.

Do not propose a migration or implementation in this task.
The Architect will choose follow-up slices after reviewing the matrix.

## D2 regression facts must remain visible

The audit must specifically reproduce/confirm, without printing raw ids:

- Teams target-quality pattern exists: rows with display + tenant + sender id but missing sender kind;
- strong Teams rows exist outside top-400;
- D2 classification remains explainable from the broader matrix.

Do not special-case the code for one named person.

## No mutation proof

Before and after the diagnostic, verify counts for the target user's:

- Object rows;
- Person Objects;
- PersonIdentity rows;
- PersonIdentityEvidence rows;
- PersonRoleTerm rows;
- PersonRoleAssignment rows;
- PendingActionPlan rows;
- GoogleAccount rows;
- YandexMailAccount rows;
- MattermostAccount rows;
- TeamsAccount rows;
- TelegramMtprotoAccount rows;
- TelegramAccount rows

are unchanged.

Rollback and close the session.

No provider/model/sync call.

## Completion protocol

On success:

1. append a compact sanitized `REL1D-HG-D3` entry to `PROJECT_STATE.md` containing:
   - production/runtime release;
   - anonymous connection inventory;
   - per-connection identity coverage matrix;
   - parser-yield matrix;
   - top-400 starvation matrix;
   - sync/history coverage categories;
   - per-connection root-cause classifications;
   - prioritized defect classes;
   - confirmation D2 Teams findings reproduced in the broader matrix;
   - explicit no provider/model/sync call;
   - explicit no product-data mutation;
   - no raw ids/addresses/usernames/server URLs/tokens.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - D3 audit completed;
   - short per-connection classification summary;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - no corrective implementation is authorized until Architect review.

3. commit + push ledger updates to `main`.

4. STOP.

On blocker:

- no mutation;
- record the exact sanitized blocker;
- return HOLD;
- commit/push accurate ledger if appropriate;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
