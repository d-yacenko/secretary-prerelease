# Current task — People R1: relationship/context ontology audit

## State

- Harness H2D is closed on `main`; MCP is not a current product priority.
- Production backend/runtime and `origin/production` remain `7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4`.
- Alembic remains `0050`.
- The canonical core ontology remains: Person=who; Task=commitment/Direction; Flow=evidence/context; Time=when.
- Existing People & Identity foundation is substantial: canonical Person objects, exact identities, evidence/feedback, salience, bounded enrichment, Person-aware Assistant retrieval/routing, first-party People workspace, explicit Person creation, identity correction, and identity-grounded communication counts.
- Social/organizational relationship semantics are intentionally not canonical yet. Existing People workspace forbids ad-hoc `member_of`, `role_at`, `manager_of`, `works_with`, `colleague`, `manager`, and `friend` edges.
- Proactive currently judges event-level personal relevance (`responsible|participant|observer|related` and `waiting_on_user|waiting_on_others|none|unknown`) but does not have a canonical durable Person-to-user relationship/context fact such as manager, colleague, friend, family, client, etc.

## Goal

Produce an evidence-backed architecture audit for the next Person relationship/context layer before any schema or product implementation.

The motivating distinction is semantic, not merely visual: the same Flow text (for example “we are waiting for you”) can imply very different attention and task consequences depending on who the Person is to the user and in what context that relationship applies.

This task MUST determine the exact existing primitives, gaps, invariants, and viable representation choices. It MUST NOT choose or implement an ad-hoc social ontology.

## Scope

### A. Current Person foundation inventory

Trace the current canonical path for:

1. Person object creation and lifecycle.
2. Exact provider identities and conflict/reject/retract semantics.
3. Person identity evidence and enrichment.
4. Person salience and its inputs.
5. People workspace overview/rooted detail and what is actually visible to the human.
6. Assistant Person resolution, communication retrieval, routes, and send-by-person.
7. Task actor roles: `requested_by`, `delegated_to`, `waiting_on`, `involves`.
8. Proactive personal-relevance evidence and event-level judgment.

For each, identify the authoritative service/model/tool/UI path and whether the fact is persisted, derived, user-confirmed, or model-judged.

### B. Durable relationship/context gap

Document precisely what is NOT represented today.

At minimum distinguish:

- identity: “this endpoint belongs to this Person”;
- salience: “this Person is currently prominent in my graph”;
- Task role: “this Person requested/is delegated/is blocking/participates in this Task”;
- event-level personal relevance: “for this specific object I am responsible/participant/observer/etc.”;
- durable Person relationship/context: “this Person is my manager / colleague / friend / family / client / etc. in some context.”

Do not treat any of the first four as a substitute for the fifth.

### C. Context and ontology constraints

The audit must explicitly analyze these invariants:

1. A relationship is not necessarily a global property of a Person.
   - One Person may be a manager in one work context, collaborator in another, and friend outside work.
2. Organization membership/role and Person-to-Person relationship are different semantic facts.
   - `role_at` / `member_of` must not be silently collapsed into `manager_of` / `colleague`.
3. A free-text label is not enough to grant authority/responsibility.
4. Message volume/salience does not imply authority or importance.
5. A model inference must not silently become a durable relationship fact.
6. Durable facts need provenance, state, reversibility, and an explicit confidence/confirmation story.
7. The model must be able to say “unknown” when context is missing or conflicting.
8. Relationship context may later inform proactive ranking/judgment, but must not become a deterministic rule such as “manager => high priority”.
9. Existing Telegram/AI privacy gates and user isolation remain hard boundaries.
10. No new Organization ontology may be smuggled in implicitly during this audit.

### D. Representation options — analysis only

Compare a small set of technically viable representations using the current codebase, including at least:

- user-relative relationship facts attached to a Person;
- explicit graph representation involving Person/context entities;
- a separate typed relationship/context record with provenance.

For each option, analyze:

- ontology meaning;
- whether context can be represented without pretending it is global;
- provenance/confirmation/retraction;
- query cost and boundedness;
- Assistant/Harness exposure;
- proactive consumption;
- human visualization;
- migration/rollback risk;
- compatibility with current Person identity and Task actor semantics.

Do NOT implement any option and do NOT select a winner unless the repository already contains an explicit prior decision that resolves it.

### E. Human visualization audit

Describe what the current first-party People workspace already exposes and what it does not expose for understanding a Person.

Identify the smallest future human projection that would let a user inspect, for one Person:

- canonical identity/endpoints;
- current Task involvement;
- recent attributable Flow;
- salience evidence/summary where appropriate;
- future relationship/context facts with provenance/confirmation.

This is a UX contract description only. No Flutter changes in R1.

### F. Assistant / proactive future contract boundary

Document the minimum future information an internal Assistant/proactive review would need to consume safely, without implementing it.

The future contract must preserve the distinction between:

- durable relationship/context facts;
- current Task actor roles/dependencies;
- event-specific participation/relevance;
- raw Flow evidence;
- derived salience.

It must allow conflicting/unknown relationship context and must not authorize model-written durable relationship facts without the normal approval/confirmation boundary.

## Deliverable

Create one concise architecture document:

`docs/person_relationship_context_audit.md`

It must contain:

1. current-state map;
2. gap map;
3. invariants;
4. representation-options comparison;
5. human projection gap;
6. Assistant/proactive consumption boundary;
7. explicitly deferred questions;
8. a short list of candidate next implementation slices, each independently bounded.

Also update `PROJECT_STATE.md` with exact audit facts and return `CURRENT_TASK.md` to HOLD.

## Out of scope

- No DB migration.
- No model/schema/service/tool/client product changes.
- No `manager_of`, `friend`, `colleague`, `member_of`, `role_at`, organization Object, or other new ontology fact.
- No automatic Person creation or sender promotion.
- No Person merge.
- No proactive behavior change.
- No prompt change.
- No MCP work.
- No G3B.
- No S3.
- No production deployment or production data inspection.
- No live provider or LLM call.

## Required verification

- Audit every factual claim against current `main`.
- Verify forbidden social/organization edge behavior remains explicit.
- Verify the current proactive relationship/dependency vocabulary and that it is event-level, not a durable Person relationship store.
- Verify current Person salience inputs and that salience does not encode durable authority/social role.
- Verify current first-party People workspace projection.
- `git diff --check`.

If a repository fact contradicts the task assumptions, stop and report the contradiction rather than widening scope.

## Completion

- Commit the audit.
- Record exact findings in `PROJECT_STATE.md`.
- Replace this task with HOLD, referencing the implementation/audit SHA.
- Push both audit and HOLD commits to `main`.
- Do not authorize or start the next slice.
- Do not deploy.
