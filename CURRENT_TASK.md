# Current task — Graph Refined P3: Person salience foundation

Graph Refined P1/P1R and P2/P2R are architect-accepted. Implement the next narrow layer: internal Person salience for already known canonical People.

Do not implement UI, proactive notifications, automatic Person creation from every sender, automatic identity enrichment, Assistant Person lookup, send-by-person, voice/media ingestion, or Task Graph redesign in this task.

Do not deploy. Production remains on Alembic `0047`; development migrations `0048/0049` remain unapplied there.

## Goal

Compute an explainable, bounded, provider-neutral signal describing how strongly a known Person currently participates in the user's active communication/work graph.

Salience is a processing/ranking feature only. It is NOT object importance and must never be a hard filter for whether an object matters.

A rare message from a low-salience/unknown person may still be highly important by content, deadlines, source semantics, or task state.

## 1. No eager Person explosion

P3 operates only on existing active `kind="person"` Objects and their active exact identities.

Do NOT create Person Objects merely because a sender appears in a message/channel.
Do NOT enrich every incidental author.
Do NOT schedule provider/LLM work for unknown authors.

If source evidence cannot be mapped safely to an existing Person through active exact identities, ignore it for P3.

## 2. Explainable salience components

Add a deterministic domain model returning:
- bounded total score;
- optional internal tier such as `focus / known / incidental`;
- component values/reasons;
- evidence window metadata/truncation flags.

At minimum support these components where existing canonical data permits them safely:

### directness
Higher weight for direct/private/1:1 communication than group/public/broadcast exposure.

Examples already represented in metadata:
- Telegram MTProto `peer_kind == "private"`;
- Teams `chat_type == "oneOnOne"`;
- Mattermost DM/group-DM channel types;
- email direct recipient/sender relationships.

### reciprocity
Higher when the user and the Person both send directly to each other within the bounded window.
Inbound-only broadcast exposure must not count as strong reciprocity.

### frequency
Bounded count of meaningful interactions. Saturate/cap so a noisy channel cannot dominate.

### recency
Recent meaningful interactions contribute more than old interactions. Use a simple deterministic decay/bucket scheme, not ML.

### user attention
Where already available without new UI:
- explicit Assistant/identity route-choice feedback from P2;
- explicit identity confirmation;
- other existing deterministic user-origin interaction records if cheaply available.

### task/calendar involvement
Use only existing deterministic links/data that are already cheap and safe:
- active graph edges involving Person and task/calendar-related objects, if present;
- exact participant/attendee identity evidence where it can be mapped deterministically.

Do not invent semantic relationship facts from names or message text.

## 3. Broadcast/noise protection

Required behavior:
- many messages from one author in a public/group channel must not by volume alone make that Person `focus`;
- one or a few direct reciprocal conversations may outweigh dozens/hundreds of passive public-channel appearances;
- frequency contribution is capped;
- public/group exposure is low-weight unless reinforced by direct/reciprocal/task/calendar/user-attention signals.

Tests should include a noisy-channel author vs a less-frequent direct correspondent and show the direct correspondent ranks higher.

## 4. Decay and durable signals

Use deterministic recency decay/buckets for interaction-derived signals.

Do not implement a scheduler just to decay scores. Score should be derived at read/evaluation time from timestamps.

Durable explicit user-confirmed identity evidence may contribute without normal interaction decay, but do not invent durable relationship categories such as manager/family unless such facts already exist explicitly in current data.

## 5. Bounded data access

Implement a `PersonSalienceService` or equivalent that:
- evaluates one Person and optionally ranks a bounded list of existing active People;
- queries only bounded recent communication/history and bounded relevant graph edges;
- has explicit constants for maximum rows/window;
- is deterministic and idempotent;
- performs zero live provider calls and zero LLM calls;
- does not enqueue jobs.

Prefer reusing:
- active Person/PersonIdentity invariants from P1/P2;
- canonical communication metadata / `conversation_projection`;
- existing graph edges;
- existing P2 feedback evidence.

Do not create a second parallel event stream if current canonical Objects/edges/evidence are sufficient.

## 6. Provider-neutral identity mapping

When mapping communication Objects to a known Person:
- email: active exact email identity;
- Mattermost: active exact server-scoped user id/username;
- Teams: active exact tenant-scoped user identity and only human `sender_kind=user`;
- Telegram MTProto: active exact positive user id scoped to account realm;
- respect active/rejected/deleted Person and identity rules from P2R.

Do not use display-name-only matching for salience attribution.

Telegram AI quarantine is unrelated to this deterministic non-AI metadata calculation and must remain unchanged. Do not bypass any AI gate elsewhere.

## 7. Object importance separation

Expose salience as a reusable feature/value only.

Do NOT modify proactive notification decisions, correlation ranking, Task Graph ranking, temporal signal creation, Inbox ordering, or Assistant behavior in P3.

Add tests proving that the service itself makes no claim that low-salience sources are unimportant. Downstream integration comes later.

## Focused proof

Add focused tests proving at minimum:
1. Only existing active People are evaluated; unknown senders do not create People.
2. Direct 1:1 interaction scores higher than equivalent passive public/group exposure.
3. Reciprocal direct interaction scores higher than one-way direct traffic.
4. Frequency saturates/caps.
5. Recent interaction scores higher than otherwise-equivalent old interaction.
6. A noisy public-channel author with many messages remains below a less-frequent direct reciprocal contact.
7. P2 route-choice feedback raises salience modestly.
8. P2 explicit confirmation is visible as a durable attention/identity component but does not alone turn arbitrary content into important.
9. Rejected/deleted People and rejected identities contribute nothing.
10. Cross-user isolation is strict.
11. Bounded row/window limits are enforced.
12. No live provider, LLM, queue/job, UI, proactive, or auto-Person creation path is introduced.
13. Existing P1/P2 focused tests remain green.

If no schema is required, do not add a migration. Prefer derived-at-read-time salience over persisted mutable scores.

Run the smallest relevant backend tests, Ruff/compile on touched Python, and `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose P4 and do not deploy.
