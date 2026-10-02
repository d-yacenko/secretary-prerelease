# Current task — HOLD

AH2-PER1 is **ARCHITECT SOURCE-ACCEPTED** and waiting for manual real-product behavior acceptance. Do not start another Executor slice from this HOLD.

## AH2-PER1 — conservative Russian name-variant candidate suggestion

- Implementation: `ece2bdfd8a3b80e8ab5fc438372408429253e7ac`
- Executor HOLD: `6efcb6b914a9526bd679211aa8690950e3c2a613`
- Source acceptance: 2026-10-02
- Production remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Alembic remains `0052 / 0052`
- Health remains PASS

## Architect source acceptance

Accepted invariants:

- `Оля/Оли/Ольги Володько` can produce `Ольга Володько` only as a `name_variant` suggestion;
- variant-only output is `state=ambiguous`, `person_id=null`, even with one candidate;
- exact identifier/title/name matching runs before the variant fallback;
- surname must match exactly and the only added family is the explicit Olga family;
- there is no fuzzy edit-distance, embedding, transliteration, phonetic, prefix, or surname-morphology matching;
- the variant lookup is read-only and does not create/merge People or write identity/evidence/alias state;
- `requested_by_person_id`, `delegated_to_person_ids`, `waiting_on_person_ids`, and `involved_person_ids` now require a Person resolved with `state=resolved` in the current Assistant turn;
- ambiguous candidate ids remain readable but cannot authorize actor-role mutation;
- `depends_on_task_ids` keeps the existing seen-Task rule;
- exact `Ольга Володько` still permits the canonical R2 `waiting_on` staging path;
- SEM1/STG1 behavior remains unchanged.

## Known stale test debt

`backend/tests/test_person_assistant.py::test_owned_source_identity_is_conflict_not_confirmable` remains red, but source history shows this is pre-existing stale expectation rather than an AH2-PER1 regression.

Relevant provenance:

- `93dd1e923dfd8df2860db390bf81cf8a0cc80802` — "Ground occupied-identity merge suggestions only in explicit evidence." It intentionally stopped display-name proposals / weak evidence from surfacing an occupied identity unless grounded by stronger evidence.
- `backend/tests/test_person_assistant.py` was not updated by that semantic change; its recent history predates `93dd1e9...`.
- current failing fixture has only the display-name-shaped source and an identity owned by another Person, so the current `_grounded_duplicate` contract intentionally returns no candidate.

Do not weaken the grounded-duplicate safety rule to make this stale test pass.

This stale test should be cleaned up in a later test-hygiene slice, after the manual PER1 behavior gate.

## Deterministic evidence

Executor reported:

- `test_ah2_per1_name_variants.py`: 13 passed
- `test_task_relations.py`: 9 passed
- `test_ah2_sem1_relation_boundary.py`: 4 passed
- `test_ah2_stg1_staging_truth.py`: 7 passed
- `test_ah2d_task_tool_descriptions.py`: 3 passed
- P1/R2 filtered eval: 3 passed
- `test_person_assistant.py`: 35 passed, 1 stale failure described above
- `git diff --check`: clean
- model calls: 0
- real network calls: 0
- schema/deploy/production: unchanged

## Manual real-product gate

Executor does not perform this gate.

Use an existing Task context and send exactly:

`Жду ответ от Оли Володько по черновику`

Expected first-turn behavior:

- no approval card;
- no Task mutation;
- no `waiting_on` relation yet;
- Secretary names `Ольга Володько` as a candidate;
- Secretary asks whether that is the intended Person;
- it does not claim that `Оли` and `Ольга` are already the same identity.

Do **not** continue to the confirmation turn until the first-turn behavior is reviewed.

After first-turn manual evidence is accepted, the Architect will give the next single test step.

## HOLD

Do not start:

- Scheduled Activity Today/Week/mobile integration;
- stale-eval/test-hygiene maintenance;
- production rollout;
- another remediation slice.

Wait for Architect authorization after manual AH2-PER1 behavior acceptance.
