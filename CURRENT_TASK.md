# Current task — ACTIVE

## REL1B-A.1 — close v2 stale-authority race and make Proactive regressions data-independent

REL1B-A implementation `0859fc4ebeb49db06f9ab12efc2f9acb552ecab9` is directionally accepted, but NOT yet Architect source-accepted.

Architect review found one real concurrency gap introduced by Personal Relevance evidence v2, plus one test-determinism problem that prevents the required Proactive regression suites from being green on the current repository database.

Do only this corrective.

Do not start REL1B-B, deploy, migrate, install the client, call a real model/provider, or mutate existing bootstrap notifications.

## Baseline that must remain unchanged

- Personal Relevance evidence version: `2`
- schema head: `0054`
- production backend/source: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- production Alembic: `0054 / 0054`
- installed Linux client source: `6f802d6959aca40758376a83d5bdfcbbd77fc537`

REL1B-A evidence semantics stay unchanged:

- exact active current-user PersonIdentity grounding only;
- no fuzzy/name/salience/promotion matching;
- max 8 known People per object;
- max 8 active roles per known Person;
- deterministic neutral ordering;
- active role display text + optional context only;
- Proactive LLM seed still does NOT receive `known_people`/role evidence in B-A.

## Verified concurrency defect

Evidence v2 signatures now include mutable known-Person facts:

- exact `PersonIdentity` grounding;
- active Person visibility/title;
- active `PersonRoleAssignment` / RoleTerm display evidence.

The existing Proactive stale fence acquires `lock_user_serialization_row()` only after the model run, then rebuilds a fresh Personal Relevance snapshot before persisting a notification.

However REL1A identity/role writers currently do not participate in that user-serialization gate:

- `PersonRoleService.assign()`
- `PersonRoleService.retract()`
- `PersonIdentityService.attach()`
- `PersonIdentityService.detach()`
- `PersonIdentityService.reassign()`
- Person consolidation apply/undo also moves identities/roles and changes Person visibility directly.

Therefore a role/identity mutation can currently commit after the fresh v2 snapshot and before notification flush, making the notification rely on stale evidence.

This must be closed before REL1B-B exposes role evidence to model judgment.

## Required concurrency correction

### 1. Serialize role writes through the existing user gate

In `PersonRoleService`:

- `assign()` must acquire the current user's serialization row before reading existing assignment/count and before any vocabulary/assignment write;
- `retract()` must acquire the same gate before reading/mutating the assignment;
- search/read methods remain read-only and must not take an unnecessary write serialization lock.

Use the existing `lock_user_serialization_row` helper and fail consistently if the user row is absent.

Do not change role lexical semantics, cap, provenance, or idempotence.

### 2. Serialize exact PersonIdentity writes through the same gate

In `PersonIdentityService`, gate mutation paths that can change exact grounding:

- `attach()`
- `detach()`
- `reassign()`

Do not add a gate to pure reads.

`create_person()` alone does not change source-object grounding and need not be broadened merely for this task; when an identity is attached, the gated path applies.

Preserve existing identity conflict/idempotence semantics.

### 3. Serialize Person consolidation mutations

`PersonConsolidationService.apply()` and `undo()` must acquire the same user serialization gate before assessment/mutation because consolidation can:

- move exact identities;
- tombstone/restore a Person;
- copy/retract role assignments.

`preview()` remains read-only.

Do not change merge semantics or audit format.

### 4. Lock initial known-Person rows during Proactive authority

The user gate prevents new identity/role mutations after authority is acquired, but generic Person Object updates (for example title/state/deletion paths) do not necessarily use that gate.

Extend the Personal Relevance authority phase so that all Person IDs present in the **initial** snapshot's `known_people` are locked `FOR UPDATE` in deterministic UUID order before the fresh snapshot is accepted.

Preferred API shape:

- pass the initial snapshot or a deduplicated initial known-Person id set into `acquire_personal_relevance_authority()`;
- keep the authority function internal and explicit.

Requirements:

- user ownership and kind=person must be checked;
- deterministic lock order;
- use `populate_existing=True` as appropriate;
- missing/changed Person before the lock must not be silently trusted — the subsequent fresh snapshot/signature comparison must fail stale if evidence changed;
- do not lock every Person in the user's graph;
- do not lock unrelated role vocabulary globally beyond the short existing user serialization gate.

After authority is held:

- a Person title/state/deletion mutation for a known participant must be unable to commit until notification persistence releases the transaction;
- exact identity/role/consolidation writes must be unable to commit because they use the same user gate.

### 5. Preserve existing stale semantics

Changes that happen before authority is acquired are allowed to commit; the fresh snapshot must then detect them and discard the pending notification as stale.

Changes attempted after authority is acquired must block/fail on lock timeout in concurrency tests until the notification transaction finishes.

Do not add a second stale mechanism.

Do not change:

- `ProactiveDecision`;
- default NONE/silence;
- notification gates;
- read-tool allowlist;
- Proactive instructions;
- role evidence exposure boundary.

## Required multi-session race tests

Use the existing isolated-user / separate-session style in the Proactive personalization suite.

