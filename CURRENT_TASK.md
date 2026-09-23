# Current task — Separate Telegram marker identity from summary self-authorship proof

## Live result

Exactly one authorized live self-authored Telegram E2E was executed.

Sanitized stdout:

```text
SELF_E2E_STARTUP=bootstrap
SELF_E2E_STARTUP=compiled
SELF_E2E_STARTUP=imported
SELF_E2E_BLOCKED=summary_cohort
```

Exit status:

`2`

The attempt is consumed. No retry is authorized.

The accepted `docker compose exec` bootstrap path worked through helper import. The block occurred inside `prove_summary_cohort()`, before process-local Telegram AI was enabled and before any provider call.

Production runtime remains:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Alembic:

`0046`

Long-running API/worker Telegram AI remains false.

## Root-cause correction

The helper currently uses `message_identity_block()` for two different purposes:

1. proving that selected E2E marker messages are canonical self-authored MTProto objects;
2. proving that every Telegram object included in a covered summary conversation group is safe/self-authored.

That predicate also requires the E2E marker text to be present.

Therefore a canonical outbound self-authored Telegram neighbor in the same conversation burst, but without `TG_SELF_E2E_0922A`, is incorrectly treated as unsafe and causes `SELF_E2E_BLOCKED=summary_cohort`.

The existing tests cover a third-party inbound neighbor but do not cover a self-authored outbound non-marker neighbor.

## Authorized work

Code/test-only.

Refactor the helper so marker membership and self-authorship are separate proofs.

### Required semantics

Create or equivalent narrowly-scoped logic with these semantics:

- a base self-authorship proof for Telegram summary/correlation members must require:
  - canonical Telegram MTProto object;
  - matching selected account id;
  - `direction == "outbound"`;
  - non-empty `sender_peer_id`;
  - non-empty account `telegram_user_id`;
  - sender id exactly equals the connected account Telegram user id;
- it must NOT require the E2E marker text;
- the selected marker cohort proof must additionally require `TG_SELF_E2E_0922A` in title or body;
- `prove_cohort()` must continue requiring the marker for every selected E2E message;
- `prove_summary_cohort()` must use only the base canonical self-authorship proof for Telegram members of covered groups;
- any inbound, unknown direction, wrong sender, wrong account, noncanonical/legacy Telegram object, or missing identity data in a covered group must still fail closed before any provider call;
- third-party message regression behavior must remain blocked;
- no provider/privacy guard may be weakened.

Do not broaden the cohort to other peers/accounts/users.

Do not change the accepted remote/bootstrap `docker compose exec` path.

## Required tests

Add focused tests proving at least:

1. selected marker messages still require the marker;
2. a canonical outbound self-authored message in the same account/peer/conversation burst WITHOUT the marker does not cause `summary_cohort`;
3. that non-marker self-authored member can be included in the approved summary privacy set;
4. an inbound third-party neighbor still causes `summary_cohort` before any embedding/summarization/correlation provider call;
5. an outbound object with sender id different from `account.telegram_user_id` still blocks;
6. unknown/missing direction or sender identity still blocks;
7. legacy/noncanonical Telegram objects do not become approved;
8. no global Telegram AI enablement occurs while proving the cohort;
9. existing live/privacy, correlation, temporal, idempotency, transport/session, and remote-wrapper tests remain green.

If useful for future diagnostics, internal tests may assert the precise base block reason, but public live output must remain sanitized and must not expose Telegram content, ids, credentials, provider responses, tracebacks, or raw exceptions.

Run focused tests, `py_compile`, Ruff check/format, and `git diff --check`.

## Hard stop

No production SSH.
No production Docker/Compose.
No remote wrapper execution.
No live E2E.
No provider calls.
No Telegram transport/session access.
No production DB writes.
No deploy/restart/recreate.
No production env changes.
No production ref movement.

When complete:

- update `PROJECT_STATE.md` factually;
- commit and push;
- report SHA and checks;
- STOP.

A new live attempt requires fresh Architect review and new explicit human authorization.
