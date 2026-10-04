# CURRENT_TASK

ACTIVE

## REL1D-HG1.5.1 — batch mention revalidation into one bounded scan

REL1D-HG1.5 implementation:

`8f3c748a805956eeed137d67ee1c75b81e49fb25`

is **NOT YET SOURCE-ACCEPTED**.

Architect review found one narrow execution-path contract violation.

Grounding correctly evaluates all extracted names through one bounded communication scan:

`PersonRoleImportMentionEvidenceService.evidence_for([...all names...])`

and the existing test `test_mention_scan_runs_once_for_the_batch` proves that grounding behavior.

However, ActionPlan execution currently calls:

`mentions.evidence_for([row.extracted_person_name])`

inside `_mention_person(...)`.

Therefore a batch containing several **different** mention-backed selected names can rescan the same bounded communication universe once per name during approve.

This violates the explicit HG1.5 requirement:

> scan once for the requested name set, not one DB scan per row.

This task is ONLY to batch approve-time mention revalidation into one bounded scan.

Do not redesign HG1.5.
Do not deploy/install anything.

## Exact current live state

Production/backend/client remain:

`67e8f14ba7ced8408086bd1ea57c2fa9f7b049dc`

Alembic remains:

`0054 / 0054`

Human REL1D acceptance remains paused.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- `backend/app/services/person_role_import_batch_service.py`
- `backend/app/services/person_role_import_mention_service.py`
- `backend/tests/test_rel1d_role_import_mentions.py`
- directly affected batch tests.

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.

Do not move `production`.

## Required implementation

In `PersonRoleImportBatchService.execute(...)`, after:

- user serialization lock succeeds;
- source lock/validation succeeds;

collect the unique extracted names for selected rows whose:

`evidence_kind == "name_mentions"`

Then call the existing mention evidence service exactly **once**:

`mention_evidence = mentions.evidence_for(unique_names)`

Requirements:

1. one `evidence_for(...)` call per ActionPlan execute, regardless of how many distinct mention-backed selected rows exist;
2. zero calls when the selected batch contains no mention-backed rows;
3. reuse that returned map for all mention-backed row revalidation;
4. no per-row mention DB rescan;
5. keep exact current HG1.5 candidate-key/display/threshold semantics;
6. keep normal Person resolution revalidation per row;
7. keep stronger identity-backed participant revalidation;
8. keep name-only Person creation through canonical `create_person`;
9. keep zero `PersonIdentity` / zero `PersonIdentityEvidence` for mention-only creation;
10. keep same-batch candidate reuse;
11. keep ActionPlan transaction atomicity and rollback behavior.

It is acceptable to change helper signatures such as:

- `_person_target(..., mention_evidence, ...)`
- `_mention_person(..., mention_evidence, ...)`

Prefer the smallest clear change.

## Important execution snapshot semantics

The one approve-time mention scan is the revalidation snapshot for all mention-backed rows in that ActionPlan execution.

Do not re-read mention evidence later in the same execution after the first mention-backed Person is created.

Strong identity participant eligibility may remain the existing one precomputed `contacts` list.

Do not introduce provider/model calls.

## Required tests

Add or modify focused tests proving at minimum:

1. an approved batch with **two different** mention-backed names calls `PersonRoleImportMentionEvidenceService.evidence_for` exactly once during execute;
2. that single call receives both unique names;
3. two selected rows for the same mention-backed name still create one Person and reuse it;
4. batch with no mention-backed selected rows performs zero approve-time mention scans;
5. lost mention evidence still fails with `role_import_grounding_changed`;
6. stronger identity-backed candidate appearing before approve still fails mention execution with grounding changed;
7. later-row failure still rolls back the name-only Person and role assignments;
8. mention-backed approval still creates zero identities/evidence;
9. existing HG1.5 grounding one-scan test remains green;
10. generic promotion and HG1.4 participant behavior remain unchanged.

Be careful when measuring execute-time calls:

- prepare/ground legitimately performs its own one scan;
- reset the spy/counter after plan preparation, or patch only around approval/execution.

Run at minimum:

- `backend/tests/test_rel1d_role_import_mentions.py`
- `backend/tests/test_rel1d_role_import_batch.py`
- `backend/tests/test_rel1d_role_import_grounding.py`
- `backend/tests/test_rel1d_role_import_participants.py`
- `backend/tests/test_person_promotion.py`
- Ruff on touched Python
- `git diff --check`.

Client changes are not expected.

Do not touch client files merely to rerun accepted UI work.

## Explicit non-goals

Do not:

- change `MIN_ROLE_IMPORT_NAME_MENTION_OBJECTS = 2`;
- change exact-name/token-boundary matching;
- add fuzzy/PER1/LLM matching;
- change grounding precedence;
- change resolved/ambiguous mention fallback;
- change identity-backed HG1.4 participant logic;
- change generic `MIN_DIRECT_HITS` promotion;
- attach identities to mention-only People;
- change Gmail/Yandex normalization;
- add schema/migrations;
- change dependencies;
- deploy backend;
- move `production`;
- build/install client;
- call provider/model APIs;
- mutate production product data;
- start another product slice.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG1.5.1` entry to `PROJECT_STATE.md` including:
   - implementation SHA;
   - changed files;
   - exact batched approve-time scan behavior;
   - execute-time one-scan test evidence;
   - exact focused test totals;
   - Ruff/diff-check result;
   - confirmation HG1.5 semantics otherwise unchanged;
   - confirmation no deploy/install/migration/provider/model/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG1.5.1 implementation SHA;
   - HG1.5 + HG1.5.1 ready for Architect source review;
   - production/backend/client remain `67e8f14ba7ced8408086bd1ea57c2fa9f7b049dc`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - do not rollout or start another slice.

3. commit + push to `main`.

4. STOP.

On blocker:

- record the exact bounded blocker;
- return HOLD;
- commit/push accurate ledger if appropriate;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
