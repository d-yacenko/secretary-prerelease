# Current task — PC1-H2: identity-conflict truth + grounded merge UX

## State

- PC1 backend release in production: `a3d546b069e7e05d68fd42906c662c3ba34caef5`.
- Production Alembic: `0051`.
- Exact-release human gate exposed real-data defects after merge.
- PC1 is NOT yet human-accepted.
- PT1 and all later roadmap slices remain unauthorized.

## Goal

Make Person consolidation semantically trustworthy on real data by fixing three bounded defects:

1. A successfully merged survivor must not show a false identity conflict merely because USER_CONFIRMED evidence is intentionally retained on the tombstoned duplicate for audit/undo.
2. `Возможно, это один человек → Объединить` must not be offered just because some source identity is owned by another Person. Ownership conflict alone is not evidence that the two Person objects are duplicates.
3. The merge picker must use deterministic People lookup by Person title and effective identity canonical/display values, not generic semantic object search.

No new ontology, no Task↔Person feature, no social roles, no Secretary Person context.

## H2A — active-person conflict semantics

Review `PersonGraphWorkspaceService._is_conflicted()` and every related conflict read.

Conflict truth for an active Person must consider only other ACTIVE same-user Person owners/confirmations.

Historical USER_CONFIRMED evidence retained on a tombstoned/absorbed duplicate is audit history and must not make the active survivor conflicted.

Requirements:
- preserve audit/undo evidence exactly; do NOT delete or rewrite historical evidence to hide the symptom;
- filter conflict ownership/confirmation truth through active same-user Person objects;
- keep genuine active Person-vs-Person identity conflicts visible and fail-closed;
- add regression: merge two People where duplicate has USER_CONFIRMED evidence, then survivor rooted workspace has no false identity conflict; undo restores prior conflict truth where applicable.

## H2B — grounded conflicting candidate semantics

Current source-candidate logic must not emit a merge CTA solely because an extracted source identity is owned by another Person.

A conflicting identity may be surfaced as a possible duplicate only when there is independent deterministic grounding to the CURRENT Person.

Use the narrowest existing evidence model. Acceptable grounding includes:
- the identity already independently matches the current Person through existing candidate/evidence logic; or
- a deterministic same-source/same-conversation linkage to an effective identity already owned by the current Person, if the repository already has such a trustworthy primitive.

Do NOT:
- infer duplicate People from display-name similarity alone;
- use LLM/fuzzy matching;
- invent manager/colleague/social semantics;
- treat “identity belongs to another Person” itself as grounding.

If safe grounding cannot be established with existing primitives, omit the duplicate CTA rather than guess.

Add regressions:
- unrelated Person-owned identity found in the global bounded source scan does NOT appear as a merge suggestion for the current Person;
- a genuinely grounded duplicate conflict still exposes `conflicting_person_id` and merge CTA.

## H2C — merge picker lookup

In `_MergePersonDialog`, replace generic `searchObjects(... kind: 'person')` lookup with the existing People workspace deterministic search contract.

Search must support case-insensitive substring matching over:
- Person title;
- effective PersonIdentity canonical_value;
- effective PersonIdentity display_value.

Requirements:
- partial opaque identity substring must find the Person; user must not type the full random ID;
- exclude current Person;
- active People only;
- deterministic ordering from People workspace;
- no semantic/vector search for this picker.

Keep preselected conflict shortcut behavior.

## Preview clarity

Without redesigning the dialog, make survivor/duplicate direction unmistakable.

At minimum:
- preserve explicit `Остаётся:` and `Исчезает:`;
- when dialog is opened from a conflict shortcut, show enough exact identity cue to understand why the other Person was proposed;
- keep `Поменять, кто останется` visible before final confirmation.

Do not auto-select or auto-merge.

## Tests

Backend focused suites must cover:
- consolidation + post-merge rooted workspace conflict truth;
- undo conflict truth;
- unrelated occupied identity does not create duplicate CTA;
- grounded duplicate still can create CTA;
- existing identity review/conflict behavior remains fail-closed.

Flutter focused tests must cover:
- partial identity substring finds merge target;
- title lookup still works;
- current Person excluded;
- preselected conflict target preview works;
- swap survivor action remains;
- blocker still disables `Объединить людей`.

Run Ruff / relevant Flutter analyze and `git diff --check`.

No migration expected; Alembic must remain `0051`.

## Production safety

Do not deploy.

Do not move `origin/production`.

Do not run merge/undo or any Person write in production.

Do not attempt to repair the user's current production data.

The human tester will use the existing PC1 undo control separately to reverse the test merge.

## Completion

1. Implement H2 and commit/push to `main`.
2. Update `PROJECT_STATE.md` with exact SHA and test results.
3. Return `CURRENT_TASK.md` to HOLD.
4. Report:
   - implementation SHA;
   - exact files changed;
   - backend focused test result;
   - Flutter focused test result;
   - Ruff/analyze/diff-check;
   - Alembic remains 0051;
   - production remains `a3d546b069e7e05d68fd42906c662c3ba34caef5`.
5. STOP.

Do not start PT1, People Landscape, Person removal, Secretary Person context, social roles, graph stabilization, MCP, G3B, or S3.
