# Current task — PP1-HG3: People inspector + promotion truth correction

## State

- PP1 backend production/runtime/origin-production: `07bd8bafdb2f53a6a8475fc2d792687fa373a149`.
- Production/repository Alembic: `0051 / 0051`.
- HG2 client implementation: `05eb5f7132d9a10cb79ec317acd3e295b99c81fc`.
- Human HG2 review is not accepted. Use the findings recorded in `PROJECT_STATE.md`.
- Current main before this authorization: `180f60bda1bbc0b40293012500e87f7d4f3f84ce`.

This task is a bounded backend+client correctness/UX slice. Do not deploy production in HG3. No migration is expected or authorized.

## Product goal

Complete the PP1 human gate by fixing both semantic truth and interaction design:

1. People graph remains the primary surface.
2. People uses the same right-side inspector grammar as Task graph.
3. Candidate review lives in that inspector and never changes graph geometry.
4. Selected Person detail is loaded from rooted Person truth, not from the lightweight overview projection.
5. Promotion must stop proposing clearly automated email endpoints as people.
6. Promotion approval must preserve the best stored server-side human display label.
7. Existing bad Person titles remain user-correctable through an explicit rename action.

Do not start Person Knowledge, Organization ontology, or relationship inference.

## A. Unified People right-side inspector

### Wide desktop

In People mode, reuse the Task graph interaction pattern:

- graph is always the primary visible surface;
- a right-side inspector can be opened/closed even when no Person node is selected;
- when no Person is selected and inspector is open, default inspector content is **Кандидаты**;
- when a Person is selected, inspector opens/switches to **Детали** for that Person;
- keep an explicit compact `Кандидаты | Детали` switch when a Person is selected so the user can review proposals without clearing graph selection;
- closing inspector must not clear Person selection;
- switching tabs must not re-root or relayout the graph.

Use approximately the same visual width/grammar as the existing desktop Task detail pane. Do not modify Task-mode behavior.

### Candidate queue

Remove the top-of-graph promotion review as the primary People UX.

Inside the inspector Candidate view:

- vertically scrollable list;
- current batch count only, e.g. `Предлагаемые · 5`;
- partial-scan disclosure preserved;
- each candidate remains a distinct compact card;
- Add / Do-not-suggest bound to that exact candidate;
- compact body-free source tiles preserved;
- hidden suggestions remain separately collapsible with Restore;
- use a visible/usable Scrollbar on desktop so scrollability is obvious;
- backend max batch remains unchanged.

A small toolbar/button cue may show that candidates exist and open the inspector. Do not claim an exact total beyond the exposed batch.

### Narrow layout

Preserve a usable compact equivalent with the existing bottom/overlay pattern. No horizontal or vertical overflow. Do not redesign mobile navigation in this slice.

## B. Selected Person inspector must use rooted truth

The current selected overview PersonPresentation is intentionally lightweight and must not be rendered as if it were full truth.

When a Person node is selected:

- keep the main People graph on the overview; selecting a node alone must NOT call `reRoot`;
- independently load `GET People workspace(root_id=person_id)` through the existing API to obtain the rooted PersonPresentation;
- show a loading state until rooted truth arrives;
- only then render task involvement, recent communications, identities, routes, salience, candidates, and their empty states;
- if rooted detail load fails, show a recoverable error/retry; never convert “not loaded” into zero/empty truth;
- cache only for the active selection/screen lifetime as appropriate; avoid request storms;
- selection races must not display Person A truth under Person B.

Keep the explicit existing `В центр` action for users who want the graph itself re-rooted.

### Overview communication metric truth

Do not display a bounded partial communication count as an authoritative zero.

Add the smallest backend/API truth bit needed to describe overview communication count partiality. Preferred shape:

- extend the existing shared bounded count operation to return counts plus whether the global communication scan was truncated;
- expose a boolean such as `recent_communication_count_truncated` on PersonPresentation.

Client semantics:

- complete scan: exact `Сообщения · N`;
- truncated scan with N > 0: present as a lower bound, e.g. `Сообщения · ≥N`;
- truncated scan with N == 0: do not say `0 сообщений`; use a compact partial/unknown cue or omit the numeric message metric with an explanatory tooltip;
- rooted recent communication section continues to use its existing own truncation truth.

Do not increase scan caps or change the accepted 90-day/400-row semantics in this slice.

### Task metric wording

Overview `open_task_count` reflects explicit graph-connected active tasks. Do not imply inferred task knowledge.

Use wording such as `Связанные задачи · N` (or a compact equivalent) rather than a broad claim that all tasks involving the person are known.

Do not create missing Task-Person edges.

## C. Person graph-card cleanup

For Person-specific graph cards:

- remove the generic visible word `Человек`;
- top row should use Person icon + strong Person name;
- provider/contact cues become secondary;
- metrics remain compact at the bottom;
- identity conflict cue preserved;
- same 186x100 footprint unless a very small bounded change is strictly necessary;
- Task generic cards must remain unchanged.

## D. Promotion quality: exclude clearly automated email endpoints

PP1 currently accepts a repeated direct inbound exact email even when the sender is obviously an automated service (human example: Google Calendar / `calendar-notification@google.com`).

Add deterministic fail-closed **promotion-only** automation filtering.

### Strong stored signals

For email promotion, reject a row/candidate when either:

1. existing stored compact headers contain non-empty `list-id`; or
2. the normalized email local-part matches a **narrow explicit automated mailbox rule**.

The automated mailbox rule should cover strong cases such as:

- `no-reply`, `noreply`, `do-not-reply`, `donotreply`;
- `mailer-daemon`, `postmaster`;
- `calendar-notification`;
- clearly equivalent notification-only spellings where the token itself is the mailbox purpose.

