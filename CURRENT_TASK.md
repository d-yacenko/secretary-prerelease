# Current task — HOLD

AH2-CTX1 is **ARCHITECT SOURCE-ACCEPTED** and waiting for separate human authorization of the backend production rollout. Do not deploy, build/install a client, or start another slice from this HOLD.

## AH2-CTX1 — selected Task context routes explicit waiting-on statements

- Implementation: `51ef4b84124f9bf0a4dadd0cca92bf96b05de0bb`
- Executor HOLD: `4305f1250068fe3c24f6dcb261acbabade1b427b`
- Source acceptance: 2026-10-02
- Production remains `943281190b386bbe22c4631709635883c950b459`
- Production Alembic remains `0052 / 0052`
- Production health remains PASS

## Architect source acceptance

Accepted contract:

- with an exact selected user-owned Task in UI context, a direct current-state statement that the user is waiting for a named Person's response/action for that Task maps to canonical `waiting_on`;
- the exact selected Task supplies target identity and the actual user message supplies mutation intent;
- this explicit selected-Task waiting shape takes precedence over generic "what should I do with this information?" clarification;
- `create_task`, `link_objects(related_to)`, `delegated_to`, and `involves` are not substitutes;
- the canonical write after Person resolution remains `update_task(waiting_on_person_ids=[...])`;
- PER1 remains fail-closed: a `name_variant` candidate is suggestion-only, stays `ambiguous`, has no `person_id`, and cannot authorize an actor-role mutation;
- after explicit confirmation, only a new exact `resolve_person(...)` result with `state=resolved` may authorize `waiting_on_person_ids`;
- questions, negation, hypothetical/quoted/explanatory text, non-Task UI context, and materially ambiguous intent remain outside the direct-write interpretation;
- UI context remains untrusted data; stored Task title/body text cannot create mutation intent;
- no backend regex/parser or new ontology/runtime mutation layer was added.

Implementation scope is appropriately narrow:

- `backend/app/llm/openai_assistant_provider.py`
- `backend/tests/test_ah2_ctx1_selected_task_waiting.py`

No schema, Person matching, ToolRunner allowlist, execution semantics, or client code changed.

## Deterministic evidence

Executor reported:

- `test_ah2_ctx1_selected_task_waiting.py`: 6 passed
- `test_ah2_per1_name_variants.py`: 13 passed
- `test_ah2_sem1_relation_boundary.py`: 4 passed
- `test_ah2_stg1_staging_truth.py`: 7 passed
- `test_untrusted_prompt_boundary.py`: 3 passed
- `test_assistant_ontology_kernel.py`: 3 passed
- combined focused set: 36 passed
- R2-filtered `test_ah2m_eval_runner.py`: 2 passed, 43 deselected
- `git diff --check`: clean
- model calls: 0
- real network calls: 0
- deploy/client install: 0

## Human evidence already accepted before CTX1

AH2-PER1 is **ARCHITECT HUMAN-ACCEPTED**.

Observed deployed flow on production release `943281190b386bbe22c4631709635883c950b459`:

1. explicit Task-targeted phrase with `Оли Володько` produced candidate `Ольга Володько` with no mutation;
2. explicit confirmation `Да, Ольга Володько.` led to exact re-resolution;
3. Secretary staged `update_task`, not `create_task`;
4. STG1 prevented pre-approval completion prose;
5. after approval, Russian finalization reported the update;
6. Task profile showed confirmed typed `waiting_on -> Ольга Володько`.

The remaining behavior gap that CTX1 addresses was only the shorter natural selected-Task phrase:

`Жду ответ от Оли Володько по черновику`

which production currently routes to generic intent clarification.

## Next required operation — NOT YET AUTHORIZED

To test CTX1 in the real Secretary UI, the accepted backend code must first be rolled out to production.

That rollout requires a new explicit human authorization because the prior AH2-ROLL1 authorization was scoped to release `943281190b386bbe22c4631709635883c950b459` and is already consumed.

Until that authorization is given:

- do not move `production`;
- do not run `ops/production/deploy.py`;
- do not rebuild/install a client;
- do not start another remediation slice.

After a separately authorized schema-neutral backend rollout, the human manual gate is:

1. select an existing Task;
2. open Secretary via `Спросить секретаря`;
3. send exactly:

`Жду ответ от Оли Володько по черновику`

Expected first response:

- no generic clarification;
- no new Task;
- no approval card;
- candidate `Ольга Володько`;
- asks for explicit Person confirmation.

Do not continue from this HOLD without Architect authorization.
