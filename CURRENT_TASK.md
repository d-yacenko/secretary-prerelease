# CURRENT_TASK

ACTIVE

## REL1D-HG1.5 — exact-name mention-backed Person fallback for role import

REL1D-HG-D1 diagnosis is accepted.

Production, backend runtime, and installed Linux client remain exact:

`67e8f14ba7ced8408086bd1ea57c2fa9f7b049dc`

Alembic remains `0054 / 0054`.

Human REL1D acceptance is paused.

D1 proved that `Шабаршина Ирина Сергеевна` has no identity-bearing participant candidate in the bounded production scan, but the exact full name appears in 12 stored Gmail communication rows in searchable title/body/subject text.

This task implements a **role-import-specific weak communication-evidence fallback**.

It must NOT invent or attach an identity.

Do not deploy/install anything in this task.

## Product rule

Role import now has two evidence tiers for a not-yet-Person extracted name:

1. **identity-backed participant evidence**
   - current HG1.4 behavior;
   - one exact identity-bearing participant hit is sufficient;
   - approval may create Person + attach that exact identity.

2. **mention-backed name evidence**
   - only when normal Person resolution is `none`;
   - only when no identity-backed participant candidate with the exact display name is available;
   - requires at least **2 distinct stored communication objects** in the bounded scan containing the exact normalized multi-token extracted person name;
   - approval creates a Person **without any PersonIdentity** and assigns the selected role;
   - the user must explicitly choose/select the candidate and approve the ActionPlan.

The organization-chart source remains role evidence, not independent Person existence proof.

A source-only name with no communication evidence remains omitted.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- `backend/app/services/person_role_import_grounding_service.py`
- `backend/app/services/person_role_import_batch_service.py`
- `backend/app/services/person_role_import_batch_models.py`
- `backend/app/services/person_promotion_service.py`
- `backend/app/services/person_assistant_service.py`
- `backend/app/services/person_identity_service.py`
- relevant role-import API/presentation/client models and tests.

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.

Do not move `production`.

## Mention evidence service

Implement a small dedicated role-import helper/service rather than weakening generic promotion.

Suggested naming is flexible, e.g.:

- `PersonRoleImportMentionEvidenceService`
- `RoleImportNameMentionEvidence`

It must scan the same bounded stored communication universe used by Person services:

- `PERSON_LOOKBACK_DAYS = 90`;
- at most `MAX_PERSON_SCAN_ROWS`;
- current user only;
- active/non-rejected `email` and `chat_message`;
- same Telegram Assistant gate/quarantine predicate as HG1.4;
- no provider calls;
- no model calls.

The scan should be done once for the requested extracted names, not one DB scan per row.

### Exact mention matching

A mention-backed candidate requires:

- collapsed/casefolded exact extracted person name;
- at least two lexical tokens after whitespace collapse;
- exact full-name phrase match with Unicode-aware token boundaries;
- flexible internal whitespace only;
- no substring-inside-longer-token match.

Eligible searchable fields:

- Object `title`;
- Object `body`;
- email metadata `subject`.

Do not use:

- embeddings;
- fuzzy similarity;
- edit distance;
- transliteration;
- PER1 name variants;
- semantic/LLM matching;
- attachment OCR/text not already represented in those stored communication fields.

Count **distinct communication Objects**, not number of occurrences inside one Object.

Define an explicit constant:

`MIN_ROLE_IMPORT_NAME_MENTION_OBJECTS = 2`

One mention is insufficient.

Positive evidence remains usable if the bounded scan is truncated.
Zero/one under truncation fails closed.

## Candidate key / public model

Mention-backed candidates need a deterministic opaque 64-hex candidate key, domain-separated from identity-backed promotion keys.

For example, derive SHA-256 from a fixed prefix plus the normalized exact display-name key.

Do not include raw content or Object ids in the key.

Keep backend-first wire compatibility with the currently deployed client.

The existing `promotion_candidate_key` selection field may continue carrying either identity-backed or mention-backed candidate keys.

Extend the grounded promotion candidate payload with an optional safe discriminator such as:

- `evidence_kind = identity_participant | name_mentions`

and a communication object count.

Do not remove/rename currently required JSON fields in a way that breaks the existing client during backend-first rollout.

If the existing `direct_hit_count` field must remain for compatibility, it may carry the bounded communication-object count for mention-backed candidates, while new source/client code should use clearer internal naming.

## Grounding precedence

For each extracted row:

