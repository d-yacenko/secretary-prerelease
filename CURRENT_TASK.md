# CURRENT_TASK

ACTIVE

## REL1D-HG6A — instant Person authoring and context-aware People stratification

### Context

HG5 shared Task/People semantic topology is human-accepted.

The next practical bottleneck is filling real People data.

Observed UX:

- selecting a Person from the unrooted People overview currently replaces the detail pane with a blocking spinner for roughly 10 seconds;
- the selected Person's overview `PersonPresentation` is already loaded and contains enough authoritative summary data to begin editing immediately, including title and active role assignments with `context`;
- the full rooted People workspace is substantially heavier because it also derives rooted communication/candidate/truth sections;
- after a role/context mutation, current UI calls a full workspace refresh + rooted reload even though the mutation endpoint already returns the authoritative assignment;
- compact People tiles currently look identical regardless of role context, and People sharing one local Task-anchor cluster are packed only by id rather than by context.

Do not introduce OpenSearch, a new cache service, embeddings, or model calls for this UX problem.

### Goal

Make the Person filling loop feel immediate and visually structured:

1. a selected Person detail card becomes usable immediately from the already-loaded overview presentation while heavy rooted truth hydrates in the background;
2. adding/removing a Person role/context updates the visible detail and People overview immediately from the authoritative mutation response, without a heavy workspace reload;
3. compact People cards use a deterministic subtle context tint;
4. within existing canonical Task geography, People use a deterministic gravity-like local cluster packing so same/related contexts form compact visual groups around the same Task-derived center;
5. no-context People keep the current default card appearance.

Prefer a client-only implementation.

No schema/Alembic or production deploy.

### A. Immediate progressive Person detail

1. When an unrooted overview Person is selected and `controller.personFor(personId)` already exists:

- install that presentation into the detail pane immediately;
- open the Details tab immediately;
- keep the background rooted People request for full truth;
- do NOT clear the visible Person presentation while the rooted request is in flight;
- do NOT show the current full-card blocking spinner.

The immediate summary should expose at least:

- title;
- rename action;
- active role assignments and their contexts;
- already-grounded/effective identity cues that are present in overview;
- safe overview metrics already present.

2. Root-only sections must not lie while hydration is incomplete.

Fields that can be empty merely because the overview response omits rooted truth must show an explicit local loading state until the rooted response becomes authoritative. In particular do not render false final statements such as:

- `Нет участия в текущих задачах`;
- `Нет недавних коммуникаций`;
- `Нет кандидатов`;

solely because the overview presentation has the default empty list.

Implementation may use the existing `_rootedPersonAuthoritative` state or one equivalent completeness flag.

3. A full-card spinner remains allowed only when there is genuinely no usable Person presentation at all (for example an unusual direct/rooted entry before any Person summary exists).

4. Rooted hydration success replaces/merges the summary with full authoritative truth exactly as today.

5. Rooted hydration failure must preserve the usable summary card and role/rename controls. Show a small recoverable `Не удалось загрузить подробности · Повторить` state for the missing heavy sections instead of replacing the whole card with an error.

6. Existing stale-response guarantees remain:

- A→B selection cannot install A into B;
- rename cannot be reverted by an older rooted response;
- Task actor mutation/reconciliation generations remain intact;
- rooted controller truth is still reused without duplicate GET when already available.

### B. Role/context mutation fast path

7. `POST /graph/people/{person_id}/roles` and `DELETE /graph/people/{person_id}/roles/{assignment_id}` already return authoritative `PersonRoleAssignment`.

Use that returned object directly.

After successful assign/retract:

- update the visible Person detail role list immediately;
- update the controller's overview `PersonPresentation.roleAssignments` immediately;
- notify/repaint the People overview immediately;
- do not require `refreshCurrentWorkspace()`;
- do not require a full rooted People reload merely to show the role/context mutation.

8. Add a narrow immutable helper such as `PersonPresentation.withRoleAssignments(...)` and one narrow controller patch method. Do not add client aliases or mutate raw JSON.

9. Role mutation must be safe against an older rooted request that started before the mutation.

An older rooted response may hydrate unrelated heavy truth, but it must not restore the pre-mutation role/context list. Use a role-specific generation/merge or an equivalent narrow stale protection.

Do not invalidate Task actor generation semantics to solve this.

10. Multiple quick role/context mutations remain deterministic and do not start an unbounded chain of rooted People requests.

11. Mutation failure leaves the existing role/context list unchanged and exposes a recoverable visible error.

### C. Context visual identity

