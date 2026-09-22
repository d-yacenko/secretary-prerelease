# Current task — Telegram MTProto final development closure: CRUD proof + synthetic false→true AI pipeline

## Context

Transport production is accepted and ordinary Inbox UX is working.

Production currently remains:

`TELEGRAM_MTPROTO_AI_ENABLED=false`

Do NOT enable it in production.

The architectural goal is to finish all Telegram-related development now so that, after the external permission question is resolved, activation requires no product redesign: only the explicit operational flag transition `false -> true` plus API/worker environment reload/recreate.

## Audit findings

Already present:
- receive/history/reconciliation;
- compose send;
- reply through `send_message(reply_to_object_id=...)`;
- outbound edit;
- exact-message delete;
- mark-read;
- pending-action-plan/approval for external writes;
- AI eligibility gate;
- bounded recurring embedding catch-up;
- auto-label pipeline gate;
- temporal eligibility includes Telegram `chat_message`;
- retrieval/context/assistant gate;
- conversation-stack semantic summary gate.

Two concrete gaps exist:

1. MTProto materialization uses native metadata such as
   `peer_id`, `peer_title`, `sender_peer_id`, `topic_id`,
   `reply_to_message_id`,
   while generic Telegram conversation projection currently expects legacy
   `chat_id`, `chat_display_name`, `from_user_id`.
   Therefore canonical MTProto messages can remain singleton and miss stack summarization.

2. `chat_message` is not a correlation trigger, so canonical MTProto messages do not initiate task/object correlation even when the Telegram AI gate is true.

## Goal

Close those gaps and add one deterministic synthetic end-to-end proof of the whole Telegram path with no real Telegram/OpenAI calls.

CODE/TEST ONLY. No production SSH, deploy, provider calls, or production flag change.

## A. Verify and preserve MTProto communication CRUD

Using fake MTProto transport + real domain services/DB, prove the existing paths:

1. receive/materialize inbound;
2. compose send into an active peer;
3. reply to an exact MTProto message;
4. edit an outbound MTProto message;
5. delete an exact MTProto message and converge local visibility;
6. mark peer/message read;
7. all external-write tools retain approval/pending-action-plan policy;
8. inbound edit remains rejected;
9. stale/wrong-account/wrong-peer/inactive-scope routes fail closed.

Do not weaken existing provider write/idempotency safeguards.

If the existing focused tests already prove a line item, reuse them rather than duplicating large fixtures.

## B. Fix native MTProto conversation projection

Update provider-neutral conversation projection to understand canonical MTProto metadata directly.

Requirements:
- historical/current MTProto objects with `transport=mtproto` must not need DB rewrites;
- account isolation remains part of identity;
- use `peer_id` as the canonical Telegram conversation peer identity;
- use `peer_title` / `group_title` / username as available for display label;
- use `sender_peer_id` as sender identity when available;
- preserve `direction`;
- preserve `reply_to_message_id` as reply reference;
- if `topic_id` is present, keep distinct forum/topic conversations separate rather than collapsing unrelated topics together;
- otherwise same-peer messages follow the existing bounded conversation-burst semantics;
- legacy Telegram metadata already supported by projection must continue to work.

Do not add legacy alias fields to new MTProto objects merely to satisfy the projection.

### Projection regressions

Prove at minimum:
- two MTProto messages in the same account+peer and burst form one stack;
- different peers do not stack;
- same peer on different accounts does not stack;
- different non-null topic IDs do not stack;
- reply metadata is preserved;
- legacy Telegram projection still works;
- with AI flag false, deterministic stack grouping works but semantic summary job is not enqueued;
- with AI flag true, eligible active-scope stack can enqueue and persist a semantic summary using a fake summarizer.

## C. Enable MTProto chat-message correlation narrowly

Canonical Telegram MTProto `chat_message` must be allowed to trigger bounded correlation when AI-eligible.

Do NOT unintentionally turn on new correlation behavior for Teams/Mattermost/other chat providers merely as an implementation shortcut.

Prefer a clear correlation-trigger eligibility helper rather than globally adding all `chat_message` to an existing constant if that would broaden unrelated behavior.

Requirements:
- false gate => MTProto correlation cannot enqueue/run;
- true gate + active scope => MTProto chat message can enqueue/run correlation;
- inactive scope => remains ineligible;
- existing correlation kinds remain unchanged;
- normal candidate/edge bounds, dedupe, rejection memory, provenance and proposed-edge semantics remain unchanged.

