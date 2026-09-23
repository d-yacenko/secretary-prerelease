# Current task — Allow self-authored Telegram messages through the normal production AI pipeline

## Architecture correction

The prior `telegram_self_authored_e2e` harness was useful for safety review, but it is not the intended acceptance mechanism.

The intended product behavior is:

- keep global `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- keep inbound/third-party Telegram content excluded from AI;
- allow a canonical Telegram MTProto message through the ordinary backend AI pipeline when it is provably authored by the connected user;
- verify the real production pipeline later by sending a new ordinary Telegram message after deployment.

No marker such as `TG_SELF_E2E_0922A` is part of the production policy.

The previous live harness attempt was terminated after roughly two hours. It produced no harness verdict; local wrapper exit `255` resulted from closing the active SSH channel. Do not retry that harness.

## Required production policy

A canonical Telegram MTProto chat message is self-authored AI-eligible while global Telegram AI is false only when ALL are true:

- provider == `telegram`;
- kind == `chat_message`;
- metadata transport == `mtproto`;
- metadata account_id resolves to a Telegram MTProto account owned by the same application user;
- metadata peer_id resolves to a `scope_active=true` selection for that account;
- metadata direction == `outbound`;
- metadata sender_peer_id is present;
- account.telegram_user_id is present;
- sender_peer_id == account.telegram_user_id.

Anything missing, malformed, inbound, wrong-account, wrong-sender, inactive-scope, legacy Bot API, or noncanonical must remain fail-closed for Telegram AI while the global flag is false.

When `TELEGRAM_MTPROTO_AI_ENABLED=true`, preserve the existing behavior: all canonical messages in active scope are AI-eligible regardless of direction, subject to existing policy.

Non-Telegram objects must preserve existing behavior.

## Authorized work

Code/test-only. No production access.

### 1. Central eligibility policy

Refactor `backend/app/domain/telegram_mtproto_ai.py` so the following remain semantically aligned:

- `telegram_mtproto_ai_eligible(session, obj)`;
- `telegram_mtproto_ai_predicate(model)`;
- `telegram_mtproto_ai_sql_fragment(alias)`.

When the global flag is false, all three must allow only the self-authored canonical MTProto exception described above.

Prefer a correlated `EXISTS` against `telegram_mtproto_accounts` + `telegram_mtproto_chat_selections` rather than trusting metadata direction alone.

Keep the active-scope requirement.

### 2. Normal ingestion path

Do not add a harness-only enqueue.

The existing `TelegramObjectMaterializer._enqueue_embed()` must naturally enqueue a newly materialized self-authored message under global false via the central eligibility policy.

A newly materialized inbound/foreign Telegram message under global false must enqueue no AI job.

### 3. Worker/downstream parity

Existing normal worker handlers and enqueue helpers must continue consulting the same eligibility policy, so a self-authored object remains allowed through:

- embedding;
- correlation;
- auto-label;
- temporal extraction/reconciliation;
- conversation-stack summary eligibility;
- context/retrieval/AI-only query surfaces that already use the SQL/ORM Telegram AI predicate.

Do not bypass daily OpenAI budget/configuration safeguards.

### 4. No false catch-up blast

Do NOT turn the existing global-false recurring embedding catch-up into a backlog sweep.

`TelegramMtprotoRecurringSyncService._enqueue_embedding_catchup()` must continue to enqueue zero Telegram catch-up jobs while the global flag is false.

This change is for newly created/semantically updated self-authored messages through the ordinary materializer path.

Historical self-authored backlog processing, if ever desired, is a separate task and authorization.

### 5. No marker coupling

Production eligibility must not depend on:
- `TG_SELF_E2E_0922A`;
- E2E harness modules;
- test-only environment variables;
- process-local AI overrides.

The existing harness may remain in the repo, but the production path must not call or import it.

## Required tests

Add/update focused tests proving at least:

1. global false + canonical active-scope outbound + sender == account.telegram_user_id => eligible;
2. global false + inbound => not eligible;
3. global false + outbound foreign sender => not eligible;
4. global false + missing/unknown direction => not eligible;
5. global false + missing sender_peer_id => not eligible;
6. global false + malformed/wrong account_id => not eligible;
7. global false + inactive scope => not eligible;
8. legacy/noncanonical Telegram remains excluded by the exception;
9. global true preserves existing active-scope inbound/outbound eligibility;
10. SQLAlchemy predicate and raw SQL fragment match Python eligibility semantics;
11. TelegramObjectMaterializer creates a new self-authored object under global false and enqueues exactly the normal embedding entrypoint;
12. the same materializer path for inbound/foreign under global false enqueues zero AI jobs;
13. embedding handler can proceed for the self-authored object under global false and enqueue its normal downstream jobs;
14. downstream enqueue helpers do not admit inbound/foreign Telegram under global false;
15. AI-only object/context/search/correlation candidate paths expose the self-authored Telegram object but not inbound/foreign Telegram while global false;
16. conversation-stack summary handler accepts an all-self-authored active-scope Telegram stack but refuses a mixed stack containing inbound/foreign Telegram;
17. recurring sync catch-up remains zero while global false, preventing historical backlog activation;
18. existing global false->true catch-up tests remain valid when the flag becomes true;
19. no Telegram transport/session decrypt is introduced into AI eligibility;
20. no E2E marker or harness dependency appears in production eligibility code.

Run the relevant Telegram/full-pipeline focused tests plus:
- `py_compile`;
- Ruff check;
- Ruff format --check;
- `git diff --check`.

## Hard stop

No production SSH.
No production Docker/Compose.
No remote wrapper/harness execution.
No provider calls.
No Telegram transport/session access.
No production DB writes.
No deploy/restart/recreate.
No production env changes.
No production ref movement.

When complete:
- update `PROJECT_STATE.md` factually;
- commit and push;
- report commit SHA and all checks;
- STOP.

Deployment and the real live Telegram message test require separate explicit human authorization after Architect review.
