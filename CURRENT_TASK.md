# Current task — Telegram MTProto C3AR2: unify scope rendering and close contract tests

## Status

Telegram MTProto C2B/C2BR/C2BR2 deterministic notifications are ACCEPTED / INTEGRATED TO MAIN.

C3A implementation:
`d761d1aeab6b99530910a0292ba82e322a5885b3`

C3AR corrective:
`8c136b742a3d2ba67cb083d32cb88b6c438d3850`

C3AR fixes are accepted in direction:
- explicit phone/code/password auth state machine;
- password UI appears only after `password_required`;
- reconcile peers became actionable;
- group forum/unavailable metadata is explicit;
- MTProto action 401s route through `AuthController.handleAuthenticationFailure()`;
- full analyzer comparison reports zero new diagnostics.

C3A/C3AR is still **REJECTED pending this narrow C3AR2 corrective**.

Production remains untouched:
- runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- production Alembic `0041`;
- repository Alembic head must remain `0046`;
- M3 NOT authorized;
- Bot API retirement NOT authorized.

## Blocking issue 1 — preview/reconcile scope rows are still duplicated and can become stale

At C3AR SHA `8c136b742a3d2ba67cb083d32cb88b6c438d3850`:

- preview rows are rendered directly with:
  `for (final dialog in preview.dialogs) _peerRow(dialog)`
- after reconcile, rows are rendered again from `_scopeDialogs(reconcile)`;
- `_scopeDialogs(reconcile)` itself merges preview dialogs and reconcile peers.

Therefore:
1. a peer present in both preview and reconcile can be rendered twice;
2. a peer present only in the old preview can remain visible/actionable after reconcile even if reconcile removed/deactivated it.

This violates the C3AR requirement for one clear current-scope list without duplicates.

Correct narrowly.

Required presentation invariant:
- before reconcile result exists: render the current preview dialog list;
- after reconcile result exists: render the current reconcile `peers` list as authoritative current scope;
- each `peer_id` appears at most once;
- a peer that existed in preview but is absent from the reconcile result must disappear from the actionable current-scope list;
- do not merge stale preview membership into reconciled membership;
- private/group/supergroup peer sync action remains available for the authoritative displayed list;
- preview counts/truncated/skipped information may remain visible as historical preview information, but its dialog rows must not be duplicated alongside reconciled rows.

Add a focused widget regression that:
1. preview returns peers A and B;
2. reconcile returns peers B and C;
3. after preview, A and B each appear once;
4. after reconcile, actionable current-scope rows are exactly B and C, each once;
5. A is no longer actionable/visible as current scope;
6. syncing B or C uses the existing exact scope-peer endpoint.

Use stable widget keys for peer rows/sync actions so the test does not depend on ambiguous text counts.

## Verification gap 2 — test server-not-configured against the real backend contract

The current widget test models server-not-configured as:
HTTP 200 with `{"configured": false, "connected": false}`.

But the existing backend route calls `_require_configured()` first and the real contract for an unconfigured MTProto backend is:
- HTTP 503
- safe detail: `Telegram MTProto is not configured`.

The implementation already has logic intended to map that safe 503 detail to the “not configured” UI. Prove that real path.

Required:
- change/add the focused test so the status request returns the real 503 response body;
- prove the UI renders the server-not-configured state;
- do not change backend behavior for this task.

You may keep model parsing coverage for `configured=false` separately if useful, but it does not replace the real route-contract widget test.

## Verification gap 3 — explicit ignore_muted round-trip proof

The C3AR acceptance report did not map the required `ignore_muted` round-trip to an exact test, and the current zero-folder widget test only proves that a PUT occurred; it does not prove the boolean sent to the backend.

Add focused evidence that:
- configured sync folders response with `ignore_muted=true` initializes the switch to true;
- toggling it to false and saving sends:
  `{"folder_names": <current selected names>, "ignore_muted": false}`;
- the zero-folder case still sends an empty `folder_names` list rather than substituting defaults;
- a subsequent loaded configured response with false is represented as false.

This can be one focused widget/API test if it proves the whole round trip.

## Acceptance evidence

Return an updated acceptance matrix:
`required invariant -> exact test name -> file`

It must explicitly include:
- real 503 server-not-configured UI path;
- configured/disconnected;
- connected identity;
- direct code auth without 2FA;
- password-required auth;
- duplicate submit protection;
- sensitive state cleared after success;
- zero-folder save;
- ignore_muted true->false round trip;
- preview truncated/skipped counts;
- preview/reconcile authoritative peer replacement with no duplicates/stale rows;
- reconcile peer sync exact endpoint + summary;
- group selected toggle;
- forum label;
- unavailable group label/non-actionability;
- manual group sync summary;
- 401 global auth failure;
- sanitized 400/409/410/503 API error convention.

## Required checks

Run:
- focused C3A/C3AR/C3AR2 Flutter tests;
- relevant existing Account/API client regressions;
- `dart format --output=none --set-exit-if-changed` on changed Dart files;
- full `flutter analyze`.

If full analyze remains non-zero:
- compare exact base `0cdcbaa0498f8e4c1ef3033c5c7d544bb8590319` vs C3AR2 head with the same command;
- report base count, head count, common/base-only/head-only;
- C3AR2 must introduce zero new diagnostics.

Also:
- `git diff --check`;
- repository Alembic head exactly `0046`;
- clean worktree.

Backend changes are not expected or authorized.

## Explicitly out of scope

Do NOT implement:
- C3B Telegram-specific Inbox/notification presentation;
- backend MTProto redesign/new endpoints;
- disconnect/delete account semantics;
- OS notifications;
- websocket/SSE;
- realtime Telethon listener;
- client-side Telegram SDK;
- migration `0047`;
- production deploy/ref move;
- production DB/env mutation;
- Bot API retirement.

## Branch / deliverable

Continue existing branch:
`review/telegram-mtproto-c3a-client-account`

Continue from exact:
`C3AR2_BASE_SHA=8c136b742a3d2ba67cb083d32cb88b6c438d3850`

Create exactly one corrective commit on top.
Do not rewrite/squash C3A or C3AR.

Return:
- `C3AR2_BASE_SHA`;
- `C3AR2_SHA`;
- changed files;
- exact scope-rendering correction;
- real-503 test proof;
- ignore_muted round-trip proof;
- updated acceptance matrix;
- focused/regression results;
- analyzer result/baseline comparison;
- Dart format;
- `git diff --check`;
- Alembic `0046`;
- clean worktree;
- remote branch SHA;
- backend/migrations/production untouched.

Final marker:
`TELEGRAM_MTPROTO_C3AR2_CLIENT_ACCOUNT_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
