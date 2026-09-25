# Current task — Person Graph G1: grounded People workspace in Graph UI

Flow Media F2 is architect-accepted. Begin the planned human projection of the existing People & Identity domain model.

Implement only the first bounded Person Graph view.

Do not implement organization inference, job-title inference, manager hierarchy, arbitrary Person-to-Person social relations, CRM workflows, Task Refinement, new LLM inference, provider directory lookups, or production deployment.

## Goal

The existing Graph screen should have two semantic modes:

`Tasks | People`

- **Tasks** preserves the current graph workspace behavior.
- **People** presents a bounded, truthful graph/workspace over already-known canonical Person Objects and existing grounded relations/data.

This is the human-side projection of the already accepted Graph Refined backend. It must use the same canonical Person/identity/evidence services as Assistant/Harness.

## 1. People workspace API

Add a dedicated read endpoint/service, for example:

`GET /graph/people-workspace`

Prefer a separate service such as `PersonGraphWorkspaceService` rather than overloading the task-seeded `GraphWorkspaceService`.

Response may reuse `GraphWorkspaceOut` where practical, but Person detail metadata must be explicit and bounded.

### Overview seeds

Overview should return active canonical Person Objects only:
- same user;
- `kind="person"`;
- not rejected/deleted/hidden;
- deterministic bounded order;
- rank by existing Person salience first where available, with deterministic tie-breaks;
- low salience must not permanently hide a Person from search/rooted view.

Keep seed/node limits similar to current Graph workspace and explicit `truncated`.

Do not eagerly create People for incidental authors.

### Rooted People workspace

When `root_id` is supplied:
- require an active same-user Person;
- include that Person;
- include a bounded set of already-existing canonical relations/objects useful for understanding that Person.

For G1, useful neighbors may include:
- existing linked Task Objects;
- existing explicitly/confirmed graph relations;
- optionally a small bounded set of relevant communication/evidence Objects only if it does not flood the view.

Do not synthesize organization/job hierarchy edges.

## 2. Person presentation DTO

Do not force the client to reconstruct identity truth from raw provider metadata.

Expose a bounded Person presentation for each Person shown, either by extending the People-workspace response or via a small dedicated detail structure keyed by Person id.

Include only safe grounded fields such as:
- person object id;
- display name/title;
- salience tier/score/components only if already safe for UI; prefer simple presentation over internal scoring detail;
- effective identities:
  - provider;
  - identity type;
  - display value;
  - realm only when useful/safe;
  - confirmation/conflict/rejected-effective state as needed;
- known concrete routes summarized display-safely where useful;
- identity conflict/ambiguity flag;
- counts of linked open Tasks / recent communications if cheap and bounded.

Never return provider secrets, encrypted references, raw session data, or unsafe provider metadata.

Phone number is NOT required in G1 unless an already-supported exact phone identity exists. Do not scrape phone numbers from message bodies/signatures in this task.

## 3. Search

In People mode, search must target canonical Person knowledge.

Prefer:
- Person title/display name;
- effective identity display values;
- exact known email/username-like identity values where appropriate.

Do not use fuzzy search to silently merge or mutate identities.

Search result click should re-root/select the canonical Person.

Bound search results and preserve user isolation.

## 4. Graph UI mode switch

In `GraphWorkspaceScreen`, add a compact two-way selector similar in spirit to Calendar `Сегодня | Неделя`:

`Задачи | Люди`

Requirements:
- default remains current Tasks mode unless product conventions clearly support persistence;
- switching modes loads the corresponding workspace;
- existing task graph behavior remains backward compatible;
- search/filter semantics adapt to the selected mode;
- selection/detail panel resets or safely maps when switching;
- fit-view and graph navigation remain functional.

Reuse existing graph layout/node/card primitives.

## 5. Person node card

People mode node cards should be visually distinct but not introduce a new complex design system.

Minimum:
- Person name/title;
- compact provider/contact indicators derived from effective identities;
- optional small salience/relevance cue only if it helps orientation and does not create a visible VIP ranking taxonomy;
- conflict indicator when identity evidence needs correction.

