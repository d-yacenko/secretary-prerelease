# Current task — Harden self-authored Telegram E2E for live correctness and provider-payload privacy

## Review status

Executor commit under review:

`9d4ed0ee25fbb2bbd9bba51888b63417f1a05957`

Architecture verdict:

- core cohort/self-authorship proof: ACCEPTED;
- summary privacy guard: ACCEPTED as a conservative pre-provider guard;
- queue parking/drain concept: ACCEPTED;
- transport/session-decrypt barrier: ACCEPTED;
- LIVE ACCEPTANCE: NOT YET READY.

Do not execute production live E2E yet.

## Blocking issue 1 — auto-label evidence is not cohort-scoped

Current `_auto_label_evidence()` counts every historical `auto_label_result` event for the user.

On production this can report `AUTO_LABEL_EXECUTED=PASS` even if the selected Telegram cohort never ran auto-label.

Fix:

- join `AITraceEvent` to `AITrace`;
- require `event_type=auto_label_result`;
- require `AITrace.object_id` in the selected marker message ids;
- snapshot/baseline existing matching event ids before AI is enabled;
- after drain, count only new matching events from this acceptance run;
- `0 accepted assignments` remains a valid classifier outcome;
- no historical unrelated event may satisfy PASS.

Add regression with pre-existing unrelated and pre-existing same-user auto-label events.

## Blocking issue 2 — correlation provider payload can include unrelated Telegram content

Canonical `CorrelationCandidateService._participant_time_candidates()` considers arbitrary user objects in a 72-hour time window. With process-local Telegram AI=true, a self-authored Telegram trigger can therefore produce candidate rows whose `content_summary` comes from unrelated/third-party Telegram messages.

That candidate text is passed to the correlation judge.

This violates the acceptance privacy rule.

### Required acceptance-only correlation privacy barrier

Do NOT redesign generic correlation behavior for this acceptance task.

At the exact correlation judge boundary, wrap the normal real/fake judge so that BEFORE the inner provider judge is called:

- inspect every `CorrelationCandidate.object_id`;
- load its canonical Object;
- non-Telegram candidates are allowed;
- canonical Telegram MTProto candidates are allowed only if their object id belongs to the already privacy-approved self-authored Telegram set for this acceptance;
- any Telegram candidate outside that approved set => `HarnessBlocked("correlation_privacy")`;
- the inner judge/provider must not be called on block.

The approved Telegram set should be derived from the same self-authored conversation/privacy proof used before summarization, not from direction alone.

Add regression:
- marker trigger + unrelated inbound Telegram message within correlation time window;
- candidate service includes it;
- privacy wrapper blocks;
- underlying correlation judge call count remains zero.

Also prove a non-Telegram marker task candidate can reach the inner judge normally.

## Blocking issue 3 — prove outcomes, not merely handler names

The eventual report must prove normal downstream product results for the marker cohort.

Add explicit PASS/FAIL evidence for:

### Embedding

- every selected marker message has current embedding provenance after the run.

### Auto-label

- at least one NEW cohort-scoped `auto_label_result` event exists;
- accepted assignment count may be zero.

### Temporal

- at least one selected marker message produces a normal temporal result attributable to that selected source;
- the explicit "Завтра в 11:00" message should produce a persisted temporal hint/evidence or an equivalent successful canonical temporal artifact/result;
- report participation/result class in sanitized form;
- no unrelated historical temporal artifact may satisfy PASS.

### Correlation

- require a proposed normal correlation edge from a selected marker Telegram message to the existing marker Secretary task;
- verify it is the exact marker task selected by `prove_cohort`;
- no historical unrelated edge may satisfy PASS.

### Conversation semantic summary

- require a current `conversation_stack_summary` representation for the selected stack/anchor produced by this acceptance;
- evidence must be tied to the selected stack/signature, not any historical summary.

### Context / retrieval

Under process-local true, prove:
- `ObjectQueryService(ai_only=True)` can see a selected marker message;
- `ContextService` can include it when directly targeted;
- normal search/retrieval can return at least one selected marker object for a narrow query derived only from the user's self-authored test content.

Do NOT invoke broad Assistant/voice prompts.

### Idempotency

