# Current task — Await explicit deploy authorization for self-authored Telegram normal pipeline

## Architect acceptance

Commit:

`681c0e04df5881124ab8d72a4c05e5a2c7977296`

is ACCEPTED / DEPLOY-READY / NOT DEPLOYED.

Verified production policy:

- global `TELEGRAM_MTPROTO_AI_ENABLED=false` remains the production default;
- non-Telegram behavior is unchanged;
- while global false, every `provider=telegram` object is AI-ineligible except the narrow proven self-authored canonical MTProto exception;
- the exception requires:
  - kind == `chat_message`;
  - transport == `mtproto`;
  - account owned by the same application user;
  - peer in `scope_active=true`;
  - direction == `outbound`;
  - non-empty `sender_peer_id`;
  - non-null account `telegram_user_id`;
  - sender_peer_id == account.telegram_user_id;
- inbound, foreign sender, wrong/malformed account, inactive scope, missing/unknown identity, legacy Bot transport, unknown transport, and non-chat Telegram remain fail-closed;
- Python eligibility, SQLAlchemy predicate, and raw SQL fragment are aligned;
- direct context access cannot bypass the false-mode Telegram gate;
- normal Telegram materialization may enqueue the ordinary embedding entrypoint for a newly created/semantically updated self-authored message;
- ordinary worker/downstream/retrieval surfaces continue to use the central eligibility policy;
- global-false recurring Telegram embedding catch-up remains zero, so historical backlog is not activated;
- global-true behavior remains unchanged;
- production policy has no E2E marker/harness dependency.

Verification reported on exact commit:

- Telegram policy/Q1/full-pipeline/C1A/C1B/C2A focused suite: 92 passed;
- `py_compile`: passed;
- Ruff check on changed files: passed;
- Ruff format --check on policy module/policy test: passed;
- `git diff --check`: clean.

## Intended live verification after deployment

The next live verification is NOT the old E2E harness.

After an explicitly authorized normal deployment of the accepted commit, the human will send a brand-new ordinary Telegram message from the connected Telegram account in an active-scope chat.

Expected normal behavior:

1. MTProto sync/materializer stores the real message.
2. Because it is canonical + outbound + self-authored + active-scope, the normal materializer enqueues the ordinary AI pipeline.
3. Existing worker handlers process normal embedding/downstream jobs.
4. Inbound/foreign Telegram messages remain excluded while global Telegram AI stays false.
5. No historical catch-up/backlog is activated merely by this policy.
6. Verification should inspect normal DB/job/audit/result evidence, not run `telegram_self_authored_e2e_remote.py`.

## Authorization state

NO deployment is currently authorized.
NO production SSH/Docker/Compose is authorized.
NO live Telegram acceptance action by Executor is authorized.
NO provider diagnostic/manual pipeline execution is authorized.

Do not:
- deploy;
- move production refs;
- restart/recreate services;
- change production env;
- set `TELEGRAM_MTPROTO_AI_ENABLED=true`;
- run the old E2E harness;
- manually enqueue Telegram AI jobs;
- process historical Telegram backlog;
- run direct SSH or manual Docker/Compose.

STOP and wait for explicit human authorization for deployment.

After deploy authorization is received, Architect must create a separate exact deploy task. Live normal-message verification remains a separate controlled step after successful deploy.
