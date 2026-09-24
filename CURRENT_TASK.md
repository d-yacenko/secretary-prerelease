# Current task — Graph Refined P3R: salience attribution + noise-starvation safety

Architect review of P3 implementation `3402cb2f450a036efc6ce4a6415441b43947a31e` found two blocking semantic defects in Person salience. Fix these defects and add provider-focused regression coverage.

Do not start P4. Do not add UI, proactive integration, Task Graph ranking changes, Assistant Person lookup, auto-Person/enrichment, send-by-person, or voice/media work. Do not deploy.

## Defect 1 — email participants can create false user reciprocity

Current email attribution:
- always treats a known Person in sender as inbound;
- always treats a known Person in recipients as outbound.

That is not equivalent to interaction with the Secretary user. On an inbound message from A to the user + known colleague B, B may be incorrectly counted as an outbound interaction by the user, creating false reciprocity/salience.

Required correction:
- derive email direction only from canonical provider metadata already stored:
  - Gmail: SENT => outbound; INBOX/UNREAD => inbound; ambiguous/unknown => fail closed for direction-sensitive direct/reciprocity evidence;
  - Yandex Mail: sent-folder semantics => outbound; inbox-folder semantics => inbound; ambiguous/unknown => fail closed.
- inbound email may attribute the sender Person only;
- outbound email may attribute known recipient Persons only;
- do not infer an outbound interaction merely because a Person appears in recipients of an inbound message;
- include CC/group-recipient count when deciding whether exposure is direct vs group/broadcast;
- use a conservative direct rule: 1:1/direct only when canonical metadata makes that defensible; otherwise treat as public/group/low-weight or omit.
- do not use display-name matching.

Add explicit tests for:
1. inbound email from A to user + known B does NOT create outbound hit for B;
2. outbound email from user to B creates outbound hit for B;
3. inbound from B and outbound to B can produce reciprocity;
4. ambiguous-direction email cannot manufacture reciprocity;
5. multi-recipient/CC mail does not get 1:1 direct weight.

## Defect 2 — unrelated traffic can starve relevant Person history

Current `_hits()` loads the latest global `MAX_COMMUNICATION_ROWS=40` communication Objects first, then attributes them. Forty unrelated channel messages can therefore push a Person's recent direct interaction completely out of salience even when it is well inside the 90-day window.

This contradicts the purpose of Person salience for a high-volume Inbox.

Required correction:
- preserve bounded reads, but make the bound apply meaningfully to Person-relevant interaction evidence rather than an arbitrary global last-40 slice;
- use an explicit bounded scan budget and a separate per-Person interaction-hit cap, or an equally safe bounded strategy;
- no unbounded full-history scan;
- a burst of unrelated messages must not erase a recent direct interaction merely because those unrelated rows are newer;
- public/group volume for the same Person remains capped and cannot dominate;
- expose truncation/budget metadata honestly if the scan or per-Person evidence is truncated.

A reasonable design is:
- bounded recent source scan within the existing 90-day window (larger than 40, explicit constant);
- attribute only exact-identity hits;
- keep at most a bounded number of relevant hits per Person for scoring;
- keep `evaluate(person)` and ranking deterministic.

Do not add a worker/cache/materialized salience table in this correction.

Add a regression test where:
- a Person has recent direct reciprocal interaction;
- more than 40 newer unrelated/noisy communication objects exist;
- the Person still retains the expected direct/reciprocity salience.

## Ranking bound integrity

While touching the bounded logic, ensure `rank()` does not silently mean “score the oldest N People and call them top N”.

Either:
- rank an explicit bounded candidate list; or
- derive a bounded candidate pool from recent exact interaction/attention/task evidence before scoring.

The returned ranking must be semantically a ranking of its documented candidate pool, not an arbitrary creation-order slice.

Keep strict cross-user and active Person/identity filtering.

## Provider-focused proof

Existing tests are mostly Telegram. Add focused safe coverage for the provider mappings that P3 claims to support:
- Gmail/Yandex direction semantics as above;
- Teams human `sender_kind=user`, with application sender ignored;
- Mattermost direct vs public inbound attribution using exact identity;
- Telegram private vs group behavior remains green.

Where a provider lacks enough canonical metadata to prove an outbound counterpart safely, fail closed rather than invent reciprocity.

## Invariants

- Salience remains derived/read-time only; no migration.
- Unknown senders never create Person.
- No LLM/provider calls or jobs.
- No downstream proactive/Inbox/Assistant/Task Graph behavior changes.
- `claims_object_importance` remains false.
- Telegram AI quarantine remains untouched.

## Checks

Run:
- `tests/test_person_salience.py`;
- P1/P2 focused identity/evidence tests;
- the smallest touched provider-normalization tests;
- Ruff/compile for touched Python;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose P4 and do not deploy.
