# CURRENT_TASK

ACTIVE

## REL1D-HG1.4.1 — complete own-identity exclusion for role-import participants

REL1D-HG1.3 is ARCHITECT SOURCE-ACCEPTED at:

`556c1ed3fff6963404b00da4251f48f3d63a59d6`

REL1D-HG1.4 implementation:

`92f8ddf5b5898dd00ba4f5a244d067a1a30c4f50`

is **NOT YET SOURCE-ACCEPTED**.

Architect review found one narrow correctness/safety blocker in the new role-import participant path:

- Telegram MTProto self user id is excluded;
- Mattermost excludes `remote_user_id`, but the username fallback is not robustly excluded;
- Google/Gmail account email identities are not excluded;
- Yandex Mail account email identities are not excluded;
- Teams account `(tenant_id, microsoft_user_id)` self identity is not excluded.

Therefore an organization-chart row matching the user's own stored display name can incorrectly expose the user as a new-Person role-import promotion candidate.

This task is ONLY to complete the cross-provider own-identity exclusion and prove revalidation uses it.

Do not redesign HG1.4, do not change generic promotion semantics, do not deploy/install anything.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- `backend/app/domain/role_import_participants.py`
- `backend/app/services/person_promotion_service.py`
- relevant account models and focused HG1.4 tests.

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.

Production/backend/client remain:

`1879aabc97bfc5ed13fbc2ffa4d0c9c7ccbb3320`

Alembic remains `0054 / 0054`.

## Required behavior

The role-import-specific participant scan must exclude exact identities owned by the current Secretary user across all supported participant providers.

Prefer exact normalized self-identity tuples scoped by provider/realm rather than loose display-name or raw-string exclusion.

### Google / Gmail

For every active/current `GoogleAccount` belonging to the Secretary user:

- normalize its account `email`;
- exclude that exact email identity from role-import participant candidates whether it appears as sender/from, recipient/to, cc, or reply-to.

Do not exclude another participant merely because the display name equals the user's name.

### Yandex Mail

For every `YandexMailAccount` belonging to the Secretary user:

- normalize its account `email`;
- exclude that exact email identity from participant candidates in all email participant positions.

### Teams

For the user's `TeamsAccount`:

- exclude the exact normalized Teams identity represented by `tenant_id + microsoft_user_id`;
- use realm-aware comparison;
- do not globally exclude the same raw user id in another tenant.

### Mattermost

For every user-owned `MattermostAccount`:

- exclude the exact own `remote_user_id` identity on that normalized server realm;
- also exclude the exact own `username` identity on that normalized server realm when the author-id path is absent;
- do not globally exclude the same username/id on another Mattermost server.

### Telegram MTProto

Preserve the current self-user-id exclusion behavior.

If refactoring, keep it exact/account-scoped where appropriate.

## Important boundaries

Do not use display name itself as self-identity proof.

A different person with the same display name but a different exact provider identity must remain eligible.

Do not weaken or modify:

- `MIN_DIRECT_HITS`;
- `overview()`;
- `eligible_direct_contacts()`;
- generic `approve()`;
- HG1.4 one-hit role-import participant rule for non-self identities;
- suppression/owned-Person checks;
- body-text exclusion;
- exact display-name matching;
- existing-Person HG1.2 communication gate;
- ActionPlan privacy/redaction.

No provider calls.

No schema/migration/dependency change.

## Approval revalidation

`approve_role_import_participant()` must re-run the same self-identity-aware participant eligibility.

Required stale behavior:

- if a participant was valid at prepare time but becomes a known self identity before approve, approval must fail closed with the existing `role_import_grounding_changed` behavior;
- no Person, identity, role term/assignment, or partial durable write may occur.

Do not special-case around the normal ActionPlan execution/serialization contract.

## Required tests

Add focused backend coverage at minimum:

1. Google/Gmail own account email as recipient with matching display name => no role-import participant candidate.
2. Google/Gmail own account email as sender with matching display name => no candidate.
3. Yandex own account email => no candidate.
4. Teams sender exact own `tenant_id + microsoft_user_id` => no candidate.
5. same Teams raw user id in a different tenant is not falsely excluded.
6. Mattermost own `remote_user_id` => no candidate.
7. Mattermost own username fallback => no candidate.
8. same Mattermost username/id on another server is not falsely excluded.
9. Telegram own-id exclusion remains green.
10. a non-self participant sharing the user's display name but with a different exact identity remains eligible.
11. ordinary non-self email/Teams/Mattermost participant HG1.4 candidates remain eligible.
12. candidate prepared, then exact identity becomes self-owned through the corresponding account record before approve => ActionPlan fails with grounding-changed semantics and creates no Person/role assignment.
13. generic promotion threshold/approve tests remain unchanged and green.

Run at minimum:

- `backend/tests/test_rel1d_role_import_participants.py`
- `backend/tests/test_rel1d_role_import_grounding.py`
- `backend/tests/test_rel1d_role_import_batch.py`
- directly affected generic promotion tests
- Ruff on touched Python
- `git diff --check`.

Client changes should not be necessary. If no client file is touched, do not run or edit client code merely for this corrective.

## Explicit non-goals

Do not:

- broaden participant evidence;
- add body-name matching;
- add fuzzy/LLM matching;
- change role-import UI/scroll behavior;
- change extraction;
- change generic People promotion;
- add migrations/schema;
- change dependencies;
- deploy backend;
- move `production`;
- build/install client;
- make real model/provider calls;
- mutate production product data.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG1.4.1` entry to `PROJECT_STATE.md` with:
   - implementation SHA;
   - files changed;
   - exact self-identity sources/gates;
   - stale approve behavior;
   - exact test totals;
   - Ruff/diff-check results;
   - confirmation generic promotion/HG1.4 non-self semantics unchanged;
   - confirmation no deploy/install/migration/model/provider/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG1.4.1 implementation SHA;
   - HG1.3 + HG1.4 + HG1.4.1 are ready for Architect review;
   - production/backend/client remain `1879aabc97bfc5ed13fbc2ffa4d0c9c7ccbb3320`;
   - Alembic remains `0054 / 0054`;
   - human acceptance remains paused;
   - do not rollout or start another slice.

3. commit + push to `main`.

4. STOP.

On blocker, record the exact bounded blocker, return HOLD, commit/push accurate ledger if appropriate, and STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
