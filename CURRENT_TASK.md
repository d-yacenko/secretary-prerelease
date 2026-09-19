# Current task — Production SSH M4ADH4: deterministic one-session read-only MTProto diagnostic harness

## Status

M4ADH3 proved the strict SSH transport can succeed end-to-end with the canonical pin.

A later M4AD-LIVE run, using an apparently equivalent contract, again failed before remote execution with host-key verification failure.

Do not continue ad-hoc/manual retries. The remaining problem is invocation nondeterminism across Executor runs.

This task authorizes **M4ADH4 — implement, test, and run one deterministic local diagnostic harness that performs pin discovery/verification and the entire production read-only MTProto diagnosis in a single SSH session per attempt**.

No production mutation is authorized.

Production target:
`root@web-itx.duckdns.org:22`

Pinned ED25519 fingerprint:
`SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs`

Expected production release:
`8091736337689b68b4510126e74d9e409397f696`

Expected Alembic:
`0046`

## Deliverable

Add a narrowly scoped local operations script, preferred path:

`ops/production/diagnose_mtproto_auth_readonly.py`

plus focused tests.

The script must:
1. import/reuse the existing exact `deploy.py::_verified_known_hosts()`;
2. generate a fresh temporary known_hosts file;
3. keep that exact file alive until the SSH subprocess exits;
4. invoke `ssh` directly as an argv list, never via local `sh -c`;
5. use one SSH session to run the complete remote read-only helper;
6. emit only sanitized/machine-readable diagnostic output;
7. make no Telegram/provider calls;
8. make no production writes.

## Strict SSH contract

Every attempt must use:

- `ssh`
- `-p 22`
- `-o BatchMode=yes`
- `-o StrictHostKeyChecking=yes`
- `-o UserKnownHostsFile=<same live temp file>`
- `-o GlobalKnownHostsFile=/dev/null`
- `-o HostKeyAlgorithms=ssh-ed25519`
- `-o ConnectTimeout=5`
- `root@web-itx.duckdns.org`

Do NOT use `-F /dev/null`.

Before each SSH attempt:
- call exact `_verified_known_hosts()`;
- require a non-empty result;
- require that the generated entry resolves to the pinned fingerprint;
- keep the temp file open/alive through subprocess completion.

Do not print base64 host-key material.

## Bounded retry rule

To tolerate the already-observed invocation/network nondeterminism without weakening trust:

- maximum 3 SSH attempts total;
- each attempt MUST regenerate and independently verify a fresh temporary known_hosts entry against the same pinned fingerprint;
- retry only when the SSH session fails before remote execution due to host-key/transport establishment;
- never accept any unpinned key;
- never use `StrictHostKeyChecking=no`;
- never modify user `~/.ssh/known_hosts`;
- never change `target.json`.

If authentication itself fails after host-key verification, stop immediately and report it; do not loop credential attempts.

If all three attempts fail before remote execution, stop with sanitized transport evidence only.

## Single remote session

On the first attempt that passes strict host-key verification and SSH authentication, run the entire authorized read-only diagnostic in THAT SAME SSH session.

Do not run a separate `true` session first.

The remote helper may be sent over stdin to a fixed command such as:
`cd /opt/secretary && python3 -`

The local script may construct that fixed remote command safely, but must not interpolate secrets or user data into it.

## Authorized remote read-only observations

### Production state

Return only sanitized facts:
- production HEAD/ref equals expected release yes/no;
- worktree clean yes/no;
- api running yes/no;
- worker running yes/no;
- db running/healthy yes/no;
- API health PASS/FAIL;
- Alembic revision equals `0046` yes/no;
- api/worker release provenance equals expected release if determinable read-only.

### Persisted MTProto state

Use read-only SQL only.

Do not output IDs.

Return only:
- total/affected MTProto account cardinality sufficient to state exactly-one yes/no;
- `session_encrypted` non-empty yes/no;
- account row freshness relative to recent activation: yes/no/unknown;
- active auth challenge count;
- manual-selected group count;
- configured sync-folder count;
- active scope count.