Add deterministic regressions that prove at least:

1. **role write before authority**
   - source has exact known Person + role evidence;
   - another session changes/retracts/adds relevant role in the existing `after_llm` hook;
   - writer commits before authority;
   - fresh snapshot differs;
   - no notification persists.

2. **role write after authority**
   - in `after_authority`, another session sets a short local lock timeout and attempts `PersonRoleService.assign()` or `retract()`;
   - operation cannot acquire the serialization gate while notification transaction holds authority;
   - notification can persist only from unchanged evidence.

3. **identity write before authority**
   - another session attaches/detaches/reassigns a source-relevant exact identity before authority;
   - fresh evidence changes;
   - notification is discarded.

4. **identity write after authority**
   - another session with short lock timeout attempts an exact identity mutation;
   - user serialization gate blocks it until authority transaction completes.

5. **Person display/state write after authority**
   - source already resolves to known Person;
   - another session attempts a direct Person Object update through the normal service/path after authority;
   - participant Person row lock prevents commit during the authority window.

6. **consolidation after authority**
   - relevant Person consolidation apply/undo cannot race past the authority gate.

Keep lock-order tests deterministic; no sleeps as correctness primitives.

## Existing Proactive test contamination

The current database already contains 5 committed bootstrap-user notifications titled:

`Дневной лимит OpenAI исчерпан`

dated 2026-09-14 through 2026-09-18.

The required Proactive suites currently report 22 failures because several tests assume the bootstrap user's notification table is globally empty or contains exactly one row.

These are pre-existing rows and must NOT be deleted, edited, hidden in product code, or cleaned from the database.

## Required test-determinism correction

Make the two affected Proactive test modules independent of pre-existing bootstrap notification rows:

- `backend/tests/test_proactive_secretary_c.py`
- `backend/tests/test_workflow_intelligence_proactive_personalization_e_c.py`

Preferred approaches:

- use an isolated temporary user for tests that require absolute notification counts; or
- capture a per-test baseline set/count and assert only the exact notification delta/source produced by the code under test.

Requirements:

- a test expecting “no notification created” must prove **no new notification** was created, not assert the user's historical table is empty;
- a test expecting one notification must prove exactly one new notification with the expected source/kind was created;
- duplicate-suppression tests must still prove no second new notification;
- do not weaken assertions into loose `>=` checks where exact behavior matters;
- do not special-case the Russian title or the number 5;
- do not delete committed notification rows in test setup;
- do not change product notification behavior merely to satisfy tests.

A small shared test helper for baseline/new notification IDs is preferred if it keeps the tests clear.

## Required checks — all must be green before HOLD

Run at minimum:

1. `backend/tests/test_rel1b_person_role_relevance_evidence.py`
2. `backend/tests/test_rel1a_person_roles.py`
3. `backend/tests/test_workflow_intelligence_personal_relevance_e_b.py`
4. `backend/tests/test_workflow_intelligence_proactive_personalization_e_c.py`
5. `backend/tests/test_proactive_secretary_c.py`
6. focused Person identity tests;
7. focused Person consolidation tests;
8. new multi-session race tests;
9. Ruff on changed Python files;
10. `git diff --check`.

The two Proactive suites that previously had 22 environment-sensitive failures must now report **0 failed** without deleting the pre-existing notifications.

Record exact pass/fail counts per grouped run.

## Scope boundary

Expected changed product files are narrowly limited to some subset of:

- `backend/app/services/person_role_service.py`
- `backend/app/services/person_identity_service.py`
- `backend/app/services/person_consolidation_service.py`
- `backend/app/services/personal_relevance_evidence_service.py`
- focused tests.

A tiny shared test helper is acceptable.

Do not modify:

- Personal Relevance evidence shape/version;
- known-Person provider extraction semantics;
- role caps/order;
- Proactive seed exposure;
- Proactive instructions;
- notification product logic;
- Alembic;
- client.

If another production file seems necessary, stop and explain it in HOLD instead of broad refactoring.

## Production / external-effect boundary

Source-only.

Do not:

- move `production`;
- deploy backend;
- run Alembic;
- install/replace client;
- delete the five existing bootstrap notifications;
- mutate production People/roles;
- run a real model;
- call providers.

Production/client remain exact `6f802d6959aca40758376a83d5bdfcbbd77fc537`, Alembic `0054 / 0054`.

## Completion protocol

After the corrective:

1. append a compact REL1B-A.1 result to `PROJECT_STATE.md` with:
   - exact writer serialization changes;
   - exact authority Person-row locking;
   - race-test evidence;
   - exact deterministic Proactive suite counts;
   - confirmation existing bootstrap notifications were untouched;

2. return `CURRENT_TASK.md` to HOLD with:
   - corrective implementation SHA;
   - evidence version still 2;
   - schema still 0054;
   - exact green test counts;
   - production/client unchanged;
   - no deploy/migration/client/model/provider/data cleanup;
   - REL1B-B not started;

3. commit + push to `main`;

4. STOP.

Do not start REL1B-B from HOLD.
