# Current task — PC1: explicit reversible Person consolidation

## State

- People PP1 core human goal is accepted after HG3 live validation.
- Production/runtime/origin-production: `9aaeb8db1a04851bcae17aa50f9a4d185c2753bb`.
- Alembic: `0051`.
- Current main before authorization: `9acb8067cc7376437a3aaa89b86be2ba5d5c09e0`.
- A real duplicate is now present: an older opaque Mattermost Person and a newer human-labeled Person represent the same real person, and identity-candidate conflict UI can see that an endpoint already belongs to another Person.
- Raw object deletion is not a safe duplicate-resolution mechanism because active PersonIdentity rows can continue to own exact tuples and block reassignment.

## Goal

Add an explicit, user-confirmed, reversible **Person merge/consolidation** workflow.

The user must be able to say:

> These two Person objects are the same real person. Keep this Person, absorb the duplicate.

The operation must consolidate exact identities and explicit Task actor participation without inventing any social/organization fact.

No automatic merge by name, provider, salience, LLM, or similarity.

## Terminology

- **survivor**: the Person that remains active and visible.
- **duplicate**: the Person absorbed into survivor and tombstoned.
- Merge is user-authorized identity consolidation, not a relationship edge.

## A. Read-only merge preview

Add a bounded read-only preview operation for two same-user active Person ids.

The preview must:

- require two distinct active `Object(kind=person)`;
- identify survivor and duplicate explicitly;
- show titles and effective provider/identity cues for both;
- list/count active exact identities on duplicate that would move;
- list/count current Task actor participation on duplicate grouped by canonical role:
  `requested_by`, `delegated_to`, `waiting_on`, `involves`;
- report active identity-evidence rows that would be copied to survivor;
- report whether duplicate is bookmarked if available cheaply;
- detect blockers before any write;
- perform no writes.

The preview must fail closed / mark `can_merge=false` if duplicate has any active incident graph edge whose semantics are not one of the canonical incoming Task->Person actor roles above.

Do not guess how to migrate generic `related_to`, `references`, social, organization, or arbitrary Person edges.

Use bounded constants. If identities/evidence/actor edges exceed the safe preview/apply cap, report a blocker rather than performing a partial merge.

## B. Explicit apply contract

Add a dedicated Person consolidation service. Do not assemble this in the Flutter client from several generic mutations.

Apply must revalidate the preview contract inside one DB transaction.

### Identities

For each active exact identity owned by duplicate:

- move ownership to survivor using the existing `PersonIdentityService.reassign` semantics or an equivalent conflict-safe path;
- preserve provider, identity_type, realm, canonical_value, and stored display_value;
- if any identity cannot be moved safely, abort the entire merge;
- after successful merge, duplicate must own no active exact identity.

Do not detach/drop an identity merely to make the merge pass.

### Identity evidence

Preserve provenance.

For every active `PersonIdentityEvidence` row on duplicate:

- create/reuse an equivalent active evidence row for survivor with the same identity tuple, evidence type, polarity, weight, provenance kind/key, source object, explanation, and details;
- when the moved exact identity now exists on survivor, point the survivor evidence copy at the corresponding survivor PersonIdentity where appropriate;
- do not create duplicate active evidence if survivor already has the same semantic evidence signature;
- keep the original duplicate evidence rows as historical audit on the duplicate Person.

Do not rewrite source Flow or provenance.

### Task actor edges

For each active/proposed Task->duplicate edge of type:

- `requested_by`
- `delegated_to`
- `waiting_on`
- `involves`

create/reuse the semantically equivalent Task->survivor actor edge with the same role, origin, state, and confidence using existing TaskRelationService semantics.

If survivor already has that exact Task/role fact, do not duplicate it.

Keep the original duplicate edge for audit; once duplicate is tombstoned normal active reads must ignore it.

Do not copy Task-to-Task or generic graph relations.

### Survivor title

The survivor title remains unchanged.

Do not auto-select the “better” name during apply. The user chooses which Person survives; existing explicit rename remains the way to change the title.

### Duplicate tombstone

After all transfers succeed:

- tombstone duplicate using the existing Secretary-local object tombstone semantics;
- remove/disable its visible bookmark if needed;
- record a bounded merge audit snapshot in duplicate Object metadata, under a clearly namespaced key, sufficient for:
  - survivor Person id;
  - merge timestamp;
  - moved identity tuples / created survivor identity row ids;
  - survivor evidence rows created specifically by this merge;
  - survivor Task actor edge rows created specifically by this merge;
  - prior bookmark state if used.

Do not put message bodies, secrets, provider tokens, or unbounded evidence into metadata.

The merge snapshot is operational audit metadata, not a new ontology fact.

## C. Reversible undo

A successful PC1 merge must expose **Отменить объединение**.

Undo must be fail-closed and transactional.

Before undo:

- duplicate merge audit must point to the requested active survivor;
- every moved identity must still be owned by survivor exactly as recorded;
- no conflicting current owner may exist;
- survivor must not contain later active evidence for a moved identity that cannot be safely distinguished from merge-created rows;
- any merge-created Task actor edge to be reversed must still be identifiable;
- if the state has diverged so undo could lose later user work, refuse undo and leave everything unchanged.

Safe undo:

