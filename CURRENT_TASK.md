# Current task — Telegram final closure: deploy accepted downstream code and build one-shot production rehearsal helper

## Human authorization

Human authorized:

- schema-neutral deploy of exact release
  `8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`
  while long-running production API/worker remain
  `TELEGRAM_MTPROTO_AI_ENABLED=false`;

- exactly ONE production synthetic ML rehearsal after helper review, using real production ML/LLM adapters, synthetic Telegram-shaped content only, and zero Telegram transport calls.

This authorization remains valid for the one rehearsal after architect review of the helper, provided scope does not change.

## Production release

Release:
`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Rollback:
`f31f8f5b704159b7ec903da4c26a590d23f86e78`

Expected Alembic:
`0046`

Canonical `production` has already been fast-forwarded non-force to the release.

## Phase A — execute canonical deploy

Execute exactly once via:

```bash
python3 ops/production/deploy.py \
  --release-sha 8ad52f0653f9f90e1932c49532dc4f993ea1a9cc \
  --rollback-sha f31f8f5b704159b7ec903da4c26a590d23f86e78 \
  --expected-alembic 0046
```

Required invariants:
- health PASS;
- Alembic 0046;
- DB container unchanged;
- DB volume unchanged;
- .env unchanged;
- API/worker recreated as normal;
- API/worker runtime Telegram AI flag remains false.

If deploy fails, STOP. No retry.

## Phase B — build rehearsal helper locally

No suitable existing helper exists.

Create a reviewable one-shot rehearsal helper under `ops/production/` plus focused tests.

Do NOT execute it against production in this task.

### Rehearsal safety contract

The helper must:

1. require explicit unique run id;
2. use only synthetic text clearly containing `TG_REHEARSAL_<run-id>`;
3. never decrypt/use MTProto session material;
4. never instantiate/call Telegram transport;
5. set/override `telegram_mtproto_ai_enabled=True` only inside the one-shot process;
6. verify at startup that long-running production API and worker environments remain false;
7. use production DB/config and real configured production ML/LLM adapters when live;
8. create only clearly attributable synthetic rows;
9. avoid leaving ordinary pending Telegram-AI jobs for the false production worker to race on;
10. execute the relevant service/handler work synchronously within the isolated process;
11. emit only sanitized markers/counters, never message bodies, prompts, responses, embeddings, Telegram ids, credentials, sessions, or secret env values;
12. make zero Telegram transport calls;
13. retain synthetic artifacts unless separately authorized for cleanup.

### Synthetic scenario

Create:
- two inbound canonical MTProto-shaped `chat_message` objects in one synthetic private conversation burst;
- one matching synthetic task;
- minimal synthetic supporting label/config as needed.

The synthetic messages should express a harmless fake scenario such as:
- synthetic project budget meeting tomorrow at 11:00;
- synthetic estimate preparation before the meeting.

Use a synthetic/private peer model so the temporal result may legitimately become personally expected.

Do not reuse real message text.

### Real ML/LLM production proof targets

The live helper, once reviewed, must prove with normal services and real configured adapters:

- Inbox eligibility PASS;
- stack grouping PASS;
- real embedding PASS;
- auto-label PASS;
- temporal extraction PASS with participation;
- proposed correlation edge PASS;
- semantic conversation summary PASS;
- AI-only context/retrieval visibility PASS;
- idempotency PASS;
- TELEGRAM_TRANSPORT_CALLS=0;
- LONG_RUNNING_API_AI=false;
- LONG_RUNNING_WORKER_AI=false.

### Queue/race design

Do not enqueue work and wait for normal worker consumption.

Prefer:
- build payload/signature through canonical enqueue logic where needed;
- identify the exact synthetic job row;
- execute its normal handler/service synchronously in the rehearsal process;
- prevent or immediately neutralize any race with the long-running false worker without pausing/reconfiguring production services.

If the canonical architecture makes safe synchronous execution impossible without altering worker behavior, STOP and report the constraint rather than weakening safety.

### Tests

Add focused tests proving:
- helper refuses non-synthetic run id/content;
- helper cannot call Telegram transport;
- process-local AI=true does not imply service-level env mutation;
- long-running API/worker false verification is required;
- synthetic object/account/scope eligibility only;
- sanitized output only;
- synchronous pipeline traversal works with fake providers;
- repeated run id fails closed or is idempotent according to explicit design;
- zero dangling pending/running rehearsal jobs after successful local fake-provider run.

Run compile, Ruff, and `git diff --check`.

## Authorization boundaries

AUTHORIZED now:
- Phase A deploy;
- local helper/tests/docs implementation;
- commit/push canonical main.

NOT AUTHORIZED in this task:
- live production rehearsal execution before architect review;
- global production AI=true;
- Telegram transport/provider calls;
- production cleanup of synthetic artifacts;
- DB migration;
- direct production SSH outside canonical helper design.

## Required report from executor

Return:
- deploy output if executor performs Phase A, otherwise human will provide it separately;
- helper commit SHA;
- files changed;
- process-isolation design;
- queue/race-safety design;
- proof Telegram transport is unreachable;
- local fake-provider rehearsal result;
- compile/Ruff/diff-check;
- live rehearsal executed=0.

Final marker:

`TELEGRAM_PRODUCTION_REHEARSAL_HELPER_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
