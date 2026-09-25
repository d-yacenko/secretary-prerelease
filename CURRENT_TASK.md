# Current task — Graph Refined P5R2: effective alias rejection + anti-starvation Person scans

Architect review of P5R implementation `29380e031071a12f097cae1ad3d1fa0467679b98` confirms the major P5R corrections: exact conflicts/rejections remain explicit, Person communication reads require a same-turn resolved Person, outbound attribution is conservative, and real source-derived identity candidates can enter the same-turn feedback allowlist.

Two remaining blocking consistency/scalability defects must be corrected before P6.

Do not start P6. Do not implement send-by-person.

Do not add live provider/directory calls, new LLM calls, proactive behavior, voice/media work, migrations, or Task Graph redesign. Do not deploy.

Known unrelated baseline failures (`pending_action_plan` response expectation and `ai_traces_user_id_fkey` in `tests/test_assistant_action_plans.py`) are not part of this task; do not claim the full suite is green.

## Defect 1 — rejected attached identity can still resolve through its display alias/name candidate

P5R correctly suppresses an active `user_rejected` Person+identity pair for:
- exact identifier resolution;
- Assistant identity summaries;
- communication attribution;
- source-derived candidate exposure.

But alias/name resolution is inconsistent:
- `PersonAssistantService._alias_people()` reads active `PersonIdentity.display_value` without checking P2 rejection;
- fallback `PersonEvidenceService.propose_candidates(None, text)` / name matching may re-propose the same Person from a rejected identity display value.

Example:
- Person Olga has attached Mattermost identity with display value `VOA`;
- user explicitly rejects that Person+identity pair;
- `resolve_person("VOA")` must not resolve Olga through that rejected identity alias.

### Required correction

Introduce/reuse a small **effective identity** rule:
- physical `PersonIdentity.state` must be active;
- Person must be active/same-user;
- active `user_rejected` for that exact Person+identity suppresses the mapping for Person-aware Assistant/P4 candidate use;
- explicit later confirmation/retraction restoring the P2 pair makes it effective again.

Apply it consistently to:
1. exact resolution;
2. identity summaries;
3. communication retrieval keys;
4. exact-identity display alias matching in `resolve_person`;
5. source-derived identity candidate matching;
6. P4 enrichment/coverage where the rejected attached identity would otherwise be treated as usable.

Person **title** remains independent of an identity rejection. Rejecting one endpoint does not erase the Person or their manually/canonically titled name.

For fuzzy/name candidate generation:
- a rejected identity's `display_value` must not be the evidence that re-proposes the rejected Person;
- if the Person independently matches by their Person title, that title-based candidate may remain.

Prefer one shared helper/service-level path rather than duplicating slightly different suppression logic.

### Proof

Add tests for at minimum:
- rejected attached identity with display alias `VOA` no longer resolves through `VOA`;
- the same Person can still resolve by independent Person title;
- explicit confirmation/retraction restoring the identity makes the alias eligible again;
- P4 coverage does not count an explicitly rejected attached identity as active provider coverage.

## Defect 2 — Person communication/candidate reads are starved by a global last-40 slice

Current P5 uses `MAX_PERSON_SCAN = 40` over the user's globally newest communication Objects, then filters for the target Person.

With realistic high-volume Inbox traffic, forty unrelated channel/email messages can erase:
- a recent direct conversation with the resolved Person;
- the inbound anchor needed to include Teams oneOnOne / Mattermost DM outbound messages;
- a real source-derived identity candidate for feedback.

This repeats the noise-starvation class already corrected in P3.

### Required scan semantics

Keep reads strictly bounded, but make the bound meaningful.

Replace the single global last-N slice with a bounded **chunked/relevance scan** (or an equally safe provider-aware bounded strategy):

- explicit total row scan budget;
- explicit chunk/page size;
- explicit max relevant Person communication hits;
- explicit max identity candidates;
- deterministic newest-first ordering;
- stop early when enough relevant results are collected;
- continue past unrelated rows while budget remains;
- return `truncated=true` when the safety budget is exhausted before the requested horizon is fully examined.

A reasonable implementation:
1. scan the requested 90-day/date/provider scope in deterministic newest-first chunks;
2. attribute rows against the resolved Person's effective exact identities;
3. accumulate relevant direct/inbound hits and 1:1 conversation anchors;
4. keep scanning through unrelated rows until the relevant-result cap is satisfied, scope ends, or total scan budget is exhausted;
5. once Teams/Mattermost 1:1 anchors are known, include matching outbound rows encountered within the bounded scan;
6. identity-candidate discovery similarly scans until candidate cap/scope end/budget, rather than taking the first 40 global rows.

Do not make the scan unbounded and do not add a cache/materialized index in this correction.

If a provider/date filter is supplied, apply it at the DB query before scan pagination.

### Required behavior

- >40 newer unrelated messages must NOT erase a still-recent direct email/Telegram interaction while scan budget remains.
- >40 newer unrelated messages must NOT hide a real source-derived identity candidate while scan budget remains.
- a Teams/Mattermost inbound 1:1 anchor behind unrelated traffic can still authorize the matching outbound side within the bounded scope.
- public/group noise never becomes a 1:1 anchor.
- if the total safety budget is actually exhausted, results report truncation honestly rather than pretending “no messages”.

Use stable cursor/pagination criteria based on the same timestamp + id ordering; do not repeatedly query overlapping first pages.

## Telegram boundary

All chunked scans must continue to apply the existing `telegram_mtproto_ai_predicate()` at query time.

Do not expose Telegram inbound content/identity metadata when the current AI policy forbids it.

The Telegram AI flag/default/semantics remain unchanged.

## Same-turn safety remains unchanged

- `find_person_communications` still requires a Person in the same-turn **resolved Person** allowlist.
- `find_person_identity_candidates` still requires a resolved Person.
- confirm/reject/retract remain ANNOTATE and require a same-turn exposed Person+identity tuple.
- conflicting owner candidates remain non-confirmable.
- no Person merge.
- no send/write/provider action.

## Focused proof

Add/extend tests proving at minimum:

1. Rejected attached identity display alias does not resolve the Person.
2. Independent Person title still resolves despite one rejected endpoint.
3. Reversal/confirmation restores alias eligibility and audit history remains intact.
4. P4 provider coverage excludes explicitly rejected attached identity.
5. More than current `MAX_PERSON_SCAN` newer unrelated objects do not hide a recent target inbound/outbound email pair.
6. Same noise does not hide a recent private Telegram Person interaction when AI-eligible.
7. Same noise does not hide a Teams oneOnOne / Mattermost DM inbound anchor and its safely attributable outbound side.
8. Same noise does not hide a real source-derived identity candidate for a resolved Person.
9. Scan budget exhaustion sets `truncated=true`.
10. Provider/date filters reduce the scanned scope before pagination and remain deterministic.
11. Rejected/deleted/cross-user People/identities remain excluded.
12. Telegram AI quarantine remains intact.
13. Existing P1–P5R focused tests and Assistant action-plan/send safety tests remain green.
14. No P6/send-by-person path is introduced.

Run:
- `tests/test_person_assistant.py`;
- `tests/test_person_enrichment.py`;
- P1/P2/P3 focused tests;
- `tests/test_tool_gateway.py`;
- touched provider-normalization tests if helpers are reused;
- Ruff/compile on touched Python;
- `git diff --check`.

Do not treat the known unrelated Assistant baseline failures as regressions introduced by this task; record them separately if encountered.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose P6 and do not deploy.
