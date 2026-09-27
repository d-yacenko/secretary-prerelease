# Current task — Assistant P1: compact ontology kernel in the top system prompt

Graph G3A-R2 is architect-accepted and HUMAN-ACCEPTED.

Production backend/runtime and `origin/production` remain:
`489741540e30a775e2ea086f3976d7305512afe2`

Alembic remains:
`0050`

This task authorizes one bounded BACKEND/PROMPT corrective on `main`.

NO production deploy is authorized.
No client product change is authorized.

Do not start `Скрыть связи`, G3B, S3, H2D, MCP parity work, or People/organization ontology design.

## Product decision

The Secretary must receive a compact ontology orientation at the TOP of its system instructions.

Canonical exact wording:

`Core ontology: Person=who; Task=commitment/Direction; Flow=evidence/context; Time=when. Relations are explicit facts, never inferred.`

This is already an accepted architectural invariant in `DECISIONS.md`.

## Why

The system prompt currently contains many correct procedural rules, but its semantic model is scattered.

The compact kernel should give the model one stable routing prior before procedural details:

- Person -> who;
- Task -> actionable commitment or ongoing Direction;
- Flow -> evidence/context around work;
- Time -> when;
- relations -> explicit graph facts, not guessed semantics.

The intent is to improve first-path/tool selection for mixed Person/Task/Flow/Time requests without widening what the model is allowed to infer or mutate.

## Exact implementation boundary

Modify the canonical Secretary `SYSTEM_INSTRUCTIONS` in:

`backend/app/llm/openai_assistant_provider.py`

Place the exact ontology sentence immediately after the opening identity sentence:

`You are the Personal Secretary assistant.`

It must appear before the procedural tool-routing rules such as:
- “Use tools to discover bounded user data”;
- Person resolution;
- retrieve/query_objects;
- Task materialization;
- reminders;
- Inbox review marker.

Do not duplicate the ontology sentence elsewhere in the same prompt.

Keep the rest of the existing prompt semantically unchanged except for minimal formatting needed to insert this sentence.

## Critical semantic constraints

The compact line is a CONCEPTUAL ORIENTATION only.

It MUST NOT imply:

- that `Flow` is a literal `Object.kind == "flow"`;
- that `Time` is a literal `Object.kind == "time"`;
- that arbitrary People roles/organization relations are implemented;
- that the model may infer relations automatically;
- that unsupported relation types are authorized;
- that writes can bypass existing typed-tool, provenance, approval, or safety contracts.

The phrase:

`Relations are explicit facts, never inferred.`

is part of the kernel specifically to preserve this boundary.

Do not change canonical relation semantics.

## Deliberately OUT OF SCOPE

Do NOT add the optional actor-role reminder in this task:

`requested_by=source, delegated_to=assignee, waiting_on=blocker, involves=participant`

That is a separate prompt hypothesis.

Do NOT add or expose:
- `manager_of`;
- `colleague`;
- `works_with`;
- `role_at`;
- `member_of`;
- organization hierarchy.

Do not alter People/Identity behavior.

Do not change Assistant tool definitions or schemas.

Do not change MCP exposure/parity.

Do not add a migration.

## Prompt contract regressions

Add a focused deterministic test for the system-instruction contract.

At minimum prove:

1. the canonical ontology kernel occurs exactly once;
2. it occurs near the top, immediately after the Secretary identity sentence and before general tool-routing instructions;
3. the exact text contains all four conceptual axes:
   - `Person=who`;
   - `Task=commitment/Direction`;
   - `Flow=evidence/context`;
   - `Time=when`;
4. it contains the explicit anti-inference boundary:
   - `Relations are explicit facts, never inferred.`;
5. existing high-value procedural instructions remain present after the insertion, at minimum:
   - `resolve_person`;
   - `retrieve`;
   - `query_objects`;
   - `create_task`;
   - `completion_mode`;
6. prompt content still reaches the OpenAI Responses request as the canonical system/developer instruction through the existing provider path.

Prefer a small prompt-contract test over brittle assertions on the entire giant prompt.

Do not test live model behavior in CI.

## Untrusted-input boundary

Run and preserve the existing untrusted-prompt boundary regressions.

The ontology kernel is trusted developer/system instruction.

User data, retrieved object text, Flow evidence, UI context, emails/messages/files, and tool outputs remain untrusted data and must not gain instruction authority.

No delimiter or prompt-injection boundary may weaken as a result of this change.

## Optional local evaluation — no live dependency

If the repository already contains a deterministic/fake-provider assistant routing harness that can compare prompt variants without network access, it is acceptable to add a SMALL non-production regression/evaluation for a few mixed-domain utterances.

Examples of semantic cases to cover only if deterministic with existing infrastructure:

- “Что у меня по статье Ивана к пятнице?” -> Person + Task/evidence + Time path;
- “Поручи Ольге подготовить материалы к понедельнику” -> Person resolution before Task actor write;
- “Что подтверждает эту задачу?” -> Task -> Flow/evidence context;
- “Когда следующий шаг по этому направлению?” -> Direction/Task + Time.

This optional evaluation must not encode a fake “expected chain of thought”.
Assert only observable tool choices/call counts/outputs.

Do not add a live OpenAI test or require an API key.

## Telemetry

Existing turn telemetry already records:

- `tool_calls`;
- `get_context_calls`;
- `openai_responses_rounds`;
- token usage.

Do NOT redesign telemetry in this task.

In `PROJECT_STATE.md`, note that these metrics are sufficient for a later real-world before/after observation of whether the ontology kernel reduces routing rounds.

Do not claim an efficiency improvement unless measured.

## Required checks

Run at minimum the focused backend suites relevant to this prompt change:

- prompt/provider tests in `backend/tests/test_assistant.py`;
- `backend/tests/test_untrusted_prompt_boundary.py`;
- `backend/tests/test_assistant_task_reuse.py`;
- `backend/tests/test_person_assistant.py`;
- any new prompt-contract test file;
- relevant provider/tool-gateway tests if touched.

Run Ruff on touched Python files.

Run `git diff --check`.

No client build is required.
No Linux bundle is required.
No migration is expected.

If an existing unrelated baseline test fails, report it precisely and do not widen scope.

## Review expectation

Expected product diff is SMALL:

- `backend/app/llm/openai_assistant_provider.py`;
- focused prompt regression test(s);
- `PROJECT_STATE.md`;
- `CURRENT_TASK.md`.

If implementation starts changing tools, schemas, MCP, relation semantics, Person graph, client code, or migrations: STOP and report why.

## Completion

On completion:

1. update `PROJECT_STATE.md` with:
   - exact ontology kernel text;
   - exact placement in the top system prompt;
   - confirmation that Flow/Time remain conceptual axes rather than required literal object kinds;
   - confirmation that no new People/organization inference was authorized;
   - prompt/untrusted-boundary test results;
   - Ruff and diff-check results;
   - implementation SHA;
   - confirmation that backend tool contracts/schema/MCP/client were unchanged;
   - note that telemetry exists for later real-world efficiency observation, but no unmeasured efficiency claim is made;
2. return `CURRENT_TASK.md` to HOLD;
3. push implementation/HOLD commits to `main`;
4. do NOT deploy production;
5. STOP.

Final report must state:

- exact inserted ontology sentence;
- exact prompt placement;
- tests run/results;
- untrusted-input boundary result;
- whether tools/schemas/MCP/client changed;
- whether migration exists;
- implementation SHA;
- HOLD/main SHA;
- rollout requirement.

Then STOP. Do not start another task yourself.