1. run normal Person resolution first;
2. if resolved/ambiguous, apply existing-Person rules below;
3. if resolution is `none`, try identity-backed HG1.4 participant candidates first;
4. only if no exact-display identity-backed participant candidate exists, try mention-backed fallback;
5. otherwise omit row.

### Existing resolved Person

Preserve the HG1.2 identity-attributable communication gate.

If attributable identity-backed communication count is positive, keep the row exactly as today.

If that count is zero, a resolved existing Person may still remain actionable for role import only when:

- the extracted name has mention evidence >= threshold; and
- the resolved Person title has exact normalized display equality to the extracted name.

Do not change global `PersonAssistantService.count_attributable_communications()`.

This is a role-import-only fallback.

### Ambiguous Person

First preserve HG1.2 filtering by positive attributable communication count.

If one or more graph candidates survive identity-backed filtering, use only those as today.

If none survive, but exact-name mention evidence >= threshold:

- keep only ambiguous candidates whose title exact-normalizes to the extracted name;
- if one or more such exact-title candidates exist, state remains `ambiguous`;
- never silently resolve;
- if none exactly match the extracted display, omit the row.

Do not use mention evidence to bless PER1 variant-only candidates with a different displayed title.

## Mention-backed new Person candidate

When normal Person resolution is `none`, no identity-backed candidate matches, and exact-name mention evidence >= threshold:

Expose one mention-backed promotion candidate with:

- display name = extracted exact normalized display;
- no raw identity;
- evidence kind = `name_mentions`;
- bounded communication-object count;
- latest occurrence if already useful to the model;
- only safe provider/category labels if shown.

Do not expose body snippets, email addresses, usernames, user ids, tenant ids, realms, candidate key, or raw Object ids in visible UI.

No Person is created during grounding.

## Client wording

The UI must clearly distinguish identity-backed and mention-backed candidates.

For identity-backed candidate, keep the existing meaning.

For mention-backed candidate, show wording equivalent to:

- `Упомянут в переписке: N сообщений`
- `Контактная личность не установлена`
- `После подтверждения будет создан новый Person без привязки контакта`

Exact Russian wording may be adjusted for clarity.

The candidate must still require:

1. explicit candidate choice;
2. row checkbox/select;
3. `Подготовить изменения`;
4. `Подтвердить`.

Do not auto-select.

The general note `Показаны только люди с подтверждённой перепиской` should be revised so it remains truthful for both participant-backed and repeated-name-backed evidence. Prefer wording equivalent to:

`Показаны только люди с подтверждением в сохранённой переписке`

The empty state should remain truthful too.

## Prepare / frozen ActionPlan

Freeze enough safe information to distinguish target mode without exposing identities.

The pending plan presentation should distinguish:

- existing Person;
- new Person with confirmed participant identity;
- new Person from repeated exact-name mentions, identity unknown.

Public ActionPlan arguments remain redacted as today.

For mention-backed target, frozen canonical data may include:

- candidate key;
- exact extracted/display name;
- target/evidence kind;

but must not freeze arbitrary body text.

## Execute / approve behavior

Execution runs under the existing user serialization lock.

For a mention-backed selected row:

1. re-run normal Person resolution for the extracted name;
2. if resolution is no longer `none`, fail `role_import_grounding_changed`;
3. re-run exact-display identity-backed participant eligibility;
4. if a stronger identity-backed candidate is now available, fail `role_import_grounding_changed` so the user can reground and choose the stronger target;
5. re-run mention evidence;
6. require the same exact candidate key/display and >= threshold;
7. if evidence is no longer sufficient, fail `role_import_grounding_changed`;
8. create exactly one Person via canonical `PersonIdentityService.create_person(display_name)`;
9. **do not attach any PersonIdentity**;
10. assign the selected role atomically in the existing batch transaction.

Multiple selected rows for the same mention-backed candidate in one batch must reuse the same newly created Person, as identity-backed promotion already does.

No duplicate Person under concurrent approval.

Reject/expiry writes nothing.

If a later row fails, the whole ActionPlan transaction rolls back including the newly created name-only Person.

## No false identity claim

This task must never infer an email/user id from:

- body text;
- subject;
- title;
- email local-part;
- co-occurrence;
- search ranking;
- role/org source.

Do not attach a `PersonIdentityEvidence` row for mention-only evidence because there is no exact identity tuple to confirm.

Do not create a synthetic identity.

## Generic promotion remains unchanged

Do not change semantics of:

