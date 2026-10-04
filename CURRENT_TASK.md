# CURRENT_TASK

## Status

ACTIVE

## REL1D-C1.2 — privacy-safe public ActionPlan serialization

REL1D-C2.1 implementation `6eac184a0b45ee4ddb6f1ccee457e622c8283bf3` is **ARCHITECT SOURCE-ACCEPTED**.

REL1D as a whole is **not yet source-accepted** because final review found one narrow backend privacy defect in the C1 ActionPlan public projection.

### Confirmed defect

The internal frozen payload for `apply_role_import_batch` correctly contains execution-only fields such as:

- `source_revision`;
- `grounding_revision`;
- `selected_rows`;
- `person_id` or `promotion_candidate_key`;
- `role_term_id`;
- extracted Person name;
- frozen target/role/context fields.

That payload is required internally for approved execution and must remain exact in `PendingActionPlan.actions`.

However `ActionPlanService._public_actions()` currently applies only the generic hidden-key filter (`operation_id`, RFC/calendar internals). Therefore public ActionPlan views for this composite expose the remaining frozen canonical payload beside the safe approval presentation.

This violates the intended privacy boundary of REL1D: approval UI/API must not expose candidate keys or raw composite execution arguments.

Backend implementation baseline:

- C1: `3d3bead03271bad5dfc5713eaf78a4d1062cb11e`
- C1.1: `5cb4fd7400c8e095b6949e25eac0d1afc7b9fa51`
- C2: `dc07dfce13bcaef08b51765ca5930266fa7c188b`
- C2.1: `6eac184a0b45ee4ddb6f1ccee457e622c8283bf3`
- current HOLD: `ba1a928a1a50417615d5c7229189fb9feed688e3`

