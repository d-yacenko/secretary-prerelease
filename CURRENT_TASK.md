# Current task — ACTIVE

## REL1A.2 — Unicode lexical-identity hardening before rollout

REL1A + REL1A.1 are Architect source-accepted, but rollout is still blocked on one bounded correctness hardening found during source review.

Do only this corrective. Do not deploy production, migrate production, install the client, or start REL1B/REL1C/REL1D.

## Verified baseline

- main before this authorization: `82908a34ee36212f4beb37a5afd57a80e0429a68`
- REL1A implementation: `e7f1e79dd83e3007bc97a6dff7aa1bd083128d93`
- REL1A.1 consolidation corrective: `9de2cccd218b76c04e98049b7bcc86c36a4058fe`
- repository Alembic head: `0053`
- production backend: `2314bf72101fbd83d50a7b264154d73740e28db1`
- production Alembic: `0052 / 0052`
- installed Linux client source: `2314bf72101fbd83d50a7b264154d73740e28db1`

REL1A semantics remain accepted:

- emergent user-scoped RoleTerm vocabulary;
- exact lexical identity only;
- trim + Unicode whitespace collapse + Unicode-aware case-fold;
- semantic near-duplicates stay distinct;
- PersonRoleAssignment is reversible and not a graph edge;
- no role weights, hierarchy, Organization inference, Task-role coercion, or Assistant writes.

## Verified defect 1 — case-fold expansion can exceed persisted key columns

The accepted display bounds are:

- role display text: max 120 code points after whitespace normalization;
- context display text: max 200 code points after whitespace normalization.

The current implementation then uses Python `.casefold()` for lexical identity, but Alembic 0053 stores:

- `person_role_terms.normalized_key` as VARCHAR(120);
- `person_role_assignments.context_key` as VARCHAR(200).

Unicode case-folding is not length-preserving. A valid display string can therefore fit the public display bound while its canonical key is longer. Example classes include characters such as German sharp-s, and some Unicode case-fold mappings expand one code point into multiple code points.

The service must never let a display-valid lexical fact fall through to an uncontrolled database length error.

## Verified defect 2 — Flutter exact-match decision is not server-authoritative

The backend uses Unicode `casefold()`.

The current Flutter add-role dialog uses `toLowerCase()` in `normalizePersonRoleText` to decide whether the typed text is an exact existing term and whether to show `Создать роль «…»`.

Lowercasing is not equivalent to Unicode case-folding. Thus the client can incorrectly offer "create new" for text that the backend correctly considers the same lexical RoleTerm.

The backend currently prevents a duplicate term, so this is not a durable-data corruption bug, but the accepted reuse-first UX must not make a false lexical-identity claim.

## Required correction

### 1. Add Alembic 0054; do not rewrite accepted 0053

Create additive revision `0054` from `0053`.

Do not edit the already source-accepted 0053 migration in place.

Widen only the canonical normalized-key storage needed for the accepted display bounds:

- `person_role_terms.normalized_key`: 120 -> 360;
- `person_role_assignments.context_key`: 200 -> 600.

Update the corresponding database check constraints to permit those widened canonical-key lengths.

Keep display fields unchanged:

- `display_text`: max 120;
- `context_text`: max 200.

No semantic/data transformation is required.

The 3x storage factor is for Unicode full case-fold expansion, not permission to accept longer display text.

Preserve:

- unique `(user_id, normalized_key)`;
- active assignment uniqueness on `(user_id, person_object_id, role_term_id, context_key)`;
- all current FK/state/provenance constraints.

Downgrade must restore the 0053 schema for 0053-compatible data. Do not silently truncate keys during downgrade.

### 2. Make domain bounds explicit and fail before DB if runtime behavior exceeds storage

In the role text domain layer, define explicit canonical-key bounds corresponding to the schema, for example:

- role key max = 360;
- context key max = 600.

After `casefold()`, verify the produced key fits its canonical-key bound before persistence/search use.

This is a last-resort storage invariant, not a new user-facing lexical rule. With the current Unicode database, all display-valid inputs within the accepted 120/200 bounds should fit.

If a future runtime ever produces a larger fold, fail with the normal deterministic validation path rather than an IntegrityError/DataError.

Do not replace `casefold()` with `lower()`.

### 3. Keep server as lexical-identity authority for autocomplete

Extend the bounded role vocabulary search response so the server explicitly reports whether the current non-empty query exactly matches an existing RoleTerm under the canonical backend normalization.

Preferred response addition:

- `exact_match_term_id: UUID | null`

Equivalent typed naming is acceptable.

Requirements:

- exact match uses the canonical backend normalized key;
- exact-match detection must not depend on whether alphabetical/substring result limiting happened to place that term in the visible page;
- empty query has no exact match;
- current-user isolation remains unchanged;
- ordinary lexical substring search and its existing cap/order remain unchanged;
- do not expose semantic/fuzzy equivalence.

### 4. Flutter must consume server exact-match truth

Update the typed API/model and add-role dialog so:

