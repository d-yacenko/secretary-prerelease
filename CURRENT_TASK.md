# CURRENT_TASK

## Status

ACTIVE

## REL1D-C1 — frozen batch ActionPlan + atomic backend persistence

REL1D-B/B.1 are ARCHITECT SOURCE-ACCEPTED.

Baseline:
- grounding: `c0599932a9c917e0efde51d237d8cb3df79c5a88`
- corrective: `baf1362493eaab5b81680c0f747664d1c432699d`
- HOLD: `56e21f5607455386755a364286e53b91852ef8d1`
- schema `0054`
- production/client `6f802d6959aca40758376a83d5bdfcbbd77fc537`

Connector payload size prevented Architect from appending the B/B.1 acceptance line to the very large `PROJECT_STATE.md`. Executor must add that acceptance together with the C1 result at completion.

Backend-only. Do not start C2/client UX.

## Goal

Create one frozen ActionPlan for explicitly selected grounded rows. Before approval only PendingActionPlan may be written. Approval must atomically revalidate and apply selected Person reuse/promotion plus role assignment. Reject/expire writes no Person/Role facts.

## Composite tool

Add exactly one internal tool:

`apply_role_import_batch`

- INTERNAL_WRITE
- assistant_exposed=false
- mcp_exposed=false
- no Assistant/OpenAI definition
- ActionPlan-only
- plan contains exactly one action

Do not expand batch into independent role actions.

## Prepare endpoint

Preferred:

`POST /people/role-import/action-plan`

Strict request:

- source_object_id
- source_revision
- grounding_revision
- items_truncated
- items, max 32, same shape as REL1D-B
- selections

Selection:

- row_index
- exactly one:
  - person_id
  - promotion_candidate_key

Reject extra fields, duplicate row_index, empty selections, incoming role_term_id/assignment/raw identity/create-role/suggestion choice.

Omitted row = skipped.

## Freshness

Prepare must rerun REL1D-B grounding server-side from source_revision + items_truncated + items.

Require exact grounding_revision match.

- source drift -> `role_import_source_changed`
- Person/promotion/RoleTerm grounding drift -> `role_import_grounding_changed`

No AI/provider call.

## Selection validation

For each selected row:

- resolved -> exact grounded person_id only
- ambiguous -> explicitly chosen person_id must be in grounded candidates
- promotion_candidates -> explicitly chosen candidate_key must be grounded
- unresolved -> cannot select

Never choose by salience/default.

Role choice remains server-owned:

- exact term -> freeze reuse_existing + role_term_id
- no exact term -> freeze create_if_missing + exact REL1A role display
- suggestions never become selected terms

## Frozen action payload

Strict canonical payload contains:

- operation_id
- source_object_id/revision/kind/truncation
- grounding_revision
- total extracted rows
- selected rows

Each selected row freezes:

- row_index
- extracted_person_name
- person_id OR promotion_candidate_key
- target_display
- role
- context
- vocabulary_mode
- role_term_id only for reuse_existing

Do not persist in action args:

- evidence_text/source_locator
- raw source
- raw identity canonical values
- normalized role keys
- salience

Use existing ActionPlanService/create-plan TTL/status machinery only.

## Approval presentation

Add deterministic presentation for `apply_role_import_batch`:

- source title/id
- selected/total counts
- source_truncated/items_truncated
- max 32 rows:
  - row_index
  - target display
  - target mode existing_person|promote_person
  - role
  - context
  - vocabulary mode reuse_existing|create_if_missing

Do not expose candidate keys, canonical identities, normalized keys, provenance keys, upload path, evidence text.

## Execution fence

At approved execution start:

1. acquire `lock_user_serialization_row`
2. lock source Object FOR UPDATE
3. for text source, lock currently used Representation rows FOR UPDATE in deterministic order
4. reload source with existing source service
5. require frozen source_revision unchanged

Raster keeps path/magic/hash checks.

## Revalidate Person target

Existing Person:
- rerun `PersonAssistantService.resolve(extracted_person_name)`
- frozen person must still be current resolved id OR still present in current ambiguous candidates
- otherwise fail whole batch
- never switch Person

Promotion:
- rerun eligible direct-contact scan
- resolver must still be none
- exact candidate_key must still be eligible and exact-display match
- call existing `PersonPromotionService.approve(identity)`
- cache candidate_key -> Person id, so multiple roles create one Person
- conflict/ineligibility fails whole batch

