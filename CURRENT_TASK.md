# Current task — People Visual P1: grounded Person cards and salience-preserving overview

Ontology/Harness H1 is accepted.

The existing People workspace already provides grounded Person identity/routing/task/communication data. P1 is the first bounded human-side visual prototype over those existing semantics.

Client presentation only. No backend/API/schema changes. No new Person ontology. No organization/manager relations. No production deploy.

## Product goal

When the user switches to `Люди`, the overview should read as a map/list of known People rather than generic graph Objects.

P1 must expose only facts already returned by the People workspace:

- Person name;
- effective identity/provider presence;
- identity conflict;
- open Task count;
- recent communication count;
- backend overview ordering, whose seed order already reflects Person salience.

Do NOT show or infer job title, employer, manager, colleague, friendship, organization membership, or any other relation that is not canonical today.

## Overview ordering

The backend People overview already returns `seed_ids` in its intended salience/ranking order.

The current generic `GraphLayout` re-sorts isolated nodes, which loses that projection.

For People mode with no root:

1. Preserve the backend `seed_ids` order in the visual overview.
2. Use the existing fixed card geometry and a deterministic 2-D grid/shelf; four columns with the existing Graph node gaps is sufficient.
3. Do NOT recompute salience in Flutter.
4. Do NOT expose the raw `salience_score` number as a user-facing ranking or badge in P1.
5. If a visible Person is somehow absent from `seed_ids`, place it deterministically after ranked seeds (stable title/id fallback).
6. This is presentation projection only: do not mutate or persist canonical controller positions solely to enforce overview order.

It is acceptable to add a small People overview projection helper and to expose the current workspace `seedIds` from the controller if needed.

Rooted People layout must keep the existing generic rooted-star geometry.

Tasks mode layout must remain unchanged.

## Person card

In People mode, a node with `kind == "person"` and a matching `PersonPresentation` should use a Person-specific card while keeping the existing `186 x 100` footprint.

The card should show, compactly:

- Person icon / human-readable `Человек` cue;
- Person name as the main title;
- up to two effective identity/provider cues already present in `PersonPresentation` (provider names/icons are enough; do not print full addresses unless the existing generic card already does);
- a clear identity-conflict warning cue when `identityConflict == true`;
- a compact grounded activity footer such as:
  `Задач: 3 · сообщений: 7`
  using `openTaskCount` and `recentCommunicationCount`.

Do not turn these counts into an importance score.

If `PersonPresentation` is unexpectedly missing, fall back safely to the existing generic card.

Non-Person neighbor cards in rooted People mode (Tasks, email/chat Flow, other grounded Objects) stay on the existing generic card.

## Detail pane

Keep the existing Person detail behavior:

- known identities;
- identity candidate/conflict correction;
- routes;
- relation audit rows;
- linked Task/Flow nodes;
- open Task count.

Add the already available `recentCommunicationCount` as a simple detail fact next to/open below the open Task count, for example:

`Недавние коммуникации: N`

Do not redesign the detail pane.

Do not display raw salience score.

## Rooted People view

Selecting/rerooting a Person continues to use the existing People workspace:

- selected/root Person at the hub;
- grounded open Tasks and limited communication/evidence neighbors around it;
- existing Graph relation rows/details.

P1 does NOT redesign People edge grammar.

In particular:
- do not add Person↔Person edges;
- do not enable forbidden `member_of`, `role_at`, `manager_of`, `works_with`, `colleague`, `manager`, or `friend`;
- do not reinterpret current edge directions;
- do not infer roles from message frequency or names.

The purpose of P1 is to get real screenshots from real People data before deciding P2 relation/layout semantics.

## Search / shell

Preserve:

- `Задачи | Люди` switching;
- People search through the existing People workspace query;
- selection-driven 360 px desktop detail pane from V8C2;
- narrow/mobile bottom detail overlay;
- Tasks mode Preserve/Relax controls only in Tasks mode.

No new filters in P1.

## Tests

Add focused client tests proving at minimum:

1. People overview visual order follows backend `seed_ids`, not alphabetical Object order;
2. repeated identical People overview produces identical positions/order;
3. unranked/missing-seed Person fallback is deterministic after ranked seeds;
4. overview ordering projection does not mutate controller canonical positions;
5. Task mode positions are unchanged;
6. rooted People layout is unchanged by the overview projection;
7. Person card shows the Person name;
8. Person card shows at most two effective provider/identity cues;
9. rejected/candidate identity does not masquerade as an effective provider cue;
10. identity conflict has a visible warning cue;
11. Person card shows open Task count;
12. Person card shows recent communication count;
13. raw `salience_score` is not rendered;
14. Person without `PersonPresentation` safely falls back to generic card;
15. non-Person rooted neighbors remain generic cards;
16. Person detail still exposes identities and routes;
17. Person detail shows both open Task count and recent communication count;
18. existing identity correction behavior remains green;
19. People search/reroot remains green;
20. V8C2 desktop/narrow detail-shell behavior remains green;
21. Tasks-mode Graph relation/hierarchy/proposal tests remain unchanged.

Run at minimum:

- `client/test/graph/people_workspace_screen_test.dart`;
- new People presentation/order tests;
- Graph workspace shell tests affected by shared card code;
- relevant Tasks graph/hierarchy/relation regression tests;
- Flutter analyze on touched files;
- `flutter build linux --debug`;
- `git diff --check`.

The three historically documented detail-screen failures may remain only if they are the exact same three pre-existing failures. Report them precisely; do not fix them in P1.

## Human review gate

P1 is a prototype.

After implementation and technical review, STOP in HOLD. Human real-data screenshots/review will decide:

- whether the Person card carries the right amount of information;
- whether salience ordering is useful;
- whether rooted Task/Flow context is understandable;
- what, if any, P2 Person relation/layout vocabulary is actually needed.

Do not start P2 automatically.

## Scope guard

Do NOT:

- implement H2 `completion_mode` tool parity;
- restrict `link_objects`;
- change prompts/tools/MCP;
- introduce organization/manager ontology;
- add a CRM table/view;
- infer social relations;
- change People backend ranking;
- change Task map geometry;
- repair legacy relation direction;
- fix unrelated Graph detail failures;
- deploy production.

## Completion

Record in `PROJECT_STATE.md`:

- implementation SHA;
- exact People card fields/cues;
- overview ordering/projection behavior;
- rooted behavior;
- test counts;
- whether backend code changed.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start P2.
Do not start H2.
Do not deploy production.
