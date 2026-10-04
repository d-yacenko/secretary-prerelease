# CURRENT_TASK

ACTIVE

## REL1D-HG2B2 — preserve named email recipients for Gmail and Yandex Mail

REL1D-HG2B1 is ARCHITECT SOURCE-ACCEPTED.

Production/backend/client remain:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Alembic remains:

`0054 / 0054`

Human REL1D acceptance remains paused.

D3 proved the same current normalization defect in both mail connectors:

- Gmail and Yandex Mail preserve a named sender/from header;
- `recipients` and `cc` are normalized to bare addresses only;
- therefore a real named To/Cc participant cannot become role-import strong identity evidence.

This task is ONLY the additive mail recipient-display source contract corrective for Gmail + Yandex Mail.

Do not backfill/refetch production mail in this task.
Do not deploy/install anything.
Do not change generic Person promotion or role-import evidence thresholds.

## Architectural goal

Preserve provider/mail-header supplied human recipient names without breaking the existing bare-address metadata contract.

For both Gmail and Yandex Mail:

- existing `metadata.recipients` must remain a list of bare addresses;
- existing `metadata.cc` must remain a list of bare addresses;
- add structured, additive named-participant metadata for To and Cc;
- role-import participant parsing should consume those structured fields as strong email identities only when both:
  - a parseable address exists;
  - a non-empty human display name exists.

Do not infer a display name from an address, local-part, domain, subject, body, signature, or other message text.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `backend/app/connectors/google/gmail_normalize.py`
- `backend/app/connectors/google/gmail_sync.py`
- `backend/app/connectors/yandex/mail_normalize.py`
- `backend/app/connectors/yandex/mail_sync.py`
- `backend/app/domain/role_import_participants.py`
- directly affected Gmail/Yandex normalization/sync tests;
- `backend/tests/test_rel1d_role_import_participants.py`
- HG2A scan-window tests.

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.

Do not move `production`.

## Additive metadata contract

Add the same structured fields to both normalized mail providers:

- `to_participants`
- `cc_participants`

Each is a JSON list of objects shaped exactly as:

```
{
  "address": "<bare parsed email address>",
  "display_name": "<collapsed human display name>"
}
```

Store only entries where:

- address is non-empty and parseable by the existing stdlib mail-address parser;
- display_name is non-empty after whitespace collapse.

Do not store a structured participant for a bare address without a human display.

Do not store extra fields.

Do not remove or rename existing:

- `sender`
- `recipients`
- `cc`
- `subject`
- `headers`
- provider-specific provenance/account metadata.

If no named To/Cc participants exist, either omit the corresponding new field or store an empty list consistently in both providers; choose one contract and test it.

## Address/display parsing

Use Python stdlib email address parsing.

For Gmail, do not rely on the current naive comma split for the new structured fields because quoted display names may contain commas.

For Yandex, existing `getaddresses(...)` semantics are acceptable.

Human display normalization for the new structured fields:

- accept only string display text returned by the parsed mail header;
- trim outer whitespace;
- collapse internal Unicode whitespace;
- preserve casing/content otherwise;
- do not decode/infer from the email local-part;
- do not synthesize a display when absent.

Address normalization/storage:

- preserve the current bare-address strings used by the connector;
- do not change global PersonIdentity email canonicalization here;
- role-import parser will pass the address into existing `normalize_email(...)`.

Do not change sender/from or reply-to semantics in this task.

## Gmail compatibility requirement

The current Gmail `metadata.recipients` and `metadata.cc` bare-address values are an existing contract.

Do not change their shape or meaning merely to support named recipients.

The new structured fields are additive.

A header such as:

`Ирина Сергеевна <irina@example.com>, "Doe, John" <john@example.com>, bare@example.com`

must produce:

- existing bare recipients containing all three addresses according to current connector semantics;
- structured To participants only for Ирина Сергеевна and Doe, John;
- no structured participant for `bare@example.com`.

## Yandex compatibility requirement

Apply the same external metadata contract:

- `recipients` stays bare addresses;
- `cc` stays bare addresses;
- named To/Cc entries are additive structured fields.

Preserve RFC2047/Unicode behavior already provided by `policy.default`.

## Role-import email participant parser

Extend only the email branch of `participant_identities(...)`.

