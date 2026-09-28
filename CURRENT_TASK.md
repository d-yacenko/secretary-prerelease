# Current task — PP1-H1: Mattermost self-author exclusion

## State

- People PP1 implementation under review: `d9437f6b8ece61e01865ae630dc0e9f196e87cc8`.
- Architect review found one blocking semantic defect in Mattermost promotion eligibility.
- Current `main` before this authorization: `0f970522c8ad7195fb76a56e3b928d2be3d00bc0`.
- Repository Alembic head remains `0051` (`person_promotion_feedback`).
- Production/runtime/origin-production remain `9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa`, production Alembic `0050`.
- Production was not deployed with PP1.

## Defect

PP1 currently treats a stored Mattermost `chat_message` with `channel_type=D` as a qualifying direct contact and extracts its `author_user_id`.

Mattermost history stores both remote and current-user-authored posts in a DM. The normalized Object metadata does not carry a reliable inbound/outbound direction field.

Therefore two current-user-authored DM posts can currently satisfy the PP1 repeated-direct-contact threshold and propose the user themself as a new Person.

The connected `MattermostAccount` already stores the authoritative same-user `remote_user_id`, and normalized message metadata stores `account_id`, `server_url`, `author_user_id`, and `channel_type`.

## Required correction

For Mattermost PP1 qualification, a stored row is a direct **remote** contact only when all of the following are proven from stored local facts:

1. `channel_type == "D"`;
2. `account_id` is present and valid;
3. `account_id` resolves to a `MattermostAccount` owned by the same Secretary user;
4. message `server_url` matches that account's stored server/realm;
5. `author_user_id` is present;
6. `author_user_id != MattermostAccount.remote_user_id`.

If any of those facts are missing, malformed, cross-user, or inconsistent, **fail closed** for that row: it contributes no promotion hit.

Do not infer direction from title/body/display name/channel naming.

Do not call Mattermost or any provider.

## Implementation constraints

- Keep PP1's existing 90-day / 400-row global scan and max-5 candidate behavior unchanged.
- Preserve exact identity normalization and candidate ranking.
- Preserve first-party Telegram quarantine behavior.
- Preserve email, Teams, and Telegram PP1 semantics.
- Preserve candidate read purity: no Object, PersonIdentity, evidence, feedback, edge, job, or provider write during reads.
- Preserve suppression/restore/approval semantics.
- Approval must revalidate through the corrected eligibility path, so a crafted approval request cannot promote the current user's own Mattermost identity.
- Do not add another migration. Repository Alembic head must remain `0051`.
- Prefer bounded same-user account lookup/preload; do not introduce unbounded per-message provider/account fan-out.

It is acceptable to move the Mattermost self/remote check from the pure domain helper into `PersonPromotionService` if account context is required. Do not weaken the fail-closed boundary merely to keep the old helper signature.

## Required regressions

At minimum prove:

1. two messages authored by the connected Mattermost account's own `remote_user_id` in a DM -> **no candidate**;
2. two messages authored by a different remote user in that same DM/account -> candidate;
3. mixed one own + one remote message -> remote identity has only one qualifying hit and is not a candidate;
4. missing `account_id` -> no candidate;
5. malformed/nonexistent `account_id` -> no candidate;
6. `account_id` belonging to another Secretary user -> no candidate;
7. message `server_url` inconsistent with the resolved same-user account -> no candidate;
8. Mattermost group/public channel remains non-qualifying;
9. repeated approval/candidate reads still create no duplicate/self Person;
10. existing email, Teams one-on-one, Telegram private, suppression/retract, approval, conflict, no-edges, 400-row truncation, and read-purity PP1 tests remain green.

Update the existing Mattermost positive PP1 fixture so it represents real stored connector facts: create a same-user `MattermostAccount`, use its actual `account_id`, set its own `remote_user_id`, and make the qualifying message author a different remote user.

## Verification

Run at minimum:

- focused `test_person_promotion.py`;
- Person identity/evidence/Assistant/People workspace suites used for PP1;
- relevant Mattermost normalization/materialization tests;
- migration-head check proving head still `0051`;
- relevant People Flutter tests if no client files change, and any touched client tests if they do;
- Ruff / formatting / `git diff --check`;
- Flutter analyze only if Dart changes.

If Graph suite is run, report baseline failures separately rather than attempting unrelated fixes.

## Build

Because this changes backend eligibility only, rebuild the Linux debug bundle **only if client source changes**. Otherwise retain the existing PP1 bundle path and explicitly state that no client rebuild was necessary; final human validation still requires the corrected backend to be available.

## Explicitly out of scope

- No production deploy.
- No schema/migration change beyond existing `0051`.
- No People UX expansion.
- No task-creation contextual prompt.
- No Person Knowledge / manager / colleague / family / client inference.
- No Organization ontology.
- No social graph.
- No Person<->Flow edges.
- No salience change.
- No Task relation change.
- No Assistant prompt/tool or MCP change.
- No provider/network/model call.
- No fixes for unrelated baseline test failures.

## Completion

1. Commit the narrow PP1-H1 implementation and regression tests.
2. Update `PROJECT_STATE.md` with exact behavior, tests, implementation SHA, and the fact that repository Alembic remains `0051` while production remains `0050`.
3. Return `CURRENT_TASK.md` to HOLD with PP1-H1 implementation SHA and human acceptance still pending.
4. Push implementation + HOLD to `main`.
5. Report exact SHA/test results/client-bundle status and STOP.

Do not deploy and do not begin the next People/Person Knowledge slice.
