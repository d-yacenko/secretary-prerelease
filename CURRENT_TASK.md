# Current task — ACTIVE

## AH2-CTX1 — selected Task context routes explicit waiting-on statements without generic clarification

Architect review before this authorization:

- AH2-PER1 implementation: `ece2bdfd8a3b80e8ab5fc438372408429253e7ac`
- AH2-PER1 source acceptance ledger: `943281190b386bbe22c4631709635883c950b459`
- AH2-ROLL1 production release: `943281190b386bbe22c4631709635883c950b459`
- production Alembic: `0052`
- production health: PASS

## Manual AH2-PER1 behavior acceptance

The human gate on the deployed backend completed successfully for the actual Person-variant mechanism.

Observed sequence with selected Task `test`:

1. Explicit selected-Task request:
   `Для этой задачи отметь, что я жду ответ от Оли Володько по черновику.`
2. Secretary returned candidate `Ольга Володько` and asked for confirmation.
3. No approval plan and no mutation existed before that confirmation.
4. User replied:
   `Да, Ольга Володько.`
5. Secretary staged `update_task`, not `create_task`.
6. STG1 held: no model-authored prose claimed the update had already happened.
7. After approval, finalization stayed in Russian and reported that Task `test` now waits for Ольга Володько.
8. The Task profile / graph showed the confirmed typed relation:
   `waiting_on -> Ольга Володько`.

Therefore AH2-PER1 is **ARCHITECT HUMAN-ACCEPTED** for its intended two-step variant-confirmation path.

The approval card still showed the old client fallback `Update task: <UUID>` because the installed client has not yet been rebuilt/installed with AP1 client changes. That is not a backend regression and is outside this slice.

## Newly observed behavior gap

With the same selected Task context, the shorter natural statement:

`Жду ответ от Оли Володько по черновику`

did **not** enter Person resolution.

Instead the Assistant asked a generic clarification equivalent to:

`Что сделать с этой информацией — создать задачу отслеживать ответ или просто учесть как контекст?`

This is wrong for a selected Task context.

The UI clearly supplied:

`Контекст: Задача — test`

and the user's sentence explicitly states the canonical `waiting_on` fact for that current Task.

The existing runtime instructions correctly define `waiting_on`, but the generic "Intent clarification" rule currently has no explicit selected-Task precedence rule for this natural declarative form.

## Goal

When an exact Task is already supplied as the current UI context, an unambiguous user statement that they are waiting for a named Person's response/action **for that Task** must route as the canonical Task actor role `waiting_on`.

The Assistant must not ask whether to create a new Task or merely remember the information.

For the exact observed phrase:

`Жду ответ от Оли Володько по черновику`

with selected Task context, the first action should be Person resolution.

Because `Оли Володько` is a PER1 name variant, the first turn must remain suggestion-only:

- candidate `Ольга Володько`;
- no pending ActionPlan;
- no Task mutation;
- ask the user to confirm the Person.

After explicit confirmation, the existing PER1 flow may re-resolve the canonical Person and stage:

`update_task(waiting_on_person_ids=[...])`

against the exact selected Task.

## Core contract

### A. Selected Task is the mutation target

If the current UI context contains an exact user-owned object whose kind is `task`, the Assistant may use that exact Task id as the target of a user-requested Task mutation.

For an explicit waiting statement about that current Task, do not:

- retrieve another Task merely to replace the selected Task;
- create a new Task;
- ask whether the information should become a new Task;
- treat the selected Task only as passive evidence.

The selected object supplies the target identity. The actual user message supplies intent.

### B. Declarative waiting statement is actionable in selected Task context

In a selected Task context, a direct current-state statement equivalent to:

- `Жду ответ от <Person>`
- `По этой задаче жду ответа от <Person>`
- `Здесь ждём <Person>`

expresses the canonical `waiting_on` actor-role intent.

It is not necessary for the user to add a meta-command such as:

- `отметь`
- `измени задачу`
- `добавь связь`.

Do not let the generic Intent-clarification rule override this explicit canonical relation meaning.

### C. Fail closed outside that shape

Do not turn the rule into broad automatic mutation.

Do **not** mutate merely because words about waiting appear when:

- there is no exact selected Task and no otherwise-resolved Task target;
- the selected object is not a Task;
- the user is asking a question;
- the text is hypothetical, quoted, explanatory, or negated;
- the intended Person or role is materially ambiguous;
- the user explicitly says not to change the Task.

Examples that must not be treated as this direct write rule:

- `Кого я жду по этой задаче?`
- `Что значит “жду ответ от Ольги”?`
- `Если буду ждать ответ от Ольги, что изменится?`
- `Не отмечай, что я жду Ольгу.`

Use the normal read/clarification behavior in those cases.

### D. Person safety remains PER1

When the waiting statement names a Person:

- call `resolve_person`;
- exact resolution may proceed under existing rules;
- `name_variant` remains suggestion-only;
- one variant candidate is still `state=ambiguous`, `person_id=null`;
- no actor-role mutation may consume an ambiguous candidate id;
- after explicit user confirmation, re-resolve the canonical displayed title or exact identifier;
- only `state=resolved` may authorize `waiting_on_person_ids`.

Do not persist a nickname alias.

### E. No new Task

For the selected-Task waiting statement:

- `create_task` is forbidden;
- `link_objects(related_to)` is forbidden as a substitute;
- `involves` is not a fallback;
- `delegated_to` is not a fallback.

