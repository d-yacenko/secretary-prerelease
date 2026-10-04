# CURRENT_TASK

ACTIVE

## REL1D-HG1.2 — communication-backed role-import grounding boundary

REL1D-HG1.1 scroll corrective is **ARCHITECT SOURCE-ACCEPTED** at:

`6f0a51b947d19eff2ccb840e7262f463a862304e`

Do not deploy or install it yet. The Architect is batching that UI corrective with this grounding corrective before the next controlled rollout.

Human acceptance clarified the product rule:

**An organization chart / roster is role evidence, not an independent source of Person existence.**

Role-import extraction may still extract every visible person/role row from the supplied source. But after `Сопоставить`, actionable grounded rows must be limited to people who have independent stored communication evidence in Secretary.

This task is only that grounding/source corrective plus the minimum client presentation needed to make the filtering understandable.

Do not deploy backend, run Alembic, move `production`, build/install the Linux client, perform the human acceptance flow, or call a real model/provider.

## Architectural rule

The source document/screenshot answers:

- “what role/title is shown for this name?”

It must **not** by itself answer:

- “this is a person the user knows / should create in People.”

Independent communication evidence is required before a row becomes actionable.

Use stored first-party communication facts only. Do not use arbitrary body-text mentions, semantic name similarity in unrelated documents, or the role-import source itself as communication evidence.

## Existing Person path

For rows where `PersonAssistantService.resolve(name)` returns an existing Person:

1. Require at least one attributable stored communication for that Person from the existing bounded Person communication scan.
2. Reuse the existing `PersonAssistantService.count_attributable_communications(...)` behavior rather than inventing a new provider scan if practical.
3. A positive count is sufficient evidence for this gate.
4. A zero count means “not proven in the bounded communication scan” and the row is not actionable.
5. If the scan is truncated and the count is zero, fail closed: do not infer lifetime absence, just exclude the row from this import proposal.

Do not change Person resolution globally.

## Ambiguous existing-Person path

When normal Person resolution is ambiguous:

1. Evaluate communication evidence for the candidate Person ids in one bounded scan where practical.
2. Keep only candidates with a positive attributable communication count.
3. If more than one remains, keep `ambiguous`.
4. If exactly one remains, **still keep the row explicit-choice / ambiguous**. Do not silently auto-resolve merely because filtering left one candidate.
5. If none remain, exclude the row from the grounded actionable proposal.
6. If graph candidates existed but all fail the communication gate, do **not** fall through to creating a new promotion candidate with the same display name in this task. Avoid accidental duplicate People.

## Not-yet-Person path

If normal Person resolution finds no existing/ambiguous graph candidate:

- reuse the existing role-import promotion path based on `PersonPromotionService.eligible_direct_contacts()`;
- keep its exact-name matching;
- keep its existing suppression/owned-identity protections;
- keep the existing repeated-direct-contact threshold and `MIN_DIRECT_HITS`;
- do **not** weaken generic promotion safety in this corrective.

Therefore a not-yet-Person name is actionable only when it already qualifies as an existing communication-backed promotion candidate.

The organization chart alone must never create a promotion candidate.

## Grounded proposal shape

After grounding:

- include only rows that passed one of the communication-backed paths above;
- omit source-only/out-of-scope rows from `RoleImportGroundedProposal.items`;
- preserve each surviving row's original extraction `row_index`; do not renumber;
- preserve source revision, source/item truncation flags, stale detection, grounding revision, role reuse/propose-new semantics, and deterministic ordering;
- ActionPlan preparation must remain possible only for explicitly selected surviving rows.

Do not change the extraction item limit as a substitute for filtering.

## Minimal client presentation

Because extraction may show many rows and grounding may intentionally return only a subset, make that transition understandable.

In the role-import grounded UI:

- when grounding has completed, state concisely that only people backed by stored communication evidence are shown/actionable;
- if `grounded.items` is empty, show a clear message such as:
  `Среди извлечённых строк нет контактов с подтверждённой перепиской`;
- do not show disabled checkboxes for filtered-out source-only rows;
- do not expose raw identities, email addresses, provider ids, candidate keys, or other private grounding internals.

No new API field/count is required unless the implementation genuinely needs one. Prefer the smallest contract change.

## Required tests — backend

Extend focused REL1D grounding coverage to prove at minimum:

1. existing resolved Person + attributable communication > 0 => row survives;
2. existing resolved Person + no attributable communication => row omitted;
3. ambiguous candidates => only communication-backed candidates survive;
4. a single surviving ambiguous candidate still requires explicit choice and is not silently resolved;
5. ambiguous graph candidates all filtered out => row omitted and no promotion fallback;
6. unknown name + existing eligible direct-contact promotion candidate => row survives as `promotion_candidates`;
7. unknown name present only in the imported source => row omitted;
8. surviving rows preserve original `row_index` when earlier rows are filtered;
9. exact RoleTerm reuse / propose-new behavior remains unchanged for surviving rows;
10. no provider/model call is introduced by grounding.

Preserve the existing source-change/stale tests.

## Required tests — client

Add/update focused widget tests proving:

- extraction can still display all extracted rows before grounding;
- after grounding, only returned communication-backed rows are rendered as actionable;
- the communication-evidence explanation is visible;
- an empty grounded proposal produces the clear empty-state message and no enabled prepare path;
- existing scroll corrective behavior is not regressed.

Run at minimum:

- `backend/tests/test_rel1d_role_import_grounding.py`;
- any directly affected Person/promotion focused tests;
- `client/test/assistant/role_import_preview_test.dart`;
- `client/test/assistant/role_import_plan_test.dart`;
- `client/test/assistant/role_import_scroll_test.dart`;
- Ruff on touched backend Python;
- focused `flutter analyze` on touched client files;
- `git diff --check`.

Do not broaden into historical unrelated warnings/debt.

## Explicit non-goals

Do not:

- change extraction prompts/models;
- lower or globally change `MIN_DIRECT_HITS`;
- treat arbitrary textual mentions as communication evidence;
- auto-create Person rows;
- auto-apply roles;
- change ActionPlan approval requirements;
- change role lexical normalization/reuse semantics;
- add schema/migrations;
- redesign Person resolution globally;
- deploy or install anything;
- perform real extraction/model calls;
- mutate product data.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG1.2` entry to `PROJECT_STATE.md` containing:
   - implementation commit SHA;
   - files changed;
   - exact backend/client focused test results;
   - Ruff/analyze/diff-check results;
   - the final communication-evidence rule implemented;
   - confirmation that generic promotion threshold/safety was unchanged;
   - confirmation that no deploy/client install/model/provider/product-data action occurred.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG1.2 implementation SHA;
   - HG1.1 and HG1.2 are ready for Architect source review;
   - production/backend/client remain `6693578d35c1ea1d6e25bf73768ca0cf6c07dac9`;
   - Alembic remains `0054 / 0054`;
   - human acceptance remains paused;
   - do not start rollout or another slice.

3. commit + push to `main`.

4. STOP.

On blocker, record the exact bounded blocker, return HOLD, commit/push accurate ledger if appropriate, and STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