12. Source of truth is only active `PersonRoleAssignment.context` already present in `PersonPresentation.roleAssignments`.

Do not infer context from:

- title;
- email/domain;
- Task title;
- message text;
- provider;
- LLM/model output.

13. Add one small shared client helper/model for Person context visualization.

It must derive from the active non-empty context strings:

- a normalized exact context key;
- a conservative visual family key;
- a deterministic sort key;
- context tint information.

No value is persisted.

14. No-context behavior:

If a Person has no active non-empty role context:

- compact People card uses the existing default `ColorScheme.surface` appearance;
- it belongs to the no-context local ordering bucket;
- no fake context/family is invented.

15. Exact-context behavior:

The same normalized context must always produce the same tint in the same theme, independent of Person id and role title.

Normalization must at least ignore case, surrounding/repeated whitespace, and punctuation used only as separators.

16. Related-context behavior:

Use one conservative deterministic client-only heuristic so obviously related context strings can share one color family with nearby shades.

It is a visual hint only and must never become stored ontology or Agent truth.

The heuristic must cover the motivating case:

- a context ending in `Arenadata` such as `УЦ группы компании Arenadata`;
- another context such as `SRE Arenadata`;

→ same color family, distinct nearby shades when the exact contexts differ.

A context like `Южный Федеральный Университет` or `Рубитех` must not be forced into the Arenadata family.

Prefer a simple normalized terminal organization token / conservative generic-suffix rule over fuzzy semantic inference.

17. If a Person has multiple distinct active non-empty contexts, do not pretend one is semantically primary.

Create one deterministic combined visual signature/family fallback for that set, or another conservative neutral multi-context treatment. Full contexts remain visible only in the detail card.

18. Tints must remain subtle and readable in light/dark themes.

- selection border/elevation remains clearly visible;
- identity-conflict icon remains visible;
- bookmark ribbon remains visible;
- text uses theme-derived contrast;
- do not hard-code context text on compact tiles.

### D. Context-aware gravity-like local packing

19. Preserve the HG5 global geography.

Context is only a secondary **local attraction** signal.

Do not change:

- Task semantic-window membership;
- persisted Task coordinates;
- Person anchor sets;
- Person anchor centroid/base;
- unanchored shelf origin;
- canonical Task world bounds;
- shared camera frame.

20. Replace the current same-anchor rectangular grid behavior with one deterministic gravity-like local packing for People that already share the same exact Task-anchor set in `projectPeopleLandscapeOverview`.

This must NOT be a general physics engine and must NOT introduce animation or nondeterministic force simulation.

Preferred shape:

- the existing Task-derived Person cluster base remains the one global center;
- derive local attractor groups from context visual families/exact contexts;
- each attractor gets a small deterministic offset around that base;
- each Person is placed in the nearest available non-overlapping slot to its attractor;
- same exact contexts therefore collapse into compact micro-clusters;
- related exact contexts in one family use nearby attractors;
- unrelated families use more separated attractors;
- no-context People use one neutral local attractor/bucket.

The exact algorithm may use deterministic rings/spiral candidate slots, bounded relaxation, or another simple bounded method. Do not add a third-party force-layout dependency.

21. Preserve centering.

After local packing, the aggregate same-anchor Person cluster must remain centered on its original Task-derived base within a small deterministic tolerance. Context must not translate the whole cluster away from the canonical anchor merely because one family has more members.

The existing inter-cluster collision separation may still translate the whole already-packed cluster only as required to avoid overlap with another anchor cluster.

22. Stability requirements:

- identical input must yield identical positions;
- input iteration order must not affect the result;
- changing one Person's context may locally rearrange that same anchor cluster, but must not move unrelated anchor clusters unless existing overlap separation requires it;
- no frame-to-frame jitter;
- no simulation state is persisted.

23. Unanchored shelf:

Keep all unanchored People on the existing shelf, but use the same context-family idea to form compact local shelf sub-clusters rather than a single arbitrary id-ordered column when space permits.

Do not move unanchored People into Task geography.

24. Context changes from a successful role mutation should immediately recompute color and the affected local packing without refitting/re-rooting the entire world.

### E. Do not change rooted truth semantics yet

23. Do not redesign the backend rooted People evidence/candidate algorithms in this task.

The source review records that the full rooted request performs several overlapping bounded communication-derived computations. If the background heavy sections still feel too slow after the blocking spinner is removed, that will be a separate backend optimization using a shared evidence snapshot.

24. Do not change:

- `PERSON_LOOKBACK_DAYS`;
- `MAX_PERSON_SCAN_ROWS`;
- identity-candidate depth;
- communication attribution semantics;
- salience semantics;
- routes semantics.

