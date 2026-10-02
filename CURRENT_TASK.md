# Current task — ACTIVE

## AH2-PER1 — conservative Russian name-variant candidate suggestion without identity assertion

Architect review before this authorization:

- AH2-SEM1 implementation: `2b52524dd3d0a4426f4c9fdf45759c7584a88497`
- AH2-SEM1 HOLD: `9c998034b03001e7e91d800433befb5d44a7b06d`
- AH2-SEM1: **ARCHITECT SOURCE-ACCEPTED**
- production remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Alembic remains `0052 / 0052`

AH2-SEM1 acceptance basis:

- closed Task relation vocabulary is now explicit in interactive Assistant instructions;
- actor roles remain exactly `requested_by`, `delegated_to`, `waiting_on`, `involves`;
- generic `link_objects` relations remain exactly `related_to`, `references`, `depends_on`, `part_of`;
- unsupported relation requests are explicitly not to be coerced into supported roles;
- T3 remains mutation-free and without approval;
- no ontology/schema/runtime mutation behavior was changed.

Known unrelated checks remain outside this slice:

1. the fixed-date M1 fixture can fail because its absolute `run_at` is now in the past;
2. the production-code parity guard is expected to fail while accepted remediation on `main` has not yet been rolled out.

Do not weaken either guard.

## Problem observed in manual acceptance

R2 worked when the exact canonical Person name was supplied:

`Ольга Володько`

But ordinary Russian forms did not produce a useful candidate:

- `Оля Володько`
- `Оли Володько`

The desired product behavior is **not** to auto-resolve or merge these forms.

The desired behavior is:

`Нашёл «Ольга Володько». Вы имеете в виду этого человека?`

Only after explicit user confirmation should the Assistant proceed with a canonical Person resolution.

## Current source facts

Current Person resolution has three relevant layers:

1. exact email/identifier resolution;
2. exact title/display alias comparison via `_alias_people`;
3. deterministic display-name candidate matching via `names_match`.

`names_match` currently compares normalized token sets and does not understand Russian diminutive/case variants.

Also important:

- `PersonAssistantService._finish()` currently returns `state=resolved` whenever exactly one candidate remains;
- `resolve_person` candidate Person ids are exposed as seen object ids;
- Task actor-role writes currently validate those ids through the generic seen-object allowlist.

Therefore a new variant match must **not** simply flow through the existing single-candidate resolution path, or it would become an implicit identity assertion.

## Goal

Add a narrow, deterministic **candidate-suggestion** path for conservative Russian given-name variants when the surname is exact.

A name variant may help the user find a likely Person, but it must never by itself:

- resolve the Person;
- merge People;
- attach an identity;
- create alias evidence;
- authorize a Task actor-role write;
- authorize a send route.

## Core behavior

### A. Suggestion-only state

For a variant-only name match:

- `ResolvePersonOutput.state` must be `ambiguous`, even if there is exactly one candidate;
- `person_id` must remain null;
- candidate(s) are returned with a distinct bounded reason such as `name_variant`;
- Assistant must ask the user to confirm the candidate;
- no mutation/approval may be staged from that candidate alone.

Do not introduce a new resolved state.

Existing exact identifier/title resolution behavior remains unchanged.

### B. Narrow matching rule

This slice is intentionally conservative.

Add a deterministic helper in the Person candidate-name domain that can recognize a small explicit Russian given-name variant family while requiring an exact surname.

At minimum support the observed Olga family:

- canonical/case forms of `Ольга`;
- diminutive/case forms of `Оля`, including `Оли`.

The exact representation is implementation choice, but prefer a compact explicit family table over fuzzy distance.

For this slice:

- require a multi-token personal name;
- require the surname token to match exactly after existing Unicode/case normalization;
- allow only an explicitly enumerated given-name family match;
- no Levenshtein/edit-distance matching;
- no embeddings;
- no transliteration;
- no phonetic matching;
- no arbitrary prefix matching;
- no surname morphology inference.

The helper may be structured so more explicitly reviewed name families can be added later, but do not turn this slice into a comprehensive Russian morphology dictionary.

