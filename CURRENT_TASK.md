# Current task — PC1-H2.1: fail-closed duplicate grounding

## State
- H2 implementation: `e416b115c5c4c6ba5971538d5af9ba2ef067c11b`.
- Production/runtime/origin-production: `a3d546b069e7e05d68fd42906c662c3ba34caef5`.
- Alembic: `0051`.
- H2A conflict truth and H2C People lookup are directionally accepted.
- H2B duplicate grounding is NOT source-ready.
- PT1 remains unauthorized.

## Goal
An identity already owned by another active Person may expose
`Возможно, это один человек → Объединить`
only with strong deterministic grounding to the current Person.

## Required fix
In `PersonAssistantService._source_candidates()`:
- remove `propose_candidates(identity, identity.display_value)` as grounding for an occupied identity;
- expose an occupied identity as a merge suggestion only when `_grounded_duplicate()` is true;
- do not change ordinary non-owned candidate behavior.

In `_grounded_duplicate()`, accept only:
1. active explicit exact-tuple evidence on the current Person:
   - `USER_CONFIRMED`;
   - `USER_ROUTE_CHOICE`;
2. the existing deterministic same-source rule where that same stored source object also contains another effective identity already owned by the current active Person.

The following must NOT ground a merge suggestion by themselves:
- `NAME_SIMILARITY`;
- `ORGANIZATION_MATCH`;
- `GRAPH_CONTEXT`;
- `LLM_SUGGESTION`;
- display-name equality;
- ownership conflict itself.

Suppressed/rejected or contradictory evidence must fail closed.

## Tests
Add backend regressions proving:
- same display name alone does not expose `conflicting_person_id`;
- active `NAME_SIMILARITY` does not ground;
- active `LLM_SUGGESTION` does not ground;
- active `USER_CONFIRMED` exact tuple does ground;
- active `USER_ROUTE_CHOICE` exact tuple does ground;
- same-source co-occurrence still grounds;
- unrelated occupied identity still does not suggest merge;
- existing confirmation remains fail-closed.

Keep H2A and H2C regressions passing. Run focused backend suites, focused Flutter consolidation tests, Ruff and `git diff --check`.

No migration. Alembic remains `0051`.

## Safety
Do not deploy or move `origin/production`.
Do not write Person data in production.
Do not start PT1 or later roadmap work.

## Completion
Commit/push H2.1, update `PROJECT_STATE.md`, return this file to HOLD, report SHAs/tests, and STOP.
