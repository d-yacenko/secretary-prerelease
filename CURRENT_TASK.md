# Current task — People C3: identity-grounded recent communication count

People C2 is accepted.

C1 + C2 now provide a complete explicit human cold-start path:

1. user creates a Person;
2. stored communication can surface a grounded identity candidate;
3. user explicitly confirms it;
4. the exact identity becomes canonical and operational.

One presentation mismatch remains:

`PersonGraphWorkspaceService._communication_count()` currently counts only explicit graph Edges between the Person and `email` / `chat_message` Objects.

C1/C2 intentionally create no Person↔Flow edges.

Therefore a Person can have canonical identity-matched real communications while People cards/details still show:

`сообщений: 0`

C3 fixes only that count semantics.

No Flow materialization.
No synthetic graph edge.
No UI redesign.
No provider/model call.
No migration.
No production deploy.

## Canonical semantic rule

`recent_communication_count` in `PersonPresentation` means:

> the bounded number of active stored communication Objects that the current canonical Person communication-matching rules attribute to this Person.

It is NOT:
- the number of explicit graph edges;
- lifetime message volume;
- a CRM activity score;
- salience;
- provider live data.

Use the same identity-grounded communication attribution semantics already accepted for `PersonAssistantService.find_person_communications`.

Do not invent a second matching implementation if the existing service can be reused safely.

## Time / boundedness

Keep the count bounded to the same canonical stored-message scan horizon/budget used by Person communication retrieval.

Do not run an unbounded COUNT over all historical messages.

The API field remains an integer count, not a completeness guarantee.

If the scan is truncated at the existing safety budget, return the number matched within that bounded scan. Do not add a new schema field in C3.

Document this bounded meaning in a short code comment or existing People docs/state.

## First-party Telegram rule

People Graph is a first-party human surface.

Existing accepted behavior allows the first-party People UI to use stored private Telegram identity/route/candidate facts even when `TELEGRAM_MTPROTO_AI_ENABLED=false`, while model-facing Assistant reads remain gated.

C3 must preserve that split.

Therefore, when counting for first-party `PersonPresentation`:
- use the existing safe first-party stored-data semantics;
- private stored Telegram communication attributable to the effective Person identity may count even if model-facing AI retrieval is disabled;
- Telegram group/public traffic must not become Person communication merely because the sender name resembles the Person;
- do not expose Telegram content to the model or change Assistant gating.

If reuse of `PersonAssistantService.find_communications` would incorrectly apply the model-facing Telegram gate, factor/reuse the internal stored matching primitive rather than weakening the Assistant gate.

## Identity state

Count only through effective canonical identities.

Must exclude:
- rejected/suppressed identity;
- detached/rejected `PersonIdentity`;
- identity owned by another Person;
- cross-user communication;
- deleted/tombstoned communication;
- rejected communication Object;
- unsafe public/group expansion that existing Person matching already excludes.

After C2-created identity is retracted/detached, the count must return to 0 unless another effective identity still matches communication.

Rejecting an identity must suppress its matched communication count; retracting that rejection may restore it.

## Existing explicit Person↔Flow edges

Do NOT add the old edge-based count on top of identity-matched count.

Avoid double-counting.

If a communication Object is both identity-matched and explicitly linked by a graph Edge, it counts once.

C3 count is identity-grounded canonical communication attribution, not union-of-arbitrary-related edges.

Explicitly related non-attributable Flow objects must not inflate this field merely because an Edge exists.

Do not remove or modify those Edges.

## Overview performance

People overview may present multiple Persons.

Do not introduce an obvious N×400 full scan if the service can batch or share one bounded communication scan.

Preferred implementation:
- perform one bounded recent communication scan for the requested People workspace result;
- attribute matching stored messages to effective identity keys per Person;
- compute per-Person counts from that shared scan.

A small number of bounded SQL queries plus one in-memory attribution pass is preferable to invoking a full Assistant scan independently for every Person card.

Rooted single-Person view may use the same helper.

Preserve existing seed/salience ordering.

## No graph expansion

C3 MUST NOT:
- add communication Objects to `nodes`;
- add edges;
- create virtual/synthetic edge types;
- change rooted layout;
- change overview layout;
- change `open_task_count`;
- change salience score;
- change routes/candidates/correction behavior.

Only the integer `recent_communication_count` changes semantic source.

## Backend tests

Add focused tests proving at minimum:

1. Person with effective email identity + matching stored inbound email has count 1 without any Edge.
2. Several matching stored communications produce the expected bounded count.
3. Unrelated communication does not count.
4. Same matching Object with an explicit Person↔Flow Edge still counts once.
5. An arbitrary explicit Edge to a non-attributable communication does not inflate count.
6. rejected identity suppresses count;
7. retract rejection restores count;
8. C2 confirmation immediately changes count from 0 to matched value;
9. C2 confirmation retract/detach returns the count to 0;
10. pre-existing effective identity behaves identically;
11. cross-user communication does not count;
12. tombstoned/deleted/rejected communication does not count;
13. Mattermost/Teams direct matching follows existing safe attribution rules;
14. public/group sender-name similarity alone does not count;
15. first-party private Telegram stored message counts with the AI model gate disabled when the effective exact Telegram identity matches;
16. model-facing Assistant Telegram gating remains unchanged;
17. scan remains bounded at the existing Person communication budget;
18. overview of multiple People uses a shared/bounded scan rather than one full scan per card (assert query/helper call behavior as practical).

Keep existing `test_person_graph_workspace.py`, `test_person_assistant.py`, salience, identity, evidence, and C2 suites green.

## Client

No Dart change should be required because the field already exists.

Do not modify card wording in C3.

If no Dart file changes:
- no Flutter analyze required;
- no Linux build required.

## Validation

Run at minimum:

- new focused C3 tests;
- `backend/tests/test_person_graph_workspace.py`;
- `backend/tests/test_person_c2_activation.py`;
- `backend/tests/test_person_assistant.py`;
- `backend/tests/test_person_identity.py`;
- `backend/tests/test_person_evidence_ledger.py`;
- `backend/tests/test_person_salience.py`;
- Ruff check/format for touched Python;
- `git diff --check`.

If any existing Person behavior must be refactored for shared attribution, keep external Assistant behavior byte-for-byte semantically equivalent, especially Telegram gating.

## Scope guard

Do NOT:

- create or infer new People;
- attach identities automatically;
- call enrichment automatically;
- create Person↔Flow edges;
- create synthetic workspace edges;
- add communication nodes to People graph;
- change task relations;
- change Person salience;
- change P1 visual layout;
- add organization/manager semantics;
- implement H2;
- migrate/deploy production;
- access production.

## Completion

Record in `PROJECT_STATE.md`:

- implementation SHA;
- exact new meaning of `recent_communication_count`;
- bounded scan behavior;
- Telegram first-party vs model-facing gate behavior;
- confirmation/reject/retract count behavior;
- performance/batching approach;
- exact test results;
- confirmation that schema/client/production did not change.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start C4.
Do not start P2.
Do not start H2.
Do not deploy production.
