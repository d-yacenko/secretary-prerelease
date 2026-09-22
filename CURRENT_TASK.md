# Current task — Replace synthetic rehearsal with real self-authored MTProto E2E acceptance

## Architecture decision

The synthetic production rehearsal path is ABANDONED for Telegram acceptance.

Do not execute or further repair:
- `ops/production/telegram_production_rehearsal.py`;
- `ops/production/telegram_production_rehearsal_remote.py`.

They may remain in history/code until later cleanup, but are no longer the acceptance path.

The new acceptance path uses REAL canonical MTProto objects produced by the normal Telegram sync, with content authored by the connected Telegram user in a dedicated private solo group.

Production global gate remains:

`TELEGRAM_MTPROTO_AI_ENABLED=false`

The acceptance process may temporarily set the gate true only inside one isolated one-shot process and must target only a proven self-authored test cohort.

## Why

This validates the actual production chain:

Telegram MTProto sync -> canonical Object -> normal enqueue/signatures -> real production ML/LLM handlers -> downstream artifacts/retrieval

without synthetic DB injection.

It also avoids sending third-party Telegram content to ML/LLM providers during acceptance.

## User-side fixture

The human will create a brand-new private Telegram group with no other participants and add it to an already-synced Secretary Telegram folder.

Use exact marker:

`TG_SELF_E2E_0922A`

Human will send at least three messages FROM THE CONNECTED TELEGRAM ACCOUNT in that group, close together in time:

1. `TG_SELF_E2E_0922A Завтра в 11:00 тестовая встреча по бюджету проекта.`
2. `TG_SELF_E2E_0922A До встречи нужно подготовить тестовую смету.`
3. `TG_SELF_E2E_0922A Это тестовый контекст для проверки Telegram AI pipeline.`

Human should not add another participant.

For deterministic correlation, human should also create through the normal Secretary UI/API a normal task containing the same marker, for example:

`TG_SELF_E2E_0922A Подготовить тестовую смету`

For deterministic auto-label, if convenient, human may create a normal Secretary label:

`TG_SELF_E2E_0922A`

The harness must not require direct DB insertion of these task/label objects.

## Current executor task — CODE/TEST ONLY

Build a new narrow ops acceptance harness for real already-synced objects.

Do NOT run it against production in this task.

Suggested location:

`ops/production/telegram_self_authored_e2e.py`
and a canonical remote wrapper under `ops/production/`.

Do not reuse the synthetic fixture creation logic.

## Cohort selection: fail closed

The harness must select Telegram messages only by the exact marker and then prove ALL of the following before any AI/provider call:

1. canonical object:
   - provider=telegram;
   - kind=chat_message;
   - metadata.transport=mtproto;
2. all selected messages belong to one user;
3. all selected messages have one `account_id` and one `peer_id`;
4. corresponding `TelegramMtprotoAccount` belongs to that same user;
5. selected chat is active scope;
6. every selected message has:
   - `direction=outbound`;
   - `sender_peer_id == TelegramMtprotoAccount.telegram_user_id`;
7. at least 2 selected messages exist; prefer 3;
8. marker appears in each selected message;
9. no selected object is already from another provider/transport;
10. no real Telegram session decrypt or provider transport call is needed.

Unknown/missing identity metadata => BLOCK, never infer self-authorship from direction alone.

## Conversation/summary privacy guard

Before semantic conversation summarization, resolve the exact conversation stack/burst that would be summarized.

The harness must prove that EVERY Telegram message whose text could enter that summary is also self-authored under the same exact identity rule above.

If a non-self-authored or unverifiable Telegram message is in the summary cohort:
- do not summarize;
- BLOCK the live acceptance before any summary-provider call.

Do not rely only on the user's statement that the group is solo.

## Other provider-call privacy guard

For every real ML/LLM call in this acceptance:
- third-party Telegram message text must be impossible to enter the payload;
- self-authored selected Telegram text is allowed;
- non-Telegram Secretary-owned data such as the user's normal task/label candidates may be used by normal product logic.

Prove this with focused tests/instrumentation around the acceptance harness.

## Execution design

Global long-running API/worker remain `TELEGRAM_MTPROTO_AI_ENABLED=false`.

One isolated one-shot backend process may set process-local:

`settings.telegram_mtproto_ai_enabled=True`

only after the cohort has passed the self-authorship/privacy checks.

Do not change production .env.
Do not restart/recreate API/worker.
Do not run embedding catch-up.
Do not enumerate/process arbitrary Telegram backlog.
Do not consume unrelated Telegram jobs.

Use canonical enqueue/signature/handler paths only for the selected cohort.

Queue safety must preserve the prior accepted principle:
- exact selected jobs are claimed/parked for synchronous in-process execution before worker visibility/race;
- false long-running worker cannot consume them;
- success/failure leaves zero selected pending/running jobs.

## Required real pipeline proof targets

The eventual live run must prove on real synced self-authored objects:

- real canonical Inbox object exists;
- normal conversation grouping works;
- embedding produced with real configured provider;
- auto-label real handler path executes and, when deterministic test label exists, produces assignment;
- temporal extraction real handler produces a test hint from the explicit date/time message;
- task correlation real handler proposes relation to the marker-matched normal Secretary task;
- conversation semantic summary produced for the self-authored-only stack;
- AI-only Context/ObjectQuery/retrieval visibility sees the selected objects under process-local true;
- idempotent repeat handling does not duplicate artifacts beyond normal contract;
- Telegram transport calls=0;
- long-running API/worker AI=false throughout;
- global env unchanged.

Do not run Assistant/voice prompts that could broaden retrieval over unrelated Telegram content. Voice parity remains architectural inheritance from Assistant.

## Tests

Add focused tests proving:
- inbound object rejected;
- outbound object with sender != account user id rejected;
- missing sender/account identity rejected;
- mixed account/peer rejected;
- inactive scope rejected;
- third-party message in summary cohort blocks before provider call;
- only exact marker cohort gets jobs;
- no catch-up/backlog enqueue;
- no Telegram transport/session decrypt;
- process-local true only after privacy checks;
- normal handlers are used;
- failure leaves zero selected dangling jobs;
- long-running service/env unchanged;
- sanitized output only.

Use fake providers locally for harness mechanics.

Run compile, Ruff, diff-check.

## Production authorization

NOT AUTHORIZED in this task:
- live production execution;
- production DB mutation caused by AI handlers;
- real provider calls;
- production SSH;
- Telegram provider calls;
- deploy/ref movement;
- global AI=true.

The human may create the Telegram solo group/messages and normal Secretary task/label manually. Those are user actions outside this code task.

## Required executor report

Return:
- commit SHA;
- files changed;
- exact self-authorship proof;
- summary/privacy guard;
- queue isolation design;
- local fake-provider results;
- tests/compile/Ruff/diff-check;
- live execution=0.

Final marker:

`TELEGRAM_SELF_AUTHORED_E2E_HARNESS_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
