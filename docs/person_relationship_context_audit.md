# Person relationship/context audit

Audit only. No representation is selected. No schema, service, tool, prompt, client, or proactive behavior is changed by this document.

Checked against `main` at the People R1 authorization. Production remains `7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4`, Alembic `0050`. The task assumptions match the code: social and organization edges are not canonical, and proactive relationship/dependency judgments are event-level.

## 1. Current-state map

Core orientation stays `Person=who; Task=commitment/Direction; Flow=evidence/context; Time=when`. Relations are explicit facts. `Flow` and `Time` are not Object kinds.

| Fact | Authoritative path | What is stored |
| --- | --- | --- |
| Person object | `PersonIdentityService.create_person` writes `Object.kind=person`, `origin=user`, `state=confirmed`. Title is required and bounded. | Persisted, user-created. Not inferred from a sender. |
| Exact identity | `PersonIdentity` row: type, provider, realm, canonical value. `attach` is idempotent for the same Person and raises `person_identity_conflict` if another active Person already holds that tuple. `detach` / `reassign` reject the old row. `resolve` ignores rejected or hidden Persons. | Persisted exact endpoint. User-confirmed at attach time (`confidence=1.0`). |
| Identity evidence | `PersonIdentityEvidence` via `PersonEvidenceService`. Types include `exact_identifier`, `provider_profile`, `name_similarity`, `organization_match`, `graph_context`, `llm_suggestion`, `user_route_choice`, `user_confirmed`, `user_rejected`. Active rows can be retracted and point at a successor. | Persisted ledger. Score explains a proposal. `AUTOMATIC_LINK_THRESHOLD` does not attach an identity or merge People. Only explicit confirm/reject/retract changes feedback state. |
| Enrichment | `PersonEnrichmentService.plan` ranks bounded candidates from stored messages and salience. It does not create Persons or edges. | Derived plan. Not a durable relationship. |
| Salience | `person_salience.score_person` / `PersonSalienceService`. Inputs: directness, reciprocity, capped frequency, recency decay, capped public exposure, user attention (confirmation or route choice), and an active task/calendar link. Window 90 days, scan caps, score capped at 100. Tiers: `focus`, `known`, `incidental`. `claims_object_importance` stays false. | Derived. Not persisted as a social role. Does not hide a known Person from search or a rooted People view. |
| People workspace | `PersonGraphWorkspaceService`. Overview orders by positive salience, then title. Rooted detail adds identities, candidates, routes, conflict, open-task count, and a bounded recent communication count. Neighbor walk skips `_FORBIDDEN_EDGE_TYPES`. | Read model over persisted Persons, identities, and allowed edges. Salience is derived. |
| First-party UI | Graph People mode. A Person card shows effective provider cues and an identity-conflict mark. Detail lists known contacts with confirm/reject/retract, routes, open-task count, and recent communication count. | Projection only. |
| Assistant Person tools | `resolve_person`, `find_person_communications`, `find_person_identity_candidates`, `list_person_routes`, `record_person_route_choice`, `confirm_person_identity`, `reject_person_identity`, `retract_person_identity_feedback`. All `mcp_exposed=False`. Communications and candidates are identity-grounded and bounded. | Reads are derived. Confirm/reject/retract and route choice persist identity evidence, not a social role. |
| Send-by-person | Route listing plus existing pending-action approval. A chosen route can record `user_route_choice`. | Route choice is persisted attention evidence. It is not authority. |
| Task actor roles | `TaskRelationService` edges `requested_by`, `delegated_to`, `waiting_on`, `involves` from Task to Person, plus `depends_on` from Task to Task. Additive and idempotent. User writes are confirmed; agent writes follow the existing proposed/confirmed write mode. Read back by `get_task_profile`. | Persisted per Task. Not a property of the Person. |
| Proactive personal relevance | Evidence in `PersonalRelevanceEvidenceService` is code-produced per object: participation roles such as sender, recipient, organizer, attendee, mentioned. Judgment enums in `PersonalRelationship` / `PersonalDependency` are model output on `ProactiveDecision`, required for `notify`. Audit metadata records `relationship` and `dependency` for that review. | Judgment is event-level. It is not a Person relationship table. |
| User self-description | `UserIdentityProfile` free text parsed into the user's own name, aliases, roles, organizations, and identifiers. Proactive copies a bounded projection into `user_context`. | Persisted text about the user. Not a link from the user to another Person, and not an Organization object. |