### C. Exact match always wins

If the query exactly matches an existing Person title/display alias under current rules, preserve current exact behavior.

Example:

- Person A title: `Оли Володько`
- Person B title: `Ольга Володько`
- query: `Оли Володько`

The exact Person A match must not be replaced by a variant suggestion for Person B.

Variant suggestion is only a fallback after current exact/name matching has produced no valid match.

### D. Negative examples

The variant path must not suggest `Ольга Володько` for:

- `Олег Володько`;
- `Оли Иванова`;
- `Оли` with no exact surname;
- an unrelated near-spelling.

If the surname differs, fail closed.

### E. Structural mutation guard

A Person returned only as an ambiguous/suggestion candidate must not be usable as a Task actor-role target.

Strengthen the Assistant tool boundary so these fields require a Person that was actually returned by `resolve_person` with `state=resolved` in the current turn:

- `requested_by_person_id`;
- `delegated_to_person_ids`;
- `waiting_on_person_ids`;
- `involved_person_ids`.

`depends_on_task_ids` is a Task-to-Task relation and should keep its existing seen-object rule.

Do not remove candidate Person ids from read visibility: the model may still need to inspect/name candidates.

But actor-role mutation must use the dedicated resolved-Person allowlist, not merely the generic seen-object allowlist.

Existing communication/route flows that already require a resolved Person must remain unchanged.

### F. Confirmation flow

Tool instructions must make the intended two-step behavior explicit.

For a single `name_variant` candidate:

1. tell the user which canonical Person candidate was found;
2. ask whether that is the intended Person;
3. do not mutate in the same turn.

After the user explicitly confirms in a later turn, the Assistant should call `resolve_person` using the candidate's canonical displayed title or exact identifier.

Only if that second call returns `state=resolved` may actor-role or communication work proceed.

Do not persist a nickname alias merely because the user said yes in conversational context.

This slice does not add a new "confirm name alias" mutation tool.

### G. No identity side effects

Variant suggestion is read-only.

It must not create or modify:

- `PersonIdentity`;
- `PersonIdentityEvidence`;
- Person objects;
- identity confirmations/rejections;
- route-choice evidence.

It must not merge two Person objects.

## Preferred implementation boundary

Expected files may include:

- `backend/app/domain/person_candidate_names.py`;
- `backend/app/services/person_assistant_service.py`;
- `backend/app/assistant/tool_runner.py`;
- `backend/app/tools/assistant_contracts.py`;
- `backend/app/llm/openai_assistant_provider.py`;
- focused Person/Assistant tests;
- ledger files.

Avoid DB/model changes.

A reasonable shape is:

- preserve current exact + current `names_match` behavior first;
- only when those yield no match, run a dedicated conservative variant-candidate matcher;
- finish that path with forced ambiguity / suggestion-only semantics;
- structurally require `resolved_person_ids` for Task actor-role writes.

Exact function names are implementation choice.

## Explicit non-goals

Do not in AH2-PER1:

- auto-merge People;
- persist aliases;
- create a general fuzzy Person search;
- infer identity from communication frequency or salience;
- change provider identity matching;
- change route selection;
- change P1 two-Person ambiguity semantics;
- change T3 relation ontology;
- change AP1/STG1/FIN1/FIN2;
- add Scheduled Activity to Today/Week/mobile;
- fix stale M1 fixture;
- change production parity guard;
- run a real model;
- deploy or install a client;
- add schema/Alembic migration.

## Required deterministic tests

At minimum prove:

1. **Olga diminutive suggestion**
   - one Person exists as `Ольга Володько`;
   - query `Оля Володько`;
   - output state is `ambiguous`;
   - `person_id is None`;
   - exactly that Person is a candidate;
   - candidate reason contains `name_variant`.

2. **Olga inflected diminutive suggestion**
   - query `Оли Володько`;
   - same suggestion-only behavior.

3. **canonical inflection if included**
   - if the explicit family supports a form such as `Ольги Володько`, it must remain suggestion-only rather than resolved.

