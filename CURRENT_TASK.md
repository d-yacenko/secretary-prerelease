# Current task — Release P1-R1: deploy compact ontology kernel to production

Assistant P1 is architect-accepted.

This task authorizes ONE schema-neutral production backend rollout and its documentation only.

## Exact authorized refs

Release SHA:
`7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4`

Rollback SHA / current production runtime:
`489741540e30a775e2ea086f3976d7305512afe2`

Expected Alembic:
`0050`

Before task authorization:
- `main = 7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4`;
- `origin/production = 489741540e30a775e2ea086f3976d7305512afe2`.

The release is a fast-forward descendant of rollback.
There are no changes under `backend/alembic/` between rollback and release.

Relative to rollback, the only backend application product change is Assistant P1 in:
`backend/app/llm/openai_assistant_provider.py`

The release history also contains already accepted client-only Graph changes and docs/encrypted architect context. This rollout MUST NOT install or replace any client. The production harness builds/recreates only `api` and `worker`.

## Product being rolled out

The production Secretary system prompt must now include exactly:

`Core ontology: Person=who; Task=commitment/Direction; Flow=evidence/context; Time=when. Relations are explicit facts, never inferred.`

It is already tested and architect-accepted at P1.

Do not modify the prompt during rollout.
Do not add the actor-role reminder.
Do not change tools, schemas, MCP, People ontology, relation semantics, or client code.

## Mandatory bootstrap

Follow `AGENTS.md` and `docs/executor_bootstrap.md`.

Use only the canonical repository:
`https://github.com/d-yacenko/secretary-prerelease.git`

Use a clean canonical `main` checkout. If the current checkout is dirty, wrong-origin, or ambiguous, leave it untouched and use a fresh temporary clone.

Fetch and verify the exact authorized refs.

Before any production ref move or SSH:
- verify current `origin/production` is exactly rollback SHA;
- verify release SHA resolves and is an ancestor-descendant fast-forward from rollback;
- verify no migration infrastructure differs between rollback and release;
- verify the P1 prompt sentence is present exactly once in release;
- run `git diff --check` for the release delta if needed.

If any exact ref/invariant is wrong, STOP. Do not improvise a replacement SHA.

## Production ref authorization

This task explicitly authorizes a NON-FORCED fast-forward of:

`origin/production`

from:

`489741540e30a775e2ea086f3976d7305512afe2`

to:

`7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4`

Do not force-push.
Do not move any other branch/tag.

After the push, fetch and verify `origin/production` equals the exact release SHA.

Do not move `origin/production` to the later task/HOLD documentation commit.

## Mandatory deployment mechanism

Read `docs/deploy.md` and the named `ops/production/` files.

Normal rollout MUST use only:

```bash
RELEASE_SHA=7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4
ROLLBACK_SHA=489741540e30a775e2ea086f3976d7305512afe2
EXPECTED_ALEMBIC=0050

python3 ops/production/deploy.py \
  --release-sha "$RELEASE_SHA" \
  --rollback-sha "$ROLLBACK_SHA" \
  --expected-alembic "$EXPECTED_ALEMBIC"
```

Direct SSH, direct Docker, direct Compose, remote shell repair, host discovery, alternate hosts, alternate repository paths, and break-glass actions are NOT authorized.

Do not edit the deployment harness.

If target/fingerprint/SSH/preflight/harness fails, report the sanitized fail-closed marker and STOP.
Do not repair production configuration in this task.

## Required successful rollout invariants

A successful rollout must report/prove through the harness:

- `RELEASE_HEAD=7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4`;
- `HEALTH=PASS`;
- `ALEMBIC=0050`;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- `api` recreated;
- `worker` recreated;
- `DEPLOYMENT=PASS`.

No DB migration is expected or authorized.

Do not recreate `db`.
Do not change the DB volume.
Do not rotate credentials.
Do not change `.env`.
Do not create production test data.

## Assistant verification boundary

Do NOT perform a live production Assistant/LLM conversation merely to prove the prompt change.

Reason: exact release identity + api/worker recreation is sufficient for this rollout, while a live Assistant call would add provider cost and could touch production user context.

Do not inspect production user conversations, messages, emails, tasks, graph objects, or AI traces.

Health and exact runtime SHA are the production gate here.

## Rollback behavior

The committed harness owns automatic rollback behavior after recreate.

If the harness fails after recreate:
- report whether automatic rollback was attempted and whether it passed;
- do not manually retry, patch, SSH, or alter data;
- STOP.

If the harness blocks before recreate:
- report the exact sanitized blocker;
- STOP.

Do not force-reset production refs as an ad-hoc response. Any recovery beyond the harness requires a new Architect task.

## No client rollout

Do NOT:

- build a new client for this task;
- install/replace the user client;
- change saved API URL/preferences/secure storage/token;
- deploy G3A-R2 as a desktop package.

The previously human-accepted G3A-R2 client remains separate from this backend rollout.

## Explicitly forbidden next work

Do NOT start:
- `Скрыть связи`;
- G3B;
- S3;
- H2D;
- MCP parity work;
- People/organization ontology design;
- actor-role prompt additions.

Do not fix unrelated baseline test failures.

## Completion

On SUCCESS:

1. update `PROJECT_STATE.md` with:
   - exact release and rollback SHAs;
   - exact `origin/production` SHA after rollout;
   - exact production runtime SHA;
   - Alembic revision;
   - harness result;
   - health result;
   - DB container/volume/.env preservation;
   - api/worker recreation;
   - confirmation that no migration/client install/production test data/live Assistant call occurred;
   - note that P1 ontology kernel is now live in production by exact release identity;
2. return `CURRENT_TASK.md` to HOLD;
3. push only completion documentation to `main`;
4. leave `origin/production` pinned to the exact release SHA;
5. STOP.

Final report must state:

- SUCCESS or BLOCKED/FAILED;
- release SHA;
- rollback SHA;
- final `origin/production` SHA;
- final production runtime SHA;
- Alembic;
- `DEPLOYMENT` result;
- health result;
- DB container/volume/.env result;
- api/worker recreation result;
- whether rollback was needed;
- whether production user data was touched;
- whether any live Assistant/LLM call was made;
- HOLD/main SHA.

Then STOP. Do not start another task.
