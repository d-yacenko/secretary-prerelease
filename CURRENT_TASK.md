# Current task — Graph Refined P2: explainable identity evidence + candidate scoring

Graph Refined P1/P1R is accepted. Build the next narrow layer: persistent, explainable evidence and deterministic candidate scoring for Person resolution.

Do not implement automatic Person merge, automatic identity attachment from weak evidence, Flutter UI, Assistant lookup, send-by-person, voice/media ingestion, or Task Graph refinement in this task.

Do not deploy. Production remains on Alembic `0047`; migrations `0048` and the new migration from this task remain development-only.

## Goal

Represent *why* Secretary thinks an endpoint/alias may belong to a Person, and derive a bounded candidate score from those facts.

Do not store one opaque probability that is mutated in place. Store evidence records with provenance and derive the current candidate score from active evidence.

The model must support future interaction learning:
- exact/provider facts;
- profile/directory facts;
- graph/context similarity;
- LLM suggestion as weak evidence only;
- user route choice;
- explicit user confirmation;
- explicit user rejection/correction.

## 1. Persistent evidence ledger

Add the smallest additive schema after `0048` for Person identity evidence.

Prefer a dedicated table such as `person_identity_evidence` with enough fields to express:
- user_id;
- target Person;
- candidate identity tuple (provider, identity_type, realm, canonical_value) OR an existing person_identity_id when evidence concerns an attached identity;
- evidence_type;
- polarity: positive / negative;
- weight/strength category or bounded numeric contribution;
- provenance/source kind;
- optional source_object_id or related provider fact reference;
- optional bounded explanation/details metadata;
- active/retracted state;
- timestamps.

Hard invariants:
- strict user isolation;
- Person target belongs to same user and is kind `person`;
- evidence cannot contain provider secrets/tokens/session data;
- evidence is append/history friendly: corrections should retract/supersede prior evidence, not rewrite history invisibly;
- deleting a source communication object must not silently destroy the derived decision history if the evidence needs to remain auditable; use safe FK semantics.

Do not alter historical migrations.

## 2. Evidence taxonomy and strengths

Define a small explicit taxonomy, for example:
- `exact_identifier`
- `provider_profile`
- `name_similarity`
- `organization_match`
- `graph_context`
- `llm_suggestion`
- `user_route_choice`
- `user_confirmed`
- `user_rejected`

You may refine names, but keep the semantics explicit and centralized.

Required policy:
- `user_confirmed` is the strongest positive evidence.
- `user_rejected` is a strong negative veto for the same Person/candidate identity pair and should suppress the same proposal until explicitly reversed.
- exact identifier/provider-profile evidence is stronger than fuzzy/name/context evidence.
- `user_route_choice` is positive evidence but must NOT be equivalent to explicit identity confirmation.
- LLM-derived evidence alone must never be sufficient for automatic attachment/merge.
- display-name/name similarity alone must never be sufficient for automatic attachment/merge.

## 3. Deterministic candidate scoring service

Add a pure/domain service that, for one candidate identity and one Person:
- loads active evidence;
- computes an explainable bounded score/confidence;
- returns the component contributions/reasons;
- returns a resolution state such as `confirmed`, `likely`, `possible`, `rejected`, or equivalent.

The exact formula may be simple and deterministic; do not train a model.

Requirements:
- user-confirmed positive => confirmed;
- user-rejected active veto => rejected regardless of weaker positive evidence;
- route-choice alone must remain below confirmed;
- name-similarity alone remains below any automatic-link threshold;
- repeated duplicate evidence from the exact same source/provenance must be idempotent or deduplicated so score cannot inflate by replay;
- contradictory evidence is visible in the explanation;
- score/result is reproducible from ledger rows.

Do NOT perform any automatic Person merge or identity attach in this task, even for high scores. P2 only ranks/explains candidates.

## 4. Candidate generation helpers

Add small deterministic helpers to propose candidate Persons from:
- existing exact identity resolution;
- normalized display/name aliases on Person titles and identity display values;
- optional bounded graph/context overlap if an existing deterministic service already exposes it cheaply.

Keep generation conservative:
- exact identity may identify one Person directly;
- textual similarity produces candidates only;
- do not create new Person objects automatically;
- do not call a live provider;
- no LLM/provider call is required for P2 tests.

If adding fuzzy text matching, use deterministic normalization and a bounded simple metric. Do not introduce a new external search service or vector DB.

## 5. Interaction feedback API at domain-service level

Add service methods suitable for future Assistant/voice use:
- record route choice evidence;
- record explicit confirmation;
- record explicit rejection/correction;
- retract/supersede mistaken feedback safely.

For now this may remain domain/backend only; no Flutter surface is required.

Important:
- choosing a route records `user_route_choice`, not `user_confirmed`;
- explicit “yes, this Telegram/email/account is Olga” records strong confirmation;
- explicit “no, this is another Olga” records strong rejection and prevents the same mistaken suggestion from recurring;
- a later explicit reversal must be possible and auditable.

## Focused proof

Add focused tests proving at minimum:
1. Evidence rows are user-isolated and Person-target validated.
2. Exact/provider evidence contributes more than name/context-only evidence.
3. Name similarity alone never yields confirmed.
4. Route choice raises confidence but does not yield confirmed.
5. Explicit confirmation yields confirmed.
6. Explicit rejection vetoes weaker positive evidence.
7. Repeated identical source evidence does not inflate score.
8. Reversal/retraction of user feedback is auditable and recomputes the score correctly.
9. Contradictory evidence appears in the explanation/components.
10. Same candidate identity may score differently for two different People, without attaching/merging either.
11. No automatic Person merge or PersonIdentity attach occurs anywhere in this task.
12. Existing P1/P1R identity and provider-evidence tests remain green.
13. Migration path from `0048` to the new head and back to `0048` works.

Run the smallest relevant backend tests, Ruff/compile on touched Python, and `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose P3 and do not deploy.
