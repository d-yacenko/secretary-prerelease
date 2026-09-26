# Current task — People C1: explicit first-party Person creation

People P1R3 is accepted.

Production contains zero Person Objects, so P1 real-data review is not useful yet.

The accepted Person architecture intentionally avoids eager sender -> Person materialization. Preserve that rule.

C1 adds the smallest safe cold-start trigger:

> the authenticated user explicitly creates a canonical Person by name in People mode.

This is a first-party human action only.

No automatic promotion, identity inference, provider lookup, merge, organization semantics, migration, or production deploy.

## Canonical semantics

A Person remains:
- an ordinary canonical Object with `kind="person"`;
- user-owned;
- created through the existing `PersonIdentityService.create_person(title)`;
- `origin=user`;
- `state=confirmed`.

A display name is NOT identity.

Therefore:
- duplicate Person titles are allowed;
- do not deduplicate by title;
- do not search/merge by fuzzy name during creation;
- do not attach any provider identity during creation;
- do not create any Person↔Flow, Person↔Task, or Person↔Person edge during creation.

Identity candidates/corrections remain the existing later workflow.

## Backend API

Add one dedicated first-party endpoint under the existing People Graph API, for example:

`POST /graph/people`

Input:
- `title: string`

Output:
- canonical `ObjectOut` for the created Person.

Use `PersonIdentityService.create_person`. Do not duplicate Person validation in the route.

Requirements:
- trim/validate through the canonical service;
- empty/invalid title returns the existing validation error surface;
- title > canonical service bound fails;
- duplicate titles succeed as separate Person Objects;
- no identity/evidence rows are created;
- no edges are created;
- no provider/model call;
- no background job enqueue solely because a Person was created.

Do not use the generic `POST /objects` from the client for C1. The dedicated People endpoint should make the human semantic contract explicit while still reusing the same canonical Person service.

No new DB schema or migration.

## Client API

Add a typed client method, e.g.:

`createPerson({required String title})`

calling the new endpoint and returning `SecretaryObject`.

No provider/contact fields in C1.

## People UI

In `Люди` mode only, add a visible action:

`Добавить человека`

It must not appear in `Задачи` mode.

Dialog:
- title: `Добавить человека`;
- one text input labeled `Имя`;
- helper text such as:
  `Контакты и связанные аккаунты можно подтвердить после создания.`
- `Отмена`;
- `Добавить`.

Behavior:
- whitespace-only cannot submit;
- trim on submit;
- prevent duplicate submission while request is in flight;
- server validation errors use the existing snackbar/error style;
- closing/canceling creates nothing.

## After successful creation

The newly created Person must become immediately usable in People mode.

Preferred behavior:

1. refresh/reload the People workspace through the existing controller/API;
2. make the created Person selected;
3. open/re-root to that Person using existing People navigation so the existing detail pane can expose grounded identity candidates/routes if any are available from stored data.

Do not invent a second local Person representation.

Do not mutate controller positions manually.
Do not add a special fit rule beyond normal existing reroot behavior.
Do not change Tasks mode.

If exact reroot-after-create is awkward, selecting the created Person after refreshed overview is acceptable only if the existing UI still provides an immediate one-click path to its rooted detail. State the chosen behavior.

## Important identity boundary

C1 does NOT fix or redesign identity materialization.

Specifically do not:
- auto-confirm an email/handle because its display name resembles the new Person;
- call `PersonEnrichmentService.plan()` automatically;
- attach a `PersonIdentity` from a candidate;
- change `correct_identity` semantics;
- create communication edges from candidate identity evidence;
- run directory/provider lookup.

The existing Person identity candidate/correction workflow must remain unchanged.

## Empty People state

When People workspace has no Person Objects:
- the user must still see `Добавить человека`;
- do not show a misleading error or require search first;
- an explicit empty-state hint is allowed, e.g. `Добавьте человека, чтобы начать.`, but keep it small.

After first Person creation, normal P1 cards/overview apply.

## Tests — backend

Add focused tests proving at minimum:

1. POST People creates `kind=person`;
2. origin/state are canonical user/confirmed;
3. title is trimmed;
4. blank title fails;
5. overlong title fails;
6. duplicate titles create distinct Person ids;
7. creating Person creates zero `PersonIdentity` rows;
8. creates zero `PersonIdentityEvidence` rows;
9. creates zero graph edges;
10. cross-user isolation remains normal;
11. existing People workspace sees the created Person.

## Tests — client

Add focused Flutter tests proving at minimum:

1. `Добавить человека` visible only in People mode;
2. empty People workspace still exposes it;
3. blank input cannot submit;
4. cancel performs no POST;
5. valid submit sends exactly one POST with trimmed title;
6. repeated tap/in-flight cannot double-create;
7. server validation error is shown and dialog/state remains safe;
8. success refreshes People workspace;
9. created Person becomes selected/rooted or has the documented immediate detail path;
10. existing P1 Person card rendering still works;
11. People search still works;
12. Tasks mode is unchanged;
13. V8C2 desktop/narrow detail-shell behavior remains green.

Run:
- new backend People-create tests;
- `backend/tests/test_person_graph_workspace.py`;
- relevant identity/evidence tests to prove no semantic drift;
- new client create-Person tests;
- existing `people_workspace_screen_test.dart`;
- affected Graph shell tests;
- Flutter analyze touched files;
- Linux debug build;
- `git diff --check`.

The three known historical Graph detail-screen failures may remain only if they are the exact same three names already recorded.

## Scope guard

Do NOT:
- auto-materialize People from messages;
- create background Person-promotion jobs;
- change salience;
- change identity candidate scoring;
- change confirmation/attach semantics;
- add Assistant/MCP `create_person` tools in C1;
- add organization/manager/member relations;
- add Person↔Person edges;
- change Task actor semantics;
- implement H2 `completion_mode` parity;
- restrict `link_objects`;
- migrate or deploy production;
- rerun any production census.

## Completion

Record in `PROJECT_STATE.md`:
- implementation SHA;
- exact endpoint;
- exact UI wording;
- post-create selection/root behavior;
- backend/client test counts;
- whether schema changed (must be no);
- whether production/network was touched (must be no).

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start C2.
Do not start P2.
Do not start H2.
Do not deploy production.
