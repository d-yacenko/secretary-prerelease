# Current task — Relation Direction V8D1: provenance and canonical-direction audit

Graph Shell V8C2 is accepted.

This is a diagnostic/audit phase first. Do NOT visually reverse arrows, rewrite existing edge rows, add a migration, change production data, or deploy production.

## Problem

Human real-data review still shows directed arrows that look semantically wrong around some Tasks.

The current Tasks-map renderer is intentionally source -> target for every directed edge:
- `related_to`: symmetric, no arrow;
- `references`: source -> target;
- `depends_on`: dependent/source -> prerequisite/target;
- `part_of`: child/source -> parent/target;
- legacy `contains`: actual stored source -> target, with no reinterpretation.

Before changing behavior, determine whether the confusing arrows are caused by:
1. a presentation/rendering defect;
2. inconsistent canonical semantics in an edge writer;
3. historical/legacy stored edges whose source/target were created under a different convention.

## Scope

Audit the complete creation/projection chain for directed relation types that can appear on the Tasks canvas.

At minimum inspect:
- `GraphService.create_edge`;
- `RelationService.create_relation`;
- `TaskRelationService.add_dependency`;
- `TaskRelationService.attach_evidence`;
- Domain tool task evidence attachment;
- Domain tool `link_objects`;
- correlation proposal creation;
- deterministic/source relation creation;
- any legacy writer that creates `contains`;
- API relation creation;
- Task Profile projections for dependency/reference/composition;
- Flutter `presentGraphMapEdge`, full edge painter, compact hairline anchor selection, and audit-row text.

Search the whole repository for every creation of `EdgeCreate` and every literal/type constant for:
- `references`
- `depends_on`
- `part_of`
- `contains`
- `related_to`

Do not assume the paths listed above are exhaustive.

## Required canonical contract

Use these as the target semantics for CURRENT code:

### related_to
Symmetric. Source/target storage order has no semantic arrow.

### references
A references B => source=A, target=B.
For Task evidence, Task must be source and evidence object target.

### depends_on
A depends on B => source=A, target=B.
Arrow must point from dependent to prerequisite.

### part_of
A is part of B => source=A (child), target=B (parent).
Arrow must point child -> parent.

### contains
Legacy only. Do NOT invent a new semantic meaning in this phase.
Document each current/legacy writer you find and the direction it actually stores.

## Deliverable A — writer matrix

Add a concise repository document, for example:
`docs/relation_direction_audit.md`

For each relation writer record:
- file/function;
- relation type(s);
- source endpoint meaning;
- target endpoint meaning;
- origin/state;
- whether the writer conforms to the canonical contract;
- whether it can create edges visible on the Tasks canvas;
- whether it is current or legacy.

Do not include secrets or production object contents.

## Deliverable B — renderer proof

Add/extend focused tests that prove the renderer itself does not reverse canonical direction:

1. `references` source -> target full edge;
2. `depends_on` source -> target full edge and dashed;
3. `part_of` child/source -> parent/target full edge;
4. compact `references` arrow follows canonical target for both Task->Flow and Flow->Task fixtures;
5. compact `depends_on` follows canonical target;
6. audit row prints source -> target consistently;
7. `related_to` stays undirected;
8. proposal state does not change direction.

If existing V8A-R/V8C1 tests already prove an item, keep them and reference them in the audit rather than duplicating unnecessarily.

## Deliverable C — writer-contract tests

Add focused backend tests for any writer whose direction is not already explicit in tests.

At minimum prove:
- task evidence creates `Task -> evidence` `references`;
- task dependency creates `dependent Task -> prerequisite Task`;
- `part_of` tool/API contract remains child -> parent;
- correlation proposal preserves trigger as source and candidate as target;
- deterministic mail RFC reference stores referencing message -> referenced message.

For `contains`, test only the actual existing writer behavior if a writer still exists. Do not normalize it.

## Deliverable D — classification

At the end of `docs/relation_direction_audit.md`, state one of these, with evidence:

- `RENDERER_DEFECT`
- `WRITER_CONTRACT_DEFECT`
- `LEGACY_DATA_LIKELY`
- or a combination, if independently proven.

Do not guess from screenshots. The classification must follow from code/tests and, only if safely available, read-only local/dev data inspection.

## Optional read-only data inspection

If the Executor has a current-main local/dev database with the real sample objects visible in the screenshots, it may inspect edge metadata READ-ONLY to compare:
- edge type;
- source object title/kind;
- target object title/kind;
- origin/state;
- metadata that identifies the writer.

No writes. No production SSH. No production DB. No content dumps beyond the minimum relation facts required for the audit.

If those real sample rows are not available locally, say so and do not block completion.

## Do NOT fix yet

Even if a defect is found:
- do not reverse existing rows;
- do not add a migration;
- do not change `presentGraphMapEdge`;
- do not change graph layout;
- do not alter relation type semantics;
- do not deploy.

V8D1 ends with diagnosis only. The Architect will choose V8D2 based on the classification.

## Validation

Run the focused backend relation/domain-tool/correlation tests you touched, plus:
- graph relation presentation tests;
- proposed relation tests;
- hybrid compact/local flower tests as relevant;
- V8B2 hierarchy tests;
- Flutter analyze touched files;
- `git diff --check`.

Linux debug build is required only if production Flutter code changed. If only tests/docs/backend tests change, report that and do not rebuild unnecessarily.

## Completion

Record:
- implementation SHA;
- audit document path;
- writer matrix summary;
- renderer verdict;
- final classification;
- exact tests run.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start V8D2.
Do not deploy production.
