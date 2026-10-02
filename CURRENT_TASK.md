# Current task — HOLD

AH2-PER1 is implemented and waiting for Architect review. Do not start the next slice from this HOLD.

## AH2-PER1 — conservative Russian name-variant candidate suggestion without identity assertion

- Implementation: `ece2bdfd8a3b80e8ab5fc438372408429253e7ac`
- AH2-SEM1 remains ARCHITECT SOURCE-ACCEPTED at `2b52524dd3d0a4426f4c9fdf45759c7584a88497` (HOLD `9c998034b03001e7e91d800433befb5d44a7b06d`, ledger `a04e2da70a0b2534bd1902814e2763b136410b4c`)
- Production remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Alembic remains `0052 / 0052`
- Health remains PASS

## Changed files

- `backend/app/domain/person_candidate_names.py`
- `backend/app/services/person_assistant_service.py`
- `backend/app/assistant/tool_runner.py`
- `backend/app/tools/assistant_contracts.py`
- `backend/app/llm/openai_assistant_provider.py`
- `backend/tests/test_ah2_per1_name_variants.py`
- `backend/tests/test_task_relations.py`
- `backend/tests/test_ah2m_eval_runner.py`

## Name-variant matching boundary

`name_variant_match` requires exactly two tokens on both the query and the Person title. The surname token must match exactly after the existing Unicode casefold. The given names must differ and both belong to the same explicit family. The only family in this slice is Olga: canonical/case forms `ольга`, `ольги`, `ольге`, `ольгу`, `ольгой` and diminutive/case forms `оля`, `оли`, `оле`, `олю`, `олей`. Identical given name plus surname is an exact title, not a variant. There is no Levenshtein, embedding, transliteration, phonetic match, prefix match, or surname morphology. The lookup reads Person titles only and runs only after exact identifier, exact title/alias, and `names_match` / `propose_candidates` find nothing.

## Suggestion-only state

A variant hit returns `ResolvePersonOutput.state=ambiguous` even when exactly one candidate remains. `person_id` stays null. The candidate reason is `name_variant`. No new resolved state was added. The candidate does not stage a mutation or an approval. Instructions tell the model to name the canonical title and ask for confirmation. After an explicit later confirmation, `resolve_person` must be called again with that canonical title or an exact identifier. A yes does not persist a nickname alias. No confirm-alias tool was added. The lookup writes no Person, PersonIdentity, PersonIdentityEvidence, route, or merge.

## Actor-role resolved-Person guard

`requested_by_person_id`, `delegated_to_person_ids`, `waiting_on_person_ids`, and `involved_person_ids` require a Person returned by `resolve_person` with `state=resolved` in the current turn (`_resolved_person_ids`). An ambiguous candidate id stays visible for read/inspection and is rejected for those fields with `person was not resolved in this Assistant turn`. `depends_on_task_ids` still uses the seen-object rule. Existing communication and route flows that already require a resolved Person are unchanged.

## Negative cases

`Оля Володько`, `Оли Володько`, and `Ольги Володько` against title `Ольга Володько` stay suggestion-only. `Оли Иванова`, `Олег Володько`, and a bare `Оли` return `none`. Exact title `Оли Володько` resolves that Person, not the `Ольга` candidate. Two canonical `Ольга Володько` people stay ambiguous and both ids are returned. After the model-visible commit, a `name_variant` candidate cannot stage `waiting_on`. An exact resolved `Ольга` can. All four actor fields reject the ambiguous id. Person, PersonIdentity, and PersonIdentityEvidence row counts stay unchanged.

## Checks

- `test_ah2_per1_name_variants.py`: 13 passed
- `test_person_assistant.py`: 35 passed, 1 failed (`test_owned_source_identity_is_conflict_not_confirmable`, the previously recorded empty owned-identity candidate list; this slice did not edit that path)
- `test_task_relations.py`: 9 passed
- `test_ah2_sem1_relation_boundary.py`: 4 passed
- `test_ah2_stg1_staging_truth.py`: 7 passed
- `test_ah2d_task_tool_descriptions.py`: 3 passed
- those six together: 71 passed, 1 failed
- `test_ah2m_eval_runner.py` filtered to P1 and R2: 3 passed, 42 deselected
- `git diff --check` clean

Model calls: 0. Real network calls: 0. No schema change. No deploy. The stale-date M1 fixture and the production-parity guard were not edited.

Manual confirmation of «Жду ответ от Оли Володько» remains a human gate after Architect source acceptance.