`organization_match` is one identity-candidate evidence type. There is no `organization` Object kind and no product writer for `member_of`, `role_at`, `manager_of`, `works_with`, `colleague`, `manager`, or `friend`. The People workspace excludes those edge types if they appear.

Telegram privacy stays split. Assistant message scans apply the Telegram AI gate. The first-party People surface may include quarantined Telegram when counting communications, listing candidates, or listing routes. User isolation remains `user_id` on Person, identity, evidence, and edge queries.

## 2. Gap map

These are different facts. None of the first four is the fifth.

| Layer | Today | Missing |
| --- | --- | --- |
| Identity | This endpoint belongs to this Person. | Nothing in this layer says who the Person is to the user. |
| Salience | This Person is prominent in recent communication, confirmation, route choice, or task/calendar linkage. | Prominence is not authority, friendship, or importance of a message. |
| Task role | This Person requested, is delegated, is blocking, or participates in this Task. | The role ends with the Task. It does not say the Person is the user's manager. |
| Event-level relevance | For this object, the model may say `responsible`, `participant`, `observer`, `related`, or `unknown`, and `waiting_on_user`, `waiting_on_others`, `none`, or `unknown`. | The judgment is not reused as a durable Person fact. `unknown` exists here and must remain available. |
| Durable relationship/context | Not represented. | “This Person is my manager / colleague / friend / family / client in some context” has no canonical row, edge, or profile field. |

The same Flow text can therefore not be interpreted through a stored relationship. “We are waiting for you” has only the message, identity resolution, Task roles if any, salience, and a fresh event-level judgment.

## 3. Invariants

1. A relationship is not automatically global. One Person can be a manager in one context, a collaborator in another, and a friend outside work. A single label on the Person object cannot say that.
2. Organization membership or role and a Person-to-Person relationship are different. `role_at` / `member_of` must not be collapsed into `manager_of` / `colleague`. This audit does not add an Organization ontology.
3. A free-text label does not grant authority. The user's own profile roles and organizations are self-description, not a confirmed duty toward another Person.
4. Message volume and salience do not imply authority or importance. Salience explicitly does not claim object importance.
5. Model output must not silently become a durable relationship. Identity suggestions already stay below automatic attach. Proactive judgments already stay on the review.
6. A durable fact needs provenance, state, reversibility, and an explicit confirmation story. The closest existing patterns are identity evidence (confirm, reject, retract) and graph edges (origin, proposed/confirmed/rejected).
7. Missing or conflicting context must be expressible as unknown. Proactive already has `unknown`. A future relationship read must too.
8. Relationship context may later be an input to proactive ranking. It must not become a rule such as “manager means high priority”.
9. Telegram AI gates and per-user isolation stay hard boundaries.
10. No new social or organization edge is authorized by naming the gap.

`DECISIONS.md` already requires a dedicated design pass before any `manager_of`, `colleague`, `role_at`, or `member_of` edge. This document is that pass's audit. It does not close the pass.

## 4. Representation options

No option is chosen.

### A. User-relative facts on the Person

Store relationship labels on the Person, scoped as “relative to this user”.

- Meaning: the Person carries the user's claim. Context is a field on that claim, or the claim is falsely global.
- Context: a single slot cannot represent manager-at-work and friend-outside-work without a context key. Adding only a string label repeats invariant 1.
- Provenance: can copy identity-evidence confirm/reject/retract, but the Person row itself is a poor history.
- Query: cheap for one Person. Bounded only if labels are capped.
- Assistant / Harness: a small read fits `get`/profile style. Writes still need the approval boundary. MCP exposure stays a separate decision.
- Proactive: easy to attach to evidence, and easy to misuse as a priority rule.
- Human view: natural on the Person card, and misleading if context is omitted.
- Migration: small, but a global label is hard to roll back into contextual facts later.
- Compatibility: does not disturb identity tuples or Task actor edges.

### B. Explicit graph edges, possibly through context entities

Represent the claim as edges. A context or organization would be another node only if a later ontology says so.

