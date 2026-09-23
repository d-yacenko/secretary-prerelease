# Current task — Fail-close noncanonical Telegram under global false

## Architect review

Commit:

`51b6b2eb2c227c00af680fd7e001289169f11dca`

is PARTIALLY ACCEPTED / NOT DEPLOY-READY.

The central self-authored MTProto exception is implemented correctly for canonical MTProto messages and the normal materializer/worker/downstream/catch-up path is directionally correct.

One policy blocker remains.

When `TELEGRAM_MTPROTO_AI_ENABLED=false`, the current ORM predicate and raw SQL fragment allow anything that is *not canonical MTProto*. `telegram_mtproto_ai_eligible()` also returns true immediately for noncanonical objects.

That preserves historical behavior for legacy Telegram, but conflicts with the newly approved production policy: while global Telegram AI is false, **all provider=telegram content must remain AI-ineligible except the narrow proven self-authored canonical MTProto exception**.

The new focused test currently encodes the wrong behavior by asserting legacy Telegram is eligible.

No production/deploy/live action is authorized.

## Required correction

Code/test-only.

### Global false semantics

When `settings.telegram_mtproto_ai_enabled == false`:

1. Objects whose provider is not `telegram` preserve existing behavior and remain eligible according to the surrounding pipeline policy.
2. Any object whose provider is `telegram` is AI-ineligible unless ALL of the following hold:
   - kind == `chat_message`;
   - metadata transport == `mtproto`;
   - account_id resolves to an account owned by the same application user;
   - peer_id resolves to a `scope_active=true` selection for that account;
   - direction == `outbound`;
   - sender_peer_id is non-empty;
   - account.telegram_user_id is non-null;
   - sender_peer_id == account.telegram_user_id.
3. Therefore legacy Bot API Telegram, unknown Telegram transports, Telegram objects with another kind, incomplete Telegram metadata, inbound Telegram, foreign sender, wrong account, and inactive scope are all false.

### Global true semantics

Do not change the existing global-true behavior. Preserve the current active-scope canonical MTProto policy and all existing non-Telegram behavior.

### Parity requirement

Keep these three implementations equivalent under global false:

- `telegram_mtproto_ai_eligible(session, obj)`;
- `telegram_mtproto_ai_predicate(model)`;
- `telegram_mtproto_ai_sql_fragment(alias)`.

A safe shape is conceptually:

- non-Telegram => existing allowed path;
- Telegram => canonical AND proven self-authored active-scope.

Do not rely on `NOT canonical` as the false-mode allow branch.

## Required tests

Update/add focused tests proving at least:

1. global false + canonical active-scope self-authored outbound => true on Python, ORM, raw SQL;
2. global false + inbound canonical => false on all three;
3. global false + foreign sender canonical => false;
4. global false + wrong/malformed account => false;
5. global false + inactive scope => false;
6. global false + Telegram legacy Bot transport => false on all three;
7. global false + Telegram unknown/non-MTProto transport => false;
8. global false + provider=telegram with non-chat kind => false;
9. global false + ordinary non-Telegram object => unchanged/eligible;
10. global true regression behavior remains unchanged;
11. normal MTProto materializer still enqueues exactly one embed entrypoint for self-authored outbound and zero for inbound/foreign;
12. global-false recurring catch-up remains zero;
13. AI-only object/context/search/correlation candidate surfaces continue to expose self-authored canonical Telegram and hide inbound/foreign/legacy Telegram;
14. no marker/harness/transport/session-decrypt dependency is introduced.

Run:
- `tests/test_telegram_mtproto_self_authored_policy.py`;
- `tests/test_telegram_mtproto_q1.py`;
- `tests/test_telegram_mtproto_full_pipeline.py`;
- any additional directly affected Telegram policy tests;
- `py_compile`;
- Ruff check;
- Ruff format --check;
- `git diff --check`.

## Hard stop

No production SSH.
No production Docker/Compose.
No deploy.
No provider calls.
No live Telegram test.
No remote E2E harness.
No production DB writes.
No production env changes.
No production ref movement.

When complete:
- update `PROJECT_STATE.md` factually;
- commit and push;
- report SHA and checks;
- STOP.

Deployment/live verification remains a separate explicit human authorization boundary after Architect review.
