# Current task — Graph Refined P4: bounded identity enrichment orchestration

Graph Refined P1/P2/P3 are architect-accepted. Implement the next narrow layer: bounded orchestration that decides **which already-known People / candidate identities are worth deeper identity resolution**, using exact provider facts, P2 evidence, and P3 salience.

Do not add live provider directory/profile calls in this task. Do not add UI, Assistant Person lookup, send-by-person, auto-merge, proactive behavior, voice/media, or Task Graph redesign. Do not deploy.

## Goal

Turn the existing foundations into a provider-neutral resolution queue/candidate plan without exploding work across every incidental sender.

P4 should answer questions such as:
- which People should be actively enriched/resolved now;
- which unresolved provider identities are worth investigating;
- why they were selected;
- which safe deterministic evidence can be attached now from existing canonical metadata;
- which cases need future provider lookup or user confirmation.

Do not perform external provider calls or LLM calls in this task.

## 1. Bounded enrichment candidate model

Add a domain/service representation such as `PersonEnrichmentCandidate` / `PersonResolutionPlan` containing at minimum:
- target Person id when already known;
- candidate identity tuple if relevant;
- source/provider;
- reason(s);
- current P2 assessment/state;
- current P3 salience/tier when applicable;
- recommended next step enum such as:
  - `attach_exact`
  - `record_provider_evidence`
  - `needs_confirmation`
  - `needs_provider_lookup`
  - `ignore_for_now`
- bounded provenance/source object references;
- truncation/budget metadata.

This is planning/orchestration only, not a UI contract.

## 2. Promotion policy

Use P3 salience to allocate identity-resolution budget.

Required behavior:
- high-salience/known People with incomplete cross-provider identity coverage are preferred;
- explicit Assistant/user attention from P2 may promote a candidate even with low communication volume;
- direct/reciprocal interaction may promote a candidate;
- public/broadcast-only incidental exposure should normally remain `ignore_for_now`;
- unknown authors in noisy channels do not automatically become Person Objects;
- salience is a prioritization feature, not proof of identity.

Do not introduce a visible VIP list.

## 3. Existing-fact enrichment only

Use only facts already stored in canonical Objects / PersonIdentity / PersonIdentityEvidence.

Examples:
- email address from canonical email metadata;
- Mattermost author user id/username/display name/server realm;
- Teams human sender id/display name/tenant;
- Telegram MTProto positive user id/account realm;
- exact existing Person identities and P2 evidence.

Do not fetch remote profiles/directories in P4.

Where an exact strong identity already resolves to an existing Person, orchestration may recommend/perform only the safe deterministic bookkeeping needed to keep evidence complete. It must not merge another Person silently.

Where only display-name similarity exists, produce a candidate/confirmation need, never auto-attach.

## 4. Safe deterministic attachment boundary

P4 may auto-attach a new exact provider identity to an existing Person only if one of these holds:
- the exact identity already resolves to that Person;
- there is an accepted deterministic bridge whose semantics are already explicit and collision-safe in current data;
- explicit `user_confirmed` evidence for that Person/identity exists.

Otherwise:
- produce candidate/evidence;
- do not attach;
- do not merge People.

A high numeric P2 score alone is NOT authorization to attach unless backed by the allowed deterministic bridge or explicit confirmation.

Any conflict with an identity already owned by another active Person must fail closed and produce a conflict/candidate state.

## 5. Cross-provider coverage view

For a bounded set of active People, compute which communication providers/identity kinds are already known and which are absent.

This coverage map is for orchestration only.

Examples:
- Olga has email + Mattermost, no Teams/Telegram identity yet;
- Maxim has Teams + Telegram, no email.

Do not assume a missing provider identity exists.

## 6. Candidate discovery from recent canonical communication

Within explicit bounded windows/budgets:
- scan recent canonical communication metadata;
- extract exact provider identities using the P1/P1R extractors;
- if exact identity already belongs to a Person, update/record explainable provider/exact evidence idempotently;
- if unresolved, compare only against bounded existing Person candidates using P2 candidate generation;
- use P3 salience/user-attention to decide whether unresolved evidence deserves a `needs_confirmation` / future lookup candidate or should be ignored for now.

Do not create Person for every unresolved identity.

## 7. Idempotency and explainability

Repeated orchestration over unchanged source data must:
- not create duplicate evidence;
- not inflate score;
- not create duplicate PersonIdentity rows;
- return deterministic ordering;
- retain provenance explaining why a candidate was selected or skipped.

Prefer reusing P2 provenance keys derived from source object/provider identity.

## 8. Telegram posture

Treat Telegram as provider-neutral for deterministic identity metadata.

Keep `TELEGRAM_MTPROTO_AI_ENABLED` untouched. No LLM/embedding/provider transmission is involved here.

Do not hardcode `TestML`.

## 9. No live provider lookup yet

If current stored facts are insufficient, emit `needs_provider_lookup` or equivalent future action rather than calling:
- Mattermost user/profile endpoints;
- Microsoft Graph profile/directory endpoints;
- Telegram contact/profile endpoints;
- Gmail/Yandex contacts/directories;
- any LLM.

A later phase can add bounded live enrichment per provider behind explicit contracts and rate/security rules.

## Focused proof

Add tests proving at minimum:
1. High-salience known Person with incomplete provider coverage is ranked ahead of incidental/public-only Person.
2. User-confirmed low-volume Person may still enter enrichment candidates.
3. Public-channel-only unknown author does not create Person.
4. Exact existing identity produces deterministic evidence/bookkeeping without duplicate identity creation.
5. Explicit user confirmation may authorize exact attach to that Person.
6. Name similarity alone yields `needs_confirmation` and never attaches.
7. Identity already owned by another Person fails closed.
8. Repeated orchestration is idempotent: no duplicate evidence/identity, stable ordering.
9. Rejected/deleted/cross-user People and identities are excluded.
10. Coverage view reports known provider identities and missing provider categories without inventing identities.
11. Candidate/source scans are bounded and truncation is explicit.
12. No live provider/LLM/job/UI/downstream action is introduced.
13. Existing P1/P2/P3 focused tests remain green.

Prefer no migration unless truly necessary. Reuse existing `person_identities`, `person_identity_evidence`, canonical Objects, and read-time salience.

Run focused Graph Refined tests, Ruff/compile for touched Python, and `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose P5 and do not deploy.
