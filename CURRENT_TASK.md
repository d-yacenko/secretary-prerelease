# Current task — GR1.2 collapsed multi-edge proposal visibility

Base state:
- GR1 / GR1.1 are HUMAN-ACCEPTED on live data.
- Production backend remains `0719e9bf5af75a8065a9916d8e27c0247a3921ec`.
- Alembic remains `0052 / 0052`.
- Canonical Task layout remains `task-map-v2.2`.

This is a client-only presentation correction. Do NOT deploy production.

## Human-observed case

For the Task «Публикация тезисов на 8-й Международной конференции …» the Graph has five non-Task neighbors plus its parent Task.

One non-Task neighbor («Решение Программного комитета DYSC 2026») currently has **two separate active relation edges** to the same Task:
- one confirmed directed `references`;
- one agent-proposed undirected `related_to`-style relation.

Another endpoint (`Program_DYSC.pdf`) has an agent-proposed relation.

In compact/unselected dandelion presentation, only one proposal diamond is visible. After selecting the Task and expanding its local Flow cards, two proposal diamonds become visible.

The inspector correctly exposes separate edge rows. The mismatch is presentation-only.

## Verified root cause

Hybrid compact presentation intentionally draws one glyph/hairline per Task↔Flow object pair.

`graphMapAnchorEdge()` gathers all edges between the same Task and Flow endpoint, then chooses one representative by relation-type rank:
1. `references`
2. `depends_on`
3. `contains`
4. `related_to`
5. other

`_withCanonicalArrow()` then copies direction/style/proposed state only from that representative edge.

Therefore if a pair has:
- confirmed `references`; and
- proposed `related_to`;

the compact hairline uses the confirmed `references` representative, so the pending proposal state is visually lost. When the Task is selected, the full edge renderer draws the real edges separately and the proposal suddenly appears.

This is deterministic presentation aggregation, not data loss and not an inspector defect.

## Product invariant

**LOD may collapse multiple relations geometrically, but it must never hide that a human-reviewable proposed relation exists.**

A compact Task↔Flow pair may still use one canonical hairline for geometry/style, but review state must be aggregated separately from representative-edge selection.

Do not change ontology or relation data to satisfy presentation.

## Required implementation

### Separate representative style from aggregate review cue

Keep deterministic representative edge selection for:
- direction;
- dash/light/structural styling;
- canonical source/target arrow.

Do NOT simply reorder all representative selection to “proposed first” if that would make a compact line pretend the wrong relation type is canonical.

Instead make compact hairline presentation distinguish:
- whether the representative edge itself is proposed;
- whether **any active edge in the collapsed Task↔Flow pair** is proposed.

Suggested shape:
- retain existing proposed styling when the representative edge itself is proposed;
- add a separate aggregate proposal cue when another collapsed edge is proposed;
- the aggregate cue may reuse the hollow diamond, but the line itself must retain the representative relation style when that representative is confirmed.

Name the model field so the semantics are explicit, e.g. `proposalCue` / `hasProposedRelation`, rather than overloading one boolean ambiguously.

### Active edge set

For the aggregate cue:
- include active `proposed` edges that are visible on the Tasks map;
- ignore `rejected` edges;
- do not make hidden actor/label/temporal relations create a proposal cue on a Task↔Flow hairline;
- preserve current Flow↔Flow hiding.

### No geometry change

Do not change:
- compact glyph position;
- halo anchoring;
- fCoSE passes;
- Task centers;
- canonical world;
- semantic-window membership;
- shared camera.

This slice should not move any node.

### Inspector remains authoritative

Keep one inspector row per actual edge.

Do not deduplicate the two rows for the same neighbor. Their coexistence is semantically meaningful:
- one can be confirmed;
- another can be proposed;
- types/directions can differ.

The inspector must remain the place where the exact edge type, direction, origin, state, and action are shown.

## Relation editing decision

Do NOT add a general relation editor, “change type”, or one-click reverse in this slice.

Current correction workflow remains:
- proposed wrong relation: reject it;
- if a correct confirmed relation to that same endpoint already exists, the endpoint remains attached;
- if the rejected relation was the only attachment, the endpoint may leave the overview and can be reopened via object search/inbox/source navigation and reattached with the existing “Добавить связь”.

This is an accepted limitation for now. Revisit only if repeated human use shows the repair workflow is too costly.

Do NOT add a transactional “replace relation” backend API in this slice.

## Required regressions

Add focused client tests matching the live case.

### A. Duplicate pair, proposal hidden today

Fixture:
- Task A;
- Flow/file object X;
- confirmed `Task A --references--> X`;
- agent-proposed `X --related_to-- Task A`.

With no selected object:
- exactly one compact glyph for X;
- exactly one compact hairline for the pair;
- representative style remains deterministic and corresponds to the existing canonical representative rule;
- aggregate proposal cue is visible despite the representative edge being confirmed.

### B. Selection does not reveal a previously hidden review state

Select Task A.

Prove:
- full/focused presentation may draw the real relations separately;
- proposal cue was already visible before selection;
- selection does not create the first indication that a proposal exists.

### C. Reject proposed duplicate

Simulate/construct post-rejection state:
- confirmed `references` remains;
- proposed duplicate is now rejected/absent from active edges.

Prove:
- compact glyph/hairline remains;
- aggregate proposal cue disappears;
- confirmed relation style remains;
- node position does not change.

### D. Single proposed relation

Preserve existing behavior:
- one proposed Task↔Flow edge still gets proposed line styling and diamond.

### E. Multiple proposed relations

If several active proposed edges exist between the same Task and Flow endpoint:
- one compact pair is still drawn;
- proposal cue is deterministic and not duplicated into overlapping diamonds.

### F. Hidden relation types

A proposed actor/label/temporal relation must not create a compact proposal cue.

### G. Geometry invariance

For all above fixtures compare before/after:
- Task top-left/center unchanged;
- compact Flow top-left unchanged;
- hairline endpoints unchanged except painter metadata;
- no new overlap.

Keep existing hybrid dandelion/focus/local-flower tests green.

## Human gate

After implementation/tests:
- build a fresh self-contained Linux debug client from a clean detached checkout of the exact implementation SHA;
- record UTC build time, executable path, BUILD_INFO, launcher SHA-256, kernel SHA-256 if present;
- do not install it.

Human check on the real Publications Task:
1. before selecting the Task, both outstanding proposals are visibly cued on their respective compact relations;
2. selecting the Task does not reveal an additional previously hidden proposal;
3. inspector still shows both separate relations to «Решение Программного комитета DYSC 2026»;
4. rejecting the wrong proposed relation leaves the correct confirmed `references` attachment intact;
5. no Task/Flow geometry changes.

## Explicitly out of scope

- backend;
- schema/Alembic;
- production rollout;
- client installation;
- relation type editor;
- reverse-direction editor;
- transactional replace-relation endpoint;
- automatic cleanup/deduplication of old agent relations;
- agent audit/harness changes;
- Task layout version changes;
- SW2-B;
- GUX1.

## Completion contract

When complete:
1. record exact root cause, implementation SHA, changed presentation semantics, tests, bundle provenance/hashes, and accepted limitation in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus concise GR1.2 human-gate summary;
3. commit/push to `main`;
4. STOP.

Do not deploy production and do not start relation-editor or agent-audit work.