It must consume:

1. existing named sender/from/reply-to evidence exactly as today;
2. new `to_participants`;
3. new `cc_participants`;
4. legacy named-envelope values in existing recipient fields, if any old/test rows already contain them.

For each structured item:

- require a mapping/object;
- require string `address`;
- require string `display_name`;
- collapse display whitespace;
- call existing `normalize_email(address, display_value=display)`;
- ignore malformed items fail-closed.

The outer existing dedup/self-identity logic remains authoritative.

Do not surface raw addresses in role-import UI.

## Strong-evidence semantics

A named To/Cc recipient from the provider header becomes the same class of strong email participant evidence as a named sender/reply-to:

- stable identity = normalized email address;
- human display = header-supplied display name.

One qualifying role-import participant hit remains sufficient for HG1.4 identity-backed candidate behavior.

Do not alter generic `MIN_DIRECT_HITS=2` promotion.

Do not make bare To/Cc addresses strong role-import participants.

## Existing-row refresh readiness

No production mail refetch/backfill is authorized now.

Prove at the normalization/parser level that if an existing provider message is refetched later under the corrected source contract:

- the normalized metadata contains the new named participant structures;
- current role-import parser emits the expected normalized email identity;
- bare-only recipients remain non-qualifying.

Do not redesign Gmail/Yandex materialization/history behavior in this task.

In particular, do not attempt to force already-known Gmail/Yandex messages to refetch now.

That will be part of a later controlled repair/backfill plan.

## Required tests

Add focused tests proving at minimum for **both providers**:

1. named To recipient is preserved in the new structured field;
2. named Cc recipient is preserved;
3. bare To address remains in `recipients` but produces no structured participant;
4. bare Cc address remains in `cc` but produces no structured participant;
5. multiple recipients preserve all bare addresses and only named structured entries;
6. quoted display name containing a comma parses correctly;
7. Unicode display names survive as human display;
8. display whitespace is collapsed;
9. malformed/empty display does not produce structured participant;
10. current bare `recipients`/`cc` shape remains backward-compatible;
11. role-import parser emits email identity from new named To metadata;
12. role-import parser emits email identity from new named Cc metadata;
13. parser does not emit from bare-only recipient metadata;
14. self email filtering still removes the user's own exact address;
15. duplicate same email from sender + To/Cc deduplicates through existing identity-key logic;
16. named sender/reply-to behavior remains unchanged;
17. HG2A expanded scan tests remain green;
18. no provider/model call occurs outside fake/local fixtures.

Run at minimum:

- directly affected Gmail normalization/sync tests;
- `backend/tests/test_yandex_mail.py`;
- directly affected Yandex history/runtime tests if necessary;
- `backend/tests/test_rel1d_role_import_participants.py`;
- `backend/tests/test_rel1d_hg2a_scan_window.py`;
- Ruff on touched Python;
- `git diff --check`.

## Explicit non-goals

Do not:

- change `source_account_email` provenance behavior;
- repair legacy Gmail/Yandex rows missing account provenance;
- refetch old messages;
- sync/backfill production mail;
- change sender/reply-to identity rules;
- infer display names from bare addresses;
- parse signatures/body text into identities;
- change generic Person promotion;
- change role-import mention fallback;
- fix Mattermost further;
- fix Teams;
- fix Telegram;
- change HG2A 10,000 ceiling;
- add schema/migrations;
- change dependencies;
- deploy backend;
- build/install client;
- call live providers;
- mutate production product data;
- start another slice.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG2B2` entry to `PROJECT_STATE.md` including:
   - implementation SHA;
   - changed files;
   - exact additive `to_participants` / `cc_participants` contract;
   - confirmation existing bare recipients/cc contract preserved;
   - confirmation bare addresses alone remain non-qualifying;
   - role-import parser behavior;
   - exact focused test totals;
   - Ruff/diff-check result;
   - explicit no refetch/backfill/sync/deploy/install/migration/provider/model/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2B2 implementation SHA;
   - source ready for Architect review;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - no mail backfill, rollout, or next connector task without fresh Architect authorization.

3. commit + push to `main`.

4. STOP.

On blocker:

- record exact bounded blocker;
- return HOLD;
- do not change legacy metadata shapes merely to force the parser;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