Perform a bounded second enqueue/drain check through normal signatures and prove:
- no duplicate temporal/correlation/summary artifacts beyond canonical contract;
- no dangling selected pending/running jobs;
- no backlog/catch-up.

The report must contain explicit markers such as:

```
EMBEDDING=PASS
AUTO_LABEL_EXECUTED=PASS
TEMPORAL=PASS
CORRELATION=PASS
SUMMARY=PASS
CONTEXT_VISIBLE=PASS
RETRIEVAL_VISIBLE=PASS
IDEMPOTENT=PASS
```

## Blocking issue 4 — live entrypoint and canonical remote wrapper are incomplete

Current helper intentionally returns:

`SELF_E2E_BLOCKED=live_not_authorized`

Current `telegram_self_authored_e2e_remote.py` only constructs a compose command. It is not yet a canonical remote/trust wrapper.

Implement CODE/TEST ONLY:

### Helper live boundary

`--live` must:
- require fixed review confirmation env;
- open normal production SessionLocal;
- use real configured production providers;
- read the already-probed long-running API/worker false state from fixed one-shot env markers;
- call `run_acceptance(... providers="live")`;
- emit sanitized stdout only;
- catch broad provider/runtime exceptions;
- fail selected pending/running jobs with fixed `harness_aborted`;
- commit failure cleanup;
- restore process-local settings/env in all paths;
- never print traceback/raw exception/provider payload/message text/ids/secrets.

### Remote wrapper

Use the already-established canonical production trust pattern:

- canonical local repo/origin/main/clean worktree;
- fetch/refresh remote refs;
- exact `origin/production == 8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`;
- target.json validation;
- pinned host key, BatchMode, strict known-hosts;
- remote production HEAD exact release;
- remote tracked worktree clean;
- probe long-running api and worker and require Telegram AI=false;
- stream reviewed helper source to a unique read-only path under `/app`;
- run isolated `docker compose run --rm --no-deps --no-build`;
- DO NOT pass `TELEGRAM_MTPROTO_AI_ENABLED=true` in container env;
- process-local setting is changed only by the helper after privacy proofs;
- no Docker socket;
- no `up`, restart, recreate, deploy, migration, or production checkout mutation;
- sanitize outer/remote errors so empty stdout is impossible.

Do not reuse the abandoned synthetic helper business logic.

## Metadata fail-closed hardening

Malformed marker metadata such as invalid UUID `account_id` or non-integer `peer_id` must become a fixed `HarnessBlocked` reason, never an uncaught ValueError/traceback.

Add tests.

## Preserve accepted behavior

Keep:
- exact marker `TG_SELF_E2E_0922A`;
- existing normal Secretary marker task; no test label required;
- existing label vocabulary only;
- zero-assignment auto-label is allowed;
- active-scope proof;
- outbound + sender_peer_id == account.telegram_user_id proof;
- summary cohort third-party block before provider calls;
- Telegram transport/session decrypt unreachable;
- no catch-up/backlog enqueue;
- unrelated pending jobs untouched;
- global production flag false;
- no synthetic object insertion.

## Validation

Run:
- focused self-authored E2E tests;
- execution-level remote-wrapper tests;
- relevant correlation/temporal/summary tests as needed;
- py_compile;
- Ruff;
- git diff --check.

## Authorization

AUTHORIZED:
- local helper/wrapper/tests correction;
- commit/push canonical main;
- update PROJECT_STATE.md.

NOT AUTHORIZED:
- production live E2E;
- production SSH;
- real provider calls;
- production DB mutation;
- deploy/ref movement;
- global Telegram AI enablement;
- Telegram transport/session decrypt;
- synthetic cleanup.

A new explicit human authorization will be requested only after architect review of the corrected live-ready harness, because this live path sends the user's real self-authored Telegram test content to production ML/LLM providers.

## Required report

Return:
- commit SHA;
- cohort-scoped auto-label evidence design;
- correlation provider-payload privacy barrier;
- explicit downstream artifact/result proofs;
- live boundary design;
- canonical remote wrapper design;
- tests/compile/Ruff/diff-check;
- live execution=0.

Final marker:

`TELEGRAM_SELF_AUTHORED_E2E_LIVE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
