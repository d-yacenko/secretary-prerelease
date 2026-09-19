# Current task — Telegram MTProto M4ADH4R3: one approved live diagnostic run

## Status

M4ADH4 corrective diagnostic harness is REVIEW ACCEPTED for one live read-only run.

Approved branch:
`review/production-ssh-m4adh4`

Approved exact harness SHA:
`ec4f51be6882433210d62ec6dbcfcdb19563be83`

Base implementation:
`a17925e5c0d38c4da79fca9c013d208052827fd6`

Focused tests reported:
`11 passed`

Ruff:
PASS

`git diff --check`:
PASS

Architect review confirmed:
- invalid failure-category SQL fixed;
- recurring provider-call inference now follows exact release semantics;
- actual manual group sync route is distinguished from scope-peer sync;
- positive and negative peer IDs are normalized to `<peer>`;
- both Docker log stdout and stderr are inspected in memory;
- raw log lines are not emitted;
- transport retry/auth/remote-start behavior remains fail-closed;
- origin review branch resolves exactly to approved corrective SHA.

This acceptance is only for the diagnostic harness. It is NOT a merge/integration acceptance for main or production code.

## Existing live evidence

Previous partial M4ADH4 run established:
- production runtime/ref match expected release: true;
- production worktree clean: true;
- health PASS;
- api/worker/db running: true;
- DB healthy: true;
- DB TCP auth PASS;
- Alembic 0046: true;
- exactly one MTProto account: true;
- encrypted session non-empty: true;
- active auth challenges: 0;
- manual-selected groups: 1;
- configured folders: 0;
- active scope: 0;
- Telegram recurring job exists and had recent activity.

Exact release code semantics additionally establish:
- with configured folders = 0, recurring `reconcile_scope()/preview_scope()` does not make Telegram discovery/history network calls;
- with active scope = 0, recurring history sync has no peer to sync;
- a manual-selected-only group is not recurring-history-synced.

The remaining missing evidence is the corrected sanitized job/log pass.

## Authorization

This task authorizes exactly **one execution** of the approved harness at exact SHA:
`ec4f51be6882433210d62ec6dbcfcdb19563be83`

No code changes before the run.

No second run unless the harness itself consumes a bounded transport retry according to its already-reviewed internal max-3 transport policy.

## Executor preparation

1. Fetch origin.
2. Checkout/use exact review branch SHA `ec4f51be6882433210d62ec6dbcfcdb19563be83`.
3. Require clean worktree.
4. Verify:
   - branch remote points to exact SHA;
   - diagnostic script content is from exact SHA;
   - target.json pin remains unchanged.
5. Do NOT amend, rebase, cherry-pick, or modify files.

## Run

Execute the approved:
`ops/production/diagnose_mtproto_auth_readonly.py`

exactly once.

Its internal strict SSH behavior is authoritative:
- pinned ED25519 verification;
- direct argv;
- temp known_hosts lifecycle;
- no host-key bypass;
- max 3 attempts only for pre-remote transport establishment;
- auth failure stops;
- any remote-started diagnostic failure stops;
- first successful SSH session performs full read-only diagnostic.

## Forbidden

Do NOT:
- retry Telegram login;
- retry manual group sync;
- Apply Scope;
- make any ad-hoc Telegram/provider call;
- run direct Telethon;
- decrypt/print session;
- mutate DB;
- restart/recreate services;
- edit env/files on production;
- run Alembic writes;
- change production/main refs;
- deploy the harness;
- modify Bot API;
- change MTProto AI flag;
- change SSH config/known_hosts/target.json.

Do not print raw logs or forbidden identifiers/secrets.

## Required report

Return the harness sanitized output, summarized as:

### Transport
- attempt matrix;
- pin/host-key/auth/remote execution status.

### Production
- release/runtime/ref match;
- worktree clean;
- health;
- api/worker/db running;
- DB healthy/TCP auth;
- Alembic 0046.

### MTProto DB
- exactly-one account;
- encrypted session non-empty;
- active challenge count;
- manual-selected group count;
- configured folder count;
- active scope count.

### Recurring worker
- job exists/status counts/recent activity;
- failure categories;
- `RECURRING_SCOPE_PROVIDER_CALL_POSSIBLE`;
- `RECURRING_HISTORY_PROVIDER_CALL_POSSIBLE`;
- overlap conclusion based on these facts.

### API/worker logs
- normalized observed MTProto routes;
- observed MTProto HTTP status codes;
- manual group sync route observed yes/no;
- manual group sync HTTP 409 yes/no;
- manual group sync authorization-invalid evidence yes/no/unknown;
- worker authorization-invalid yes/no;
- worker provider-unavailable yes/no;
- normalized error classes;
- exact evidence booleans for:
  - AUTH_KEY_DUPLICATED
  - AuthKeyDuplicatedError
  - AUTH_KEY_UNREGISTERED
  - AuthKeyUnregisteredError
  - SESSION_REVOKED
  - SessionRevokedError
  - UnauthorizedError
  - AuthKeyNotFound

### Classification

Choose only from evidence:
A. provider authorization truly revoked/unregistered;
B. likely concurrent auth-key duplication;
C. stored-session persistence/corruption defect;
D. insufficient evidence.

Do not repair/re-authenticate.

Also confirm:
- no Telegram/provider call made by diagnostic;
- no session decrypted/printed;
- no production mutation;
- no SSH trust data changed.

Final marker:
`TELEGRAM_MTPROTO_M4ADH4R3_LIVE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
