# CURRENT_TASK

ACTIVE

## REL1D-HG1.3 — role-import scroll geometry + operation auto-follow corrective

Human REL1D acceptance on deployed release:

`1879aabc97bfc5ed13fbc2ffa4d0c9c7ccbb3320`

confirmed that HG1.1 removed the RenderFlex overflow, but exposed two remaining client UX defects:

1. the role-import scroll region visibly stops well above the composer in an otherwise empty Assistant conversation, leaving an artificial blank message-list area below it;
2. after role-import operations such as `Извлечь роли` / `Сопоставить`, new loading/result content can appear below the current scroll position, so the user sees only a few pixels or no obvious state change until manually scrolling.

This task is ONLY the source corrective for those client UX defects.

Do not change backend code, role-import extraction/grounding semantics, communication evidence rules, candidate discovery, ActionPlan semantics, schema, dependencies, production runtime, or the installed client.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- `client/lib/assistant/assistant_screen.dart`
- `client/lib/assistant/role_import_preview.dart`
- `client/test/assistant/role_import_scroll_test.dart`

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as the source base.

Production/backend/client remain exact `1879aabc97bfc5ed13fbc2ffa4d0c9c7ccbb3320`; do not deploy/install anything in this task.

## Required behavior A — scroll geometry

Fix the real `AssistantScreen` layout, not a standalone test harness.

When role-import context is active:

1. The role-import scroll surface must use the available vertical space naturally.
2. In an empty conversation/message list, do **not** reserve a large artificial blank message-list floor below role import.
3. The role-import scroll viewport should extend down close to the composer while still leaving the composer fully visible and usable.
4. If ordinary Assistant messages are actually present, preserve a reasonable visible message-history area rather than letting role import permanently cover it.
5. Do not reintroduce RenderFlex overflow.
6. Do not hide/truncate role-import rows to make the geometry pass.
7. Keep the active-context banner visible.
8. Keep the composer visible.
9. Keep ordinary conversation scrolling independent from role-import scrolling.

Add an explicit role-import `ScrollController` if needed.

Prefer a visible/normal desktop scrollbar associated with the role-import controller so its track/thumb clearly corresponds to the actual role-import viewport. Do not create a second competing role-import scrollable.

## Required behavior B — operation auto-follow

User-triggered role-import operations must make their newly rendered progress/result state visible without requiring manual discovery.

At minimum:

- after pressing `Извлечь роли`, the role-import surface follows/reveals the loading/result content;
- after pressing `Сопоставить`, the surface follows/reveals the grounding result/empty-state content;
- after pressing `Подготовить изменения`, the pending ActionPlan controls become visible;
- after approve/reject/edit-selection transitions, the resulting role-import state should remain visible.

The simplest acceptable behavior is to auto-scroll the role-import surface to its current end after the relevant role-import callback starts/completes, after layout has settled.

Requirements:

- only role-import actions trigger this auto-follow;
- ordinary Assistant message/controller updates must not unexpectedly yank the role-import scroll position;
- callbacks must preserve existing error/stale/selection/frozen-plan behavior;
- no duplicate API call may be introduced;
- do not auto-scroll the ordinary Assistant message list as a substitute.

## Focused tests

Extend the real `AssistantScreen` integration widget coverage.

At minimum prove:

1. constrained desktop surface still has zero RenderFlex overflow;
2. with an empty Assistant message list and long role-import content, the role-import viewport bottom sits close to the composer instead of leaving the previous large blank floor;
3. composer remains fully visible;
4. a role-import scrollbar/scrollable has one clear controller/path;
5. tapping `Извлечь роли` and waiting for completion makes the lower result/action area visible without an explicit test-side `scrollUntilVisible`;
6. tapping `Сопоставить` makes the grounding result/empty-state/lower control visible without manual test-side scrolling;
7. preparing a plan makes confirm/reject reachable/visible via the production auto-follow behavior;
8. when ordinary Assistant messages exist, message history remains present and independently scrollable;
9. no unrelated Assistant controller update forces the role-import view to jump.

Run at minimum:

- `client/test/assistant/role_import_scroll_test.dart`
- `client/test/assistant/role_import_preview_test.dart`
- `client/test/assistant/role_import_plan_test.dart`
- any directly affected Assistant layout/conversation tests
- focused `flutter analyze` on touched client source/tests
- `git diff --check`

Do not broaden into unrelated historical warnings/debt.

## Explicit non-goals

Do not:

- modify `PersonRoleImportGroundingService`;
- modify `PersonPromotionService`;
- change communication participant/direct-contact rules;
- change extraction prompts/models/item limits;
- change backend/API/schema;
- change dependencies;
- deploy backend;
- move `production`;
- build/install the Linux client;
- perform human REL1D acceptance;
- call model/provider APIs;
- mutate product data.

The separate communication-candidate issue observed for names such as Шабаршина Ирина Сергеевна will be handled by a later Architect task after this UI corrective is reviewed.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG1.3` entry to `PROJECT_STATE.md` with:
   - implementation SHA;
   - files changed;
   - geometry behavior;
   - auto-follow behavior;
   - exact focused test/analyze/diff-check results;
   - confirmation no backend/API/schema/grounding/candidate semantics changed;
   - confirmation no deploy/install/model/provider/product-data action occurred.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG1.3 implementation SHA;
   - source ready for Architect review;
   - production/backend/client remain `1879aabc97bfc5ed13fbc2ffa4d0c9c7ccbb3320`;
   - Alembic remains `0054 / 0054`;
   - human acceptance remains paused;
   - do not deploy/install or start the communication-candidate corrective without fresh Architect authorization.

3. commit + push to `main`.

4. STOP.

On blocker, record the exact bounded blocker, return HOLD, commit/push accurate ledger if appropriate, and STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