Do not put full contact lists on every node.

## 6. Person detail panel

Selecting a Person should show a clear grounded summary:

- name;
- known identities/contact endpoints grouped by provider;
- display-safe known routes;
- whether an identity is confirmed / conflicted / rejected-effective where relevant;
- linked open Tasks;
- bounded recent communications/evidence or a button/expansion to inspect them;
- `Спросить секретаря` remains available with Person object context.

The panel should make the system's understanding inspectable.

## 7. Identity correction in UI

G1 should provide only correction actions already supported safely by Graph Refined semantics.

At minimum, when existing backend operations can support it without inventing a second identity system:
- explicitly reject a mistaken Person+identity association;
- retract prior rejection/confirmation where supported;
- confirm an exposed candidate identity only when the existing Person evidence rules allow it.

If current Person feedback functions exist only inside Assistant ToolRunner and are not safely reusable from first-party UI, expose a narrow first-party API that delegates to the same `PersonEvidenceService` / `PersonIdentityService` invariants.

Requirements:
- no direct client mutation of `person_identities` rows;
- no auto-merge;
- no silent reassignment;
- conflicting owner/multiple confirmation remains explicit;
- operations are reversible/audited through existing evidence ledger;
- user must be shown the exact identity being corrected.

Do not implement drag-and-drop merging in G1.

## 8. Existing relations

Do not reinterpret generic existing edges as organizational truth.

People view may display already confirmed/user-created graph edges involving Person Objects, but labels must reflect their actual edge type.

Do NOT map generic `related_to` into claims such as colleague/manager/friend.

Do NOT create `member_of`, `role_at`, `manager_of`, or `works_with` automatically in G1.

Those remain future grounded relation work.

## 9. Actor/Task symmetry

Where an existing Person is linked to Tasks through actual graph edges, surface those Tasks in rooted/detail People view.

Do not infer Task participation merely from name mentions.

This prepares the UI for the central ontology:
- Person -> open commitments/tasks;
- Task -> participating Actors/evidence.

Do not redesign Task Graph in G1.

## 10. Boundedness and truthfulness

The People graph must remain useful at large scale:
- bounded overview;
- salience helps ordering/budget, never hard-access filtering;
- explicit truncation;
- search/rooted view can reach low-salience known People;
- do not materialize all public-channel authors;
- do not render a giant communication graph by default.

Prefer truthful incompleteness over guessed social structure.

## Focused proof

Add backend/client tests proving at minimum:

1. People workspace overview contains active Person Objects, not arbitrary message authors.
2. Rejected/deleted Person is excluded.
3. Overview ordering uses existing salience deterministically without making low-salience Person inaccessible.
4. Search finds Person by title and effective identity display value.
5. Rooted People workspace for a valid Person works; cross-user/non-Person root fails closed.
6. Person presentation exposes bounded effective identities and no secrets.
7. Explicitly rejected identity is not presented as effective.
8. Multiple-confirmation/conflict state is visible rather than silently resolved.
9. Existing linked open Task appears for that Person only when an actual graph relation exists.
10. No inferred manager/company/social edges are created.
11. UI shows `Задачи | Люди` and Tasks remains backward compatible.
12. Switching to People loads People workspace and resets incompatible selection safely.
13. Person node/card displays grounded compact identity/provider cues.
14. Person detail panel shows identities/routes/open Tasks.
15. Search in People mode re-roots/selects canonical Person.
16. Supported identity correction delegates to existing evidence invariants and is reversible.
17. Conflicting ownership still fails closed.
18. Existing Graph task workspace tests remain green.
19. Graph Refined Person tests remain green.
20. No new migration unless absolutely necessary.
21. No organization/job-title inference, LLM calls, provider lookup, media expansion, Task Refinement, or deployment.

Run focused People-workspace/API/client graph tests, existing Graph workspace tests, Graph Refined tests, Flutter analyze/tests for touched graph code, Ruff/compile for touched Python, and `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not begin organizational relation inference, Task Refinement, Mattermost/Teams media download adapters, or deploy.
