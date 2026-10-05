# CURRENT_TASK

ACTIVE

## REL1D-HG2C1 — provider repair/refetch capability audit and bounded repair-plan evidence

The REL1D source-corrective train through HG2B3 is ARCHITECT SOURCE-ACCEPTED.

Accepted corrective implementations include:

- HG2A / HG2A.1 — role-import 90-day / 10,000-row communication scan contract;
- HG2B1 — Mattermost human author display preservation;
- HG2B2 — Gmail/Yandex named recipient preservation;
- HG2B3 — Telegram MTProto cached inbound sender human identity preservation;
- HG2B3.1 / HG2B3.2R — test-only cleanup needed to return the relevant source suite to green.

Production/backend/client remain:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Alembic remains:

`0054 / 0054`

Human REL1D acceptance remains paused.

No accepted HG2 source corrective has been rolled out to production yet.

This task is READ-ONLY / SOURCE-AUDIT ONLY.

Do not implement repair.
Do not call providers.
Do not inspect or mutate production data.
Do not deploy.

## Goal

Produce a code-grounded operational audit of how legacy communication rows could later be repaired/refetched safely, provider by provider, without guessing or silently broadening connector semantics.

The audit must cover exactly:

1. Mattermost
2. Gmail
3. Yandex Mail
4. Microsoft Teams
5. Telegram MTProto

