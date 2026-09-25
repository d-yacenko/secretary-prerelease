# Architecture

See `personal_secretary_llm_build_playbook.md` section 2 for the minimal architecture overview.

PostgreSQL + pgvector is the single source of truth. FastAPI exposes REST; MCP exposes the same domain services. Flutter client targets Android and Linux.


## Product domain north star

Secretary is primarily a system for managing the user's obligations and relationships across academic, research, teaching, organizational, engineering, and business-like work.

The product has two primary managed domain entities:

1. **Person — who.** A real-world individual across provider identities, interaction history, known communication routes, salience, and commitments involving that person.
2. **Task / Commitment — what must happen.** An open obligation or loop: something the user must do, promised, was asked to do, delegated, is waiting for, must decide, must revisit, or must close.

**Object / Evidence** is the supporting information layer rather than a peer managed entity in the same sense. Emails, chat messages, calendar events, meetings, documents, notes, media, voice notes, publications, and provider records preserve what happened, where a fact came from, and the context supporting People and Tasks.

A common useful relation is:

`Person -> Object/Evidence -> Task/Commitment -> deadline/state -> later evidence -> completion`

Time/calendar is primarily a dimension and evidence source. Organizations, labels, channels, documents, courses, publications, projects, and roadmaps should remain graph/context or compositions of Tasks unless repeated workflows demonstrate a genuinely independent lifecycle.

Importance is compositional. A high-salience Person may send routine information, while an unknown Person may generate a critical deadline or obligation. Future ranking and proactive attention should combine Person salience, Task state/risk, object/content relevance, time/deadlines, and source semantics.

### Strategic roadmap

1. Finish **Graph Refined / People & Identity** to a trustworthy operational level.
2. Add provider-neutral **media/voice ingestion and transcription** as an input/integration layer.
3. Make **Task Refinement** the next large domain effort.
4. Build stronger proactive assistance later as a derived function over People + Tasks + Evidence + Time.

Task Refinement is the largest remaining core-domain gap. It should make Task/Commitment reliable, transparent, understandable, and convenient without turning Secretary into an enterprise project-management suite.

The target direction includes:
- clear Task/Commitment identity and lifecycle;
- useful semantics such as mine, delegated, waiting-for, promised-to, decision-needed, or revisit when justified;
- provenance/evidence for why a task exists;
- explicit links to People, source Objects, deadlines/time, and dependencies;
- progress/status and a reliable completion/closure loop;
- project/roadmap composition from tasks;
- bounded discovery/correlation of obligations from communication/evidence;
- easy answers to what is open, why, for whom, from whom, what is blocked, what changed, what is due, and what needs attention;
- a graph/UI that explains relations instead of exposing graph complexity for its own sake.

Avoid unnecessary ontology and workflow bureaucracy. Add a new top-level entity only when repeated real workflows require a genuinely independent lifecycle.

This document is a strategic description, not Executor authorization. `CURRENT_TASK.md` remains the only active implementation task.