1. restore duplicate from tombstone to its prior active confirmed object state;
2. move the recorded identities back to duplicate;
3. remove/retract only survivor evidence rows created specifically by the merge;
4. reject/remove only survivor Task actor edges created specifically by the merge;
5. original duplicate evidence and original duplicate Task actor edges become visible again naturally;
6. restore prior bookmark state where tracked;
7. clear/close the active merge marker while retaining minimal historical audit if needed.

Never undo pre-existing survivor identities/evidence/Task roles.

## D. Idempotence

- Repeating apply for a duplicate already merged into the same survivor should return the established result, not create new rows.
- Attempting to merge a duplicate already merged into another survivor must fail closed.
- Repeating safe undo should be idempotent.

## E. First-party People UX

In the right-side Person inspector:

### Generic action

Add a compact **Объединить с…** action.

It opens a Person-only search/selection surface and then a confirmation preview.

The preview must clearly state:

- which Person remains;
- which Person disappears from active People;
- identities to move;
- linked Task actor facts to preserve;
- any blocker.

Allow the user to swap survivor/duplicate before final confirmation.

The final action must use explicit wording such as **Объединить людей** and require a confirmation click.

### Conflict shortcut

Where current identity-candidate UI says an endpoint is already connected to another Person / conflict, provide a shortcut such as:

**Возможно, это один человек → Объединить**

It must open the same preview; it must never auto-merge.

### Post-merge

After success:

- duplicate disappears from active People graph/search;
- survivor remains selected;
- survivor inspector refreshes with the union of effective identities and preserved Task actor involvement;
- conflicting possible-contact rows that were caused solely by the duplicate should disappear on refresh;
- show a compact merge-history row such as:
  `Объединено: <old title> · Отменить`
  when undo remains safe.

### Delete

Do **not** add a raw “delete Person and discard its identities” action in PC1.

For a duplicate with identities/Task facts, consolidation is the safe path. Generic Person deletion/lifecycle can be designed separately.

## F. Assistant / model boundary

PC1 is first-party identity maintenance only.

- no LLM/model call;
- no Assistant prompt/tool changes;
- no MCP;
- no automatic merge suggestion generated by a model;
- no new Person context injected into Secretary.

The new DECISIONS rule remains authoritative: future Person context for Secretary is lazy and bounded, never the full People registry.

## G. Required backend regressions

At minimum cover:

1. preview of two active same-user Persons is read-only;
2. cross-user Person is rejected;
3. same Person id twice is rejected;
4. unsupported active incident edge on duplicate blocks merge;
5. active exact identity moves to survivor and duplicate has no active ownership;
6. multiple identities/providers move without loss;
7. identity conflict aborts whole transaction;
8. active evidence is copied/reused on survivor with provenance preserved;
9. duplicate evidence remains historical;
10. Task actor roles move logically to survivor for all four canonical roles;
11. pre-existing identical survivor Task actor edge is not duplicated;
12. no unsupported graph relation is copied;
13. duplicate is tombstoned only after all transfers succeed;
14. partial failure leaves both Persons unchanged;
15. repeat apply is idempotent;
16. successful merge removes the duplicate from active People reads;
17. merge audit metadata is bounded and contains no source body/secret;
18. safe undo restores duplicate, identities, and original actor visibility;
19. undo removes only rows created by the merge;
20. unsafe/diverged undo fails closed and preserves current state;
21. salience/communication attribution for moved identities resolves to survivor after merge;
22. no Person<->Flow edge, social relationship, Organization fact, or new Task inference is created.

No Alembic migration. Repository head must remain `0051`.

## H. Required Flutter regressions

At minimum:

1. Person inspector exposes `Объединить с…`;
2. merge picker searches only active Persons and excludes current Person;
3. preview clearly shows survivor vs duplicate;
4. survivor/duplicate can be swapped before confirm;
5. blocked preview cannot be applied;
6. conflict candidate exposes merge shortcut without auto-merge;
7. successful merge refreshes graph and removes duplicate card;
8. survivor stays selected and shows consolidated contacts/tasks;
9. merge-history row exposes `Отменить`;
10. safe undo restores both Person cards;
11. rename still works;
12. candidate Add/Do-not-suggest/Restore remain green;
13. Task graph behavior remains unchanged;
14. no overflow in wide/narrow supported layouts.

Run focused People/identity/task-relation suites plus relevant Graph regressions.

Run Ruff, Flutter analyze on touched Dart files, and `git diff --check`.

## Build

Build a fresh Linux debug bundle for human validation.

Do not deploy production in PC1.

## Explicitly out of scope

- No production deploy.
- No migration/schema change.
- No automatic/fuzzy merge.
- No name-similarity authority.
- No provider/network/model lookup.
- No raw destructive Person delete.
- No manager/colleague/family/client/context relationship facts.
- No Organization ontology.
- No Task-Person inference from message text.
- No task-creation contextual promotion prompt.
- No Secretary Person-context tool/prompt change yet.
- No MCP/G3B/S3.
- No unrelated Task graph redesign.

## Completion

1. Commit implementation + focused regressions.
2. Record exact implementation SHA, test results, Alembic head, and bundle path/checksum in `PROJECT_STATE.md`.
3. Return `CURRENT_TASK.md` to HOLD stating:
   - PC1 source ready / human gate pending;
   - production remains `9aaeb8db1a04851bcae17aa50f9a4d185c2753bb`;
   - Alembic remains `0051`.
4. Push implementation + HOLD to `main`.
5. Report exact SHAs/tests/bundle and STOP.

Do not deploy and do not begin Task<->Person visualization or Secretary Person-context work until PC1 is accepted.
