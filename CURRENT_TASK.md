# Current task — Telegram MTProto M4ADH4R2: corrective harness review fixes

## Status

M4ADH4 implementation `a17925e5c0d38c4da79fca9c013d208052827fd6` on branch
`review/production-ssh-m4adh4` is REVIEWED and NOT ACCEPTED yet.

The first live run did obtain useful read-only production facts, but the remote helper stopped before log analysis.

Confirmed blockers in the implementation:

1. **Invalid failure-category SQL**
   - the query selects one expression but uses `GROUP BY 2 ORDER BY 2`;
   - this is the direct cause of `FAILURE_STAGE=database-query`.

2. **Wrong recurring-provider-call inference**
   - current helper derives `RECONCILE_SCOPE_PROVIDER_CALLS_POSSIBLE` from active scope count;
   - exact release behavior is:
     `TelegramMtprotoRecurringSyncService.run()` -> `reconcile_scope()` -> `preview_scope()`;
   - `preview_scope()` returns locally when configured folders are empty, before Telegram discovery/fetch calls;
   - with configured folders = 0, that recurring reconcile path does not make a Telegram provider network call;
   - manual-selected groups are not recurring-history-synced unless `scope_active` is true.

3. **Wrong manual-group-sync log detection / unsafe peer normalization**
   - actual manual endpoint is `POST /telegram/mtproto/groups/{peer_id}/sync`;
   - helper currently tests `sync-scope` for the manual 409/auth-invalid condition;
   - negative Telegram peer IDs must never appear in emitted normalized routes.

4. **Incomplete log stream inspection**
   - subprocess captures stdout and stderr separately;
   - helper currently scans only `docker logs` stdout;
   - diagnostic must safely inspect both streams without printing raw lines.

5. **Test coverage incomplete**
   - existing five tests do not explicitly cover all required retry/redaction/target/port/output properties.

This task authorizes only **M4ADH4R2 corrective changes on the existing review branch plus local tests**.

NO production rerun is authorized yet.

## Branch / base

Continue on:
`review/production-ssh-m4adh4`

Base implementation:
`a17925e5c0d38c4da79fca9c013d208052827fd6`

Do not modify main or production.

## Required corrective changes

### A. Fix job failure-category query

Replace the invalid positional grouping with valid PostgreSQL SQL.

Prefer deriving sanitized recurring failure evidence from existing structured fields where possible:
- `status`;
- `payload->>'last_error_kind'`;
- `payload->>'last_error_retryable'`;
- sanitized `last_error` class name.

Do not emit raw `last_error` text.

At minimum output aggregate/boolean facts sufficient to distinguish:
- authentication;
- transient/provider-unavailable;
- unknown/other;
- exact stored error class evidence for `TelegramMtprotoAuthorizationInvalidError` and `TelegramMtprotoProviderUnavailableError` when present.

No IDs.

### B. Correct recurring provider-call inference

Use exact release semantics.

For the current recurring path:
- configured folders > 0 => `reconcile_scope()/preview_scope()` can call Telegram;
- configured folders = 0 => preview returns without Telegram discovery/fetch;
- after reconcile, history sync only targets `scope_active=true` selections;
- a merely manual-selected, non-scope-active group is not recurring-history-synced.

Emit sanitized facts such as:
- `RECURRING_SCOPE_PROVIDER_CALL_POSSIBLE=true/false`;
- `RECURRING_HISTORY_PROVIDER_CALL_POSSIBLE=true/false`.

Do not infer concurrency solely from `active scope`.

### C. Detect the actual manual group sync

Detect only the actual route:
`/telegram/mtproto/groups/{peer_id}/sync`

Normalize any numeric peer segment, including negative IDs, to:
`/<peer>/`

Never emit a raw peer ID.

Return:
- manual group sync route observed yes/no;
- HTTP 409 observed for that route yes/no;
- authorization-invalid class/text evidence yes/no/unknown, only if safely observable.

Do not confuse with:
`/telegram/mtproto/sync-scope/peers/{peer_id}/sync`.

### D. Inspect both Docker log streams safely

For `docker logs`, inspect both captured stdout and stderr in memory.

Never emit raw log lines.

Only emit:
- normalized route names;
- HTTP status codes associated with MTProto route lines;
- whitelisted normalized exception/error class tokens;
- exact evidence booleans requested by M4ADH4.

### E. Fix route/output redaction

All emitted route normalization must redact:
- positive numeric peer IDs;
- negative numeric peer IDs.

No user/account/peer IDs, phones, provider refs, session material, secrets, IPs, or raw content may be emitted.

### F. Keep transport/retry semantics fail-closed

Preserve:
- exact pinned key;
- exact target/port;
- direct argv;
- no local shell wrapper;
- temp known_hosts lifetime through SSH;
- max 3 attempts;
- retry ONLY pre-remote transport/host-key establishment failure;
- auth failure does not retry;
- any remote-started diagnostic failure does not retry;
- no unpinned key acceptance.

## Required focused tests

Expand focused tests so every property below has an explicit assertion:

1. exact target is `root@web-itx.duckdns.org`;
2. exact port is `22`;
3. complete strict SSH option set;
4. no local shell wrapper;
5. temp known_hosts exists throughout subprocess;
6. pin mismatch blocks before SSH;
7. maximum 3 attempts with fresh verified temp files;
8. ONLY pre-remote transport failure retries;
9. authentication failure does not retry;
10. remote-started failure does not retry;
11. successful SSH session runs diagnostic in that same session;
12. remote helper has no Telegram/provider call path;
13. remote helper has no session decryption path;
14. remote helper contains no production-write commands;
15. negative and positive peer IDs are redacted from normalized route output;
16. manual group route is distinguished from sync-scope peer route;
17. HTTP 409 detection is tied to the manual group sync route;
18. both docker-log stdout and stderr are inspected;
19. failure-category SQL is valid-by-construction and does not use the broken `GROUP BY 2`;
20. output sanitizer/allowlist cannot emit forbidden identifiers/secrets/raw log lines;
21. recurring provider-call inference matches configured-folder/scope semantics.

Run:
- focused pytest;
- Ruff on changed Python files;
- `git diff --check`.

## Review handoff only

After corrections:
- commit on the same review branch;
- push the review branch;
- report full corrective SHA;
- report exact test count/pass;
- report Ruff and diff-check;
- summarize each blocker and its fix;
- explicitly list any remaining coverage gap.

Do NOT rerun production diagnostic yet.

Final marker:
`TELEGRAM_MTPROTO_M4ADH4R2_REVIEW_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