- suggestions still display as today;
- a suggestion can still be selected;
- `Создать роль «…»` is shown only when the server says there is no exact lexical RoleTerm for the typed non-empty query;
- the client does not independently approximate Unicode case-fold equality with `toLowerCase()`;
- backend remains authoritative for assignment idempotence.

Avoid a new dependency merely to reproduce Python Unicode case-folding in Dart.

Handle async search safely: an older response must not overwrite the exact-match state for newer typed text if the current implementation can race. If the dialog already has this stale-response risk, fix it within this same narrow surface.

### 5. Preserve every accepted REL1A/REL1A.1 semantic boundary

Do not change:

- RoleTerm open-ended vocabulary semantics;
- semantic near-duplicate policy;
- role/context display normalization;
- 16 active-role cap;
- assignment/retract lifecycle;
- Person consolidation role copy/undo behavior;
- People workspace projection semantics;
- Task actor relations;
- Person identity matching/merge rules;
- salience;
- Personal Relevance;
- Proactive Review;
- Assistant tools/instructions;
- MCP;
- Organization;
- Scheduled Activity.

No graph Edge may be created for a role.

## Required deterministic tests

At minimum prove:

1. **0054 migration**
   - `0053 -> 0054`;
   - normalized-key columns/check constraints accept the widened canonical keys;
   - accepted indexes/uniqueness still exist;
   - downgrade restores the 0053 shape for 0053-compatible rows;
   - no unrelated Person/Task/identity data changes.

2. **Role case-fold expansion**
   - a 120-character display-valid role whose case-folded key is longer than 120 persists successfully;
   - its stored normalized key is the full canonical case-fold, not truncated.

3. **Context case-fold expansion**
   - a 200-character display-valid context whose case-folded key is longer than 200 persists successfully;
   - the full context key participates in idempotence.

4. **Unicode exact reuse**
   - create a term whose spelling demonstrates lower-vs-casefold difference, e.g. a `Straße` / `STRASSE` class case;
   - the second lexical form reuses the same RoleTerm;
   - same Person + same normalized context remains assignment-idempotent.

5. **Near-duplicate safety**
   - semantic near-duplicates such as `директор` and `генеральный директор` remain distinct.

6. **Search exact-match truth**
   - server returns the exact RoleTerm id for a query equal under canonical case-fold;
   - exact match is still reported even if bounded suggestion ordering could otherwise omit it;
   - empty/unmatched query returns null;
   - cross-user term never becomes an exact match.

7. **Flutter reuse-first truth**
   - exact server match suppresses `Создать роль`;
   - non-exact input still shows explicit create-new;
   - selecting suggestion still assigns;
   - optional context still works;
   - stale async search response cannot incorrectly flip the create/exact state for newer input.

8. **Regression**
   - existing REL1A role tests;
   - Person consolidation tests including REL1A.1 role preservation/undo;
   - People workspace tests;
   - Person identity/promotion regressions touched by projection;
   - SEM1 relation boundary;
   - focused Task relation/layout regressions.

## Required checks

Backend:

- migration 0054 focused tests;
- `backend/tests/test_rel1a_person_roles.py`;
- `backend/tests/test_person_consolidation.py`;
- `backend/tests/test_person_graph_workspace.py`;
- focused Person identity/promotion suites;
- `backend/tests/test_ah2_sem1_relation_boundary.py`;
- focused Task relation/layout suites;
- Ruff/format for changed Python files.

Client:

- role section tests;
- affected People overview/create/model/API tests;
- focused `flutter analyze` on changed files;
- `flutter build linux --debug`.

Also:

- `git diff --check`.

Record exact pass/fail counts and identify any genuine pre-existing failure precisely.

## Production / external-effect boundary

This task is source-only.

Do not:

- move `production`;
- run production migration 0053 or 0054;
- deploy backend;
- build-and-install/replace the user's installed client;
- make real model calls;
- make provider actions;
- mutate real user product data.

Production must remain:

- backend/source `2314bf72101fbd83d50a7b264154d73740e28db1`;
- Alembic `0052 / 0052`;
- installed Linux client source `2314bf72101fbd83d50a7b264154d73740e28db1`.

## Explicit non-goals

Do not start:

- REL1B role-aware importance;
- REL1C Assistant role read/write;
- REL1D screenshot/document import;
- Organization ontology;
- Scheduled Activity;
- unrelated cleanup or refactoring.

Do not redesign the People surface.

## Completion protocol

After implementation:

1. append a compact REL1A.2 result to `PROJECT_STATE.md` with:
   - exact migration/schema changes;
   - exact normalization/storage invariant;
   - server-authoritative exact-match API behavior;
   - client stale-response behavior if changed;
   - exact test/build evidence;

2. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - Alembic head `0054`;
   - changed files;
   - exact pass/fail counts;
   - confirmation that REL1 semantics remain unchanged;
   - confirmation that Personal Relevance/Proactive/Assistant/MCP were untouched;
   - production still `2314bf72101fbd83d50a7b264154d73740e28db1`, Alembic `0052 / 0052`;
   - no production deploy/migration/client install/model/provider call;

3. commit + push to `main`;

4. STOP.

Do not start rollout or the next product slice from HOLD.
