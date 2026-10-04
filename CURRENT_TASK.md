# CURRENT_TASK

ACTIVE

## REL1D-HG2B1 — Mattermost human author display normalization

REL1D-HG2A / HG2A.1 are ARCHITECT SOURCE-ACCEPTED.

Production/backend/client remain:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Alembic remains:

`0054 / 0054`

Human REL1D acceptance remains paused.

D3 proved a current Mattermost source-contract defect:

- 2526 Mattermost communication rows in the 90-day audit had stable `author_user_id` and `author_username`;
- zero had a usable human `author_display_name`;
- therefore current `participant_identities(...)` emitted zero Mattermost participant identities.

Source inspection shows:

- Mattermost sync already resolves author profiles in batches with `get_users_by_ids(...)`;
- `normalize_mattermost_post(...)` currently stores only profile `display_name` into `author_display_name`;
- when that field is empty, title falls back to technical `username`;
- current normalization does not derive a human full name from profile `first_name` + `last_name`.

This task is ONLY the Mattermost source normalization corrective.

Do not backfill or resync production history in this task.
Do not deploy/install anything.
Do not change role-import matching semantics.

## Architectural goal

When Mattermost already returns a user profile with a stable author id and real human name fields, preserve a safe human author label in stored message metadata so downstream identity parsing can use:

- stable identity: Mattermost server realm + author user id;
- human display: provider-supplied human name.

Do not invent or semantically transform names.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `backend/app/connectors/mattermost/normalize.py`
- `backend/app/connectors/mattermost/sync.py`
- `backend/app/connectors/mattermost/materialize.py`
- `backend/app/connectors/mattermost/transport.py`
- `backend/app/domain/role_import_participants.py`
- `backend/tests/test_phase_27b_mattermost.py`
- `backend/tests/test_phase_28c_b2c3b_mattermost_history_runtime.py`
- `backend/tests/test_rel1d_role_import_participants.py`

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.

Do not move `production`.

## Required human-display derivation

Add one small helper in the Mattermost normalization layer, e.g.:

`_author_human_display(author)`

Exact naming is flexible.

The helper must use only fields already present in the Mattermost user profile returned by the current transport.

Required precedence:

1. a non-empty explicit profile `display_name`, if it is not merely the same normalized text as `username`;
2. otherwise, a collapsed full name built from non-empty `first_name` **and** non-empty `last_name`, in provider order:
   `first_name + " " + last_name`;
3. otherwise no human display.

Do **not** derive `author_display_name` from:

- username;
- nickname;
- email;
- email local-part;
- user id;
- message text;
- channel name;
- team name.

Do not transliterate.
Do not reverse first/last name order.
Do not apply PER1 variants.
Do not fuzzy-match.

Whitespace handling:

- trim outer whitespace;
- collapse internal Unicode whitespace;
- preserve provider casing/content otherwise;
- bound the stored result to an existing reasonable Mattermost text limit, preferably `MAX_TITLE_CHARS`, without adding a schema change.

If explicit `display_name` equals `username` after collapse/casefold, treat it as non-human and continue to full-name fallback.

If only first name or only last name exists, do not synthesize a strong human display.

## Required normalization behavior

`normalize_mattermost_post(...)` must continue storing:

- `author_user_id`;
- `author_username`;

and now set:

- `author_display_name`

when the helper returns a human display.

Do not store new raw profile fields such as:

- `author_first_name`;
- `author_last_name`;
- profile email;

unless a directly required existing contract forces it. No such expansion is expected.

Keep the existing metadata schema JSON-only; no DB migration.

## Title behavior

Use the same derived human display for Mattermost Object title presentation when available.

Required title label precedence:

1. human display from the helper;
2. username fallback;
3. generic `Mattermost` fallback.

Important distinction:

- username may remain a presentation fallback in title;
- username alone must **not** populate `author_display_name`.

This keeps technical handles visible when nothing better exists without pretending they are a human full name.

