# CURRENT_TASK

ACTIVE

## REL1D-HG2A — remove shared top-400 starvation from role-import evidence scans

REL1D-HG-D3 is ARCHITECT-ACCEPTED.

D3 proved that the shared newest-`MAX_PERSON_SCAN_ROWS=400` communication window is materially starving strong role-import evidence across providers:

- full 90-day communication universe: 4481 Objects;
- newest-400 cutoff: 2026-09-30T13:50:46Z;
- strong Gmail/Yandex/Teams/Telegram identities frequently exist outside the newest 400;
- high-volume Mattermost occupies 260/400 rows while currently yielding zero identities.

This task is ONLY the provider-neutral source corrective for role-import scan starvation.

Do not fix connector normalization in this task.
Do not repair/backfill production rows.
Do not deploy/install anything.

## Exact current live state

Production/backend/client remain:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Alembic remains:

`0054 / 0054`

Human REL1D acceptance remains paused.

## Architectural rule

The generic Person/Assistant bounded communication contract remains unchanged:

`MAX_PERSON_SCAN_ROWS = 400`

Do not globally increase it.

Role import is an explicit, user-triggered, bounded operation over at most 32 extracted names and needs a larger independent evidence window so one high-volume provider cannot hide strong identities from other providers.

Introduce a role-import-only ceiling:

`MAX_ROLE_IMPORT_COMMUNICATION_SCAN_ROWS = 10_000`

and keep:

`PERSON_LOOKBACK_DAYS = 90`

The role-import ceiling is a hard safety bound, not a statement that 10,000 rows equal complete history.

Positive evidence found within the bound is usable.
Absence under truncation remains fail-closed.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- `backend/app/domain/person_assistant.py`
- `backend/app/domain/role_import_participants.py`
- `backend/app/services/person_assistant_service.py`
- `backend/app/services/person_promotion_service.py`
- `backend/app/services/person_role_import_grounding_service.py`
- `backend/app/services/person_role_import_mention_service.py`
- `backend/app/services/person_role_import_batch_service.py`
- relevant focused tests.

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.

Do not move `production`.

## Required scan semantics

Every role-import evidence path below must use the role-import-only 90-day ceiling of 10,000 rows rather than the generic 400-row ceiling.

### A. Identity-backed not-yet-Person participant discovery

The HG1.4 role-import participant scan used by:

- grounding;
- approve-time revalidation;

must inspect up to the newest 10,000 qualifying communication Objects in the 90-day role-import window.

Qualifying base rows remain:

- current user only;
- active;
- non-rejected;
- kinds `email` and `chat_message`;
- same Telegram Assistant gate/quarantine predicate;
- same deterministic newest-first ordering.

Do not change participant parsing semantics in `participant_identities(...)`.

In particular do not fix:

- missing Mattermost human display;
- missing Teams `sender_kind`;
- missing Telegram inbound display;
- Telegram Business unsupported transport;
- email recipient display loss.

Those are later tasks.

### B. Mention-backed evidence

`PersonRoleImportMentionEvidenceService` must use the same 90-day role-import-only 10,000-row ceiling.

Preserve HG1.5 semantics exactly:

- threshold = 2 distinct Objects;
- exact normalized multi-token phrase;
- Unicode token boundaries;
- title/body/email subject fields only;
- one Object counts once;
- no fuzzy/PER1/LLM matching.

Grounding still scans requested names once per requested-name set.

Approve-time HG1.5.1 still scans all selected mention-backed names once per execution.

### C. Existing resolved / ambiguous Person communication gate

Role-import grounding currently relies on `PersonAssistantService.count_attributable_communications(...)`.

Do not change its generic default behavior.

Add a role-import-specific bounded option/path so that **only role-import grounding** counts attributable communications over up to 10,000 rows.

Acceptable approaches include:

- optional explicit `max_scan_rows` / scan-policy argument with default 400;
- a dedicated role-import method;
- a small shared scan policy object.

Requirements:

- every non-role-import caller keeps historical 400-row semantics;
- role-import resolved/ambiguous filtering uses the 10,000-row ceiling;
- exact identity attribution semantics stay unchanged;
- no display/fuzzy matching is introduced into PersonAssistant attribution.

## Query implementation

The implementation must remain bounded and deterministic.

Preferred implementation:

- fetch in bounded pages/chunks rather than one unbounded query;
- page size may reuse 400;
- stop after at most 10,000 qualifying rows;
- preserve ordering by `coalesce(occurred_at, created_at) DESC` plus stable Object id tie-break;
- return/propagate whether the role-import ceiling was truncated.

A single `LIMIT 10001` query is acceptable only if it preserves the same deterministic semantics and tests prove the hard bound; do not load an unbounded 90-day set.

