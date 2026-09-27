# Current task — People R4: provider-neutral source-derived identity review

## State

- People R2 rooted Person truth surface is accepted and deployed.
- People R3 explicit manual email binding is accepted, deployed, and verified by the human on a real Person.
- Manual email binding is a recovery/bootstrap affordance, not the intended primary identity-acquisition workflow.
- Current `main` before this authorization is `4cc3ac7f8b0d3b66477459bb3d25906a09359e9b`.
- Production backend/runtime and `origin/production` are `1b851f91bd37d0e79531ef740b02febb3c3af69d`.
- Alembic remains `0050`.

The existing Person foundation already supports multiple exact identities per Person and already extracts source identity evidence from stored Flow for:

- email from Gmail/Yandex email Objects -> canonical provider `email`;
- Telegram MTProto -> `telegram_user_id` scoped by account realm;
- Mattermost -> user id and username scoped by server realm;
- Teams -> user id scoped by tenant realm.

The existing read-only `find_identity_candidates` path scans stored communication Objects, groups exact identity tuples, preserves ownership conflicts, and only proposes a Person match through the existing evidence/name-candidate rules. First-party People reads may include stored Telegram candidates while model-facing Telegram retrieval remains gated.

Current rooted People projection discards most candidate evidence. It mixes candidates into the general identity list and keeps only provider/type/value/state/confirmable. Candidate `reasons`, `assessment_resolution`, and `source_object_ids` are not exposed to the human. Therefore the human cannot understand why Secretary proposed an endpoint or inspect the source Flow before confirming it.

## Goal

Turn the existing source-derived identity candidate machinery into a clear, provider-neutral **first-party discovery/review experience** for an existing Person.

When the human roots a Person, Secretary should automatically derive bounded candidate endpoints from already-ingested Flow and present them separately as possible contacts with evidence.

The human can then:

- inspect why the endpoint was proposed;
- inspect the source Flow;
- confirm it;
- reject it;
- later reverse a rejection.

Confirmation continues to activate the exact canonical identity through the already accepted C2 / identity-correction path.

This task must not create a second resolver and must not auto-merge or auto-attach on name similarity.

## Core invariant

**Discovery may be automatic; durable identity attachment remains explicit unless the exact identity is already canonically owned.**

A display-name match, repeated messages, common domain, username similarity, initials, organization string, or salience score MUST NOT by itself create or attach a PersonIdentity.

Unknown/ambiguous remains a valid result.

## Backend contract

### A. Reuse the existing candidate authority

For rooted People detail, use the existing:

`PersonAssistantService.find_identity_candidates(person_id, include_quarantined_telegram=True)`

and the existing:

`extract_person_identity_evidence(...)`

Do not create a parallel fuzzy resolver.

Do not call `PersonEnrichmentService.plan()` from a People read, request side effect, scheduler, or background job in R4.

Do not add live provider/directory/model lookup.

### B. Dedicated first-party candidate projection

Add a dedicated rooted-only candidate projection to `PersonPresentation` rather than forcing candidates to masquerade as known contacts.

Suggested field:

`identity_candidates`

Each candidate must expose enough information for truthful review:

- provider;
- identity_type;
- realm;
- canonical_value;
- display_value;
- confirmable;
- candidate state: `candidate|conflicted`;
- existing candidate `reasons`;
- existing `assessment_resolution` when present;
- up to 3 source Flow previews derived from the existing `source_object_ids`;
- top-level candidate-list truncation from the existing candidate result.

A source preview should contain only:

- object_id;
- kind;
- provider;
- title;
- occurred_at.

Do not expose message bodies in the candidate summary.

Source Object lookup must be same-user, active, bounded, and fail closed if a referenced Object is unavailable.

Do not materialize Person<->Flow edges.

### C. Known contacts remain canonical identities

`identities` continues to represent attached/effective/conflicted/rejected canonical identities.

A source-derived candidate must not appear as an effective known contact until explicit confirmation activates it through the existing correction path.

Preserve multiple identities of the same category. One Person may legitimately have multiple email addresses or multiple provider identities.

Do not collapse Gmail/Yandex into separate Person identity types: email remains the existing provider-neutral canonical email identity.

### D. Confirmation

Use the existing first-party `identity-correction` confirm path.

On confirm:

- revalidate grounding;
- preserve current ownership/conflict fail-closed behavior;
- attach the exact identity if currently unowned, as C2 already does;
- record/reuse the existing user-confirmed evidence;
- refresh rooted Person detail;
- candidate disappears from “possible contacts” and appears under known contacts/routes where applicable;
- newly attributable R2 Flow may appear immediately through existing exact-identity semantics.

No new confirmation endpoint.

### E. Rejection and reversibility

Use the existing first-party `identity-correction` reject/retract semantics.

A rejected source-derived candidate must not become an effective identity and must stop being offered as an active candidate.

However, first-party UI must preserve a bounded reversible representation of active user rejection so the human can undo a mistaken rejection without reconstructing the raw tuple manually.

Implement this from the existing evidence ledger; no new table.

The reversible rejection projection may be a separate `rejected_identity_candidates` list or equivalent. It must expose only the exact tuple and a human-safe display value/provider plus a `Вернуть` action.

Do not resurrect a candidate automatically. Retract only removes the user's rejection; normal candidate discovery rules then decide whether it is proposed again.

### F. Provider coverage

Focused tests must prove discovery/review works provider-neutrally for stored Flow evidence from at least:

- email;
- Telegram MTProto private context;
- Mattermost direct-message context;
- Teams one-on-one context.