### Required tests — progressive detail

At minimum prove:

1. Selecting an overview Person with an existing `PersonPresentation` renders title + role/context controls before a deliberately delayed rooted People response completes.
2. No full-card `person-detail-loading` spinner is shown in that case.
3. Root-only empty sections show loading placeholders, not false `Нет ...` final states, before hydration.
4. Delayed rooted success hydrates those sections without replacing the selected Person.
5. Delayed rooted failure preserves summary + role controls and shows recoverable detail-load error/retry.
6. A→B selection rejects stale A response.
7. Existing rooted-controller reuse still avoids duplicate GET.
8. Existing HG4E rename stale-response tests remain green.
9. Existing HG4B/HG4E Task actor reconciliation tests remain green.

### Required tests — role/context fast path

10. Role assign success performs one role mutation request and immediately updates the detail role list from the returned assignment.
11. Same success immediately updates the overview Person presentation without a People workspace refresh.
12. Retract success immediately removes/retracts the role/context locally without a People workspace refresh.
13. Role mutation failure leaves prior role/context unchanged and shows recoverable error.
14. A rooted response started before a successful role/context mutation cannot restore the old role/context list.
15. Multiple role changes remain bounded/deterministic and do not create an unbounded rooted-refresh cascade.

### Required tests — color/grouping

16. No-context compact Person card keeps the existing default surface color.
17. Same normalized context on different People produces identical context visual key/tint.
18. `УЦ группы компании Arenadata` and `SRE Arenadata` share a visual family and have nearby-but-distinct exact-context treatment.
19. `Южный Федеральный Университет` and `Рубитех` are not assigned to the Arenadata family.
20. Same-context People sharing one anchor set form one compact local micro-cluster independent of input order.
21. `УЦ группы компании Arenadata` and `SRE Arenadata` use nearby attractors inside one Arenadata family, while unrelated contexts use more separated attractors.
22. The aggregate packed cluster remains centered on the original Task-derived base within deterministic tolerance.
23. Cards never overlap, even when one context group dominates the cluster.
24. Identical input produces identical positions and there is no frame-to-frame jitter.
25. Changing one Person context only locally rearranges its same-anchor cluster; unrelated anchor clusters retain their positions unless existing collision separation requires movement.
26. Unanchored People remain on the shelf and form deterministic context-aware shelf sub-clusters.
27. Multiple-context Person behavior is deterministic and does not silently select one stored context as truth.
28. Selection/conflict/bookmark visuals remain distinguishable on tinted cards.

### Regression suites

Keep green:

- `people_overview_window_test.dart`;
- `people_landscape_overview_test.dart`;
- `person_rename_test.dart`;
- `person_task_bridge_test.dart`;
- Person role section tests;
- any graph shared-world/camera tests touched by layout ordering.

### Expected scope

Likely client-only:

- `client/lib/api/api_models.dart`;
- `client/lib/graph/graph_workspace_controller.dart`;
- `client/lib/graph/graph_workspace_screen.dart`;
- `client/lib/graph/person_roles_section.dart`;
- `client/lib/graph/people_landscape.dart`;
- one small new context-visual helper under `client/lib/graph/`;
- focused Flutter tests.

Do not edit backend unless a compile/API mismatch proves strictly necessary. If backend behavior must change, STOP and report rather than expanding scope.

### Checks

Run focused Flutter suites covering the contracts above.

Also run:

- `dart format` on touched Dart;
- `dart analyze` on touched Dart;
- `git diff --check`.

### Explicitly out of scope

Do NOT:

- add OpenSearch/Elasticsearch;
- add cache infrastructure;
- add schema/Alembic;
- deploy production;
- move production refs;
- change backend candidate/message scan depth;
- start identity-candidate/email discovery repair;
- change Task semantic topology;
- change Task coordinates;
- create stored Person coordinates;
- add new Person ontology/social relations;
- change Task actor semantics;
- change generic PATCH/embedding;
- change Agent/harness/tool contracts in this task;
- call providers/models;
- resume historical repair;
- modify role-import raster extraction.

### Completion protocol

When implementation/checks are green:

1. update `PROJECT_STATE.md` with concise HG6A implementation/test facts;
2. replace this file with `HOLD`, recording implementation SHA and exact checks;
3. commit + push canonical `main`;
4. STOP.

Do not deploy production and do not start Agent/harness or email-candidate work automatically.

Production remains:
`0031f531d1215970093bea7add44fcd2259ec71b`

Alembic remains:
`0054 / 0054`

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