Never decrypt or print session material.

### Recurring Telegram job

Read-only inspect:
- recurring Telegram MTProto source-sync job exists yes/no;
- status pending/running/failed/other;
- recent run/failure relative to activation/manual-sync window if determinable;
- sanitized failure category/class only;
- whether configured folder/scope state means `reconcile_scope` can issue provider calls;
- whether recorded worker timing plausibly overlaps the manual sync window.

Do not trigger/rearm jobs.

### API/worker evidence

Inspect a narrow recent window only.

Return sanitized aggregates/facts, not raw logs:
- observed MTProto route names;
- observed HTTP status codes;
- manual group sync returned authorization-invalid / HTTP 409 yes/no/unknown;
- worker independently logged authorization-invalid yes/no;
- worker independently logged provider-unavailable yes/no;
- exact class/token evidence yes/no for:
  - `AUTH_KEY_DUPLICATED`
  - `AuthKeyDuplicatedError`
  - `AUTH_KEY_UNREGISTERED`
  - `AuthKeyUnregisteredError`
  - `SESSION_REVOKED`
  - `SessionRevokedError`
  - `UnauthorizedError`
  - `AuthKeyNotFound`

Do not emit raw log lines if they contain identifiers/content. Prefer counts/booleans/class names.

## Forbidden remote behavior

The remote helper MUST NOT:
- make any network call to Telegram;
- import/use Telethon for a live call;
- decrypt the stored session;
- retry login or history sync;
- apply scope;
- restart/recreate containers;
- write DB;
- edit env/files;
- run Alembic writes;
- move refs;
- change Bot API;
- change AI quarantine;
- deploy code.

Do not print:
- Secretary user/account IDs;
- Telegram user IDs;
- peer IDs;
- phone;
- session ciphertext/plaintext;
- bearer tokens;
- credential key/API hash;
- provider refs;
- IPs;
- raw user message content.

## Local focused tests

Add tests that prove at minimum:

1. exact direct argv contains all strict SSH options;
2. local shell wrappers are not used;
3. temp known_hosts remains alive until subprocess completion;
4. pin mismatch fails closed before SSH;
5. max attempts is 3;
6. retry is permitted only for pre-remote transport/host-key failure;
7. auth failure does not loop;
8. successful first authenticated session runs the remote diagnostic in that same session;
9. remote helper contains no Telegram/provider call path and no session decryption;
10. parser/output redacts/omits forbidden identifiers/secrets;
11. no production write command is present in the remote helper.

Run the focused tests and report exact count/pass.

## Execution after tests

After tests pass, execute this exact harness once against production.

Do not deploy the script to production; run it locally against the existing production host.

If transport still fails all 3 pinned attempts:
- return sanitized attempt matrix;
- no further retry.

If one attempt succeeds:
- return the sanitized M4AD live evidence from that one SSH session.

## Classification

Based only on live evidence choose:

A. provider authorization truly revoked/unregistered;
B. likely concurrent auth-key duplication;
C. stored-session persistence/corruption defect;
D. insufficient evidence.

If evidence remains insufficient, propose the smallest next separately-authorized test.

## Completion report

Return:
- implementation commit SHA;
- focused tests PASS/count;
- attempt matrix: attempt -> pin verified -> host-key/auth/remote execution result;
- production ref/runtime/Alembic/health facts if obtained;
- MTProto DB booleans/counts if obtained;
- recurring job facts if obtained;
- sanitized API/worker evidence if obtained;
- AuthKeyDuplicated evidence yes/no/unknown;
- classification A/B/C/D;
- confirmation no Telegram/provider call was made;
- confirmation no session was decrypted/printed;
- confirmation no production mutation occurred;
- confirmation user SSH config/known_hosts and `target.json` were not changed.

Final marker:
`TELEGRAM_MTPROTO_M4ADH4_DIAGNOSIS_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
