# Current task — HOLD

UX-CAP1 is complete. Do not start the next remediation item from this HOLD.

## Implementation

- SHA: `68ade82eb612953c416dda9de5ae4a05fd065582`
- Changed files:
  - `client/lib/capture/capture_controller.dart`
  - `client/lib/navigation/secretary_navigation.dart`
  - `client/lib/objects/object_detail_screen.dart`
  - `client/lib/graph/graph_workspace_screen.dart`
  - `client/test/capture/capture_test.dart`

## Regression behavior

- Ordinary `openCapture` calls `beginFreshTaskCapture`. The new session has empty text, title, context ids, context refs, dependency ids, due/planned fields, and the default completion mode `finite`.
- Graph and Object Detail pass the selected object into `openCapture`, which calls `beginTaskCaptureWithContext`. The session context is that object only.
- Leaving the capture route calls `beginFreshTaskCapture`, so an abandoned draft cannot remain for the next entry.
- A current contextual session still shows `Контекст: …` and sends that object id.
- Same-session `attachContext` still adds a further object and does not clear due, planned interval, or completion mode.
- Successful submit still resets the draft and still sends the current session's explicit context.

## Checks

- `flutter test test/capture/capture_test.dart test/objects/object_detail_test.dart test/graph/graph_workspace_screen_test.dart test/shell/app_shell_test.dart`: 44 passed, 3 failed.
- The 3 failures are in `graph_workspace_screen_test.dart`:
  - `Details delete refreshes overview without deleted task`
  - `Details delete current root falls back to overview`
  - `Details Ask Secretary does not refresh disposed Graph screen`
  They look for visible text `Удалить` or `Спросить секретаря` after opening object detail. This slice did not change those controls.
- `flutter analyze` on `capture_controller.dart`, `secretary_navigation.dart`, `object_detail_screen.dart`, and `capture_test.dart`: no issues.
- Backend `tests/test_auth_capture.py` and `tests/test_capture_s2_completion_mode.py`: 38 passed.
- `git diff --check`: clean.

## Unchanged

- Backend capture semantics were not changed.
- No schema or Alembic change.
- `backend/app` still matches production `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`.
- Production was not changed. Runtime/ref remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`, Alembic `0052 / 0052`, health PASS.
- Model calls: 0. No deploy.