Telegram Business is explicitly OUT OF SCOPE except for one factual note that it remains a separate architecture/parser decision and is not included in the repair plan.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`

Then inspect at minimum:

### Mattermost

- `backend/app/connectors/mattermost/sync.py`
- `backend/app/connectors/mattermost/mattermost_history_state.py`
- `backend/app/connectors/mattermost/normalize.py`
- `backend/app/connectors/mattermost/materialize.py`
- directly relevant Mattermost tests

### Gmail

- `backend/app/connectors/google/gmail_sync.py`
- `backend/app/connectors/google/gmail_history_state.py`
- `backend/app/connectors/google/gmail_normalize.py`
- Gmail materialization/upsert path used by sync
- directly relevant Gmail history/backfill tests

### Yandex Mail

- `backend/app/connectors/yandex/mail_sync.py`
- `backend/app/connectors/yandex/mail_history_state.py`
- `backend/app/connectors/yandex/mail_normalize.py`
- IMAP fetch path used by sync
- Yandex materialization/upsert path
- directly relevant Yandex history/backfill tests

### Teams

- `backend/app/connectors/teams/sync.py`
- `backend/app/connectors/teams/transport.py`
- `backend/app/connectors/teams/normalize.py`
- `backend/app/connectors/teams/materialize.py`
- relevant Teams sync tests
- historical commit/context around `92aef7e6c9fb2e5acd6afc7056b26ea67ea99d07` only as needed to establish why missing legacy `sender_kind` cannot be repaired heuristically

### Telegram MTProto

- `backend/app/services/telegram_mtproto_history_service.py`
- `backend/app/connectors/telegram/mtproto_transport.py`
- `backend/app/connectors/telegram/materialize.py`
- relevant reconcile/history tests, including HG2B3 tests

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.
Do not move `production`.

## Required output artifact

Create exactly one source-audit document:

`docs/rel1d_hg2_provider_repair_audit.md`

This is an operational repair audit for Executor/Architect coordination, not Architect recovery context.

Do not copy or reconstruct private/local Architect context into it.

## Required audit structure

The document must contain:

### 1. Scope and invariants

State explicitly:

- source review only;
- no provider calls;
- no production DB access;
- no mutation;
- no deployment;
- no schema/migration;
- current production/backend/client SHA;
- current Alembic head;
- accepted HG2 source contracts are not yet rolled out.

### 2. Provider capability matrix

For each of the five providers, record all of the following from source:

- exact current sync/history/reconcile entrypoint(s);
- whether current code can revisit OLD already-stored communications;
- how the revisit is bounded:
  - days/window;
  - row/page/message limit;
  - cursor/history state;
  - per-run cap;
- exact provider fetch primitive(s) that would be invoked;
- whether the current normalizer would produce the newly required identity metadata;
- exact materializer/upsert identity used to find the existing Object;
- whether reprocessing updates the same Object or risks duplication;
- whether sync/history state is mutated by the existing path;
- whether a repair can be targeted without resetting/advancing ordinary sync state;
- classification:
  - `SAFE_EXISTING_REUSE`
  - `REQUIRES_DEDICATED_BOUNDED_REPAIR`
  - `NOT_REPAIRABLE_FROM_CURRENT_PROVENANCE`
- source path/test evidence for each conclusion.

Do not infer capabilities not present in code.

### 3. Provider-specific questions that MUST be answered

#### Mattermost

Determine whether existing bounded history/backfill can safely revisit legacy posts and enrich the SAME Object with HG2B1 profile-derived display fields.

Record whether ordinary history state would be advanced/mutated and whether that makes direct reuse unsuitable for a one-off controlled repair.

#### Gmail

Determine whether existing history/backfill/refetch paths preserve enough provider identifiers to re-fetch legacy messages and pass them through HG2B2 normalization.

Explicitly distinguish:

- stored rows that remain refetchable from provider message identity;
- rows for which missing account/provenance prevents safe refetch;
- whether ordinary Gmail history state would be changed.

Do not assume missing `source_account_email` can be reconstructed.

#### Yandex Mail

Determine the equivalent facts for IMAP/Yandex:

- stable stored provider/mailbox/message identifiers;
- whether legacy rows can be fetched again safely;
- whether mailbox UID semantics/provenance permit exact repair;
- whether ordinary mail history state would be changed.

Do not invent a refetch path if the current source does not expose one.

#### Teams

Determine whether current sync code has any bounded historical refetch path capable of repairing pre-`92aef7e6c9fb2e5acd6afc7056b26ea67ea99d07` rows.

Missing legacy `sender_kind` MUST remain ambiguous.

No heuristic mapping of missing kind to `user`.

If current code only supports forward/overlap sync and cannot safely target old rows, classify it accordingly and identify the smallest source primitive a future dedicated repair would have to reuse, without implementing it.

#### Telegram MTProto

Determine exactly how `reconcile_recent_messages(...)` revisits already-stored Objects:

- row limit;
- peer rotation/cursors;
- provider call primitive;
- existing Object identity;
- metadata update behavior;
- how HG2B3 fields now flow through it.

Determine whether it is suitable for a later explicitly authorized bounded repair as-is or requires a dedicated repair wrapper/state isolation.

Do not run reconcile.

### 4. Proposed repair sequence — DESIGN ONLY

Based only on verified source capabilities, propose a provider-by-provider ordering.

For each provider include:

- prerequisite accepted source SHA;
- preflight counts needed before mutation;
- exact maximum batch/window bound to use or, if current code is unsuitable, state `TBD — dedicated repair required`;
- stop conditions;
- post-run verification counts;
- rollback semantics that are actually possible from current materializer/data model.

Do not claim DB rollback is available unless source proves it.

Prefer stop-and-review between providers rather than one cross-provider batch.

### 5. Release boundary

Record that this audit does NOT authorize:

- selecting/moving a release SHA to production;
- backend rollout;
- client rollout;
- provider repair/refetch;
- backfill;
- reconcile;
- Telegram Business parsing;
- human REL1D acceptance.

The final Architect will separately select one accepted source release SHA and separately authorize rollout and each data-repair slice.

## Evidence discipline

Every technical conclusion in the audit must name the exact source file and function/class/test that supports it.

If a point cannot be proven from repository source/tests, write:

`UNPROVEN FROM CURRENT SOURCE`

Do not fill gaps with assumptions.

Do not use live provider accounts, credentials, secrets, production logs, production DB, screenshots, or manual UI.

## Required checks

Because this task is documentation/source-audit only:

- verify `git diff --check` is clean;
- verify the only non-ledger new artifact is `docs/rel1d_hg2_provider_repair_audit.md`;
- no runtime Python/client/migration file may change.

No provider-backed test or live integration test is authorized.

Local unit tests are not required unless needed solely to understand an existing code contract; if run, they must use existing fake/local transports only and the exact result must be recorded.

## Completion protocol

On success:

1. add `docs/rel1d_hg2_provider_repair_audit.md`;
2. append a compact `REL1D-HG2C1` entry to `PROJECT_STATE.md` containing:
   - implementation SHA;
   - artifact path;
   - classification for each provider;
   - explicit no provider/production/runtime/schema/deploy action;
   - `git diff --check` result;
3. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2C1 implementation SHA;
   - audit ready for Architect review;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - no rollout/repair/backfill/reconcile/Telegram Business/next task without fresh Architect authorization;
4. commit + push to `main`;
5. STOP.

On blocker:

- record the exact source evidence gap;
- return HOLD;
- do not implement missing repair functionality;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