- `MIN_DIRECT_HITS = 2`;
- `PersonPromotionService.overview()`;
- `eligible_direct_contacts()`;
- generic `approve()`;
- HG1.4 one-hit identity participant rule;
- self/owned/suppression gates.

Mention-backed fallback is role-import-only.

## Recipient-normalization issue is out of scope

Do not change Gmail/Yandex normalization in this task.

D1 showed that recipient display-name loss was **not proven as the root cause for this target**.

The known fact that Gmail/Yandex currently store `To/Cc` as bare addresses may be recorded as deferred connector debt, but do not broaden this corrective into connector resync/backfill.

## Required backend tests

Add focused tests proving at minimum:

1. normal resolution `none` + 2 distinct exact full-name communication Objects => one mention-backed candidate;
2. 1 distinct Object with many repeated occurrences => no candidate;
3. 2 Objects with only substring/partial-name matches => no candidate;
4. single-token extracted name => no mention-backed candidate;
5. case/whitespace normalization works;
6. title exact phrase counts;
7. body exact phrase counts;
8. email metadata subject exact phrase counts;
9. identity-backed exact-display participant candidate supersedes mention fallback;
10. source-only row with no communication evidence remains omitted;
11. mention-backed candidate contains no identity tuple;
12. mention-backed candidate prepare is allowed only after explicit selection;
13. approve creates one Person + selected role and zero PersonIdentity rows for that Person;
14. reject creates no Person/role;
15. evidence falls below threshold between prepare and approve => `role_import_grounding_changed`, no write;
16. stronger identity-backed candidate appears between prepare and approve => grounding changed, no name-only Person;
17. Person with same exact title appears between prepare and approve => grounding changed, no duplicate;
18. two selected rows for same name candidate create one Person and both role assignments as appropriate;
19. later-row failure rolls back mention-created Person and assignments;
20. resolved existing Person with zero identity-attributable count but >=2 exact-name mention Objects remains actionable only when Person title exact-matches extracted name;
21. ambiguous candidates with zero identity counts use mention fallback only for exact-title candidates and remain ambiguous;
22. variant/different-title ambiguous candidate is not blessed by name mention;
23. generic promotion tests remain unchanged and green;
24. HG1.4 participant tests remain green;
25. no provider/model call occurs.

Run at minimum:

- `backend/tests/test_rel1d_role_import_grounding.py`
- `backend/tests/test_rel1d_role_import_batch.py`
- `backend/tests/test_rel1d_role_import_participants.py`
- directly affected generic promotion tests
- new mention-evidence focused tests
- Ruff on touched Python
- `git diff --check`.

## Required client tests

Update focused client fixtures/tests to prove:

1. mention-backed candidate is visibly distinguished from identity-backed candidate;
2. visible text says identity/contact is unknown/not attached;
3. evidence count shown as communication messages/objects, not “direct hits”;
4. raw identity/candidate key/Object ids remain absent from visible UI;
5. explicit choice + checkbox is still required;
6. ActionPlan card distinguishes mention-backed new Person safely;
7. empty state remains correct;
8. HG1.3 scroll/auto-follow tests remain green.

Run at minimum:

- `client/test/assistant/role_import_preview_test.dart`
- `client/test/assistant/role_import_plan_test.dart`
- `client/test/assistant/role_import_scroll_test.dart`
- focused `flutter analyze` on touched client source/tests.

## Explicit non-goals

Do not:

- add fuzzy name matching;
- bind identity from text;
- change global Person resolution;
- change generic promotion thresholds;
- change Personal Relevance/salience communication attribution;
- add schema/migrations;
- change dependencies;
- change connectors or resync providers;
- deploy backend;
- move `production`;
- build/install client;
- call provider/model APIs;
- mutate production product data;
- start another product slice.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG1.5` entry to `PROJECT_STATE.md` with:
   - implementation SHA;
   - files changed;
   - exact mention threshold/matching semantics;
   - new candidate/approval behavior;
   - confirmation no identity is invented/attached for mention-only candidate;
   - exact backend/client test totals;
   - Ruff/analyze/diff-check results;
   - confirmation generic promotion/HG1.4 participant semantics unchanged;
   - confirmation no deploy/install/migration/provider/model/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG1.5 implementation SHA;
   - source ready for Architect review;
   - production/backend/client remain `67e8f14ba7ced8408086bd1ea57c2fa9f7b049dc`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - do not rollout or start another slice.

3. commit + push to `main`.

4. STOP.

On blocker, record the exact bounded blocker, return HOLD, commit/push accurate ledger if appropriate, and STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