Keep this narrow. Do NOT broadly reject ordinary role addresses such as:

- `support@`;
- `sales@`;
- `team@`;
- `office@`;
- `info@`.

No domain blacklist. No special-case `google.com`. No LLM/model/provider call.

The exact same rule must be used by candidate read and approval revalidation so a crafted approval cannot bypass it.

Do not change general identity extraction or attribution semantics for existing Persons. This rule is only about assisted **promotion into a Person**.

## E. Promotion display-name authority

### Mattermost fallback

In stored Mattermost identity evidence, use:

`author_display_name -> author_username -> no display label`

for the exact Mattermost user-id identity.

Do not derive a name from message body/title text.

### Approval freeze

Refactor promotion approval so that eligibility revalidation and the chosen server-side display label come from the same current exposed hit/candidate snapshot.

Approval must:

- revalidate exact tuple;
- obtain the current eligible server-side hit;
- create Person title from that hit's best stored display label, canonical fallback only when no better label exists;
- attach the exact identity with that same best display label where valid;
- continue to record user_confirmed evidence;
- never trust a client-supplied display name as authority;
- preserve idempotence/conflict behavior.

Add regression proving a Mattermost candidate displayed as a human display name/username cannot become a canonical opaque ID after approval.

## F. Explicit Person rename for existing bad titles

There are already accepted Persons created before this fix whose Object title may be an opaque provider identifier.

Do not auto-rewrite persisted Person titles.

Expose a small explicit `Переименовать` action in the Person inspector:

- reuse the existing generic `PATCH /objects/{id}` ObjectUpdate title path;
- validate non-empty title through existing backend rules;
- after success refresh graph node and rooted inspector truth;
- no identity tuple changes;
- no merge;
- no provider lookup.

If the client API lacks a thin generic patch-title method, add only that client wrapper; no new backend endpoint is required.

## G. Required backend regressions

At minimum:

1. normal repeated personal email -> candidate;
2. email with `List-Id` -> no promotion candidate;
3. `calendar-notification@...` repeated direct inbound -> no candidate;
4. no-reply/noreply equivalents -> no candidate;
5. mailer-daemon/postmaster -> no candidate;
6. ordinary `support@` repeated direct inbound remains eligible;
7. automation filter is enforced by approval revalidation;
8. Mattermost display_name -> candidate and approved Person title preserve display_name;
9. Mattermost username fallback -> candidate and approved Person title preserve username;
10. no Mattermost display/username -> canonical fallback remains allowed;
11. approval attaches display value from server-side hit, not client input;
12. existing self-author Mattermost exclusions remain green;
13. overview communication count reports global scan truncation truth without changing 400-row boundary;
14. existing rooted H2 salience/communication semantics remain green;
15. no Person<->Flow edges, relationship facts, Task actors, or Organization facts are created.

No Alembic migration. Head remains `0051`.

## H. Required Flutter regressions

At minimum:

1. Person graph card has Person icon + name and no visible generic `Человек` label;
2. Task graph card behavior/text remains unchanged;
3. People inspector can open with no selection and shows Candidates;
4. Candidate queue is vertically scrollable with visible desktop Scrollbar;
5. selecting Person switches inspector to Details without re-rooting overview graph;
6. Candidates/Details switch works while selection remains;
7. closing/reopening inspector does not corrupt graph selection;
8. selected Person shows loading before rooted truth, not false zero/empty data;
9. rooted truth response populates communications/task involvement correctly;
10. selection race A->B cannot show A detail for B;
11. rooted load error has retry;
12. truncated overview communication metric is presented as partial/lower-bound, never false authoritative zero;
13. complete zero may still render as exact zero;
14. task metric wording reflects explicit linked tasks;
15. Person rename updates visible graph title/detail and does not alter identities;
16. promotion Add/Do-not-suggest/Restore still work;
17. candidate source tiles remain body-free and clickable;
18. no top promotion panel consumes graph height in People overview;
19. narrow supported layout does not overflow;
20. existing rooted correction/contact/salience actions remain reachable.

Run focused People/promotion/identity tests and relevant broader Graph suites. Report unrelated baseline failures separately; do not fix them.

Run Ruff, Flutter analyze for touched Dart files, and `git diff --check`.

## Build / human gate

Because backend behavior changes, build a fresh Linux debug HG3 bundle but do not claim it is human-testable against production until the HG3 backend is separately rolled out.

Report bundle path and SHA-256 for source provenance.

## Explicitly out of scope

- No production deploy in HG3.
- No migration/schema change.
- No scan-cap increase.
- No inferred manager/colleague/family/client/company role.
- No Organization ontology.
- No Person-to-Person social graph.
- No task-creation contextual promotion prompt.
- No provider/network/model lookup.
- No domain-specific sender blacklist.
- No automatic renaming of existing Person objects.
- No automatic creation of Task-Person edges.
- No MCP/G3B/S3 work.
- No Task graph redesign.

## Completion

1. Commit implementation + focused regressions.
2. Record exact implementation SHA, changed truth semantics, tests, Alembic head, and HG3 bundle path/checksum in `PROJECT_STATE.md`.
3. Return `CURRENT_TASK.md` to HOLD stating:
   - HG3 source ready / human gate pending backend rollout;
   - production still `07bd8bafdb2f53a6a8475fc2d792687fa373a149`;
   - Alembic still `0051`.
4. Push implementation + HOLD to `main`.
5. Report exact SHAs/tests/bundle and STOP.

Do not deploy and do not begin Person Knowledge or the next product slice.
