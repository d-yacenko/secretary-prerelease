# CURRENT_TASK

ACTIVE

## REL1D-HG-D1 — BREAK-GLASS read-only production diagnosis of participant false negative

Human REL1D acceptance on the fully aligned release:

`67e8f14ba7ced8408086bd1ea57c2fa9f7b049dc`

produced this exact result:

- HG1.3 scroll geometry / auto-follow: visually PASS;
- extracted org-chart row: `Шабаршина Ирина Сергеевна`;
- after `Сопоставить`: no communication-backed contacts were returned;
- prior Search UI visibly showed multiple stored objects involving that same name.

The Architect has already identified one source-level storage/read mismatch:

- Gmail/Yandex normalizers preserve a named `sender` header;
- but normalize `recipients` and `cc` to bare email addresses;
- HG1.4 intentionally rejects bare addresses without a participant display name.

That mismatch may or may not be the production root cause for this person because prior Search also showed chat-like objects.

This task is a **BREAK-GLASS READ-ONLY production diagnostic only**.

It authorizes direct pinned production SSH and a bounded read-only process inside the existing API container solely for the checks below.

Do not change source code.
Do not deploy.
Do not move `production`.
Do not build/install the client.
Do not migrate.
Do not sync providers.
Do not call model/provider APIs.
Do not create/update/delete any product row.

## Exact live state expected

