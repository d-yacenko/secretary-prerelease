# Current task — People C2: explicit confirmation activates canonical identity

People C1 is accepted.

C1 gives People a safe human cold-start: an explicit named Person can be created without inferring identity.

The remaining cold-start gap is narrower:

- a bare Person can see a grounded source-derived identity candidate;
- Graph UI `confirm` currently records `user_confirmed` evidence only;
- canonical communication matching (`_effective_keys`) still depends on an active `PersonIdentity`;
- therefore the user can say “yes, this account is this Person” but the exact identity may still not become operational until separate enrichment orchestration runs.

C2 closes only that gap.

No automatic sender promotion.
No fuzzy merge.
No background enrichment run.
No provider/model call.
No Person↔Flow edge creation.
No schema migration.
No production deploy.

## Canonical rule

An explicit user confirmation of a grounded identity candidate is strong enough to activate that exact provider identity for that Person, provided the identity is not owned/conflicted elsewhere.

After successful confirmation:

- there is one active canonical `PersonIdentity` for that exact tuple;
- the `user_confirmed` ledger row remains the human provenance;
- repeated confirmation is idempotent;
- current Person resolution / communication / route services can use the identity without a later `PersonEnrichmentService.plan()` call.

Do NOT treat display-name similarity alone as sufficient. Activation happens only inside the existing explicit `confirm` correction path after its grounding and conflict checks.

## Scope: first-party Graph correction only

Implement this in the existing first-party path:

`POST /graph/people/{person_id}/identity-correction`

for `action=confirm`.

Do not change Assistant confirmation semantics in C2 unless a shared helper can be reused without changing externally observable Assistant behavior.

Do not add a new Assistant/MCP tool.

## Confirm behavior

Preserve the current sequence of safety checks:

1. Person must be active and same-user.
2. Identity tuple must parse canonically.
3. Identity must be grounded as already attached, existing evidence, or an exposed source-derived candidate.
4. A blocked/conflicted candidate remains rejected.
5. An identity owned by another Person must fail closed.
6. Multiple active conflicting confirmations must fail closed.

Then:

### Already attached to the same Person

- record/retain the normal `user_confirmed` evidence;
- do not create another `PersonIdentity`;
- mark nothing as “created by this confirmation”;
- a later retract of this confirmation must NOT detach a pre-existing identity.

### Not attached anywhere

- attach exactly once with `PersonIdentityService.attach(person_id, identity)`;
- record/retain the existing `user_confirmed` evidence;
- link that confirmation evidence to the newly created `PersonIdentity` using the existing nullable `person_identity_id` field, so reversal can distinguish this activation from a pre-existing identity;
- if an idempotent active confirmation row already exists from pre-C2 behavior, it is acceptable to populate its `person_identity_id` when this explicit confirmation first activates the identity.

The whole request is one DB transaction. A failure must not leave a half-attached identity without the confirmation semantics.

Do not call `PersonEnrichmentService.plan()` from the route/service.

## Retract behavior

Preserve current reversible feedback semantics.

When `action=retract` retracts an active `user_confirmed` row:

- if that confirmation row's `person_identity_id` identifies an active identity that was created by this C2 confirmation, detach/reject that exact `PersonIdentity` as part of the same user reversal;
- if the confirmation did not create the identity (pre-existing attachment), do not detach it;
- do not detach an identity merely because a rejection row is being retracted.

Existing reject semantics remain:

- rejecting an attached identity suppresses it through the evidence ledger;
- the underlying identity may remain stored so retracting the rejection can restore it;
- do not turn reject into destructive deletion.

Historical evidence rows remain history; do not delete them.

## Operational result

After confirming a candidate that C2 activates, without running P4 planner:

- rooted People detail shows that identity as `effective`, not as a candidate;
- `resolve_person` / exact resolution can resolve it under existing rules;
- `find_person_communications` can use it through canonical active identity keys;
- existing safe route discovery can use it where that provider supports a route.

