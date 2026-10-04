# CURRENT_TASK

ACTIVE

## REL1D-HG1.4 — role-import communication-participant candidate discovery

REL1D-HG1.3 is **ARCHITECT SOURCE-ACCEPTED** at:

`556c1ed3fff6963404b00da4251f48f3d63a59d6`

Do not deploy/install HG1.3 yet. The Architect is batching it with this backend/client corrective before the next controlled rollout.

Human REL1D acceptance exposed a grounding false negative: an extracted organization-chart name can have many stored communications in Secretary, including being a sender/author or explicit recipient, yet current role-import grounding omits it when the person is not already in the Person graph because the not-yet-Person path is limited to generic `eligible_direct_contacts()` / repeated direct inbound promotion.

The product rule remains:

**An organization chart/roster is role evidence, not an independent source of Person existence.**

But for role import, a strong identity-bearing participant in already stored communications is sufficient independent evidence to offer an explicit user-confirmed Person promotion, even when generic People promotion would not yet expose that contact.

This task is ONLY that role-import-specific participant discovery + approval revalidation, plus the minimum client wording/count adaptation.

Do not deploy backend, move `production`, run Alembic, build/install the Linux client, perform the human gate, call a real model/provider, or mutate production product data.

## Core architectural constraints

### Generic promotion stays unchanged

Do **not** change the semantics of:

- `PersonPromotionService.overview()`
- `PersonPromotionService.eligible_direct_contacts()`
- generic `PersonPromotionService.approve()`
- `MIN_DIRECT_HITS`
- generic direct-contact ranking/suppression behavior.

The ordinary People promotion surface must remain exactly as safe/strict as before.

If shared helpers are refactored, focused tests must prove generic promotion behavior is unchanged.

### Role-import-specific participant path

Add a bounded, read-only role-import participant candidate path.

A not-yet-Person extracted name may become a role-import promotion candidate when:

1. the source organization-chart name matches a **display name carried by a stored communication participant identity** after the existing conservative whitespace/casefold display normalization; and
2. that participant has an exact normalized identity tuple that can be attached to a Person; and
3. the identity is not the user's own identity, is not suppressed/rejected, and is not otherwise unsafe to promote; and
4. at least **one** qualifying stored communication participant hit exists in the bounded scan.

One strong identity-bearing communication participant hit is sufficient **for role import only** because:
- the communication is already stored;
- the independent role source supplies a second piece of evidence;
- the user still makes an explicit row selection;
- durable creation remains approval-gated.

Do not lower generic `MIN_DIRECT_HITS`.

## Qualifying participant evidence

Use only first-party stored `email` / `chat_message` metadata. No live provider calls.

Qualifying evidence should include, where exact identity + display name are available:

### Email (Gmail / Yandex)

- inbound sender/from;
- outbound or inbound explicit recipients in existing recipient/to metadata;
- CC participants;
- reply-to only when it is represented as a parseable exact email participant with its own display name.

For each participant, require:
- parseable normalized email identity;
- a non-empty participant display name from the envelope/header value;
- exact normalized display-name equality to the extracted organization-chart name.

Do not infer a person from a bare email address whose display name is absent.

Do not treat arbitrary names in subject/body as participant identities.

### Mattermost

- message author identity using existing exact author user-id/username metadata;
- author display name must be present and exactly match the extracted name;
- both DM and channel/group authors may qualify.

### Teams

- stored user sender identity using tenant + sender id;
- sender display name must be present and exactly match the extracted name;
- oneOnOne and group/channel sender participation may qualify;
- do not treat non-user/system senders as people.

### Telegram MTProto

- inbound sender user identity in private or group/channel messages when an exact sender user id and stored sender display name are available;
- for an outbound private conversation, the private peer may qualify only when exact peer user id + stored peer display/title represent the remote person;
- never treat a group/channel peer id/title itself as a Person candidate;
- preserve the existing Telegram first-party/AI quarantine gates used by Assistant-facing Person scans.

If current normalized metadata does not provide a safe display+identity pair for one of these cases, fail closed for that case rather than guessing.