- Meaning: matches “relations are explicit facts”. A Person-to-user edge still needs a context dimension, or it becomes global.
- Context: a bare `manager_of` edge between Persons collapses invariants 1 and 2. A context node would be a new ontology and is out of scope here.
- Provenance: existing edge origin and proposed/confirmed/rejected already match Task actors. Rejection is the reversal.
- Query: People workspace already walks edges with caps and already drops the forbidden social types. New types would be a deliberate allow-list change.
- Assistant / Harness: could reuse `link_objects` only if the type is canonical. It is not. A generic writer would be the wrong door.
- Proactive: an edge is easy to over-read as a standing order.
- Human view: the graph can show the edge, but a label without context looks like a permanent social fact.
- Migration: adding an edge type is reversible by rejection, but a mistaken type pollutes the graph the People view must keep filtering.
- Compatibility: Task actor edges stay Task-to-Person. Social edges must not be inferred from them.

### C. Separate typed relationship/context record

A row keyed by user, Person, context, and relationship kind, with origin, state, confidence, and retract/supersede.

- Meaning: the fact is “in this context, the user claims this relationship”, not a property of the Person and not an organization membership.
- Context: the context key can be unknown, a free description, or a later structured scope. It does not require an Organization object.
- Provenance: can follow the identity-evidence ledger: active, rejected, retracted, superseded. Model suggestions stay non-durable until confirmation.
- Query: one bounded read per Person. No graph scan. Caps are explicit.
- Assistant / Harness: a dedicated read can return facts plus unknown. A write stays behind confirmation. Not an MCP task.
- Proactive: the record is evidence to include, not a priority function.
- Human view: a short list on the Person detail, each line showing kind, context, state, and origin.
- Migration: a new table is the largest schema step and the cleanest rollback if the table is unused by other writers.
- Compatibility: identity, salience, and Task actors stay untouched. `organization_match` remains candidate evidence, not a row in this table.

All three can be implemented badly by omitting context, confirmation, or unknown. The repository has no accepted decision that picks one.

## 5. Human projection gap

The People workspace already shows, for one Person:

- title and provider cues;
- identities and candidates, including conflict, confirm, reject, and retract;
- routes;
- open-task count, not the Task list or actor role;
- a recent communication count, not the Flow items.

It does not show salience components, Task actor roles, attributable messages, or any relationship/context fact.

The smallest later projection, after a representation exists, is one Person detail section that inspects:

- canonical identities and endpoints, already present;
- current Task involvement from existing Task-to-Person edges, without inventing roles;
- recent attributable Flow from the existing identity-grounded communication read;
- a salience summary that still does not mean importance;
- relationship/context rows with context, provenance, state, and confirmation.

No Flutter change belongs in this audit.

## 6. Assistant and proactive boundary

A future consumer may see five separate inputs:

1. durable relationship/context facts, including unknown or conflict;
2. current Task actor roles and dependencies;
3. event-level participation evidence and the event-level relevance judgment;
4. raw attributable Flow;
5. derived salience.

Rules for that future contract:

- unknown stays a valid answer;
- conflicting contexts stay visible rather than collapsed;
- the model does not write a durable relationship without the existing confirmation or approval boundary;
- proactive may read the facts and must not treat a relationship as a deterministic priority;
- Telegram quarantine and user isolation stay as they are;
- Person tools are not MCP-exposed by this audit.

## 7. Deferred questions

- Which representation in section 4, if any, becomes canonical.
- Whether relationship kinds are a closed vocabulary or confirmed claims plus a context description.
- What “context” is before any Organization object exists.
- Whether several active contexts for one Person are allowed on day one.
- Whether an agent may propose a relationship the way it proposes a Task edge, or only the user may confirm one.
- How long an event-level `responsible` judgment may be shown before it is mistaken for a durable fact.

## 8. Candidate next slices

Not authorized. Each assumes a later explicit choice of representation.

1. One persistence slice for a single user-confirmed, contextual, retractable relationship fact. No inference, no Organization object, no graph type dumped into `link_objects`.
2. One read-only Person detail projection of identities, Task involvement, recent attributable Flow, salience summary, and those facts.
3. One Assistant read that returns the facts and unknown, with no write tool.
4. One proactive evidence addition that includes the facts and does not add a priority rule.
5. Harness or MCP exposure only after the read contract exists, and not as part of the persistence slice.
