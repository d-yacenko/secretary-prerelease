# Current task — ACTIVE

## REL1A.2.1 — bind role autocomplete truth to the current query

REL1A.2 implementation `5b2e19c8f386225c262be4b3a551096f0427d6fc` is directionally accepted, but NOT yet Architect source-accepted because one narrow client truth gap remains in the reuse-first role dialog.

Do only this corrective.

Do not deploy production, migrate production, install the client, or start REL1B/REL1C/REL1D.

## Verified baseline

- main before this authorization: `f17c69aacab2c30b2261f0ab38ec0a2da2e47588`
- REL1A: `e7f1e79dd83e3007bc97a6dff7aa1bd083128d93`
- REL1A.1: `9de2cccd218b76c04e98049b7bcc86c36a4058fe`
- REL1A.2: `5b2e19c8f386225c262be4b3a551096f0427d6fc`
- Alembic head: `0054`
- production backend/source: `2314bf72101fbd83d50a7b264154d73740e28db1`
- production Alembic: `0052 / 0052`
- installed Linux client source: `2314bf72101fbd83d50a7b264154d73740e28db1`

REL1A.2 backend/schema work is accepted in direction:

- `0054` widens canonical case-fold keys to 360/600 without rewriting `0053`;
- display bounds remain 120/200;
- full Unicode `casefold()` remains canonical;
- overlong canonical keys fail before persistence;
- search returns server-authoritative `exact_match_term_id`;
- exact matching is independent of bounded suggestion-page inclusion;
- stale completed older responses are fenced by generation.

Do not change those semantics.

## Verified remaining defect

Current Flutter `_AddPersonRoleDialogState._load` increments a generation and ignores an older response after it completes, but it leaves the previous query's:

- `_terms`;
- `_exactMatchTermId`;

in visible state until the new request completes.

The parent dialog also does not synchronously bind the displayed create/reuse truth to the newly typed query before awaiting the server.

Therefore during an in-flight search for query B, the UI can still expose truth from query A.

Examples:

1. query A had no exact match and exposed `Создать роль …`;
2. user types query B which is actually an exact existing RoleTerm;
3. before B's server response arrives, the prior create affordance/truth can remain visible.

Or conversely, a previous exact match can temporarily suppress create for a genuinely new current query.

The backend remains safe and assignment is idempotent, so this is not durable-data corruption. It is a first-party truth/UX defect: the accepted contract says create-new is shown only when the server has reported no exact match for the CURRENT typed query.

Old suggestions are likewise not authoritative suggestions for the new current query while its search is pending.

## Required correction

Make autocomplete state explicitly query-bound.

Preferred behavior:

1. On every role-input change, synchronously invalidate the previous query's server-derived state before awaiting the next request.
2. While the current non-empty query is awaiting its server response:
   - do not show `Создать роль «…»`;
   - do not present prior-query RoleTerm suggestions as if they belonged to the current query.
3. When the response for the current generation/query arrives:
   - publish its `terms`;
   - publish its `exact_match_term_id`;
   - allow create-new only when:
     - current collapsed input is non-empty;
     - the current query has a completed authoritative server result;
     - that result has `exact_match_term_id == null`.
4. An older response must never publish terms OR exact-match state after a newer input exists.
5. Empty query behavior may continue to show the bounded reusable vocabulary page after its own response, but must still be query-bound.
6. A failed current search must not fall back to previous-query suggestions or previous-query exact-match truth. Preserve existing error conventions; do not invent a new global error system.

Implementation may use a generation/token plus explicit loading/resolved-query state. Keep it local and simple.

Do not implement Unicode case-folding in Dart. Server remains the lexical-identity authority.

## Required deterministic tests

Extend focused Flutter tests to prove at least:

1. **new query invalidates old non-exact truth immediately**
   - query A completes with `exact_match_term_id = null` and create-new visible;
   - query B is entered and its response is deliberately held;
   - while B is pending, create-new is NOT visible;
   - after B returns exact match, create-new remains absent.

2. **new query invalidates old exact truth immediately**
   - query A completes as exact;
   - query B is entered and held;
   - while B is pending, create-new is NOT shown merely from guessed client state;
   - after B returns non-exact, create-new appears.

3. **old suggestions are not current-query suggestions**
   - query A returns one or more terms;
   - query B is entered and held;
   - A's suggestions are absent while B is pending;
   - B's terms appear only after B completes.

4. **out-of-order response fence remains**
   - A request is slower than B;
   - B completes and publishes its truth;
   - A completes later;
   - neither terms nor exact-match/create state regress to A.

5. Existing role flows stay green:
   - suggestion selection;
   - exact-match suppresses create;
   - new role create;
   - optional context;
   - retract;
   - multiple-role rendering.

## Required checks

Client:

- `client/test/graph/person_roles_section_test.dart`;
- affected People overview/create tests;
- focused `flutter analyze` on changed files;
- `flutter build linux --debug`.

Backend/schema:

- no backend/schema change is expected.
- Re-run the focused REL1A backend set only if any shared API/model source is unexpectedly touched.

Also:

- `git diff --check`.

Record exact pass/fail counts.

## Explicit non-goals

Do not:

- change Alembic `0054`;
- add `0055`;
- change RoleTerm normalization;
- change role search semantics or API response shape;
- change assignment/retract/consolidation semantics;
- redesign People UI;
- add debounce unless strictly needed for correctness;
- change Personal Relevance or Proactive;
- add Assistant role tools;
- add screenshot/document import;
- add Organization;
- change Scheduled Activity;
- deploy/migrate production;
- install/replace the user's client;
- call a real model/provider.

## Completion protocol

After implementation:

1. append a compact REL1A.2.1 result to `PROJECT_STATE.md`;
2. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - exact client state semantics;
   - exact test/build evidence;
   - confirmation Alembic head remains `0054`;
   - confirmation backend/schema semantics are unchanged unless explicitly required by the fix;
   - production still `2314bf72101fbd83d50a7b264154d73740e28db1`, Alembic `0052 / 0052`;
   - installed client unchanged;
   - no deploy/migration/model/provider action;
3. commit + push to `main`;
4. STOP.

Do not start rollout or REL1B/REL1C/REL1D from HOLD.