Schema remains `0054`. Production/backend/client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`.

## Goal

Keep the exact frozen canonical action payload **internal**, while making every public ActionPlan representation of `apply_role_import_batch` privacy-safe.

The public approval truth for this composite is the deterministic backend `presentation`, not its execution arguments.

## Required serialization behavior

### A. Tool-aware public arguments

Make ActionPlan public serialization tool-aware.

For `apply_role_import_batch`:

- public `arguments` must contain **no frozen canonical execution payload**;
- preferred minimal shape: `{}`;
- do not expose:
  - `operation_id`;
  - source revision;
  - grounding revision;
  - `selected_rows`;
  - `person_id`;
  - `promotion_candidate_key`;
  - `role_term_id`;
  - extracted Person name;
  - frozen execution-only target data;
  - provenance/internal keys.

Do not weaken or delete the internally stored `PendingActionPlan.actions`.

Approved execution must continue to read the exact stored canonical payload, not the redacted public view.

### B. Preserve existing tools

Do not globally erase arguments for ordinary ActionPlans.

Existing public argument behavior for other tools must remain unchanged, including the current generic hidden-key rules.

Implement the redaction specifically for `apply_role_import_batch` (or via a narrowly explicit per-tool public projection mechanism).

No broad serializer redesign.

### C. Preserve safe presentation

The public action for `apply_role_import_batch` must retain its deterministic safe `presentation`:

- source title/id;
- selected/total counts;
- truncation flags;
- bounded rows:
  - row_index;
  - target display;
  - target mode;
  - role;
  - optional context;
  - vocabulary mode.

Presentation must still exclude candidate key, canonical identity, normalized role key, provenance key, upload path and evidence text.

### D. Generic approve/reject response must retain presentation

`backend/app/api/assistant.py::_serialize_action_plan_response()` currently reconstructs public actions without passing through `presentation`.

Correct this so approve/reject responses retain the already-frozen backend presentation.

Do not rebuild presentation at approve/reject time.

This matters for role-import because the client replaces its local plan with the approve/reject response.

### E. Specialized prepare endpoint

`POST /people/role-import/action-plan` must continue to prepare exactly one normal persisted ActionPlan through the existing C1 service.

Its response must expose:

- plan id;
- status;
- expires_at;
- one public action;
- safe presentation;
- redacted/empty public arguments.

Do not create a second plan DTO with independent approval semantics.

### F. Result semantics remain unchanged

Do not redact or redesign the C1 execution result in this slice.

The existing composite result contract is intentional and may include:

- source_object_id;
- counts;
- row_index;
- person_id;
- assignment_id;
- role_term_id;
- role/context;
- status.

It contains no promotion candidate key or canonical identity.

Client C2 already displays only the bounded truthful subset.

### G. Internal/external boundary proof

A test must prove both simultaneously:

1. the persisted internal ActionPlan still contains the exact frozen `promotion_candidate_key` / Person target and execution payload needed for approval;
2. the API/public `PendingActionPlanView` for the same plan does not contain it.

Do not "fix" privacy by deleting execution data from storage.

## Required tests

Add/extend focused backend tests proving at minimum:

1. role-import prepare with an explicit promotion candidate persists the exact candidate key internally;
2. prepare API response JSON does **not** contain that candidate key;
3. prepare response public action `arguments == {}` (or equivalently contains no canonical fields);
4. safe role-import presentation is still present and complete;
5. prepare response string/JSON contains no `promotion_candidate_key`, `selected_rows`, `grounding_revision`, `source_revision`, `role_term_id`, or extracted execution-only Person name outside intentional presentation;
6. approve response also has redacted arguments and retains the same frozen presentation;
7. reject response also has redacted arguments and retains the same frozen presentation;
8. repeated approve/idempotent executed response remains redacted;
9. failed/expired public views remain redacted;
10. `ActionPlanService.get_for_resume()` / `list_recent_terminal_plans()`, if exercised for this tool, also return the redacted public projection;
11. approved execution still succeeds using the internal canonical payload;
12. ordinary non-role-import ActionPlan public arguments remain backward-compatible;
13. generic hidden-key behavior for existing tools remains green;
14. approval presentation tests remain green;
15. C1/C1.1 batch tests remain green;
16. C2/C2.1 client parsing/UX tests remain green if backend response fixtures are affected.

Prefer an adversarial assertion over a promotion case because the opaque candidate key is the clearest privacy sentinel.

## Regression suites

Run at minimum:

- `backend/tests/test_rel1d_role_import_batch.py`;
- focused ActionPlan service/API tests;
- approval presentation tests;
- tool gateway/registry tests if serializer coupling reaches them;
- focused Assistant ActionPlan API tests;
- relevant C2 API/client tests if response serialization changes their fixtures;
- Ruff on changed Python;
- `py_compile` if useful;
- `git diff --check`.

All relevant focused checks: 0 failed.

Do not repair unrelated historical/shared-test debt.

## Expected files

Narrow backend subset, likely:

- `backend/app/services/action_plan_service.py`;
- `backend/app/api/assistant.py`;
- focused tests.

`backend/app/api/routes/role_import.py` only if a tiny response typing adjustment is necessary.

No domain persistence changes expected.

## Preserve all accepted semantics

Do not change:

- C1 atomic batch persistence;
- source/Object/Representation locks;
- Person grounding/promotion;
- RoleTerm normalization/reuse;
- assignment provenance;
- active cap 16;
- C2 explicit selection;
- C2 approve/reject endpoints;
- C2.1 conversation/session fence;
- voice approval behavior;
- ActionPlan TTL/status semantics;
- schema/Alembic;
- provider/model config.

No Assistant/model call is needed for this corrective.

## Production boundary

Source-only.

Do not:

- move `production`;
- deploy;
- migrate;
- install/replace client;
- call a real model/provider;
- run a real role import;
- mutate production data.

Production/backend/client remain exact:

`6f802d6959aca40758376a83d5bdfcbbd77fc537`

Alembic remains:

`0054 / 0054`.

REL1D rollout remains unauthorized.

## Completion

1. update `PROJECT_STATE.md` with:
   - C2.1 Architect source acceptance;
   - this privacy corrective implementation/proof;
   - exact test counts;

2. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - exact green checks;
   - proof that internal frozen payload remains intact but public role-import ActionPlan args are redacted;
   - schema `0054`;
   - production/client unchanged;
   - no deploy/migration/client install/model/provider/production-data action;
   - REL1D still awaits final Architect review;

3. commit + push `main`;

4. STOP.

Do not start rollout.
