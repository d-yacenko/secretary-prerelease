# Architecture

See `personal_secretary_llm_build_playbook.md` section 2 for the minimal architecture overview.

PostgreSQL + pgvector is the single source of truth. FastAPI exposes REST; MCP exposes the same domain services. Flutter client targets Android and Linux.

## Product domain north star

Secretary exists to **reduce cognitive load and keep the user focused on consequential obligations**, not to maximize the number of entities, dashboards, workflows, or features the user must manage.

The product ontology therefore has only two primary managed concepts.

### Actor / Person — who

An Actor is a participant in the user's real-world activity. Today the principal Actor implementation is `Person`: the user, colleagues, managers, students, editors, collaborators, family members, and other people across provider identities and communication routes.

An Actor may:
- initiate or request a Task;
- own or perform a Task;
- participate in, depend on, block, or wait for a Task;
- communicate Flow that creates or changes Task state.

Not every sender observed in a high-volume feed needs to become a fully managed Person. Identity resolution and enrichment remain lazy and relevance-driven.

### Task / Commitment — what must happen

`Task` is broader than a checklist action. It is a **stateful required or intended process / open loop**: what needs to happen or what state needs to be reached.

Examples include:
- work the user must perform;
- a promise or obligation;
- a request from another Actor;
- delegated work;
- something waiting on another Actor;
- an unresolved decision;
- a recurring process such as a daily routine;
- a project or roadmap expressed as a composition of Tasks.

A Task normally has Actor relations, but it need not be "created by a Person". Its trigger may be:
- an Actor;
- a Flow event;
- another Task;
- time / recurrence;
- the user's own decision.

The current user may be an implicit/default owner when no explicit Actor relation adds useful information.

Useful Actor↔Task relations may include roles such as owner, requester, assignee, participant, stakeholder, beneficiary, or waiting-on. Add role vocabulary only when it improves real workflows.

### Flow — what happened / what arrived

`Flow` is the stream of observable events, messages, and artifacts entering or produced by the system:

- email and chat messages;
- meetings and calendar events;
- files and shared documents;
- notes;
- media and voice;
- publications and provider records;
- other source Objects.

Flow is **not another primary workload for the user to manage**. It is information about reality.

A Flow item may act as:
- a trigger that creates a Task;
- a control signal that changes Task state;
- evidence explaining why a Task exists;
- progress or completion evidence;
- an input/resource needed by a Task;
- an output/artifact produced by a Task;
- irrelevant/noisy information that should not create any Task at all.

Therefore the central model is:

`Actor <-> Task`

with Flow observing and changing that relationship:

`Flow -> creates / explains / advances / blocks / closes Task`

and:

`Actor -> emits / receives / participates in Flow`.

A common lifecycle is:

`Actor -> Flow signal -> Task/Commitment -> changing state -> later Flow evidence -> completion`.

### Time is a dimension, not another top-level workload

Time cuts across the model:
- Task: deadline, schedule, recurrence, stale/open duration;
- Flow: occurred-at time;
- Actor: recency and salience of interaction.

Calendar data is therefore both a temporal view and a Flow/evidence source rather than a separate managed universe.

### What should collapse into this model

Do not introduce a new top-level entity merely because a feature can be named.

Prefer to express:
- **Project** as a composition/group of Tasks with Actors and Flow;
- **Roadmap** as Tasks + dependencies + ordering/time;
- **Conversation** as Flow between Actors;
- **Waiting for** as Task state / Actor relation;
- **Commitment** as Task semantics;
- **Document / knowledge** as Flow artifact/evidence/resource;
- **Meeting** as temporal Flow that may create or update Tasks;
- **Proactive attention** as a derived decision over Actor + Task + Flow + Time.

Add another top-level lifecycle only when repeated real workflows cannot be expressed cleanly in this model.

## Product focus principle

Secretary should continually compress incoming complexity into the smallest useful set of things that deserve the user's attention.

The desired transformation is not:

`many messages -> many features -> many things to manage`

but:

`large noisy Flow -> understood Actors + a small reliable set of consequential Tasks`.

The system should help answer:
- What actually needs my attention?
- What must happen next?
- Why does this Task exist?
- Who is involved?
- What am I waiting for?
- What changed?
- What is at risk or overdue?
- What can safely be ignored?

Person salience, content relevance, deadlines, Task state/risk, source semantics, and explicit user feedback are inputs to prioritization. No single signal establishes importance: a close colleague can send routine noise, while an unknown editor can create a critical obligation.

The UI and automation should therefore prefer **focus, explanation, and reliable closure** over exposing every internal capability.

## One ontology, two interfaces

The domain ontology is the semantic contract shared by the human user and the Secretary model.

The center of the product is not the UI and not the LLM. It is the same domain reality:

`Actor <-> Task`, observed and changed through `Flow`, across `Time`.

That reality has two projections.

### Human projection — UI / UX

