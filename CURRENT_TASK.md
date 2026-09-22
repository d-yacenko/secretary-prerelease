# Current task — Final narrow correction before live self-authored Telegram E2E

## Reviewed commit

`32eb444d6df318e779b540acee8103bfd5870616`

Architect verdict:

ACCEPTED:
- cohort-scoped auto-label evidence;
- self-authorship/active-scope proof;
- summary privacy guard;
- queue isolation/drain;
- explicit embedding/summary/context/retrieval/idempotency proofs;
- live boundary;
- canonical SSH/trust wrapper;
- Telegram transport/session-decrypt barrier.

LIVE RUN remains NOT AUTHORIZED until the three narrow corrections below are reviewed.

## Correction 1 — correlation privacy must cover ALL Telegram-provider candidates

Current `PrivacyCorrelationJudge` only blocks:

`is_canonical_telegram_mtproto_object(obj) and obj.id not in approved`

This is insufficient because production intentionally retains historical Telegram Bot-derived objects.

Required rule at the acceptance correlation-provider boundary:

- if `obj.provider != "telegram"`: allowed;
- if `obj.provider == "telegram"`: allowed ONLY when `obj.id in approved_telegram_ids`;
- otherwise `HarnessBlocked("correlation_privacy")` before inner judge call.

Therefore:
- legacy Bot Telegram candidate => BLOCK;
- inbound MTProto candidate => BLOCK unless already explicitly in approved self-authored set (which it should not be);
- unknown Telegram transport/kind => BLOCK;
- approved self-authored MTProto candidate => allowed;
- non-Telegram Secretary task/calendar/etc => allowed.

Add regressions proving:
1. legacy/non-MTProto `provider=telegram` candidate blocks before inner judge;
2. canonical inbound MTProto candidate blocks;
3. approved self-authored Telegram candidate plus non-Telegram marker task can reach inner judge.

Do not change generic product correlation logic.

## Correction 2 — correlation outcome proof must not require exact relation type

The acceptance requirement is that the normal real correlation pipeline proposes a valid relation from a selected marker Telegram message to the exact marker Secretary task.

Do NOT require exactly `edge.type == "related_to"`.

PASS when:
- edge is NEW for this acceptance;
- source_id is selected marker Telegram object;
- target_id is exact `cohort.task_id`;
- state is `proposed`;
- type is in canonical `CORRELATION_ALLOWED_TYPES`.

Report only:
`CORRELATION=PASS`

No relation text is needed in output.

Add regression with another allowed relation type.

## Correction 3 — temporal outcome proof must accept canonical successful existing-anchor outcomes

Current proof requires a NEW `temporal_hint` Object.

A correct real run may instead produce a successful normal temporal outcome such as:
- `calendar_first_match`;
- `hint_merged`;
- `already_evidenced` tied to the selected source revision;
- a new temporal hint.

Use cohort-scoped NEW AI-audit evidence, analogous to auto-label:

- join `AITraceEvent` to `AITrace`;
- event_type = `temporal_signal_result`;
- `AITrace.object_id` in selected marker ids;
- snapshot event ids before AI true;
- after run consider only NEW matching events.

PASS only for a canonical successful temporal outcome attributable to selected source. At minimum allow:
- new temporal hint;
- `calendar_first_match`;
- `hint_merged`;
- `already_evidenced` when the referenced canonical evidence/anchor is still present for that selected source revision.

Reject/FAIL disabled, ineligible, stale, parse/reject, or unrelated historical events.

Keep sanitized output:
- `TEMPORAL=PASS|FAIL`
- `TEMPORAL_PARTICIPATION=expected|possible|none`
- `TEMPORAL_RESULT=temporal_hint|calendar_match|hint_merged|already_evidenced|none`

No ids, titles, message text, prompts, or provider payloads.

Add regressions for:
- historical unrelated temporal event does not satisfy PASS;
- new calendar_first_match does satisfy PASS;
- new temporal hint still satisfies PASS.

## Preserve everything else

Do not alter:
- exact marker `TG_SELF_E2E_0922A`;
- real existing canonical objects only;
- global production AI=false;
- process-local true only after privacy proof;
- no catch-up/backlog;
- no Telegram transport/session decrypt;
- no synthetic object insertion;
- canonical remote wrapper trust checks;
- no deploy/restart/recreate/migration.

## Validation

Run:
- focused self-authored E2E tests;
- remote-wrapper tests;
- relevant correlation/temporal tests;
- py_compile;
- Ruff;
- git diff --check.

## Authorization

AUTHORIZED:
- code/test-only corrections above;
- commit/push canonical main;
- update PROJECT_STATE.md.

NOT AUTHORIZED:
- live production E2E;
- production SSH;
- provider calls;
- production DB mutation;
- deploy/ref movement;
- global AI=true;
- Telegram transport calls.

## Required report

Return:
- commit SHA;
- all-Telegram correlation privacy rule;
- generalized correlation PASS rule;
- cohort-scoped temporal evidence rule;
- tests/compile/Ruff/diff-check;
- live execution=0.

Final marker:

`TELEGRAM_SELF_AUTHORED_E2E_FINAL_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