4. **surname boundary**
   - `Оли Иванова` does not suggest `Ольга Володько`.

5. **given-name false positive**
   - `Олег Володько` does not suggest `Ольга Володько`.

6. **single token fails closed**
   - `Оли` alone does not trigger the new variant matcher.

7. **exact match wins**
   - an exact active Person named `Оли Володько` remains the exact resolution result even if `Ольга Володько` also exists.

8. **duplicate candidate remains ambiguous**
   - two active People with the same canonical candidate name remain ambiguous and are both returned within existing bounds.

9. **candidate cannot mutate actor role**
   - call `resolve_person("Оли Володько")`;
   - commit the model-visible output;
   - attempt `update_task(waiting_on_person_ids=[candidate_id])`;
   - tool runner rejects because the candidate Person is not resolved;
   - no action is staged.

10. **resolved Person can mutate actor role**
    - exact `resolve_person("Ольга Володько")` returns resolved;
    - after committing that output, the same actor-role update passes existing staging rules.

11. **all four actor fields use resolved-Person gate**
    - requested_by / delegated_to / waiting_on / involves cannot consume an ambiguous candidate id.

12. **Task dependency unchanged**
    - `depends_on_task_ids` still uses the existing Task seen-object contract and is not accidentally forced through Person resolution.

13. **no identity side effects**
    - variant lookup changes no Person/identity/evidence row counts.

14. **P1 ambiguity regression**
    - two distinct exact Anna candidates remain ambiguous;
    - salience does not select a winner.

15. **R2 exact regression**
    - exact `Ольга Володько` path can still stage `waiting_on_person_ids`.

16. **tool/instruction contract**
    - `resolve_person` documents that a one-candidate ambiguous `name_variant` result is suggestion-only;
    - runtime instructions require explicit user confirmation and exact re-resolution before mutation.

17. **SEM1/STG1 regression**
    - unsupported relation boundary and staged-truth tests remain green.

## Manual acceptance after source review

Executor does not perform this step.

Primary manual flow later:

First user prompt:

`Жду ответ от Оли Володько по черновику`

Expected first response:

- no approval card;
- no mutation;
- candidate suggestion naming `Ольга Володько`;
- asks for confirmation.

Only after the user confirms the canonical Person should a subsequent turn be allowed to stage the typed `waiting_on` relation.

Manual behavior acceptance remains separate from source acceptance.

## Required checks

Run at least:

- `backend/tests/test_person_assistant.py`;
- focused new name-variant tests;
- Assistant tool-runner tests for resolved-vs-ambiguous actor ids;
- R2 relation regression tests;
- P1 ambiguity regression tests;
- `backend/tests/test_ah2_sem1_relation_boundary.py`;
- `backend/tests/test_ah2_stg1_staging_truth.py`;
- relevant Assistant tool-contract tests;
- `git diff --check`.

Record exact pass counts.

Do not require the stale-date M1 fixture or production-code parity guard to be green; do not modify them.

Model calls: 0.
Real external network calls: 0.

## Acceptance criteria

AH2-PER1 is complete only when:

- `Оля/Оли Володько` can produce a useful `Ольга Володько` candidate;
- that candidate remains suggestion-only, never auto-resolved;
- exact matching still wins;
- surname mismatch and near-name false positives fail closed;
- ambiguous Person candidates cannot be used for Task actor-role mutation;
- exact resolved People still can;
- no identity/merge/schema side effect occurs;
- P1/R2/SEM1/STG1 regressions remain green;
- production is untouched.

## Completion protocol

After implementation:

1. append a compact factual AH2-PER1 result to `PROJECT_STATE.md`;
2. record AH2-SEM1 Architect source acceptance in the same ledger update;
3. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - exact name-variant matching boundary;
   - suggestion-only state behavior;
   - actor-role resolved-Person guard;
   - negative-case evidence;
   - exact test counts;
   - confirmation of no schema/model/network/deploy;
4. commit + push to `main`;
5. STOP.

Do not start Scheduled Activity integration, stale-eval maintenance, rollout, or any other slice from HOLD.
