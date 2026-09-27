# Current task — People R3: explicit user-confirmed email binding

## State

- People R2 implementation is accepted/source-ready at `84953e50b4a1d7044fa9eadc52bd27e0b2f09969`.
- R2 human visual review is not yet complete because the only real Person inspected is a bare Person with no attached endpoint.
- Human evidence reproduced a real stored email Flow containing an address the user knows belongs to that Person, but Secretary cannot connect the endpoint to the Person.
- Current first-party `identity-correction` intentionally requires the identity to have already been exposed as an attached/evidence/candidate identity. It must keep that guard.
- There is currently no first-party action for the user to assert an exact known email for an existing Person when no candidate can be derived automatically.
- Production/origin-production remain `7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4`; Alembic remains `0050`.

## Goal

Add one explicit first-party user action:

**“This exact email belongs to this Person.”**

This closes the real Person cold-start identity bootstrap gap without introducing fuzzy inference, social/organization ontology, provider lookup, or model-written identity facts.

R3 is email-only.

## Product semantics

A manual email binding is a strong explicit user-confirmed identity fact.

It is NOT:

- name similarity;
- a model inference;
- an organization relation;
- a social role;
- evidence that every message containing the address was authored by the Person;
- permission to bypass existing direction/attribution rules.

After binding, existing exact-identity machinery decides which stored communications are attributable to the Person.

Do not infer an email from initials, local-part text, Person title, domain, organization, or message body.

## Backend

### A. Separate explicit manual-binding path

Add a dedicated first-party endpoint/service action for binding one email to an existing active Person.

Do NOT weaken `POST /graph/people/{person_id}/identity-correction`.
That endpoint must continue requiring prior candidate/evidence grounding exactly as today.

Suggested product API shape:

`POST /graph/people/{person_id}/emails`

body:

```json
{"email":"person@example.com"}
```

Equivalent naming is acceptable if it remains narrowly email-specific and first-party.

### B. Canonical normalization

Use the existing `normalize_email` contract:

- identity_type = `email`;
- provider = `email`;
- realm = empty;
- canonical value case-folded/validated by the existing normalizer.

No provider-specific Gmail/Yandex identity type.

Malformed email => validation error. No write.

### C. Conflict and idempotency

For the current user:

1. If the canonical email is not owned by any active Person:
   - attach it to the selected Person using the existing Person identity service;
   - record strong `user_confirmed` evidence with explicit first-party/manual provenance;
   - if this confirmation created the PersonIdentity row, link the confirmation evidence to that identity row using the existing reversible C2 pattern.

2. If the same active Person already owns the email:
   - succeed idempotently;
   - do not create a duplicate PersonIdentity;
   - do not create unbounded duplicate confirmation evidence.

3. If another active Person owns the email or there is an unresolved confirmation conflict:
   - fail closed with a clear conflict;
   - do not reassign;
   - do not merge People;
   - do not mutate the other Person.

Duplicate Person display names remain legal.

### D. Reversibility

The newly bound identity must participate in the existing rejection/retraction/effective-identity semantics.

A mistaken manual binding must be suppressible/reversible through the existing first-party identity correction behavior without deleting or rewriting source Flow.

Do not add destructive source-message changes.

### E. Immediate read effects

After a successful manual binding, without background work:

- rooted People detail shows the email under known contacts;
- existing email route discovery may expose it through the current route rules;
- R2 recent communication/count uses the exact identity and may begin showing attributable stored Flow;
- canonical Person salience may change naturally from existing inputs;
- Assistant Person communication retrieval may use the identity subject to all existing Assistant/provider privacy gates.

No separate backfill/materialization job.

## First-party UI

In rooted Person detail, add a compact action under/near «Известные контакты»:

`Добавить email`

Dialog:

- title: `Добавить email`;
- one email field;
- helper text equivalent to:
  `Добавляется только точный адрес, который вы подтверждаете как принадлежащий этому человеку.`
- actions: `Отмена`, `Добавить`.

On success:

- close dialog;
- refresh current rooted Person;
- newly attached email appears in existing contact/route/truth projections.

On malformed input or conflict:

- keep the dialog/surface recoverable;
- show a concise human-readable error;
- do not silently reassign.

Do not add provider pickers, realm fields, Telegram numeric ids, Teams ids, Mattermost ids, or a generic “identity editor” in R3.

## Required tests

Backend focused coverage:

1. explicit valid email binds to an existing Person;
2. normalization/case-folding is canonical;
3. same-Person repeat is idempotent;
4. another-Person ownership fails closed;
5. malformed email writes nothing;
6. manual binding records user-confirmed evidence with explicit manual provenance;
7. existing identity-correction candidate guard remains unchanged;
8. rejection suppresses the newly bound identity from effective reads and attribution; retraction restores it according to existing semantics;
9. existing stored email communication becomes attributable after binding using current direction rules;
10. no Person<->Flow edge is materialized;
11. user isolation.

Flutter focused coverage:

- «Добавить email» appears only in rooted Person detail;
- successful add refreshes contacts and R2 truth surface;
- malformed/conflict error is visible and recoverable;
- existing identity correction controls still work;
- overview/search do not gain per-Person write controls or extra fan-out.

Run relevant Person/People backend suites, focused Graph Flutter tests, Ruff, touched-file Flutter analyze, Linux debug build, and `git diff --check`.

Known unrelated baseline failures may be reported only if reproduced outside the R3 diff.

## Out of scope

- No DB migration.
- No automatic candidate generation from `voa`, initials, Person title, domain, or free text.
- No arbitrary generic identity attachment.
- No Telegram/Teams/Mattermost manual binding.
- No Person merge or reassignment.
- No Organization ontology.
- No durable relationship/context facts such as manager/colleague/friend/client/family.
- No Task semantics change.
- No proactive behavior change.
- No Assistant prompt/tool write change.
- No MCP work.
- No G3B.
- No S3.
- No production deploy/data inspection.
- No live provider or LLM call.

## Human gate after R3

Build a Linux debug bundle.

The human should then bind the known real email to the existing real Person and verify:

1. the email appears as a known contact;
2. the previously found real Flow becomes attributable where existing direction semantics allow it;
3. rooted R2 Task/Flow/salience sections become meaningfully inspectable;
4. no unrelated messages are pulled in.

The Executor must not perform this human acceptance.

## Completion

- Commit implementation.
- Record exact behavior/tests in `PROJECT_STATE.md`.
- Return `CURRENT_TASK.md` to HOLD with implementation SHA and Linux bundle path.
- Push implementation + HOLD to `main`.
- Stop.
- Do not start social relationship persistence or another People slice.
