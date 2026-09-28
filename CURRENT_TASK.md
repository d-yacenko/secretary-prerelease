# Current task — PP1: Assisted Person Promotion

## State

- Human People R4-H2 gate is PASS and is recorded in PROJECT_STATE.
- Current main before this authorization: `6d89e2e40356f3a6fa22b07fb15a5565e555176c`.
- Production/runtime/origin-production remain `9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa`.
- Alembic on production remains `0050`.
- Read the new **Assisted Person promotion** section in `DECISIONS.md` before implementation.

## Product goal

Manual Person creation is a fallback, not the primary acquisition workflow.

Build the first complete assisted-promotion loop:

`stored Flow -> exact unresolved identity -> bounded promotion candidate -> People review -> user approval -> Person + exact identity`

Most observed senders/participants must continue to remain only source/provider evidence. PP1 must not create a Person merely because an identity was observed.

This slice is deliberately **People-view-first**. Do not add push notifications or task-creation prompts yet. Those are later contextual surfaces built on this foundation.

## Promotion semantics

### Candidate is not a Person

A promotion candidate is a derived read model over stored Flow and exact normalized provider identity evidence.

Candidate reads must create:

- no Object(kind=person);
- no PersonIdentity;
- no PersonIdentityEvidence;
- no Person<->Flow edge;
- no provider/network/model call.

Do not use display-name similarity as sufficient authority. A confirmable promotion candidate must have a normalized exact provider identity.

Reuse existing identity normalizers/extractors and existing provider direction/directness semantics. Do not build a second competing identity parser or resolver.

### Initial eligibility

PP1 is intentionally conservative.

A candidate is eligible only when all are true:

1. the exact normalized identity does not already resolve to an active Person;
2. it is not actively suppressed by unresolved-promotion feedback;
3. the stored evidence is a **direct** first-party communication context, not a public/group/broadcast exposure;
4. the same exact identity has at least **2 qualifying direct communication hits** inside the bounded recent scan.

Use the existing 90-day Person lookback and the existing rooted Person maximum communication scan boundary of 400 rows. Do not scan beyond 400.

Provider expectations:

- email/Yandex: incoming exact sender in a direct message context according to the existing email direction/audience semantics;
- Mattermost: exact remote author in a DM/direct channel;
- Teams: exact remote user sender in one-on-one context;
- Telegram MTProto: exact remote sender in a private/direct chat;
- repeated public/group/channel authors do not become promotion candidates in PP1.

For the first-party People surface, preserve the existing policy that quarantined Telegram may participate in non-AI identity/People presentation. Do not expose it to Assistant/LLM/model paths and do not change `TELEGRAM_MTPROTO_AI_ENABLED`.

If current stored metadata cannot safely prove directness for a provider, fail closed for that row.

### Ranking and boundedness

Return at most 5 active promotion candidates in People overview.

Rank deterministically by:

1. more qualifying direct hits;
2. more recent qualifying hit;
3. stable exact identity key tie-break.

Cap the counted direct-hit contribution at 8 for presentation/ranking so a single high-volume identity cannot create unbounded work.

Expose a `truncated`/partial indicator when the global 400-row scan is incomplete.

For each visible candidate return:

- exact normalized identity tuple: provider, identity_type, realm, canonical_value;
- a safe display label from stored provider metadata, falling back to canonical value if needed;
- qualifying direct-hit count (bounded/capped presentation count);
- most recent qualifying timestamp;
- simple non-probabilistic reasons such as `repeated_direct_contact`;
- up to 3 same-user active source Flow previews: id, kind, provider, title, occurred_at only;
- no message body/snippet.

## Persistent unresolved suppression

A user must be able to say **do not suggest this unresolved identity again** without creating a Person.

Add the smallest dedicated persistence for unresolved promotion feedback. Do not overload `PersonIdentityEvidence`, because that table requires an existing Person.

Preferred contract:

- new table/model for promotion feedback;
- keyed by same-user exact normalized identity tuple;
- feedback kind in PP1: suppression only;
- active/retracted state;
- user origin/provenance;
- reversible;
- one active suppression per exact identity;
- no source message body or provider secret stored.

This requires the next Alembic revision after 0050. Keep the migration narrowly scoped to this table/index/check constraints.

Suppression must be exact-identity scoped. Suppressing one email/account must not suppress another person with a similar display name.

Expose a small **hidden suggestions** read so the first-party People UI can restore an active suppression. Retraction makes an otherwise eligible identity discoverable again.

## Approval / promotion write

Add one explicit first-party approval operation for a currently exposed promotion candidate.

On approval the backend must, in one transaction:

1. revalidate/freeze the exact identity;
2. fail closed if another active Person already owns it;
3. create the canonical `Object(kind=person)` using the candidate display label (canonical identity fallback allowed);
4. attach exactly that normalized PersonIdentity;
5. record `user_confirmed` PersonIdentityEvidence for that identity;
6. return the created Person identity/result.

The write must be atomic and idempotent at the semantic level.