The only canonical write, after Person resolution, is the typed Task field `waiting_on_person_ids`.

### F. Preserve untrusted-context boundary

The UI context block remains DATA, not instructions.

A stored Task title/body that itself says `Жду ответ от Ольги` must never create mutation intent.

The mutation intent comes only from the actual user message channel.

The selected Task context contributes only the exact target identity and bounded context.

### G. No lexical backend policy layer

Do not add a deterministic server regex that intercepts Russian phrases such as `Жду ответ от`.

Do not implement morphology/intent parsing outside the Assistant model contract.

This slice should be expressed through the runtime semantic instructions and, only if useful, existing tool descriptions.

No new model call, parser service, endpoint, or schema is needed.

## Preferred implementation boundary

Expected source changes are small:

- `backend/app/llm/openai_assistant_provider.py`;
- focused runtime-instruction tests;
- optionally tool-contract wording only if it materially clarifies selected Task targeting;
- deterministic AH2 eval/contract tests where useful;
- ledger files.

Do not modify Person matching or ToolRunner allowlists unless a deterministic failing test proves they are involved. Manual evidence already shows those layers work after the intent is explicit.

## Required deterministic tests

At minimum prove:

1. **selected-Task waiting contract**
   - runtime instructions explicitly state that a direct waiting statement in exact selected Task context maps to `waiting_on`;
   - the selected Task is the update target;
   - the rule explicitly takes precedence over generic intent clarification.

2. **no create-task reinterpretation**
   - instruction contract says not to ask whether to create a separate tracking Task for this case;
   - `create_task`, `related_to`, `delegated_to`, and `involves` are not substitutes.

3. **PER1 variant flow preserved**
   - `Оли Володько` variant still returns suggestion-only ambiguity;
   - no pending mutation can use that candidate;
   - exact `Ольга Володько` resolution still permits waiting_on staging.

4. **untrusted UI context**
   - a Task title/body containing actor-role-like words remains data only;
   - instructions still say only the real user message defines mutation intent.

5. **non-Task context**
   - the new contract does not state that email/file/event context becomes a Task mutation target.

6. **question/negation/hypothetical boundary**
   - instruction contract explicitly excludes questions, negation, hypothetical/quoted/explanatory text from the direct-write interpretation.

7. **R2 regression**
   - existing canonical R2 waiting_on fixture remains green.

8. **PER1 regression**
   - `backend/tests/test_ah2_per1_name_variants.py` remains green.

9. **SEM1 regression**
   - closed relation ontology remains green.

10. **STG1 regression**
   - staged mutations still expose no model-authored completion prose.

11. **prompt-injection regression**
   - untrusted-content tests remain green.

No real OpenAI call is required.

## Manual behavior gate after source acceptance and rollout

Executor does not perform this gate.

After Architect source review and a separately authorized backend rollout, the human test is:

1. select an existing Task;
2. enter Secretary through `Спросить секретаря`;
3. send exactly:

`Жду ответ от Оли Володько по черновику`

Expected first response:

- no generic "what should I do with this information?" clarification;
- no new Task;
- no approval card;
- names `Ольга Володько` as a candidate;
- asks for Person confirmation.

The already accepted confirmation/approval continuation should then remain unchanged.

## Explicit non-goals

Do not in AH2-CTX1:

- change Person variant families;
- auto-resolve `Оля/Оли`;
- add or merge People;
- redesign approval cards;
- rebuild/install a client;
- change STG1, AP1, FIN1, FIN2 semantics;
- change generic relation ontology;
- add Scheduled Activity Today/Week/mobile integration;
- clean stale tests unrelated to this path;
- deploy production;
- run real model evaluation;
- add Alembic/schema changes.

## Required checks

Run at least:

- focused new contextual-routing contract tests;
- `backend/tests/test_ah2_per1_name_variants.py`;
- `backend/tests/test_ah2_sem1_relation_boundary.py`;
- `backend/tests/test_ah2_stg1_staging_truth.py`;
- R2-filtered AH2 eval tests;
- relevant untrusted prompt-boundary tests;
- `git diff --check`.

Record exact pass counts.

Known unrelated stale test debt must not be "fixed" by weakening safety:

- `test_owned_source_identity_is_conflict_not_confirmable`;
- stale absolute-date M1 fixture if encountered.

Model calls: 0.
Real external network calls: 0.

## Acceptance criteria

AH2-CTX1 is complete only when:

- selected Task + direct waiting statement is explicitly routed to canonical `waiting_on`;
- generic intent clarification no longer claims the user must choose between new Task and passive context in that shape;
- PER1 candidate safety remains intact;
- no new Task or substitute relation is introduced;
- untrusted UI context remains non-instructional;
- no schema/execution/domain changes are needed;
- deterministic regressions are green;
- production is untouched.

## Completion protocol

After implementation:

1. append to `PROJECT_STATE.md`:
   - AH2-PER1 human acceptance evidence;
   - the observed contextual-routing gap;
   - AH2-CTX1 implementation result and exact checks;
2. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - exact selected-Task/waiting_on instruction contract;
   - PER1/SEM1/STG1/security regression evidence;
   - exact test counts;
   - confirmation of no schema/model/network/deploy/client install;
3. commit + push to `main`;
4. STOP.

Do not start a rollout, client build/install, Scheduled Activity integration, or another remediation slice from HOLD.