Use the current extractor semantics exactly. Do not broaden email recipient semantics, Telegram group semantics, Mattermost channel semantics, Teams group-chat semantics, or provider privacy policy in R4.

### G. Privacy boundary

First-party authenticated People UI may continue to inspect stored Telegram private identity evidence using the already accepted `include_quarantined_telegram=True` path.

This MUST NOT change:

- `TELEGRAM_MTPROTO_AI_ENABLED`;
- model-facing Assistant candidate visibility;
- model-facing communication retrieval;
- self-authored eligibility;
- provider ingestion policy.

No source body is sent to an LLM.

## First-party UI

In rooted Person detail restructure the identity surface conceptually into:

### «Известные контакты»

Show attached canonical identities only.

Keep existing effective/conflicted/rejected controls.

Keep `Добавить email` as a manual fallback. It must not become the primary visual action.

### «Возможные контакты»

Show only source-derived candidates.

For each candidate show:

- human provider label;
- display value;
- exact canonical endpoint in secondary text when display differs;
- concise explanation derived only from existing reason/resolution fields;
- up to 3 source Flow rows with provider/title/date;
- `Подтвердить` when confirmable;
- `Это не этот человек` / equivalent reject action;
- visible conflict state instead of a confirm action when another Person owns the identity.

Source rows must navigate to the existing Object detail/open path; do not invent a new Flow viewer.

Do not display opaque percentages or model-confidence language.

Suggested explanation mapping:

- `name_similarity` -> «Имя в источнике похоже на имя этого человека»;
- `exact_identifier` -> «Точный идентификатор уже известен» (normally should not remain a candidate for the same Person);
- `identity_conflict` -> «Этот контакт уже связан с другим человеком»;
- unknown future reason -> neutral «Найдено в сохранённых сообщениях», not an invented semantic claim.

`assessment_resolution` may refine wording only if the current domain meaning is clear; do not translate it into a probability.

If candidate results are truncated, show a compact “показаны не все возможные контакты” indicator.

### «Отклонённые предложения»

If there are active reversible candidate rejections, show them compactly with `Вернуть`.

Do not show this section when empty.

## Refresh behavior

Rooted Person load automatically computes the bounded candidate projection from stored Flow.

After confirm/reject/retract:

- refresh the rooted Person truth surface;
- preserve the current Person root;
- update known/candidate/rejected sections immediately.

Overview/search must not scan candidates per Person and must not fan out source previews.

## Tests

### Backend focused coverage

At minimum:

1. rooted Person exposes a source-derived email candidate with reason and source preview;
2. Telegram private candidate is exposed first-party while model-facing Telegram candidate remains gated;
3. Mattermost DM candidate is exposed with exact realm/identity tuple;
4. Teams one-on-one candidate is exposed with exact tenant-scoped identity;
5. public/group/non-eligible provider contexts do not become candidates beyond current extractor rules;
6. candidate list is bounded/truncation preserved;
7. source previews are same-user, active, bounded, and body-free;
8. candidate does not create PersonIdentity merely by being read;
9. confirm uses existing correction semantics and moves the endpoint to known identities;
10. another-Person ownership stays conflicted/non-confirmable and is not reassigned;
11. reject suppresses the active candidate;
12. rejected candidate remains first-party reversible and retract allows normal rediscovery;
13. overview/search do not run candidate/source-preview fan-out;
14. no Person<->Flow edge is created.

Run existing Person Assistant, evidence, identity, enrichment, People workspace, R2 and R3 focused suites.

### Flutter focused coverage

At minimum:

- known contacts and possible contacts are visually distinct;
- candidate explanation/provider/exact value render;
- up to 3 source rows render and navigate to existing Object detail;
- confirm refreshes into known contacts;
- reject removes active candidate and exposes reversible rejected item;
- retract refreshes candidate review;
- conflict is visible and cannot be confirmed;
- manual `Добавить email` remains available as fallback;
- candidate truncation message;
- empty candidate state does not add noise;
- overview/search do not show review controls.

Run relevant Graph/People suites, touched-file analyze, Linux debug build, and `git diff --check`.

Known unrelated baseline failures may be reported only if reproduced outside the R4 diff.

## Out of scope

- No DB migration.
- No new Person identity type.
- No automatic Person creation from senders/authors.
- No automatic identity attach from name similarity or score.
- No Person merge.
- No provider/directory/network lookup.
- No background enrichment worker or scheduler.
- No LLM inference.
- No change to `PersonEnrichmentService.plan()` semantics unless a narrow bug blocks reuse; if so STOP and report instead of widening.
- No manual Telegram/Mattermost/Teams generic editor.
- No social/organization relationship ontology.
- No manager/colleague/friend/client/family facts.
- No proactive behavior change.
- No Assistant prompt/tool change.
- No MCP work.
- No G3B.
- No S3.
- No production deployment or production data inspection.

## Human gate after R4

Build a Linux debug bundle.

The human will inspect one or more real rooted People and verify:

1. known contacts remain trustworthy;
2. source-derived candidates appear without manual provider entry where real stored evidence exists;
3. candidate reasons/source Flow make the proposal understandable;
4. confirmation immediately expands canonical identity/Flow truth;
5. rejection removes a bad proposal and can be reversed;
6. no unrelated endpoint is silently attached.

The Executor must not perform this human acceptance.

## Completion

- Commit implementation.
- Record exact behavior and verification in `PROJECT_STATE.md`.
- Return `CURRENT_TASK.md` to HOLD with implementation SHA and Linux debug bundle path.
- Push implementation + HOLD to `main`.
- STOP.
- Do not deploy.
- Do not start durable relationship/context ontology or any later People slice.
