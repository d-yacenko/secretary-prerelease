# Current task — ACTIVE

## UX-CAP1.1 — close the client test gate for UX-CAP1

Architect review status:

- UX-CAP1 implementation: `68ade82eb612953c416dda9de5ae4a05fd065582`
- Executor HOLD / review base: `2e7255ad4d4753a1b8b68709a434fe18ceaeea87`
- production remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Alembic remains `0052 / 0052`

The UX-CAP1 source diff is architecturally sound on review: explicit capture-session initialization is localized to the client, contextual entry is atomic, same-session attachment remains available, and backend explicit-context semantics were not changed.

Formal acceptance is blocked only because the required focused client gate is red: 44 passed / 3 failed.

The three failures are all in `client/test/graph/graph_workspace_screen_test.dart`:

- `Details delete refreshes overview without deleted task`
- `Details delete current root falls back to overview`
- `Details Ask Secretary does not refresh disposed Graph screen`

The failing finders look for old visible text such as `Удалить` and `Спросить секретаря` after entering `ObjectDetailScreen`. Current UI uses the stable delete key/tooltip and the current Ask Secretary action presentation; UX-CAP1 itself did not modify those controls.

## Goal

Close the UX-CAP1 test gate without broadening product scope.

## Required work

1. In a clean checkout/worktree, establish whether the same three tests fail at the pre-UX-CAP1 authorization base:
   `87d9c71a7f8368f72a6b0ed2ca5ed5989844f273`.

2. Record the exact baseline result.

3. If the same failures reproduce on that base, treat them as stale/brittle test expectations and update only the affected tests to target the current semantic UI surface:
   - prefer stable keys, widget types, or tooltips;
   - do not restore obsolete visible labels merely to satisfy tests;
   - for delete, use the existing `object_detail_delete` key or `Удалить из Секретаря` tooltip rather than assuming visible `Удалить`;
   - for Ask Secretary, target the current action/tooltip rather than assuming the long phrase is visible text.

4. If any of the three tests is green at the pre-UX-CAP1 base but red on current main, STOP treating it as baseline debt. Diagnose the UX-CAP1 regression and make only the narrowest product correction needed.

5. Re-run the full required UX-CAP1 client gate and make it green:
   - `client/test/capture/capture_test.dart`
   - `client/test/objects/object_detail_test.dart`
   - `client/test/graph/graph_workspace_screen_test.dart`
   - `client/test/shell/app_shell_test.dart`

6. Re-run focused `flutter analyze` on every client file changed by UX-CAP1/UX-CAP1.1.

7. Re-run:
   - `backend/tests/test_auth_capture.py`
   - `backend/tests/test_capture_s2_completion_mode.py`
   - `git diff --check`

## Scope

Expected change if baseline is confirmed:

- `client/test/graph/graph_workspace_screen_test.dart`
- ledger only.

Do not change product code just to make a stale finder pass.

Product code may be changed only if baseline comparison proves an actual UX-CAP1 regression.

## Non-goals

Do not:

- start another remediation item;
- change capture semantics beyond a proven UX-CAP1 regression;
- change backend capture behavior;
- touch Assistant prompt/tools/eval behavior;
- work on finalization, T3, Person resolution, approval UX, Scheduled Activity, or other manual-acceptance findings;
- call a model;
- deploy or install a client;
- change schema/Alembic.

## Acceptance

UX-CAP1.1 is complete only when:

- baseline provenance for the three failures is explicit;
- the four-file Flutter gate is fully green on current main;
- UX-CAP1 stale-context regression coverage remains green;
- backend explicit-context tests remain green;
- analyze and `git diff --check` are clean;
- no unrelated product behavior is changed.

## Completion protocol

After completion:

1. append a compact factual UX-CAP1.1 result to `PROJECT_STATE.md`;
2. return `CURRENT_TASK.md` to HOLD with:
   - baseline comparison result;
   - implementation SHA;
   - changed files;
   - exact test/analyze counts;
   - confirmation that production/schema/model calls were untouched;
3. commit + push to `main`;
4. STOP.

Do not start the next remediation item from HOLD.
