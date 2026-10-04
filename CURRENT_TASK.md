# CURRENT_TASK

ACTIVE

## REL1D-HG1.1 — role-import preview/grounding scroll containment corrective

Human REL1D acceptance exposed a real desktop layout blocker.

Observed on the exact installed/production release `6693578d35c1ea1d6e25bf73768ca0cf6c07dac9`:

- a large extraction preview overflows the Assistant viewport instead of scrolling;
- a smaller extraction preview initially fits, but after `Сопоставить` the grounded rows extend below the visible area;
- Flutter shows the yellow/black RenderFlex overflow stripe;
- lower grounding controls/results become unreachable because the role-import surface has no usable vertical scroll path.

This task is ONLY the source corrective for that UI/layout defect.

Do not change role-import extraction semantics, Person grounding semantics, promotion eligibility, role vocabulary behavior, backend APIs, schema, production runtime, installed client, or human acceptance data in this task.

## Required bootstrap

Use only the canonical repository:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `client/lib/assistant/assistant_screen.dart`
- `client/lib/assistant/role_import_preview.dart`
- focused tests required for the fix.

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as the implementation base. Current main contains only ledger changes after the accepted REL1D product release; do not rebuild/install/deploy from this task.

## Required behavior

Fix the Assistant role-import layout so that both extraction and grounded/plan content remain usable at bounded desktop window heights.

Acceptance requirements:

1. No vertical `RenderFlex overflow` for a role-import preview with many extracted rows.
2. No vertical `RenderFlex overflow` after grounding adds substantially more row content.
3. The role-import content has an explicit usable vertical scroll path.
4. The user can scroll from the top of the role-import draft to:
   - `Сопоставить`;
   - grounded candidate choices/check boxes;
   - `Подготовить изменения`;
   - pending plan content and `Подтвердить` / `Отклонить`, when those states are present.
5. The Assistant message composer remains visible/usable rather than being pushed below the viewport by role-import content.
6. The active-context banner and ordinary Assistant conversation behavior must not regress.
7. Do not create multiple competing scroll regions unless required by the existing Assistant layout. Prefer the smallest integration-consistent fix.
8. Existing role-import loading/error/stale/selection/frozen-plan semantics must remain unchanged.
9. Do not reduce item counts, hide rows, truncate UI content, or change backend limits as a substitute for scrolling.

## Tests

Add focused widget coverage that reproduces the human failure at a constrained desktop height.

At minimum prove:

- extraction with enough rows to exceed the available height renders without overflow;
- the lower `Сопоставить` control becomes reachable by scrolling;
- after grounding with enough rows to exceed the available height, grounded content and the lower action control become reachable by scrolling;
- the message composer remains present in the actual Assistant integration;
- no Flutter layout exception / overflow is emitted in those cases.

Prefer an integration-level Assistant widget test for the production layout. Update `role_import_preview_test.dart` only where useful; do not satisfy this task solely by wrapping the standalone test harness in a scroll view if the real Assistant layout remains broken.

Run at minimum:

- focused role-import preview/plan tests;
- the focused Assistant screen/layout test(s) you add or modify;
- `flutter analyze` on touched client files;
- `flutter test` for the touched focused suites;
- `git diff --check`.

Do not broaden into unrelated existing Flutter warnings/infos.

## Explicit non-goals

Do not:

- change `PersonRoleImportGroundingService`;
- change `PersonPromotionService`;
- change candidate filtering or communication evidence rules;
- change role extraction prompts or item limits;
- change backend code;
- change dependencies;
- deploy backend;
- move `production`;
- build/install/replace the Linux client;
- perform human REL1D acceptance;
- call a model/provider;
- mutate production/product data.

The Architect will review the separate communication-evidence grounding rule after this UI blocker is source-fixed.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG1.1` entry to `PROJECT_STATE.md` containing:
   - implementation commit SHA;
   - files changed;
   - exact focused test results;
   - analyze result;
   - `git diff --check` result;
   - confirmation that no backend/API/schema/candidate semantics changed;
   - confirmation that no deploy/client install/model/provider/product-data action occurred.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - scroll corrective implemented;
   - exact implementation SHA;
   - source is ready for Architect review;
   - production/backend/client remain `6693578d35c1ea1d6e25bf73768ca0cf6c07dac9`;
   - human REL1D acceptance remains paused until Architect reviews and authorizes rollout;
   - do not start the communication-evidence grounding change or any other slice.

3. commit + push to `main`.

4. STOP.

On blocker, record only the exact bounded blocker, return HOLD, commit/push accurate ledger if appropriate, and STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
