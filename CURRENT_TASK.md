# CURRENT_TASK

## Status

ACTIVE

## REL1D-C1.1 — close generic staging path and representation-insert race

REL1D-C1 implementation `3d3bead03271bad5dfc5713eaf78a4d1062cb11e` is directionally correct but is **not yet Architect source-accepted**.

Architect review found two bounded contract defects.

### A. Composite tool is still generically stageable

`apply_role_import_batch` is correctly hidden from Assistant/MCP and requires approved write mode to execute, but it is currently registered with:

- `prepare_method="prepare_apply_role_import_batch"`

and `DomainToolService` exposes that generic prepare method.

The C1 contract required:

- one specialized `POST /people/role-import/action-plan` prepare path;
- no generic tool-gateway prepare path for this composite batch action.

Remove the generic prepare path.

Required final registry contract:

- name = `apply_role_import_batch`
- permission = INTERNAL_WRITE
- assistant_exposed = false
- mcp_exposed = false
- `prepare_method is None`
- execution_input_model remains the strict frozen canonical batch model
- no Assistant/OpenAI function definition

Remove `DomainToolService.prepare_apply_role_import_batch`.

Keep `DomainToolService.apply_role_import_batch` approved-only.

The specialized role-import endpoint remains the only supported plan-preparation path.

Do not introduce a second approval mechanism.

### B. Source critical section does not prevent a new Representation insert

C1 locks:

- user serialization row;
- source Object;
- existing full/chunk Representation rows used by the source.

That is sufficient when a canonical representation writer must delete/update an existing locked Representation.

But when a text source currently uses Object.body fallback and has no full/chunk rows, a canonical representation writer can currently:

- see/delete zero Representation rows;
- insert a new full/chunk Representation;
- commit without acquiring the locked source Object row.

That can change the role-import source after the batch revision check and before confirmation finishes.

Fix canonical representation writers so every mutation that can replace/add/delete role-import-relevant stored Representations serializes on the owning Object row first.

Preferred minimal design:

- add one small `RepresentationService` helper that locks the current-user Object row `FOR UPDATE`;
- `RepresentationService._replace_representations()` acquires that Object lock before delete/insert;
- `ClientRepresentationPersistence.replace_for_object()` acquires the same Object lock before delete/insert;
- `ClientRepresentationPersistence.delete_all_for_object()` acquires the same Object lock before delete.

Audit other production writers of full/chunk Representations. Any writer that can change the text selected by `PersonRoleImportSourceService` must participate in the same Object-row serialization.

Do not table-lock Representations. Do not add a global mutex.

Preserve normal read-only representation reads without new locks.

## Required source-execution invariant

During approved `apply_role_import_batch` execution:

1. user serialization gate is held;
2. source Object is locked;
3. existing used Representation rows are locked when present;
4. source revision is recomputed;
5. until the ActionPlan critical section completes, canonical product writers must not be able to:
   - replace full/chunk rows;
   - insert the first full/chunk row over a body-fallback source;
   - delete the relevant representations.

After the batch transaction releases locks, normal representation writes proceed.

## Required deterministic tests

Extend focused C1 tests / representation tests to prove at minimum:

1. `TOOL_REGISTRY["apply_role_import_batch"].prepare_method is None`;
2. no `prepare_apply_role_import_batch` method remains on `DomainToolService`;
3. tool stays INTERNAL_WRITE, assistant_exposed=false, mcp_exposed=false;
4. specialized `/people/role-import/action-plan` still prepares one valid frozen plan;
5. approved action still executes through execution_input_model;
6. a text source using body fallback and **zero** Representations is held inside approved batch execution;
7. concurrent `ClientRepresentationPersistence.replace_for_object()` attempting to add a full/chunk representation hits short `lock_timeout` and cannot commit;
8. concurrent `RepresentationService.ingest_text_content()` similarly cannot replace/insert while source Object lock is held;
9. concurrent representation delete path cannot pass the same Object lock;
10. existing source Representation lock test remains green;
11. after the confirmation transaction releases, a normal representation write can succeed;
12. no sleeps as correctness primitives.

Also rerun:

- `backend/tests/test_rel1d_role_import_batch.py`
- `backend/tests/test_rel1d_role_import_grounding.py`
- `backend/tests/test_rel1d_role_import_source.py`
- focused `test_representations.py`
- focused client-representation persistence/intake tests
- `backend/tests/test_tool_gateway.py`
- ActionPlan focused tests
- REL1C role-write regression
- REL1B concurrency regression
- Ruff
- py_compile if useful
- `git diff --check`

All new/focused relevant tests must report 0 failed.

## Preserve C1 semantics

Do not change:

- specialized prepare request/selection semantics;
- server re-grounding;
- source/grounding stale errors;
- Person/promotion revalidation;
- RoleTerm reuse/create semantics;
- role-import provenance;
- active cap 16;
- batch dedup;
- ActionPlan atomic rollback;
- execution result/effects;
- client code;
- Alembic/schema.

## Expected changed files

Expected narrow subset:

- `backend/app/tools/registry.py`
- `backend/app/services/domain_tool_service.py`
- `backend/app/services/representation_service.py`
- `backend/app/services/client_representation_service.py`
- `backend/tests/test_rel1d_role_import_batch.py`
- focused representation/client-intake/tool-gateway tests
- parity doc only if required

No Flutter changes expected.

## Production boundary

Source-only.

Do not:

- move `production`;
- deploy;
- migrate;
- build/install client;
- call a real model/provider;
- mutate production product data.

Production/backend/client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`.
Alembic remains `0054 / 0054`.

REL1D-C2 must not start.

## Completion

Update `PROJECT_STATE.md` with compact C1.1 result and note that C1 remains pending Architect acceptance until this corrective is reviewed.

Return `CURRENT_TASK.md` to HOLD with:

- implementation SHA;
- changed files;
- exact green test counts;
- proof generic prepare path is gone;
- proof body-fallback -> first Representation insert is blocked during approved batch;
- schema still `0054`;
- production/client unchanged;
- no deploy/migration/client install/model/provider/product-data action;
- C2 not started.

Commit + push `main`, then STOP.
