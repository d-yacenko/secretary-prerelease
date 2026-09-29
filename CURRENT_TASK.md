# Current task — PT1-A: Person-side Task↔Person actor bridge

## State

- PC1 Person consolidation: COMPLETE / human accepted.
- Production/runtime/origin-production: `93dd1e923dfd8df2860db390bf81cf8a0cc80802`.
- Alembic: `0051`.
- Canonical Task actor roles already exist:
  - `requested_by`
  - `delegated_to`
  - `waiting_on`
  - `involves`
- Task Profile already reads/adds/removes these roles.
- Person detail already shows read-only `Участие в задачах`.
- PT1 goal is to finish the bridge from the Person side without inventing new relation types.

## Goal

Make Task↔Person actor relations visible and safely manageable from either side.

This slice is specifically the Person-side bridge. Reuse the existing TaskRelationService and canonical task actor endpoints. Do not create generic `related_to` edges for this feature.

## Backend read contract

Extend Person task involvement rows with the exact actor-edge identity needed for safe mutation:

- `edge_id`;
- keep existing `task_id`, title, status/completion mode/due date, role, edge state and origin;
- include confidence only if already useful/available without widening scope.

Keep current boundedness and active-task filtering.

Do not expose rejected edges or hidden/tombstoned tasks.

## Person UI

In the Person inspector, section `Участие в задачах`:

1. Preserve existing task tiles, role label, due cue and navigation to the Task.
2. Add a clear action such as `Связать с задачей` / `Добавить участие`.
3. Dialog:
   - choose one existing canonical role: `Запросил`, `Поручено`, `Ждём`, `Участвует`;
   - search/select an active Task;
   - show enough Task cue to avoid accidental selection;
   - call canonical `POST /tasks/{task_id}/actors` with the current Person id and selected role;
   - no generic graph edge creation.
4. Existing confirmed user/agent actor relation may be removed from the Person side via canonical `DELETE /tasks/{task_id}/actors/{edge_id}`.
5. Existing proposed actor relation must show the same proposal semantics as Task Profile and allow explicit Confirm / Reject using the canonical relation-decision endpoint.
6. After mutation, refresh the Person presentation so both count and `Участие в задачах` reflect the new truth.
7. Keep click/navigation on the task itself.

Do not auto-create a Task, auto-select a role, or infer a role from messages/names.

## Cross-side truth

The same actor edge must be visible consistently:

- Person -> Task involvement;
- Task -> Task Profile actor group.

Do not duplicate an existing exact Task/Person/role relation. Rely on the canonical idempotent backend semantics.

A Person may legitimately have multiple different roles on the same Task; do not collapse them into one generic link.

## Tests

Backend focused tests:
- Person task involvement exposes `edge_id`;
- confirmed/proposed actor edges preserve role/state/origin;
- rejected actor edges and inactive Tasks are absent;
- existing bounded/truncated behavior remains;
- no generic `related_to` substitution.

Flutter focused tests:
- Person detail shows role on existing involvement;
- `Связать с задачей` can search/select Task + role and calls canonical actor POST;
- exact repeated add stays idempotent/does not duplicate visible row;
- confirmed actor can be removed via task actor DELETE;
- proposed actor can be confirmed/rejected through relation decision;
- navigation to Task remains;
- refresh after mutation updates Person involvement;
- different roles on the same Task remain distinguishable.

Run focused backend suites, focused Flutter tests, relevant Flutter analyze, Ruff, and `git diff --check`.

## Scope boundaries

No migration expected; Alembic must remain `0051`.

Do NOT:
- change Person consolidation;
- add/remove Person identities;
- invent social roles such as manager/colleague/director;
- start People Landscape;
- change LLM/Harness/Secretary prompt context;
- infer Task actor roles automatically;
- start final graph stabilization;
- deploy to production.

## Completion

1. Implement PT1-A and push to `main`.
2. Update `PROJECT_STATE.md` with exact SHA and test results.
3. Return `CURRENT_TASK.md` to HOLD.
4. Report changed files, test results, Alembic state, and confirmation production was not changed.
5. STOP.