## Explicitly non-qualifying evidence

Do not create a role-import promotion candidate from:

- arbitrary body-text name mentions;
- subject/title text;
- search-result text snippets;
- fuzzy/semantic name similarity;
- organization-chart content alone;
- a display name with no exact attachable identity;
- provider/group/channel titles that are not a person identity.

A body mention may explain why Search finds a name, but it is not sufficient to create a new Person in this task.

## Existing-Person behavior

Preserve HG1.2 semantics for names that normal `PersonAssistantService.resolve(name)` resolves to graph People:

- resolved Person requires positive bounded attributable communication count;
- ambiguous Person candidates are filtered to positive communication counts;
- even one surviving ambiguous graph candidate remains explicit-choice and is not silently resolved;
- if graph candidates existed but all fail the communication gate, omit the row and do not fall through to a new Person candidate.

Do not redesign global Person resolution.

## Identity already belongs to an existing Person

The new participant scan must not create duplicate People.

If a qualifying participant identity is already bound/effectively owned by an active Person:

- do not expose it as a new-Person promotion candidate;
- if normal name resolution already surfaced that Person, use the existing-Person path;
- otherwise fail closed / omit rather than silently binding a differently named extracted row to that Person in this task.

No automatic alias creation.

## Bounded scan

Reuse the existing Person communication bounds/gates where practical:

- `PERSON_LOOKBACK_DAYS`
- `MAX_PERSON_SCAN_ROWS`
- active/non-rejected stored communication objects;
- existing Telegram AI predicate/gate.

The scan is bounded evidence, not a lifetime claim.

A positive qualifying hit is usable even if the overall scan is truncated.
A zero result under truncation means only “not proven in this bounded scan” and must remain omitted.

No provider call.

## Candidate model / privacy

Prefer the existing role-import promotion UI shape and candidate-key contract where possible.

The candidate key must continue to be derived from the exact normalized identity and must remain internal/frozen; do not expose raw email/user ids/realm/provider identifiers beyond the already-safe provider label.

The public UI may show:

- display name;
- provider category/label;
- a bounded communication evidence count.

For wire/backward compatibility, retaining the existing `direct_hit_count` JSON field is acceptable even if the internal role-import-specific candidate model calls this `participant_hit_count` / `communication_hit_count`. Do not break the currently deployed old client during backend-first rollout.

Do not expose:
- raw email addresses;
- usernames/user ids;
- candidate keys in visible text;
- provenance keys;
- normalized identity tuple.

Update Russian UI wording if needed so it does not claim that every count is a direct-message count.

## Approval / frozen ActionPlan must work end-to-end

This is mandatory.

Current batch execution re-fetches `eligible_direct_contacts()` and calls generic `promotion.approve()`. That is not sufficient for the wider role-import participant path.

Add a dedicated role-import participant revalidation/approval path such that:

1. grounding exposes only currently qualifying participant candidates;
2. prepare freezes only the candidate key + safe display as today; public ActionPlan arguments remain redacted;
3. execute revalidates the exact candidate key + exact display name against the **role-import participant scan**, not generic `eligible_direct_contacts()`;
4. if evidence disappeared/changed, fail with the existing grounding-changed style behavior rather than creating a Person;
5. durable Person creation + exact identity attachment occur only during approved ActionPlan execution;
6. the identity is rechecked for ownership/conflict under the existing user serialization lock;
7. suppression/owned identity protections remain effective;
8. no duplicate Person is created under races;
9. role assignment remains atomic with the batch;
10. generic promotion approval behavior is untouched.

A dedicated method such as `eligible_role_import_participants()` / `approve_role_import_participant()`, or a small dedicated service, is preferred over weakening the generic promotion methods.

## Grounding result behavior

For normal-resolution state `none`:

- match the extracted name against role-import participant candidates by exact normalized display name;
- if exactly/one or more identity candidates match, return `promotion_candidates` and keep explicit user choice;
- cap candidates using the existing role-import promotion cap;
- deterministic order by stable candidate key;
- preserve original extraction `row_index`.