If a concurrent/repeated approval finds that the same exact identity already belongs to an active Person, return that existing Person rather than creating a duplicate where safe. If ownership is conflicting/ambiguous, return conflict and leave no orphan Person.

Do not infer or write any relationship/role knowledge during promotion.

Approval means only:

**remember this real-world Person and bind this exact endpoint.**

It does NOT mean manager, colleague, employee, family, organization member, authority, requester, task owner, or importance.

## First-party People UX

In People overview, add a compact section:

**Предлагаемые люди**

Show no more than 5 candidates.

Each candidate should make the approval understandable without opening raw source data:

- display name / exact identity;
- provider;
- concise explanation, e.g. `2 прямых контакта · последнее сегодня`;
- up to 3 source Flow rows, body-free, using the existing object-detail navigation.

Actions:

- **Добавить** — runs the explicit promotion approval;
- **Не предлагать** — records exact-identity suppression.

After successful approval:

- candidate disappears from suggestions;
- newly created Person appears through the normal People model;
- no second manual identity-entry step is required.

Add a compact reversible section for actively suppressed unresolved identities:

**Скрытые предложения**

with **Вернуть**.

When there are no active candidates/suppressions, add no empty noise.

Keep existing manual Person creation as fallback. Do not remove it in PP1.

Do not put promotion suggestions inside every rooted Person detail. This is an overview/review surface.

## Existing systems to reuse

Reuse rather than duplicate:

- `extract_person_identity_evidence` and provider-specific identity normalizers;
- `PersonIdentityService.resolve/attach/create_person`;
- `PersonEvidenceService.record_confirmation`;
- existing Person lookback / scan constants where semantically applicable;
- existing provider direction/directness helpers;
- existing body-free Flow preview/navigation patterns from People R4.

`PersonEnrichmentService.plan()` may inform implementation but must not be invoked as a supposedly read-only UI projection if its current side effects would make the promotion read mutate state. Preserve read purity.

## Required backend scenarios

At minimum cover:

1. two direct unresolved email hits -> one candidate;
2. one direct hit -> no candidate;
3. repeated public/group exposure -> no candidate;
4. already-owned exact identity -> no promotion candidate;
5. email normalization dedupes equivalent spellings;
6. Mattermost DM qualifying case;
7. Teams one-on-one qualifying case;
8. Telegram private qualifying case with first-party quarantine behavior preserved;
9. Telegram group sender does not qualify for PP1 promotion;
10. bounded 400-row scan and truthful truncation;
11. source previews are same-user, bounded, active, and body-free;
12. candidate read performs no writes;
13. suppress removes exact identity from active suggestions;
14. suppression of one identity does not suppress a similar display name / other endpoint;
15. retract suppression allows rediscovery when evidence still qualifies;
16. approval creates Person + exact identity + active user-confirmed evidence;
17. approval creates no Person<->Flow edge;
18. repeated/concurrent-safe approval does not create duplicate Person ownership;
19. conflicting exact ownership fails closed without orphan Person;
20. approval does not create Task actor, relationship, Organization, or social edges.

## Flutter coverage

Add focused tests proving:

- candidate section renders only when data exists;
- explanation and exact route/provider are understandable;
- Add promotes and removes the candidate;
- Do not suggest moves it to hidden suggestions;
- Restore returns it when still eligible;
- source rows open existing object detail;
- no message bodies are displayed;
- no manager/colleague/organization wording is inferred;
- existing People R4/H2 known contacts, candidate contacts, recent Flow, and salience sections remain intact.

Run the relevant People/Graph tests and touched-file analyzer.

## Build

Produce a Linux debug bundle for human verification.

The Executor does not perform the human acceptance.

## Explicitly out of scope

- No production deploy.
- No provider or directory lookup.
- No LLM/model call.
- No proactive notification.
- No task-creation contextual prompt yet.
- No auto-create Person.
- No automatic attach without the explicit promotion approval.
- No fuzzy/name-only promotion.
- No Person knowledge / manager / colleague / family / client inference.
- No Organization ontology.
- No Person-to-Person social graph.
- No new Person<->Flow edges.
- No salience formula change.
- No Task actor semantic change.
- No Assistant prompt/tool change.
- No MCP.
- No G3B or S3.

If implementation requires broadening any of those boundaries, STOP and report rather than expanding scope.

## Verification

Run focused backend coverage for:

- promotion candidate read;
- promotion feedback;
- promotion approval;
- Person identity/evidence;
- Person Assistant attribution helpers used by the implementation;
- People workspace.

Run adjacent People/Graph Flutter coverage.

Run Ruff/formatting, migration checks, `git diff --check`, and relevant Flutter analyze.

## Completion

1. Commit implementation, migration, and focused regression tests.
2. Record exact behavior, migration revision, test results, and implementation SHA in `PROJECT_STATE.md`.
3. Return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - new Alembic head;
   - Linux debug bundle path;
   - production/runtime unchanged at `9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa` / Alembic 0050;
   - human acceptance pending.
4. Push implementation + HOLD to `main`.
5. Report exact SHAs/results/bundle path and STOP.

Do not deploy and do not begin contextual task prompts or Person Knowledge after PP1.
