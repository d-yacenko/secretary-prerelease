# Current task — Graph Refined P6R: concrete route-preference semantics

Architect review of P6 implementation `1f8279a9c282ed150f384c5a9a62658eae1beb68` confirms the core safety design: route discovery is READ-only, Person-targeted sends use same-turn exposed routes, existing send engines prepare/freeze canonical destinations, and approval executes frozen actions without re-resolving the Person.

One blocking semantic defect remains, plus one adjacent bounded correctness edge. Fix only these. Do not start the next roadmap stage and do not deploy.

## Defect 1 — route preference is identity-wide instead of concrete-route-specific

Current `record_route_choice()` correctly records provenance key:
`assistant:user_route_choice:{route_key}`.

But route rendering calls `_has_route_choice(identity)`, which checks only:
- user;
- active `user_route_choice`;
- provider/type/realm/canonical identity.

Therefore if the same exact identity has more than one concrete route (for example the same Teams user in two stored oneOnOne chat/account contexts), choosing route A causes routes A and B both to render `has_route_choice=true` and both get the preference ordering boost.

This violates the accepted separation:
- identity/endpoint ownership;
- concrete route preference.

### Required correction

Make concrete route ordering/annotation use the exact route choice provenance.

For one route:
- `has_route_choice=true` only when there is an active `user_route_choice` row for that Person+identity whose provenance key corresponds to that exact `route_key`;
- a choice of route A must not mark another route B of the same identity as chosen;
- email routes remain route-specific naturally by address;
- chat routes are route-specific by their stable concrete conversation route key;
- existing P2 scoring may still treat route choice as weak/moderate evidence for the identity in general. Do not change P2 score semantics merely to fix route ordering.

Prefer changing `_has_route_choice` to accept `route_key` and validating the exact provenance key. No migration should be needed.

## Defect 2 — provider-filtered exposed route can fail record_route_choice due to unfiltered top-N re-list

Current `record_route_choice(person_id, route_key)` re-runs:
`list_routes(ListPersonRoutesInput(person_id=...))`
without a provider/category constraint, then searches only the visible top `MAX_PERSON_ROUTES`.

A route legitimately exposed to the model by:
`list_person_routes(person_id, provider="teams")`
can therefore fail during recording if more highly ordered routes from other providers fill the unfiltered visible top-N.

### Required correction

Validate the chosen route against the same concrete route category implied by the `route_key`, or otherwise use a bounded exact-route lookup that cannot be starved by unrelated provider routes.

Requirements:
- still verify the route currently exists and remains effective for that Person;
- do not trust the route key merely because the model supplied it;
- do not turn validation into an unbounded scan;
- same-turn Assistant allowlist remains mandatory at ToolRunner level;
- direct/domain calls remain safe and fail closed.

A simple acceptable approach:
- derive category/provider from the route key prefix;
- call bounded `list_routes` constrained to that provider/category;
- require exact route-key match.

Do not weaken route discovery bounds.

## Focused proof

Add/extend tests proving at minimum:

1. One Person has one exact Teams identity but two concrete oneOnOne Teams routes.
2. Before any choice, both routes are unpreferred and ambiguity remains.
3. Choosing route A records one `user_route_choice` and only route A gets `has_route_choice=true`.
4. Route B remains unpreferred even though it has the same identity tuple.
5. The selected route sorts before B, but `ambiguous` remains true.
6. Repeating the same route choice remains idempotent/no score inflation.
7. Choosing route B later may mark B independently; it must not rewrite/delete route A evidence automatically.
8. A route exposed under a provider-filtered list can still be recorded even when unrelated routes would push it outside the unfiltered top `MAX_PERSON_ROUTES`.
9. An invented/nonexistent/stale route key still fails closed.
10. Same-turn route allowlist still blocks an unexposed route.
11. Existing email/chat frozen pending-plan tests remain green.
12. Existing P1–P6 focused Graph Refined tests remain green.
13. No new send engine, migration, live provider lookup, deployment, or next-stage work is introduced.

Run:
- `tests/test_person_routes.py`;
- P1–P5 focused Graph Refined tests;
- `tests/test_tool_gateway.py`;
- existing safe external-send/action-plan tests used by P6;
- Ruff/compile on touched Python;
- `git diff --check`.

Known unrelated Assistant baseline failures around `pending_action_plan` response expectation and `ai_traces_user_id_fkey` remain outside this task.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose the next roadmap stage and do not deploy.
