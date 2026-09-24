# Current task — Graph Refined P3R3: salience candidate dedupe + scoring consistency

Architect review of P3R2 implementation `37130c3468418fefa2231094d7b28ced5415bd42` confirms that the global oldest-identity / unrelated-edge ranking problem is fixed. One remaining integrity issue exists inside bounded attention/task candidate and scoring reads.

Fix only these bounded dedupe/scoring-consistency defects. Do not start P4.

Do not add UI, proactive/Inbox/Assistant/Task Graph integration, automatic Person creation/enrichment, send-by-person, voice/media, migrations, provider calls, LLM calls, or jobs. Do not deploy.

## Defect 1 — attention bound is row-based, not Person-candidate-based

`_attention_candidates()` orders active `user_confirmed` / `user_route_choice` rows and then applies `LIMIT MAX_ATTENTION_CANDIDATES + 1` before deduplicating Person ids.

A single Person with many active feedback rows/identities can consume the row budget and hide other People, even though the documented source is a bounded set of Person candidates.

Required correction:
- bound **distinct Person candidates**, not raw evidence rows;
- explicit confirmation has priority over route choice;
- within the same strength, newer feedback has priority;
- deterministic tie-break;
- rejected/deleted/cross-user People remain excluded;
- truncation means there were more distinct eligible Person candidates than the bound, not merely more rows for an already-selected Person.

A window-function / grouped latest-best-evidence query or a bounded ordered scan with explicit dedupe budget is acceptable.

## Defect 2 — task/calendar bound is row-based, not Person-candidate-based

`_task_candidates()` limits relevant edge rows before deduplicating Person ids. A Person with many active task/calendar edges can occupy the whole row budget and hide other People.

Required correction:
- bound distinct Person candidates;
- rank each Person by its newest relevant active Person<->task/calendar edge;
- deterministic ordering by newest relevant edge with stable tie-break;
- truncation means more distinct eligible Person candidates than the configured candidate bound.

## Defect 3 — scoring reads can disagree with pool membership

After the pool is built:
- `_attention(people)` still applies a raw `LIMIT MAX_SCAN_ROWS` without semantic ordering/deduplication;
- `_task_calendar_people(people)` still limits raw edges before filtering to task/calendar relevance.

Therefore a Person can enter the pool because of strong attention/task evidence but then receive zero `user_attention` or `task_calendar` component purely because unrelated/duplicate rows consumed the scoring read.

Required correction:
- for an already bounded `people` set, determine attention flags deterministically for every Person in that set; do not let another Person's duplicate evidence consume the score read;
- for task/calendar, query/filter relevant active Person<->task/calendar relations before any safety limit, or use a bounded per-Person/existence strategy;
- if an internal safety bound is still needed, it must not silently turn a known pool reason into a false zero. Either compute exact boolean existence for bounded People or surface incompleteness explicitly.

## Invariants

- `rank()` still returns at most `MAX_RANKED_PEOPLE`.
- Existing communication scan remains bounded and exact-identity only.
- `evaluate(person)` remains unchanged unless shared helpers can be made safer without semantic drift.
- Rejected/deleted People and rejected identities remain excluded.
- Cross-user isolation remains strict.
- Salience remains read-time only and `claims_object_importance=false`.
- No downstream integration, migration, provider/LLM call, job, or Person creation.

## Focused proof

Add tests proving at minimum:
1. More than `MAX_ATTENTION_CANDIDATES` feedback rows for one Person do not hide a newer eligible confirmed Person.
2. Candidate attention truncation is based on distinct People.
3. More than `MAX_TASK_CANDIDATES` relevant edges for one Person do not hide another Person with a newer relevant task/calendar edge.
4. Candidate task truncation is based on distinct People.
5. A Person admitted by explicit confirmation receives the `user_attention` component even when other selected People have many feedback rows.
6. A Person admitted by task/calendar relation receives the `task_calendar` component even when selected People have many unrelated/duplicate edges.
7. Repeated `rank()` calls are deterministic.
8. Existing P3/P3R/P3R2 provider, direction, noise, caps, active-state, and cross-user tests remain green.
9. P1/P2 focused tests remain green.
10. No P4 work or downstream integration is introduced.

Run `tests/test_person_salience.py`, P1/P2 focused tests, Ruff/compile for touched Python, and `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose P4 and do not deploy.