```
PRODUCTION_RELEASE=67e8f14ba7ced8408086bd1ea57c2fa9f7b049dc
EXPECTED_ALEMBIC=0054
SOURCE_TITLE=Снимок экрана от 2026-10-04 13-47-27.png
TARGET_DISPLAY_NAME=Шабаршина Ирина Сергеевна
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
- `backend/app/domain/role_import_participants.py`
- `backend/app/services/person_promotion_service.py`
- `backend/app/services/person_role_import_grounding_service.py`
- `backend/app/services/person_assistant_service.py`
- `backend/app/connectors/google/gmail_normalize.py`
- `backend/app/connectors/yandex/mail_normalize.py`
- `backend/app/connectors/mattermost/normalize.py`
- `backend/app/connectors/teams/normalize.py`
- relevant Telegram normalize/gate source if Telegram rows are found.

Verify:

1. fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task;
2. fresh `origin/production == PRODUCTION_RELEASE`;
3. production runtime exact release remains `PRODUCTION_RELEASE`;
4. health PASS;
5. Alembic `0054 / 0054`.

If any differ, return HOLD and STOP.

## BREAK-GLASS SSH contract

Use only the committed canonical production target and pinned host-key fingerprint.

Require one real strict pinned public-key-only SSH no-op as defined by `AGENTS.md` / `docs/executor_bootstrap.md`:

- `PasswordAuthentication=no`
- `KbdInteractiveAuthentication=no`
- `PreferredAuthentications=publickey`
- strict pinned host-key checking

Do not probe another host.
Do not create/copy/request credentials.
Do not print credentials or environment values.

This task explicitly permits direct production SSH and read-only `docker compose exec` only for this diagnostic.

## Diagnostic execution boundary

Run one bounded Python diagnostic inside the existing `api` container using the canonical Compose files/environment from `docs/deploy.md`.

Use application `SessionLocal` and application services/domain helpers where practical.

The diagnostic must:

- open a DB session;
- perform SELECT/read-only service calls only;
- not call `commit()`;
- finish with explicit rollback/close;
- not enqueue jobs;
- not call provider transports;
- not call LLM/model code;
- not change sync state;
- not manufacture test data.

Before and after the diagnostic, prove no intended product mutation occurred. Do not dump tables.

## Identify the exact Secretary user safely

Find active current production Object rows whose title exactly equals:

`Снимок экрана от 2026-10-04 13-47-27.png`

Require exactly one user owner for the matching source context.

Do not print the user UUID or source Object UUID.

If the title cannot identify exactly one user safely, STOP and report only:

`DIAGNOSTIC_BLOCKED=source_owner_not_unique`

Do not guess another user.

## Required diagnostic A — Person resolution path

For:

`Шабаршина Ирина Сергеевна`

run the same normal Person resolution used by role-import grounding.

Report only:

- resolution state: `resolved|ambiguous|none`;
- number of graph Person candidates before communication filtering;
- number surviving the HG1.2 positive attributable-communication gate;
- attributable communication count(s), but no Person ids/titles beyond the already-known target name.

Purpose:

Determine whether the row is being lost **before** the new-Person participant path because an existing graph Person resolves but has zero attributable communications.

Do not mutate Person identity/evidence.

## Required diagnostic B — role-import participant scan

Run the same production role-import participant scan used by HG1.4/HG1.4.1.

Filter results by exact normalized display-name equality to:

`Шабаршина Ирина Сергеевна`

Report only:

- exact-display candidate count;
- provider category for each candidate;
- bounded hit count;
- whether candidate is absent due to:
  - no parsed identity-bearing participant;
  - exact identity already owned by an active Person;
  - current-user self identity;
  - active promotion suppression;
  - or another existing production guard that can be proven without revealing identity values.

Do not print:

- email addresses;
- usernames;
- user ids;
- tenant ids;
- account ids;
- realms/server URLs;
- candidate keys;
- Object ids;
- hashes/prefixes of secrets or identities.

If a raw identity is needed internally for comparison, keep it in-process and output only booleans/categories.

## Required diagnostic C — stored communication shape

Use the same 90-day / bounded communication universe used by Person services.

Inspect at most `MAX_PERSON_SCAN_ROWS` current-user active non-rejected `email` / `chat_message` rows.

Do not print body text or arbitrary titles.

For rows structurally or textually associated with the exact target name, print only a sanitized category summary.

### Email summary

For Gmail/Yandex rows, report counts of rows where:

- named `sender` display equals target and has parseable email identity;
- `recipients` contain only bare addresses and therefore cannot carry target display name;
- `cc` contains only bare addresses;
- named `reply-to` display equals target and has parseable identity;
- target name appears only in title/body/subject text, not an identity-bearing participant field.

Do not print any address.

### Mattermost summary

Report counts where:

- `author_display_name` exactly equals target;
- exact `author_user_id` exists;
- exact username fallback exists;
- title/body contains target but author display identity does not.

No ids/usernames/server URL in output.

### Teams summary

Report counts where:

- `sender_display_name` exactly equals target;
- `sender_kind == user`;
- tenant id present;
- sender id present;
- title/body contains target but sender display identity does not.

No ids/tenant values.

### Telegram summary

Only if relevant rows exist, report:

- target sender/peer display exact-match count;
- exact user identity presence;
- whether existing Telegram Assistant gate admits or quarantines those rows.

No ids/account values.

## Required diagnostic D — explain the Search/grounding divergence

Produce one concise classification based only on the observed production facts:

Choose one or more of:

- `existing_person_without_attributable_identity`
- `email_recipient_display_lost_at_normalization`
- `name_only_in_searchable_text`
- `mattermost_participant_metadata_missing_or_mismatched`
- `teams_participant_metadata_missing_or_mismatched`
- `telegram_participant_quarantined_or_mismatched`
- `participant_filtered_as_self`
- `participant_filtered_as_owned`
- `participant_filtered_as_suppressed`
- `other_structural_mismatch:<bounded description>`

Do not speculate beyond production evidence.

## Optional local source comparison

You may compare the production structural result to connector normalization source locally.

Do not change source in this task.

If the production cause is already proven, do not broaden into a general provider audit.

## Product-data mutation proof

The diagnostic must not deliberately mutate product state.

At minimum, before/after within the read-only diagnostic session, verify counts for the target user's:

- Person Objects;
- PersonIdentity rows;
- PersonRoleTerm rows;
- PersonRoleAssignment rows;
- PendingActionPlan rows

are unchanged.

Use counts only. Do not print row contents.

Rollback and close the session.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG-D1` entry to `PROJECT_STATE.md` containing only sanitized findings:
   - production/runtime release;
   - resolution state and communication-count category;
   - participant-scan exact-display candidate count/provider categories;
   - sanitized per-provider structural summary;
   - root-cause classification;
   - explicit no provider/model call;
   - explicit no product mutation;
   - no raw identity/account/user ids.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - D1 diagnosis completed;
   - exact root-cause classification(s);
   - production/backend/client remain `67e8f14ba7ced8408086bd1ea57c2fa9f7b049dc`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - no corrective implementation is authorized until Architect review.

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
