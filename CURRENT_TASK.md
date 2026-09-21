# Current task — Telegram MTProto M4AW2: build/review read-only Inbox eligibility probe

## Status

M4AV1 is deployed in production at:
`2db36510fe884eadc40d63fed8661ed3627f1cbb`

M4AW1 human UI verification loaded the normal Inbox but showed no Telegram items in the visible feed snapshot.

Known pre-existing state:
- one manual-selected Telegram group;
- `manual_selected=true`;
- `scope_active=false`;
- history complete;
- 228 persisted MTProto objects.

The deployed ordinary transport visibility semantics are:
`manual_selected=true OR scope_active=true`.

The Inbox applies additional filters and ordering beyond transport visibility, including source eligibility, rejected/deleted/status filters, outbound-chat suppression, and paginated feed ordering by `feed_at`.

## Goal

BUILD / REVIEW ONLY.

Create a zero-provider, read-only human-shell production probe that explains where the 228 imported MTProto objects are lost between persistence and the visible Inbox page.

Do NOT run it live in this task.

## Executor workspace

Work only from:
`~/work/secretary-executor`

Canonical origin:
`https://github.com/d-yacenko/secretary-prerelease.git`

Bootstrap:
```bash
git fetch origin
git switch main
git pull --ff-only
git remote get-url origin
git rev-parse HEAD
git status --short
```

Require canonical origin, current `origin/main`, clean worktree.

Read:
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `AGENTS.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `backend/app/domain/telegram_mtproto_visibility.py`
- `backend/app/services/recent_source_service.py`
- `backend/app/api/inbox.py`
- `backend/app/db/models.py`
- existing `manual_mtproto_visibility_state*` probe files for trust/protocol patterns.

## New artifact

Create a new read-only human-shell probe under `ops/production/`, e.g.:

`manual_mtproto_inbox_eligibility_probe.sh`

A Python helper/protocol validator plus focused tests are allowed.

## Future live production guards

Pin and verify:
- canonical target.json;
- exact SSH host-key fingerprint;
- production HEAD exact `2db36510fe884eadc40d63fed8661ed3627f1cbb`;
- `origin/production` exact same SHA;
- clean production worktree;
- Compose/db/api/worker running;
- DB healthy;
- Alembic exact `0046`.

Use the accepted production DB credential/host Alembic check contract and isolated stdin.

## Read-only diagnostic stages

Inside the running API container, with `SessionLocal(autoflush=False)`, no flush/commit/write:

1. Require exactly one MTProto account and one `manual_selected=true` selection.
2. For that exact account+peer, count:
   - `IMPORTED_OBJECT_COUNT`: canonical Telegram MTProto chat_message objects;
   - `TRANSPORT_VISIBLE_COUNT`: same exact objects passing `telegram_mtproto_active_object_predicate()`;
   - `INBOUND_COUNT`: metadata direction != outbound (use Inbox semantics carefully; missing direction should be treated as not-outbound exactly as canonical filter does);
   - `OUTBOUND_COUNT`: metadata direction == outbound;
   - `INBOX_ELIGIBLE_COUNT`: exact objects satisfying the canonical `RecentSourceService` Inbox eligibility semantics.
3. Inspect current Inbox first page using the same `RecentSourceService.list_page(limit=30)` semantics and report only aggregates:
   - `FIRST_PAGE_TOTAL_COUNT`
   - `FIRST_PAGE_TELEGRAM_COUNT`
4. If Telegram exists but is not on first page, compute a safe bounded placement indicator without printing IDs/content:
   - `TELEGRAM_VISIBLE_WITHIN_FIRST_50=true|false` using `list_page(limit=50)`;
   - optionally a bounded ordinal/rank of newest Inbox-eligible Telegram item if it can be computed without identifiers/content.
5. Report whether any exact imported Telegram object is individually `get_inbox_eligible`-eligible, as a count only.
6. No message text/title/sender/group/account/message IDs or exact provider references.

Do NOT enqueue conversation summaries or any writes. If calling API-layer grouping would enqueue work, do not call it. Use only RecentSourceService read eligibility/page semantics.

## Safe output

Allowed:
- production guard booleans;
- `ACCOUNT_EXACTLY_ONE`
- `MANUAL_SELECTED_EXACTLY_ONE`
- `MANUAL_SELECTED`
- `SCOPE_ACTIVE`
- `HISTORY_COMPLETE`
- `IMPORTED_OBJECT_COUNT`
- `TRANSPORT_VISIBLE_COUNT`
- `INBOUND_COUNT`
- `OUTBOUND_COUNT`
- `INBOX_ELIGIBLE_COUNT`
- `FIRST_PAGE_TOTAL_COUNT`
- `FIRST_PAGE_TELEGRAM_COUNT`
- `FIRST_50_TELEGRAM_COUNT` or equivalent
- optional bounded ordinal/rank
- `TELEGRAM_NETWORK_CALLS=0`
- allowlisted failure stage/class
- terminal marker.

Never print:
- IDs;
- message content/title;
- sender/group names;
- exact timestamps;
- session/reference/access hashes;
- DB credentials;
- raw SQL rows;
- traceback/raw stderr.

## Strictly forbidden

Do NOT:
- construct TelegramClient;
- connect to Telegram/provider;
- Sync;
- Apply Scope;
- login/re-login;
- change selections/folders;
- write/flush/commit DB;
- enqueue jobs/summaries;
- materialize/upsert;
- restart/recreate;
- migrate;
- edit production;
- enable AI;
- change Bot API.

## Interpretation contract

- `TRANSPORT_VISIBLE_COUNT=0` with imported > 0 => deployed visibility semantics are not effective at runtime; STOP.
- transport visible > 0 and `INBOX_ELIGIBLE_COUNT=0` => isolate which canonical Inbox filter removes them (especially outbound/status/state/origin) using additional safe aggregate breakdown in the same probe if possible.
- inbox eligible > 0 and first-page Telegram count = 0 => not a visibility defect; items are simply ordered below the first page. Report first-50 count/rank and STOP.
- first-page Telegram count > 0 but UI still shows none => backend feed contains them; next phase is client presentation/merge diagnosis, not Sync.

## Local tests/review

At minimum:
- valid transport-visible + first-page-positive transcript;
- valid inbox-eligible but first-page-zero transcript;
- transport-visible-zero fail/diagnostic transcript;
- outbound-only scenario;
- zero-import scenario;
- premature EOF;
- unsafe/unknown output fail closed;
- no provider calls;
- no DB write/flush/commit;
- no summary/job enqueue path;
- Alembic credential/host + stdin isolation regression;
- bash -n;
- helper compile;
- Ruff;
- diff-check.

## Deliverable

If PASS:
- commit/push canonical main;
- update `PROJECT_STATE.md`;
- do NOT run live probe.

Report:
- commit SHA;
- files changed;
- test counts/results;
- lint/diff-check;
- production SSH=0;
- Telegram/provider calls=0;
- production mutation=0.

Final marker:
`TELEGRAM_MTPROTO_M4AW2_INBOX_PROBE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
