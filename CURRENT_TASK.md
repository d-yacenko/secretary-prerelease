# Current task — Harness H2B: constrain link_objects to canonical relation types

Harness H2A/H2A-R is accepted.

H2B closes the second blocking ontology/Harness gap from H1:

`link_objects.relation_type` is currently a free string.

That allows the model/MCP client to store relation types that the human Graph UI and canonical map grammar do not understand.

H2B must constrain generic `link_objects` to the same canonical relation vocabulary already offered by the human `RelationService`.

No new relation type.
No migration.
No graph rewrite.
No client change.
No production access/deploy.

## Canonical generic allowlist

`link_objects` may create exactly:

- `related_to`
- `references`
- `depends_on`
- `part_of`

No other relation type is valid for this tool.

Important distinctions:

- `requested_by`, `delegated_to`, `waiting_on`, `involves` remain canonical Task actor roles, but model writes them through the typed fields on `create_task` / `update_task`, NOT through generic `link_objects`.
- `labeled_with` remains assign_label-only.
- `contains` remains protected / non-generic.
- legacy/custom stored edges may continue to exist and be readable; H2B only prevents new unsupported writes through `link_objects`.
- `remove_relation` semantics are unchanged in H2B.

## Single source of truth

Avoid keeping divergent string sets in:
- human `RelationService`;
- tool schema;
- DomainToolService;
- Assistant definition;
- MCP wrapper.

Prefer a small canonical domain-level relation constant/type that both human and tool paths can import.

It must represent the four generic user relation types above.

Do not accidentally fold Task actor roles into this generic allowlist.

If moving `USER_RELATION_TYPES` out of `relation_service.py`, preserve existing imports/tests as needed or update them narrowly.

## Shared LinkObjectsInput

Change `LinkObjectsInput.relation_type` from unconstrained string to the canonical four-value type.

The shared Pydantic schema must:
- accept exactly the four values;
- reject arbitrary/custom strings;
- reject `labeled_with`;
- reject actor role strings;
- reject `contains`;
- reject null.

Do not make relation_type optional.

## Assistant contract

Update Assistant `link_objects` JSON schema so `relation_type` is an enum exactly:

- `related_to`
- `references`
- `depends_on`
- `part_of`

Update its description concisely:

- `related_to`: symmetric general relation;
- `references`: source cites/refers to target;
- `depends_on`: source/dependent depends on target/prerequisite;
- `part_of`: source child Task belongs to target parent Task; composition, not dependency; one active/proposed parent; do not infer.

State that actor roles use the typed Task fields, labels use `assign_label`, and unsupported relation names must not be invented.

Do not add a global prompt rewrite unless necessary.

## MCP contract

Change MCP `link_objects` signature/schema to expose the same required four-value enum.

Because relation_type is required, no omission/null sentinel is needed.

Real MCP behavior must reject:
- null;
- arbitrary string;
- `requested_by`;
- `labeled_with`;
- `contains`;

before the domain write path.

The same valid values must reach `execute_mcp_tool`.

## Domain defense in depth

Even with typed input schemas, `DomainToolService.link_objects` must fail closed if an unsupported relation type somehow reaches it.

Validate relation_type against the canonical four-value allowlist before:
- duplicate lookup;
- part_of validation;
- `GraphService.create_edge`.

Do not rely only on Assistant/MCP schema validation.

Preserve existing special semantics:
- self-link rejection;
- exact duplicate idempotency;
- proposal/approved-confirmed state/origin behavior;
- confidence behavior;
- `part_of` uses the existing `validate_part_of_edge`;
- no direction inversion.

Do not create a new generic validator that changes GraphService behavior for non-tool internal writers.

## Direction contract

H2B must not change meaning/direction:

- `related_to` symmetric;
- `references`: source → target;
- `depends_on`: dependent/source → prerequisite/target;
- `part_of`: child/source → parent/target.

Tests should verify the stored source/target are unchanged for directional relations.

## Existing typed Task relations

Regression coverage must prove that restricting `link_objects` does NOT break:

