# CURRENT_TASK

HOLD

## REL1D-HG6C — read-only diagnosis of role-authoring degradation after progressive hydration

### Status

Diagnostic complete. No product-code change, production mutation, deploy, service restart, or corrective is included.

Primary classification: `CLIENT_CONCURRENCY_SUPPORTED`.

Secondary findings:

- role-term search failures hide the API detail and suppress both suggestions and the explicit create action;
- assign/retract failures show only `Не удалось обновить роль`;
- rooted Person hydration starts one heavy GET per selection and does not cancel or serialize those requests.

### Local client concurrency

Uncommitted scratch widget harness, deleted before this ledger commit. Eight distinct overview People. Each rooted `GET /graph/people-workspace?root_id=` stayed gated.

- rooted GETs started: 8
- peak simultaneous unresolved rooted GETs: 8
- completed while gates were held: 0
- selection-token logic did not stop the requests; it only gates later response application
- after all gates were released: in-flight rooted GETs returned to 0, completed 8

Role-term search forced to HTTP 500: suggestions absent, create action absent, response detail not visible, generic role message not shown.

Role assign forced to HTTP 500: only `Не удалось обновить роль` is visible; response detail is not visible. Retract uses the same generic client string and discards the exception.

### Production identity

Pinned public-key-only SSH no-op succeeded. One read-only diagnostic, plus a follow-up read-only correction of the two `pg_stat_activity` aggregates whose first SQL `GROUP BY` position was invalid.

- runtime HEAD: `0031f531d1215970093bea7add44fcd2259ec71b`
- runtime `origin/production`: `0031f531d1215970093bea7add44fcd2259ec71b`
- GitHub `production` checked before SSH: the same SHA
- API health: `{"status":"ok"}`
- Alembic: `0054 (head)`

### Production API logs, last 2 hours

API log lines scanned: 6361. Route timing fields are absent.

- `GET /graph/people-workspace`: 200 × 12, 500 × 7
- `GET /graph/person-role-terms`: 200 × 8, 500 × 12
- `POST /graph/people/*/roles`: 200 × 7
- `DELETE /graph/people/*/roles/*`: 200 × 3, 500 × 3

Error-class word hits in that window: `sqlalchemy` 588, `TimeoutError` 84, `QueuePool` 42. Paired trace class/location: `sqlalchemy.exc.TimeoutError` at `httptools_impl.py:422` × 41.

### Role-cap aggregates

One user, so these totals are that user. No identifiers or role text were selected.

- active PersonRoleAssignment rows: 14
- PersonRoleTerm rows: 7
- maximum active assignments on one active Person: 2
- active People at `MAX_ACTIVE_ASSIGNMENTS=16`: 0

### DB activity at diagnostic time

`pg_stat_activity` for the application database:

- `idle` / `Client` / `ClientRead`: 8
- `idle in transaction` / `Client` / `ClientRead`: 2
- `active` / no wait event: 1

Transaction-age buckets: `<5s` × 3, no open transaction × 8, `5–30s` × 0, `>30s` × 0.

### Runtime snapshot

Compose services `api` and `db` only. No restart.

- API: running, up 20 hours; CPU 1.38%; memory 466.7MiB / 3.819GiB
- DB: up 6 weeks, healthy; CPU 1.16%; memory 620.5MiB / 3.819GiB

### Check categories

- local Flutter widget harness with gated mock rooted GETs and forced role HTTP 500 paths; scratch file not committed
- pinned host-key compare, then public-key-only SSH no-op
- read-only remote: `git rev-parse`, API health, `alembic current`, Compose API logs for 2 hours, Compose `ps` for `api`/`db`, one `docker stats --no-stream`, aggregate SQL counts, `pg_stat_activity` group counts

### Stop

Do not start a corrective from this HOLD.