Do not use OFFSET-based pagination if concurrent inserts could duplicate/skip rows across pages; prefer one bounded query or stable keyset semantics.

No provider calls.

## Truncation semantics

Role-import must distinguish:

- complete within 90 days;
- truncated at 10,000.

Existing fail-closed rules remain:

- positive strong identity evidence inside the bound is usable;
- positive mention evidence >=2 inside the bound is usable;
- zero participant evidence under truncation does not prove lifetime absence;
- zero/one mention hit under truncation does not qualify;
- do not show a false statement that the person has no communication in all history.

No client UI change is required solely for the 10,000 ceiling unless existing wire models already carry a safe truncation flag and a directly affected test needs adaptation.

Do not expose row counts or internal scan bounds to the user unless already part of an existing safe diagnostic field.

## Approval consistency

Approve-time revalidation must use the same role-import scan ceiling as grounding.

This includes:

- identity-backed participant revalidation;
- mention-backed revalidation;
- existing Person role-import checks if re-evaluated during execution.

A plan must not ground under 10,000 rows and then approve under 400.

HG1.5 stronger-evidence precedence remains:

- if a mention-backed plan is prepared;
- and a strong identity-backed candidate is available inside the role-import evidence window at approve time;
- approval fails with `role_import_grounding_changed`.

## Generic behavior must remain unchanged

Do not change semantics of:

- `MAX_PERSON_SCAN_ROWS = 400`;
- generic `PersonPromotionService.overview()`;
- generic `eligible_direct_contacts()`;
- generic `approve()`;
- normal Assistant Person relevance/salience attribution;
- non-role-import `PersonAssistantService` callers.

Add regression tests proving this.

## Required backend tests

At minimum prove:

1. role-import identity participant older than the newest 400 but within row 401..10,000 is discovered;
2. the same row remains invisible to generic 400-row direct-contact/person scan where historical semantics require that;
3. mention evidence with two exact-name Objects both older than newest 400 but within 10,000 qualifies;
4. one mention Object older than 400 still does not qualify;
5. resolved existing Person whose only attributable communication is older than newest 400 but within 10,000 remains actionable in role import;
6. ambiguous Person candidate with attributable communication outside newest 400 but within 10,000 survives role-import filtering and remains ambiguous;
7. generic PersonAssistant/default count remains capped at 400;
8. generic promotion remains capped/unchanged;
9. role-import participant grounding and approve-time revalidation use the same expanded ceiling;
10. mention prepare/approve use the same expanded ceiling;
11. strong identity appearing outside newest 400 supersedes a mention-backed plan at approve and yields `role_import_grounding_changed`;
12. hard role-import ceiling never reads more than 10,000 qualifying rows plus at most one sentinel row;
13. when >10,000 qualifying rows exist and target evidence is beyond the ceiling, zero evidence remains fail-closed and no Person is created;
14. Telegram gate/quarantine behavior is unchanged;
15. no provider/model call occurs.

Use focused fixtures/mocks rather than materializing 10,001 heavyweight DB Objects if a lighter deterministic test can prove the query ceiling.

Run at minimum:

- `backend/tests/test_rel1d_role_import_grounding.py`
- `backend/tests/test_rel1d_role_import_participants.py`
- `backend/tests/test_rel1d_role_import_mentions.py`
- `backend/tests/test_rel1d_role_import_batch.py`
- directly affected PersonAssistant tests
- directly affected generic Person promotion tests
- Ruff on touched Python
- `git diff --check`.

Client files should not change.

## Explicit non-goals

Do not:

- change Mattermost normalization;
- change Teams normalization/parser discriminators;
- infer missing Teams `sender_kind`;
- change Telegram normalization/parser support;
- add Telegram Business support;
- change Gmail/Yandex recipient metadata;
- repair account provenance;
- call providers;
- sync/backfill;
- mutate product data;
- add schema/migrations;
- change dependencies;
- deploy backend;
- build/install client;
- broaden mention matching;
- change generic Person scan limits;
- start another product slice.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG2A` entry to `PROJECT_STATE.md` with:
   - implementation SHA;
   - files changed;
   - exact role-import-only scan ceiling/page semantics;
   - confirmation generic 400-row contracts unchanged;
   - exact focused test totals;
   - Ruff/diff-check result;
   - confirmation no connector semantics, deploy/install/migration/provider/model/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2A implementation SHA;
   - source ready for Architect review;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - next planned class after Architect review is connector normalization/parser contract correction, not rollout unless Architect explicitly authorizes it;
   - do not start another task.

3. commit + push to `main`.

4. STOP.

On blocker:

- record the exact bounded blocker;
- return HOLD;
- commit/push accurate ledger if appropriate;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