Do not change promotion eligibility.

## Role execution

reuse_existing:
- revalidate current-user RoleTerm and lexical identity

create_if_missing:
- use frozen exact role text
- if exact term appeared after staging, reuse it
- semantic near-duplicates stay distinct

## Assignment provenance

Extend `PersonRoleService.assign_outcome()` backward-compatibly with optional `source_object_id`.

Default callers unchanged.

When supplied:
- validate current-user active source
- write source_object_id only on newly created assignment

New imported assignment:
- origin=user
- provenance_kind=role_import_confirmed
- bounded operation-derived provenance_key
- source_object_id=source

Already-active assignment:
- truthful no-op
- never rewrite prior origin/provenance/source

Manual and REL1C provenance must stay unchanged.

## Dedup / cap / atomicity

Dedup final writes by:

- final Person id
- REL1A role lexical identity
- REL1A context identity

Duplicate selected rows create one assignment; others report duplicate/no-op.

Same role + different context remains distinct.

Active cap stays 16.

Existing ActionPlan nested transaction is the atomic boundary. Any later-row failure must roll back all earlier promotions, identities/evidence, RoleTerms, and assignments from this batch.

Required adversarial rollback test: row 1 would create promotion+role, row 2 fails; after plan failure row 1 leaves no durable state.

## Output

Composite output includes:

- changed
- source_object_id
- selected_count
- people_created
- assignments_changed
- assignments_no_op
- duplicate_rows
- per-row:
  - row_index
  - person_id
  - person_created
  - assignment_id
  - role_term_id
  - role/context
  - changed
  - status applied|already_active|duplicate_selected_row

No canonical identities.

Overall changed=true if any Person or assignment was created.

Add execution-effect support: changed/no_op using aggregate counts only.

## Required tests

Add focused C1 batch ActionPlan tests proving at minimum:

Prepare:
1. fresh request creates one pending one-action plan and no Person/Role writes
2. tool policy internal-only
3. invalid/empty/duplicate/injected selections fail
4. resolved/ambiguous/promotion/unresolved selection rules
5. source and grounding stale errors
6. frozen args omit evidence/raw identities
7. presentation is human-readable/privacy-safe
8. reject/expire write nothing

Approve:
9. existing Person + existing/new role
10. explicit ambiguous Person only
11. promotion -> Person+identity/evidence+role
12. two roles same promotion -> one Person
13. semantic duplicate -> one assignment
14. same role different contexts -> distinct
15. manual existing assignment no-op preserves provenance/source
16. new import assignment has role_import_confirmed + source_object_id
17. REL1C provenance unchanged
18. exact RoleTerm race reused
19. cap 16 fails whole plan
20. source/Person/promotion drift fails whole plan
21. identity conflict fails whole plan
22. later-row failure rolls back earlier writes
23. repeated approve is idempotent
24. result counts/statuses truthful
25. prepare/approve creates no AITrace/budget/provider call

Concurrency, separate sessions + short lock timeout, no sleeps:
26. batch holds user gate
27. concurrent REL1C role writer blocked
28. concurrent identity/consolidation writer blocked
29. source Object row locked
30. used Representation rows locked

Regression:
- REL1D grounding/source
- REL1A
- REL1C writes
- ActionPlan
- tool gateway
- Person promotion
- REL1B concurrency
- approval presentation
- execution effects
- registry/MCP drift
- Ruff, py_compile if useful, git diff --check

All relevant focused tests 0 failed.

## Scope

Expected backend only:

- new batch service
- role-import route/schemas
- PersonRoleService optional source_object_id
- tools schemas/registry
- DomainToolService
- approval presentation
- execution effects
- source service only for small lock helper
- tests

No Flutter changes. No Alembic/schema changes. No Person resolver/promotion eligibility/RoleTerm normalization/REL1B/Proactive/provider config changes.

## Production boundary

Source-only. Do not deploy, migrate, install/build client, call real model/provider, or mutate production data.

## Next

REL1D-C2 will add client row selection, prepare button, frozen ActionPlan card, approve/reject and truthful results.

Do not start C2 from HOLD.

## Completion

Update PROJECT_STATE with:
- B/B.1 Architect acceptance
- C1 design/result/freshness/atomicity/provenance/tests

Return CURRENT_TASK to HOLD with implementation SHA, files, exact tests, schema 0054, production/client unchanged, no external effects, C2 not started.

Commit + push main, then STOP.