- `create_task(requested_by_person_id=...)`;
- `create_task(delegated_to_person_ids=...)`;
- `create_task(waiting_on_person_ids=...)`;
- `create_task(involved_person_ids=...)`;
- `create_task(depends_on_task_ids=...)`;
- corresponding additive `update_task` fields;
- evidence `references` attachment.

Actor/dependency writers remain typed and canonical.

## Read/remove compatibility

Do not hide existing unknown/legacy edge types from generic reads solely because writes are now constrained.

`get_object`, `get_context`, `list_neighbors`, Graph workspace, and audit/read paths keep their existing read behavior.

Do not tighten `remove_relation` in H2B. Its current protected/removable set remains a separate existing contract.

## Tests — schema/contracts

Add focused tests proving at minimum:

1. `LinkObjectsInput` accepts each of the four canonical values;
2. rejects an arbitrary string;
3. rejects `requested_by`;
4. rejects `labeled_with`;
5. rejects `contains`;
6. rejects null;
7. Assistant schema enum is exactly the four values;
8. MCP `list_tools()` schema enum is exactly the same four values and relation_type remains required/non-nullable;
9. no other tool schema is accidentally changed.

## Tests — real MCP

Through real MCP `Client.call_tool`:

1. each canonical value passes input validation and reaches the normal approval/domain boundary;
2. arbitrary custom value is rejected before `execute_mcp_tool`;
3. `requested_by`, `labeled_with`, `contains`, and null are rejected before `execute_mcp_tool`.

Use a spy if useful to prove rejected values are not forwarded.

## Tests — DomainToolService

Prove:

1. `related_to` still creates/proposes correctly;
2. `references` stores source→target unchanged;
3. `depends_on` stores source dependent → target prerequisite unchanged;
4. `part_of` stores child/source → parent/target and still runs all composition guards;
5. duplicate valid relation remains idempotent;
6. self-link remains rejected;
7. unsupported relation fails before any Edge is inserted;
8. direct defense-in-depth path cannot persist a custom type;
9. proposed vs approved-confirmed behavior unchanged.

If direct construction of `LinkObjectsInput` makes an unsupported value impossible, test the service guard through the narrowest practical bypass/monkeypatch/helper without weakening the public model.

## Regression

Run at minimum:

- new H2B focused tests;
- `backend/tests/test_domain_tools.py`;
- `backend/tests/test_tool_gateway.py`;
- `backend/tests/test_task_relations.py`;
- `backend/tests/test_task_composition.py`;
- relevant Graph/RelationService tests;
- relevant MCP tests for `link_objects`;
- H2A completion_mode tests to prove no regression;
- Ruff check/format touched Python;
- `git diff --check`.

The four already-known unrelated failures from the H2A-R combined run may remain only if they are the exact same four:
- two Task lifecycle historical failures;
- two MCP list/smoke failures caused by missing `get_task_profile`.

Do not fix them in H2B.

## Documentation

Update:

`docs/SECRETARY_TOOLSET_MATRIX.md`

so `link_objects` is no longer described as a free relation string.

Append a closure note to:

`docs/ontology_harness_parity_audit.md`

Record:
- H2A closed completion_mode write parity;
- H2B closes the free-form relation write gap;
- actor typed fields remain separate;
- legacy/custom relation reads are not rewritten;
- planned start/end and the `get_task_profile` MCP-list mismatch remain separate open/nonblocking findings as applicable.

Do not rewrite H1 history.

## Scope guard

Do NOT:

- add a relation type;
- change relation directions;
- change `part_of` composition matrix;
- change actor relation semantics;
- change `remove_relation` allowlist;
- rewrite existing edges;
- change Graph renderer;
- add planned interval tool fields;
- fix `get_task_profile` MCP exposure/list mismatch;
- fix unrelated Task lifecycle failures;
- change People;
- change client/schema migrations;
- access/deploy production.

## Completion

Record in `PROJECT_STATE.md`:

- implementation SHA;
- exact four-value generic allowlist;
- single-source-of-truth location;
- Assistant/MCP/shared schema parity;
- defense-in-depth result;
- directional relation regression result;
- typed actor/dependency regression result;
- exact tests;
- known unrelated failures unchanged;
- schema/client/production unchanged.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start H2C.
Do not start Task stabilization.
Do not deploy production.
