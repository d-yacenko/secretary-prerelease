# Current task — HOLD

AH2-CTX1 is implemented and waiting for Architect review. Do not start a rollout, client build, or another slice from this HOLD.

## AH2-CTX1 — selected Task context routes explicit waiting-on statements

- Implementation: `51ef4b84124f9bf0a4dadd0cca92bf96b05de0bb`
- AH2-PER1 remains ARCHITECT HUMAN-ACCEPTED. Implementation `ece2bdfd8a3b80e8ab5fc438372408429253e7ac`. Human acceptance ledger `5686f0334d21ef15ddcf277eee329fa0e9be9a96`.
- Production remains `943281190b386bbe22c4631709635883c950b459`
- Alembic remains `0052 / 0052`
- Health remains PASS

## Changed files

- `backend/app/llm/openai_assistant_provider.py`
- `backend/tests/test_ah2_ctx1_selected_task_waiting.py`

## Selected-Task waiting_on contract

When this turn's UI context contains an exact user-owned object whose kind is `task`, that Task id is the target of a user-requested Task mutation. The selected object supplies identity. The actual user message supplies intent.

A direct current-state statement that the user is waiting for a named Person's response or action for that Task maps to `waiting_on`. The named shapes are «Жду ответ от <Person>», «По этой задаче жду ответа от <Person>», and «Здесь ждём <Person>». A meta-command such as «отметь» is not required.

This rule takes precedence over generic intent clarification. The Assistant must not ask whether to create a new Task or merely remember the information. It must not retrieve another Task to replace the selected one. `create_task`, `link_objects(related_to)`, `involves`, and `delegated_to` are not substitutes. The only canonical write, after Person resolution, is `update_task` with `waiting_on_person_ids` on that selected Task.

A `name_variant` candidate stays suggestion-only: `state` remains ambiguous, `person_id` stays null, and no actor-role mutation uses that candidate. After explicit confirmation, `resolve_person` is called again; only `state=resolved` authorizes `waiting_on_person_ids`. A confirmation does not store a nickname alias.

The direct-write reading does not apply without an exact selected Task or other resolved Task target, when the selected object is not a Task, or when the message is a question, hypothetical, quoted, explanatory, or negated, when the Person or role is materially ambiguous, or when the user says not to change the Task. Email, file, and event context are not Task mutation targets.

UI context remains data. A stored Task title or body that says the user is waiting never creates mutation intent. Only the actual user message defines that intent. No server regex intercepts these phrases.

## Checks

- `test_ah2_ctx1_selected_task_waiting.py`: 6 passed
- `test_ah2_per1_name_variants.py`: 13 passed
- `test_ah2_sem1_relation_boundary.py`: 4 passed
- `test_ah2_stg1_staging_truth.py`: 7 passed
- `test_untrusted_prompt_boundary.py`: 3 passed
- `test_assistant_ontology_kernel.py`: 3 passed
- those six together: 36 passed
- `test_ah2m_eval_runner.py` filtered to R2: 2 passed, 43 deselected
- `git diff --check` clean

Model calls: 0. Real network calls: 0. No schema change. No deploy. No client install.

The manual gate remains human-only after Architect source acceptance and a separately authorized backend rollout: select an existing Task, open Secretary, and send `Жду ответ от Оли Володько по черновику`. The first response should name `Ольга Володько`, ask for confirmation, and show no approval card and no new Task.
