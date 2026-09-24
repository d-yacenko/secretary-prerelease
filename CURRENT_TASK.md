# Current task — Graph Refined P2R: evidence ownership + active-candidate safety

Architect review of P2 implementation `c74571132b643a816a2069d0ce6708c128a8dba4` found two blocking integrity issues. Correct only these issues and add focused regression coverage.

Do not start P3. Do not add Person salience, UI, Assistant lookup, auto-merge, auto-attach, send-by-person, voice/media, or Task Graph work. Do not deploy or apply migrations `0048/0049` in production.

## Defect 1 — linked PersonIdentity may belong to another Person

`PersonEvidenceService.record(... person_identity_id=...)` currently validates:
- same Secretary user;
- same provider/type/realm/canonical identity tuple.

It does NOT validate that the linked `PersonIdentity.person_object_id` equals the evidence target `person_id`.

Therefore an evidence row for Person A can point at a PersonIdentity actually attached to Person B if the tuple matches. That violates ledger semantics.

Required correction:
- when `person_identity_id` is provided, require it to belong to the exact target Person;
- require the linked identity to be active/not rejected at record time;
- cross-user, wrong-Person, tuple mismatch, and rejected identity all fail closed;
- historical evidence rows must remain valid/auditable if the identity is later detached/rejected; do not cascade-delete or rewrite history.

If a small helper signature change is needed, pass `person_id` into linked-identity validation explicitly.

## Defect 2 — rejected/deleted People or identities can re-enter candidate generation

Current `_name_matches()` scans all `kind="person"` Objects and all identity display values without excluding rejected/deleted People or rejected PersonIdentity rows.

Required correction:
- candidate generation must consider only active/non-rejected Person Objects;
- display-name candidates from `PersonIdentity.display_value` must use only active/non-rejected identities whose target Person is also active;
- exact resolution must likewise not return a rejected/deleted Person;
- do not physically delete historical Person/evidence rows to accomplish this;
- use the repository's existing object visibility/state semantics rather than inventing a parallel deletion rule.

This correction may touch `PersonIdentityService.resolve/_require_person` if that is the cleanest shared invariant, but do not broaden scope beyond active Person safety.

## Focused proof

Add/extend tests proving at minimum:
1. Evidence targeting Person A rejects a `person_identity_id` attached to Person B even when the normalized tuple matches.
2. Evidence accepts an active identity attached to the same Person.
3. A rejected/detached identity cannot be newly linked by `person_identity_id`.
4. Existing historical evidence remains readable after the linked identity is later rejected/detached.
5. Rejected Person is not returned by exact resolution and is not proposed by name.
6. Deleted/hidden Person is not returned/proposed.
7. A rejected PersonIdentity display value does not create a name candidate.
8. Existing P1/P1R and P2 scoring/replay/confirmation/rejection/retraction tests remain green.
9. No automatic Person merge or identity attach is introduced.
10. Migration `0049` remains unchanged unless a schema correction is truly required; prefer service/domain correction if sufficient.

Run the smallest relevant backend tests, Ruff/compile on touched Python, and `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose P3 and do not deploy.