## Participant parser behavior

Do not change the Mattermost identity-key contract in `participant_identities(...)`.

It should continue to prefer:

- `author_user_id` + server realm

and use `author_username` only as the existing fallback when user id is absent.

The task should make future/refreshed normalized rows satisfy the parser by supplying a real `author_display_name`.

Do not introduce transliteration or alternate-name matching in the parser.

## Existing-row refresh readiness

No production refresh/backfill is authorized now.

However, prove in tests that reprocessing an already stored Mattermost post with newly available human profile fields:

- updates the same Object by external id;
- does not create a duplicate Object;
- adds/updates `author_display_name`;
- updates title consistently;
- preserves author_user_id / server/account provenance;
- makes the refreshed Object eligible for the current Mattermost participant parser when stable id + human display are present.

It is acceptable that a title change causes the existing materializer to classify the Object as semantically updated and enqueue its normal embed job.

Do not change materializer update rules solely to avoid that.

## Required tests

Add focused tests proving at minimum:

1. explicit non-technical `display_name` remains the human display;
2. empty/missing `display_name` + first_name + last_name => collapsed full human display;
3. explicit `display_name` equal to username falls through to first+last;
4. username-only profile => `author_username` stored, `author_display_name` absent;
5. first-name-only profile => no synthesized `author_display_name`;
6. last-name-only profile => no synthesized `author_display_name`;
7. nickname-only profile => no synthesized `author_display_name`;
8. full name whitespace is collapsed;
9. title uses human display when available;
10. title still uses username as presentation fallback when human display is absent;
11. role-import `participant_identities(...)` emits a Mattermost identity when normalized row has:
    - server realm,
    - author_user_id,
    - derived human display;
12. parser does not emit a participant from username-only normalized row;
13. self-identity filtering remains exact realm/id/username behavior;
14. reprocessing same external post with enriched first+last updates one existing Object rather than duplicating it;
15. refreshed Object becomes participant-identity-ready;
16. batch author resolution remains one `get_users_by_ids` call per resolved batch as before;
17. no provider/model call occurs outside fake test transport.

Run at minimum:

- directly affected Mattermost normalization/sync tests in `backend/tests/test_phase_27b_mattermost.py`;
- directly affected Mattermost history/runtime tests if materializer behavior is touched;
- `backend/tests/test_rel1d_role_import_participants.py`;
- HG2A scan-window tests to prove connector change does not alter scan semantics;
- Ruff on touched Python;
- `git diff --check`.

If existing focused tests already cover some requirements, extend them rather than duplicating large fixtures.

## Explicit non-goals

Do not:

- perform production Mattermost sync;
- perform history backfill;
- repair the 2526 legacy rows;
- call live Mattermost;
- change Mattermost credentials/account model;
- change server realm normalization;
- change generic Person promotion;
- change role-import exact-name matching;
- add transliteration;
- reorder first/last names;
- use nickname as strong human display;
- fix Teams;
- fix Gmail/Yandex;
- fix Telegram;
- change the 10,000 role-import scan ceiling;
- add schema/migrations;
- change dependencies;
- deploy backend;
- build/install client;
- mutate production product data;
- start another slice.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG2B1` entry to `PROJECT_STATE.md` including:
   - implementation SHA;
   - changed files;
   - exact human-display precedence;
   - confirmation username is not promoted into `author_display_name`;
   - confirmation stable Mattermost identity contract unchanged;
   - existing-row refresh-readiness behavior;
   - exact focused test totals;
   - Ruff/diff-check result;
   - explicit no backfill/sync/deploy/install/migration/provider/model/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2B1 implementation SHA;
   - source ready for Architect review;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - no production refresh/backfill or next connector task without fresh Architect authorization.

3. commit + push to `main`.

4. STOP.

On blocker:

- record exact bounded blocker;
- return HOLD;
- do not broaden into parser heuristics or live provider work;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
