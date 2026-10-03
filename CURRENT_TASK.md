# CURRENT_TASK

## Status

ACTIVE

## REL1D-B.1 — preserve extraction completeness through grounding and fence stale retry

REL1D-B implementation `c0599932a9c917e0efde51d237d8cb3df79c5a88` is directionally correct but **not yet Architect source-accepted**.

Architect review found one narrow B→C contract defect:

1. REL1D-A can return `items_truncated=true` when provider output contains more than 32 normalized rows;
2. REL1D-B grounding currently has no input field carrying that extraction fact and constructs every grounded proposal with `items_truncated=false`;
3. therefore `grounding_revision` cannot distinguish a complete 32-row extraction from a truncated-to-32 extraction;
4. the Dart `RoleImportGroundedPreview` also drops `source_kind`, `source_truncated`, and `items_truncated`, which would make the grounded proposal an incomplete freeze for REL1D-C;
5. after a backend `role_import_source_changed` conflict, the stale extraction remains visibly marked stale but `Сопоставить` can still be invoked again, producing repeated doomed requests instead of requiring re-extraction.

Fix only these truthfulness/freshness issues.

Do not start REL1D-C.

No deploy, migration, client install, model/provider call, or production-data mutation.

## Preserve the accepted REL1D-B direction

Do not change:

- Person grounding through existing `PersonAssistantService.resolve()`;
- ambiguous/name-variant safety;
- promotion-candidate eligibility or exact-display matching;
- opaque promotion keys;
- exact RoleTerm reuse / propose-new semantics;
- lexical suggestion behavior;
- read-only/no-write/no-AI guarantee;
- max 32 extraction rows;
- max 3 promotion candidates;
- max 5 role suggestions;
- source-revision revalidation;
- neutral candidate ordering;
- schema head `0054`.

Production/backend/client remain:
`6f802d6959aca40758376a83d5bdfcbbd77fc537`

Alembic remains:
`0054 / 0054`.

## Required correction A — carry extraction items_truncated into grounding

Extend strict grounding request to include:

- `items_truncated: bool`

Request fields become exactly:

- `source_object_id`
- `source_revision`
- `items_truncated`
- `items`

Extra properties remain forbidden.

The client must send the exact `RoleImportPreview.itemsTruncated` value returned by REL1D-A.

The backend must not derive this flag from `len(items) == 32` because:

- exactly 32 provider rows may be complete;
- >32 provider rows are truncated to the same visible length.

### Grounded response

Set:

- `items_truncated = request.items_truncated`

The server continues to compute:

- `source_kind`;
- `source_truncated`;

from the currently revalidated source, not from client claims.

Because `grounding_revision` hashes the complete grounded response excluding only itself, the truthful `items_truncated` value must participate automatically.

Required proof:

- same source/rows with `items_truncated=false` and `true` produce different `grounding_revision`;
- exactly 32 rows + false stays false;
- 32 rows + true stays true;
- zero rows may carry false; client D-A path should naturally send false for an empty non-truncated proposal.

## Required correction B — preserve grounded completeness fields in Dart model

`RoleImportGroundedPreview` must retain:

- `sourceObjectId`
- `sourceRevision`
- `sourceKind`
- `sourceTruncated`
- `itemsTruncated`
- `groundingRevision`
- `items`

Do not silently drop the fields already returned by the backend.

The grounded UI may continue using the extraction preview for the current warning, but the grounded model itself must be self-contained enough for REL1D-C freshness/confirmation work.

## Required correction C — stale source disables grounding until re-extraction

When `role_import_source_changed` occurs:

- `roleImportStale=true`;
- grounded result remains cleared;
- user sees exactly the existing message or equivalent:
  - `Источник изменился — извлеките роли заново`;
- another grounding request from that stale extraction must not be issued.

Implement both layers:

1. controller `groundRoles()` returns immediately when `roleImportStale` is true;
2. UI disables or hides `Сопоставить` while `sourceStale` is true.

Explicit re-extraction:

- clears stale state;
- receives a new/current source revision;
- restores grounding eligibility when rows exist.

Changing object context also clears stale state as today.

A late response from a previous source/extraction must remain fenced by epochs/revision checks.

## Required deterministic backend tests

Extend `backend/tests/test_rel1d_role_import_grounding.py` to prove:

1. request without `items_truncated` fails strict validation;
2. extra fields still fail;
3. `items_truncated=false` is preserved in response;
4. `items_truncated=true` is preserved in response;
5. exactly 32 rows does not force truncation when false;
6. exactly 32 rows remains truncated when true;
7. toggling only `items_truncated` changes `grounding_revision`;
8. source kind/truncation are still server-derived;
9. no product rows or AI audit rows are written;
10. existing Person/promotion/RoleTerm grounding tests remain green.

## Required deterministic client tests

Extend focused role-import preview/controller tests to prove:

1. grounding JSON sends `items_truncated` from the exact extraction preview;
2. grounded model parses/stores:
   - source kind;
   - source truncated;
   - items truncated;
3. backend source-changed conflict marks extraction stale;
4. while stale:
   - grounding button is disabled/absent;
   - calling controller `groundRoles()` directly issues no HTTP grounding request;
5. explicit re-extraction clears stale state;
6. new extraction may be grounded again;
7. existing late-response/context-change guards remain green;
8. `Ничего не сохранено` remains visible;
9. no save/approve/apply controls are introduced.

## Regression checks

Run at minimum:

Backend:

- `backend/tests/test_rel1d_role_import_grounding.py`
- `backend/tests/test_rel1d_role_import_source.py`
- `backend/tests/test_rel1d_role_import_extraction.py`
- focused PER1/promotion/REL1A/REL1C regressions if touched
- Ruff
- `git diff --check`

Client:

- `client/test/assistant/role_import_preview_test.dart`
- focused Flutter analyze on changed Dart files.

All new/focused relevant checks must be 0 failed.

Known unrelated shared-DB/transcription debt remains out of scope.

## Expected changed files

Expected product changes are narrowly limited to:

- `backend/app/services/person_role_import_grounding_service.py`;
- `backend/tests/test_rel1d_role_import_grounding.py`;
- `client/lib/api/role_import_models.dart`;
- `client/lib/api/secretary_api_client.dart`;
- `client/lib/assistant/assistant_controller.dart`;
- `client/lib/assistant/role_import_preview.dart`;
- focused client test.

Do not change Person resolver, promotion eligibility, RoleTerm service, extraction provider, audit/budget code, Alembic, Proactive, Assistant ActionPlan tools, or schema.

## Explicit non-goals

Do not add:

- Person selection;
- promotion execution;
- RoleTerm creation;
- PersonRoleAssignment writes;
- batch ActionPlan;
- save/apply/approve UI;
- source provenance persistence;
- Organization;
- deployment.

## Production / external-effect boundary

Source-only.

Do not:

- move `production`;
- deploy;
- migrate;
- build/install client;
- call real model/provider;
- mutate production data.

## Completion protocol

After implementation:

1. append compact REL1D-B.1 result to `PROJECT_STATE.md` with:
   - truthful items-truncated propagation;
   - grounding-revision proof;
   - self-contained grounded client model;
   - stale retry fence;
   - exact test counts;

2. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - exact green test counts;
   - schema still `0054`;
   - production/client still `6f802d...`;
   - no deploy/migration/client install/model/provider/product-data action;
   - REL1D-C not started;

3. commit + push to `main`;

4. STOP.

Do not start REL1D-C from HOLD.