Add a synthetic correlation test in which a canonical MTProto message and a task candidate produce a bounded proposed relation using fake deterministic candidate/judge inputs. No external LLM.

## D. Synthetic false→true full-pipeline proof

Build a focused integration test/harness using real DB/domain code and synthetic canonical MTProto objects.

It must use no real Telegram and no real OpenAI/provider calls.

Use fake embedding/classifier/temporal extractor/correlation judge/conversation summarizer as appropriate.

### D1. Flag=false matrix

For active-scope synthetic MTProto messages prove:
- visible in ordinary Inbox;
- deterministic conversation grouping works;
- no embedding job is created;
- no auto-label AI work;
- no temporal AI work;
- no correlation AI work;
- no semantic conversation-summary job;
- assistant/retrieval/context AI-only surfaces exclude the MTProto object;
- recurring embedding catch-up returns/queues zero.

### D2. Flag transition in test only: false→true

Without recreating/reimporting the synthetic message rows, switch the settings value to true inside the isolated test.

Prove:
- active-scope object becomes AI-eligible;
- inactive-scope object remains excluded;
- bounded catch-up queues existing accumulated MTProto objects;
- catch-up is idempotent and respects existing bounds/cursor behavior;
- embedding can run with a fake embedding service;
- embedding downstream queues the normal applicable work.

### D3. Downstream parity with normal feature settings enabled

Explicitly enable the ordinary user settings required by each subsystem in the fixture. The Telegram flag must not bypass these settings.

Prove:
- auto-label job/classifier can assign a normal label to the MTProto object;
- temporal extraction can process the Telegram `chat_message` and persist the normal temporal hint/evidence result using fake extractor/judge;
- correlation can create the normal proposed task/object relation;
- conversation-stack semantic summary can be produced with fake summarizer;
- search/retrieval/context/assistant AI-only path can expose the eligible active MTProto object;
- no special Telegram-only LLM path is introduced.

Voice does not need a separate Telegram model path: prove/document that voice reaches the existing Assistant message/tool flow and therefore inherits the same retrieval/context gate.

## E. Catch-up behavior is the future activation mechanism

Preserve and test the existing bounded mechanism in
`TelegramMtprotoRecurringSyncService._enqueue_embedding_catchup`:

- false => zero;
- true => scan bound 100, enqueue bound 10/run;
- current embedding provenance => skip;
- pending/running exact-signature job => no duplicate;
- cursor advances/wraps safely;
- only active-scope canonical MTProto objects for the account are eligible.

Do not introduce a second migration/backfill system.

## F. Activation contract

Document in `DECISIONS.md` / state as needed:

Future production activation after explicit external permission is:

1. change `TELEGRAM_MTPROTO_AI_ENABLED=false` to `true`;
2. reload/recreate API and worker with the changed environment through an explicitly authorized production operation;
3. recurring MTProto sync performs bounded catch-up automatically.

No DB migration, data rewrite, Telegram relogin, folder reconfiguration, or code redesign should be required.

Do not build or execute the production toggle in this task.

## Validation

Run the focused suites covering:
- MTProto communication send/reply/edit/delete/mark-read;
- MTProto history/materialization;
- conversation projection/stack/summary;
- AI gate/quarantine;
- embedding catch-up;
- auto-label;
- temporal signals;
- correlation;
- retrieval/context/assistant visibility.

Also run:
- Python compile;
- Ruff;
- `git diff --check`.

If a focused test reveals another real parity gap, fix it within this task if it is local and directly required by the stated goal; otherwise report it explicitly rather than hiding it.

## Authorization

AUTHORIZED:
- local code/tests/docs for the final Telegram downstream-readiness closure;
- synthetic DB objects and fake provider/LLM components in tests;
- update `PROJECT_STATE.md` and `DECISIONS.md`;
- commit/push canonical `main`.

NOT AUTHORIZED:
- production SSH;
- deploy/rollback/ref movement;
- production env modification;
- production `TELEGRAM_MTPROTO_AI_ENABLED=true`;
- real Telegram calls;
- real OpenAI/LLM calls for this proof;
- DB migration;
- destructive historical cleanup.

## Required report

Return:
- commit SHA;
- files changed;
- CRUD proof summary;
- conversation projection fix;
- correlation-trigger fix;
- false-gate matrix results;
- true-gate synthetic pipeline results;
- catch-up proof;
- assistant/voice visibility proof;
- any remaining gap;
- test/compile/Ruff/diff-check results;
- production flag unchanged=false;
- production SSH=0;
- real Telegram calls=0;
- real LLM/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_MTPROTO_FULL_PIPELINE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
