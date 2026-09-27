# Current task — People R2: observable Person truth surface

## State

- People R1 audit is accepted at `46c3a1261106c171fb9f5affd17b6e46e9ebb615`.
- Current `main` before this authorization is `7f14156c9cb7f38cd80aeb568c3c388c7a16acea`.
- Production backend/runtime and `origin/production` remain `7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4`.
- Production Alembic remains `0050`.
- R1 confirmed that identity, salience, Task actor roles, event-level proactive relevance, and durable relationship/context are distinct concepts.
- No durable social/organizational relationship representation has been selected yet.

## Goal

Make the existing canonical Person foundation inspectable by the human before introducing a new relationship ontology.

For one rooted Person, the first-party People detail must expose already-existing, grounded facts:

1. exact/current identities and routes — already present;
2. current Task actor involvement with the exact canonical role;
3. recent identity-attributable communication Flow;
4. an explainable salience summary.

This is a read/projection task. It must not create, infer, or persist any social/organizational relationship fact.

## Product invariant

The screen is a **truth surface**, not a classifier.

- Task involvement means only existing Task->Person actor edges:
  `requested_by`, `delegated_to`, `waiting_on`, `involves`.
- Communication means only Flow that the existing exact-identity attribution path can ground to this Person.
- Salience means only the current derived Person-salience signal. It must be labelled as activity/presence context, not message importance or authority.
- Proposed Task actor edges, if shown, must remain visibly proposed and must not be presented as confirmed truth.
- No social role may be inferred from Task roles, message volume, salience, provider, title, free text, or organization-like strings.

## Backend contract

Extend the existing rooted People workspace projection. Do not add a new top-level Person product API unless the current workspace contract cannot express this safely.

### A. Task involvement

For a rooted Person only, expose a bounded list of non-terminal active Tasks connected through non-rejected canonical actor edges.

Each row must include enough information to render truthfully:

- Task id;
- title;
- status;
- `completion_mode`;
- due date if present;
- exact actor role: one of `requested_by|delegated_to|waiting_on|involves`;
- edge state;
- edge origin.

Requirements:

- Use only `TASK_ACTOR_ROLES`.
- Do not treat generic `related_to`, `references`, `part_of`, labels, or arbitrary Person<->Task edges as actor involvement.
- Preserve proposed/confirmed distinction.
- Exclude rejected edges and deleted/hidden/terminal Tasks.
- Bound the list to at most 8 rows with explicit truncation metadata.
- Deterministic ordering.
- Do not mutate or materialize any edge.

Keep existing `open_task_count` compatibility unless a test proves it is already defined as canonical actor involvement. If its existing semantics are broader, add a separate exact count/list rather than silently changing an unrelated public contract.

### B. Recent attributable Flow

For a rooted Person only, expose up to 8 newest active stored communication Objects attributable by the existing effective exact-identity rules.

Each item:

- object id;
- kind;
- provider;
- title;
- occurred_at.

Requirements:

- Reuse the existing canonical Person communication attribution path; do not add display-name matching.
- Preserve existing exact identity rejection/conflict semantics.
- First-party People UI is a non-AI read. It may include stored Telegram MTProto communication that is already allowed on first-party People surfaces even while `TELEGRAM_MTPROTO_AI_ENABLED=false`.
- This must NOT weaken the Assistant/LLM Telegram gate. Model-facing `find_person_communications` behavior must remain gated exactly as today.
- Bound scans using existing Person scan limits; no unbounded query.
- Return explicit truncation.
- Do not create Person<->Flow graph edges merely to render the list.

If reuse requires a service parameter, its default must preserve the current Assistant-safe behavior and the first-party bypass must be explicit at the People workspace call site.

### C. Salience summary

For a rooted Person only, expose the existing `PersonSalienceService.evaluate` result in bounded presentation form:

- score;
- tier;
- component name/value pairs;
- truncated flag;
- window_days;
- `claims_object_importance` (must remain false).

Do not invent new weights or recompute salience in the client.

Overview ordering remains unchanged.

## First-party UI

Extend the existing Person detail section in People mode.

### Task section

Show current Task involvement as rows with human-readable canonical role labels.

Suggested Russian labels:

- `requested_by` — «Попросил(а)»
- `delegated_to` — «Делегировано»
- `waiting_on` — «Ждём от»
- `involves` — «Участвует»

The wording may be adjusted for grammatical clarity, but the underlying role must remain exact.

A proposed edge must be visibly marked as proposed, using the existing Secretary proposal vocabulary where practical.

A Task row must allow navigation to the existing Task graph/detail path without inventing a new Task view.

### Flow section

Show recent attributable communications with provider, title and date/time. Selecting an item must open the existing object detail path.

Do not render message bodies directly in the Person summary.

### Salience section

Show the score/tier and component breakdown in a compact, inspectable form.

Include a short human-facing clarification equivalent to:

`Сигнал активности и контекста, не оценка важности человека или сообщения.`

Do not add badges implying authority, priority, friendship, management, or importance.

### Existing sections

Preserve identity correction and route presentation.

## Performance / safety

- Rooted detail may perform the bounded extra reads above.
- Ordinary People overview/search must not perform per-Person Task/communication/salience-detail fan-out.
- User isolation remains strict.
- No provider/network call.
- No LLM call.
- No background enrichment run.
- No writes except the already-existing identity correction actions when the human explicitly uses them; R2 itself adds no write path.
- Telegram privacy/AI gates remain unchanged outside the explicit first-party read described above.

## Tests

Add focused backend tests covering at least:

1. exact Task actor roles appear;
2. generic Person<->Task edges do not masquerade as actor involvement;
3. rejected actor edges and terminal/deleted Tasks do not appear;
4. proposed actor edge state/origin is preserved;
5. list cap/truncation is deterministic;
6. recent communication list is identity-grounded;
7. rejected identity suppresses attribution;
8. first-party People detail can read eligible stored Telegram without enabling model-facing Telegram retrieval;
9. salience projection equals the canonical service result and `claims_object_importance=false`;
10. overview/search do not fan out into rooted detail reads.

Add focused Flutter coverage for:

- Task role rows and proposed marking;
- Task navigation;
- recent Flow rows and object-detail navigation;
- salience disclaimer/components;
- empty states;
- existing identity/routes still render.

Run the relevant existing People/Person/Graph suites, Ruff on touched Python, Flutter analyze on touched Dart, `git diff --check`, and a Linux debug build.

Known unrelated baseline failures may be reported only if reproduced outside the R2 diff.

## Out of scope

- No DB migration.
- No durable relationship/context table.
- No `manager_of`, `friend`, `colleague`, `member_of`, `role_at`, Organization object, or any replacement social taxonomy.
- No automatic Person creation, merge, or identity attach beyond existing explicit correction behavior.
- No Assistant prompt change.
- No proactive behavior or evidence change.
- No Task semantics change.
- No MCP work.
- No G3B.
- No S3.
- No production deploy or production data inspection.
- No synthetic production data.

## Completion

- Commit the implementation.
- Record exact behavior and verification in `PROJECT_STATE.md`.
- Build a Linux debug bundle for later human visual review; do not perform the human acceptance yourself.
- Return `CURRENT_TASK.md` to HOLD with the implementation SHA and bundle path.
- Push implementation and HOLD commits to `main`.
- Stop. Do not start relationship persistence or the next People slice.