C2 does NOT require People Graph to materialize communication nodes or edges. The rooted graph may still have no Flow neighbor edge; that is a separate presentation/materialization decision.

Do not change `recent_communication_count` in C2.

## Provenance and idempotency

Use existing:
- `user_confirmed`;
- `graph_ui:user_confirmed:...`;
- `user_feedback`;
- `person_identity_id` link.

Do not invent a new evidence type.

Repeated confirm must produce:
- one active `PersonIdentity`;
- one active idempotent Graph UI confirmation row for the same provenance;
- no duplicate attachment.

Race/conflict failures must remain fail-closed.

## Tests — backend

Add/adjust focused tests proving at minimum:

1. bare Person + grounded source candidate starts with zero active `PersonIdentity`;
2. Graph UI confirm creates exactly one active canonical identity;
3. confirmation evidence is `user_confirmed`, keeps `graph_ui:` provenance, and links `person_identity_id` to the newly created identity;
4. rooted People refresh now presents the identity as `effective`, not `candidate`;
5. `PersonAssistantService.find_person_communications` can retrieve matching stored communication immediately after confirm, without calling `PersonEnrichmentService.plan()`;
6. an applicable known route becomes available under existing route rules after confirm;
7. repeated confirm is idempotent for identity and evidence;
8. identity already attached to the same Person is not duplicated;
9. retracting a confirmation that created the identity detaches/rejects that created identity;
10. after that retract, exact identity no longer acts as an active attached identity and the grounded source candidate can be offered again when appropriate;
11. retracting confirmation on a pre-existing identity does NOT detach the pre-existing identity;
12. reject after activation suppresses the identity but does not destructively remove it;
13. retracting that rejection restores the existing identity under current semantics;
14. identity owned by another Person fails closed with no new identity/evidence side effect;
15. multiple-confirmation/conflict protections remain green;
16. cross-user isolation remains green;
17. no Person↔Flow, Person↔Task, or Person↔Person edge is created by confirm;
18. no provider/model/background job path is called.

Use both email and one chat/provider case where practical, but do not expand C2 into provider-specific redesign.

## Tests — client

No new UI concept is required.

Update/add only focused client regression if the existing correction flow needs it:

1. confirm still calls the same identity-correction endpoint once;
2. successful correction refreshes/reloads the selected Person detail through the existing path;
3. effective identity replaces candidate after backend response/refresh fixture;
4. reject/retract controls remain available under the existing UI contract.

Do not redesign the Person card or detail pane.

## Validation

Run at minimum:

- `backend/tests/test_person_graph_workspace.py`;
- `backend/tests/test_person_identity.py`;
- `backend/tests/test_person_evidence_ledger.py`;
- `backend/tests/test_person_assistant.py`;
- `backend/tests/test_person_enrichment.py` to prove P4 semantics did not regress;
- any new focused C2 tests;
- relevant People Flutter correction/workspace tests if Dart changes;
- Ruff/format on touched Python;
- Flutter analyze only if Dart changes;
- Linux build only if Dart changes;
- `git diff --check`.

Do not alter unrelated historical Graph detail failures.

## Scope guard

Do NOT:

- auto-create Person from a sender/message;
- invoke `PersonEnrichmentService.plan()` automatically;
- infer/attach from display name without explicit confirmation;
- merge People;
- create graph edges from identity activation;
- change salience;
- change organization/manager ontology;
- add Assistant/MCP create/confirm tools;
- implement H2 `completion_mode`;
- restrict `link_objects`;
- migrate/deploy production;
- rerun production census.

## Completion

Record in `PROJECT_STATE.md`:

- implementation SHA;
- exact confirmation activation behavior;
- exact retract distinction for C2-created vs pre-existing identity;
- idempotency/conflict behavior;
- whether any edges/schema/background/provider/model behavior changed;
- exact backend/client test results.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start C3.
Do not start P2.
Do not start H2.
Do not deploy production.
