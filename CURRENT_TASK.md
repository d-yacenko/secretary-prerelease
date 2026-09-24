# Current task — Graph Refined P3R2: salience ranking-pool integrity

Architect review of P3R implementation `52928587b8ff4f5586b216e8ffb989cc28a50c3d` confirms the email-direction and noise-starvation corrections, but found one remaining blocking issue in `PersonSalienceService.rank()`.

Fix only ranking-pool selection and its bounded semantics. Do not start P4.

Do not add UI, proactive/Inbox/Assistant/Task Graph integration, automatic Person creation/enrichment, send-by-person, voice/media, migrations, provider calls, LLM calls, or jobs. Do not deploy.

## Problem

The current ranking pool is no longer limited to the oldest People, but it is still built from arbitrary bounded slices:

- `_active_identity_index()` selects the first `MAX_IDENTITY_ROWS` active identities ordered by identity creation time, so a newer highly relevant Person may be invisible to interaction attribution when more than 500 identities exist.
- `_attention_people()` uses `LIMIT MAX_RANKED_PEOPLE` without semantic ordering, so recent explicit route-choice/confirmation for a newer Person may be omitted.
- `_task_calendar_pool()` uses a global `LIMIT MAX_GRAPH_EDGES` without semantic ordering, so an active/recent Person-task relation may be omitted merely because unrelated older edges occupy the slice.

That means `rank()` can still return “top N of an arbitrary storage slice”, not top N of a clearly defined bounded candidate pool.

## Required semantics

Define a deterministic, documented bounded candidate-pool policy before scoring.

The pool should be assembled from three independent bounded sources:

1. **recent exact interaction candidates**
   - derive from the bounded 90-day communication scan;
   - exact identities only;
   - active Person/identity only;
   - do not require loading an arbitrary oldest-N identity table first if that can hide recent participants;
   - the scan may remain bounded and may report truncation honestly.

2. **recent/strong user-attention candidates**
   - active P2 `user_confirmed` and `user_route_choice`;
   - deterministic ordering, with explicit confirmation preferred and/or newest feedback first;
   - bounded by an explicit candidate constant;
   - rejected/deleted People excluded.

3. **active task/calendar-linked candidates**
   - active edges linking an active Person to an active task/calendar object;
   - deterministic ordering, preferably most recently updated/created relevant edges first;
   - bounded by an explicit candidate constant;
   - unrelated edges must not consume the entire pool before relevant Person-task/calendar edges are identified.

Union the three sources, then score the resulting bounded candidate set and return top `MAX_RANKED_PEOPLE`.

If a source is truncated, expose that through the existing salience truncation/budget signal. Do not pretend the ranking is globally exhaustive.

## Identity lookup strategy

Keep exact-identity attribution provider-neutral and safe.

Acceptable approaches include:
- build identity lookup only for identities actually referenced by the bounded recent communication scan; or
- use bounded provider-specific exact resolution while attributing scan rows; or
- another deterministic bounded method that cannot exclude a newly relevant Person merely because their `PersonIdentity.created_at` is newer than 500 older identities.

Do not use display-name matching.

## Evaluate(person) invariants

`evaluate(person_id)` semantics from P3R should remain unchanged unless a tiny shared-helper refactor is needed.

The existing 90-day bounded scan and per-Person direct/public caps are acceptable for this phase as long as truncation remains explicit. Do not add caches/materialized salience state in this correction.

## Focused proof

Add tests proving at minimum:

1. More than `MAX_IDENTITY_ROWS` older active identities cannot hide a newer Person who has a recent exact direct interaction from `rank()`.
2. More than the attention candidate bound of older route-choice rows cannot hide a newer explicit confirmation.
3. More than the graph-edge bound of unrelated/older edges cannot hide a newer active Person-task/calendar relation.
4. Candidate pool ordering is deterministic across repeated calls.
5. Rejected/deleted People and rejected identities remain excluded.
6. Cross-user isolation remains strict.
7. Existing P3/P3R email direction, reciprocity, noisy-channel, scan-bound, Teams/Mattermost/Telegram tests remain green.
8. `rank()` still returns at most `MAX_RANKED_PEOPLE`.
9. No automatic Person creation, enrichment, downstream integration, provider/LLM call, or job is introduced.

Run `tests/test_person_salience.py`, P1/P2 focused tests, Ruff/compile for touched Python, and `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose P4 and do not deploy.