If there is no qualifying participant candidate, omit the row as HG1.2 does.

RoleTerm reuse/propose-new semantics remain unchanged.

## Client wording

Preserve the existing explanation that only communication-backed people are shown.

For a role-import promotion candidate:
- keep the explicit warning that a new Person is created only after confirmation;
- show safe display name + provider + communication evidence count;
- do not call the count “direct hits” in visible Russian text;
- raw identities remain hidden.

No UI redesign beyond the minimum text/model adaptation.

## Required backend tests

Extend focused tests to prove at minimum:

1. unknown extracted name + one inbound email sender with exact display name/email => participant promotion candidate;
2. unknown extracted name + one outbound email recipient with exact display name/email => participant promotion candidate;
3. email CC participant with exact display name/email => participant promotion candidate;
4. bare recipient email without matching display name => no candidate;
5. body-text-only mention of exact extracted name => no candidate;
6. Mattermost group/channel author with exact display + identity => candidate;
7. Teams group sender with exact display + identity => candidate;
8. Telegram group/private sender with safe display + user id => candidate where current Telegram gate allows it;
9. group/channel title alone => no Person candidate;
10. generic `eligible_direct_contacts()` still requires the historical threshold and is unchanged;
11. generic `approve()` behavior remains unchanged;
12. role-import participant candidate can be prepared and approved end-to-end;
13. approval creates exactly one Person + exact identity + selected role assignment;
14. participant candidate evidence removed between prepare and approve => no Person/role write and deterministic stale/validation failure;
15. participant identity already bound to a Person => no duplicate Person;
16. suppression/owned identity blocks role-import promotion;
17. multiple participant identities with the same exact display name remain explicit candidates, never auto-chosen;
18. original `row_index` survives filtering;
19. no provider/model call occurs during participant discovery/grounding/approval.

Keep existing HG1.2 existing-Person tests green.

Run at minimum:
- `backend/tests/test_rel1d_role_import_grounding.py`
- `backend/tests/test_rel1d_role_import_batch.py`
- directly affected promotion/person tests
- focused tests for any new participant helper/service
- Ruff on touched backend Python
- `git diff --check`

## Required client tests

Update focused fixtures/tests only as needed to prove:

- role-import participant candidates render with safe display/provider/evidence count;
- raw identity/candidate key remains absent from visible UI;
- explicit candidate choice is still required before row selection;
- existing communication-backed empty state still works;
- HG1.3 scroll/auto-follow tests remain green.

Run at minimum:
- `client/test/assistant/role_import_preview_test.dart`
- `client/test/assistant/role_import_plan_test.dart`
- `client/test/assistant/role_import_scroll_test.dart`
- focused `flutter analyze` on touched client source/tests.

## Explicit non-goals

Do not:

- use full-text Search as identity proof;
- treat arbitrary body mentions as promotable people;
- add fuzzy/LLM matching;
- change extraction model/prompt;
- change generic People promotion threshold;
- change global Person resolution;
- add migrations/schema;
- change dependencies;
- deploy backend;
- move `production`;
- build/install client;
- make real model/provider calls;
- mutate production product data;
- start ORG1 or another product slice.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG1.4` entry to `PROJECT_STATE.md` with:
   - implementation SHA;
   - files changed;
   - exact participant evidence rules implemented;
   - confirmation generic promotion/`MIN_DIRECT_HITS` unchanged;
   - approval revalidation path;
   - exact backend/client test totals;
   - Ruff/analyze/diff-check results;
   - confirmation no deploy/install/migration/model/provider/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG1.4 implementation SHA;
   - HG1.3 and HG1.4 are ready for Architect source review;
   - production/backend/client remain `1879aabc97bfc5ed13fbc2ffa4d0c9c7ccbb3320`;
   - Alembic remains `0054 / 0054`;
   - human acceptance remains paused;
   - do not rollout or start another slice.

3. commit + push to `main`.

4. STOP.

On blocker, record the exact bounded blocker, return HOLD, commit/push accurate ledger if appropriate, and STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
