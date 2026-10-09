# CURRENT_TASK

HOLD

## REL1D-HG4D — COMPLETE

### Result

Schema-neutral production rollout for accepted People fixes (HG4B/HG4C) succeeded through the committed deploy harness.

Release SHA / production runtime:

`a9221699b4b725888213ff38e6673495a512042c`

Rollback SHA:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Expected Alembic:

`0054`

### Ref movement

Canonical GitHub `production` was non-force fast-forwarded:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6` → `a9221699b4b725888213ff38e6673495a512042c`

Preflight confirmed empty Alembic infrastructure delta and release on `origin/main`.

### Deploy harness

Command:

```bash
python3 ops/production/deploy.py \
  --release-sha a9221699b4b725888213ff38e6673495a512042c \
  --rollback-sha f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6 \
  --expected-alembic 0054
```

Result:

- `DEPLOYMENT=PASS`
- `RELEASE_HEAD=a9221699b4b725888213ff38e6673495a512042c`
- `HEALTH=PASS`
- `ALEMBIC=0054`
- `DB_CONTAINER_UNCHANGED=true`
- `DB_VOLUME_UNCHANGED=true`
- `ENV_FILE_UNCHANGED=true`
- `API_RECREATED=true`
- `WORKER_RECREATED=true`
- application rollback unused
- exit 0

### Post-deploy read-only verification

- runtime HEAD = release SHA
- `origin/production` = release SHA
- health OK
- Alembic `0054 (head)`
- OpenAPI `GET /graph/people-workspace` exposes optional query parameter `window_index`

### Boundaries

No product code/schema change, provider/model call, client install, Person rename investigation, or second deploy attempt.

No next coding/deploy phase is authorized by this HOLD.