The UI should expose the smallest useful set of affordances for understanding and managing:
- consequential Actors;
- consequential Tasks and their state;
- the Flow evidence needed to explain what happened and why the Task exists or changed.

Flow should normally support understanding and action rather than become another large workload the user must curate.

### Model projection — Harness / Toolset / MCP

The LLM should receive machine-operable affordances over the same semantics:
- resolve/read Actors;
- read relevant Flow;
- create/read/update/close Tasks and their relations when authorized;
- inspect provenance, time, dependencies, and state;
- perform external actions only through the existing safety/approval boundaries.

Prompts define the Secretary's behavioral policy over the ontology: when to ask, when to stay quiet, how to handle ambiguity, what requires approval, and how to avoid guessing. Prompts should not invent a parallel domain model.

The symmetry is **semantic, not one-to-one UI/tool mirroring**. One screen may aggregate many domain reads; one user gesture may map to several safe tool calls; a low-level tool may have no dedicated button. What must remain aligned is meaning, state, provenance, and safety.

### Feature acceptance gate

A proposed feature should normally pass all of the following questions before it becomes product scope:

1. **Ontology fit.** Can it be expressed cleanly as understanding an Actor, maintaining a Task, interpreting Flow, or using Time across those concepts?
2. **Human affordance.** What concrete user problem does it solve, and does the UI reduce or increase what the user must consciously manage?
3. **Model affordance.** What corresponding capability does the Secretary need through Harness/Tools/MCP to act on the same domain meaning?
4. **Shared semantics.** Do UI and LLM paths use the same canonical domain services/state/provenance rather than creating parallel implementations?
5. **Focus test.** Does the feature help compress noisy reality into fewer consequential decisions/tasks, or does it merely expose more information and controls?
6. **Safety test.** Are ambiguity, reversibility, external side effects, privacy/eligibility gates, and approval boundaries explicit?
7. **Complexity test.** Could the capability be represented as a composition/view/state of existing Actor/Task/Flow semantics instead of introducing a new top-level entity or workflow?

Failure of one question does not make a feature impossible, but it creates a high bar: the independent lifecycle and user value must be demonstrated by repeated real workflows.

This principle is intentionally restrictive. Secretary should gain power mainly by improving the shared domain model and its two interfaces, not by accumulating unrelated feature silos.

## Strategic roadmap

1. Finish **Graph Refined / People & Identity** to a trustworthy operational level.
2. Add provider-neutral **media/voice ingestion and transcription** as an input/Flow capability; this is important integration work but does not change the core business ontology.
3. Make **Task Refinement** the next major domain effort.
4. Build stronger proactive assistance later as a derived function of Actor + Task + Flow + Time.

### Task Refinement direction

Task is currently the least mature primary managed concept. The goal is not an enterprise project-management suite. It is a reliable, transparent, low-friction model of obligations and open loops.

Task Refinement should eventually support, where justified by real workflows:
- clear Task identity and lifecycle;
- ownership/participation relations to Actors;
- mine / delegated / waiting-for / promised-to / decision-needed / recurring semantics;
- provenance: which Flow or Actor caused the Task to exist;
- deadlines, recurrence, dependencies, and composition;
- progress and state transitions derived from trustworthy Flow evidence;
- explicit completion/closure;
- projects and roadmaps as task composition rather than separate complexity by default;
- bounded discovery/correlation of obligations from communication and other Flow;
- clear answers to what is open, why, for whom, from whom, what is blocked, what changed, and what requires attention;
- a Task Graph/UI that explains relationships rather than exposing graph machinery.

The architectural test for every future feature is: **does it help understand Actors, keep Tasks correct, interpret Flow, or direct attention to consequential state changes?** If not, it should face a high bar for inclusion.

This document is a strategic description, not Executor authorization. `CURRENT_TASK.md` remains the only active implementation task.


## Backlog: Person Graph View

**Status:** backlog only; not Executor authorization. Target placement: after media/voice Flow work and before major Task Refinement, unless reprioritized.

Add a second Graph workspace mode, conceptually `Tasks | People`, reusing the existing graph UI/layout.

The first bounded People view should expose only grounded Person knowledge already held by Secretary: canonical Person, name/title, effective identities and safe contact routes, salience where useful, linked Tasks and communication/evidence on inspection, search, identity conflict state, and reversible correction of mistaken identity links/confirmations/rejections.

The purpose is to help the user find, understand, and correct important People. It must not become a CRM or a giant social graph.

Do not initially infer organizational hierarchy, job titles, or Person-to-Person relations from weak communication evidence. If real use later demonstrates value, add only a small grounded relation vocabulary (for example organization membership, role in organization, manager relation, collaboration relation) based on explicit/provider facts or user confirmation. Organizations remain contextual graph Objects, not a new primary managed entity.

This backlog item closes the human-side projection of People & Identity under the principle **one ontology, two interfaces**, and should prepare for Task Refinement: Person -> open commitments/tasks; Task -> participating Actors and evidence.
