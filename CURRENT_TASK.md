# Current task — Graph Refined P5: Person-aware Assistant retrieval + reversible identity feedback

Graph Refined P1–P4 are architect-accepted. Implement the first Assistant-facing Person layer.

P5 includes:
1. read-only Person resolution/retrieval for Assistant queries such as “что писала Ольга?”;
2. reversible identity feedback operations for explicit user confirmation/rejection/correction.

Do NOT implement send-by-person or route selection in this task. That remains P6.

Do not add proactive behavior, general UI, live provider directory/profile calls, migrations unless strictly necessary, voice/media ingestion, or Task Graph redesign. Do not deploy.

## Goal

Allow Assistant to:
- resolve a named Person conservatively;
- explain ambiguity instead of guessing;
- retrieve bounded communication objects linked to that Person through active exact identities;
- let an explicit user statement confirm/reject a candidate identity in the existing P2 evidence ledger;
- preserve all existing action-plan and provider-safety boundaries.

## 1. Read-only Person resolution service/tool

Add a bounded domain/service API and Assistant-exposed READ tool, e.g. `resolve_person` / `find_person_communications`, or the smallest equivalent design.

The resolver should accept a user-facing query such as a name/alias string and return bounded candidate People with:
- person_id;
- title;
- active identities summarized safely (provider/category + display-safe value where appropriate);
- P2 candidate assessment/reasons;
- P3 salience/tier;
- ambiguity state.

Resolution order:
1. exact identity input when the query itself is a normalized exact identifier;
2. exact/confirmed aliases already attached to Person;
3. deterministic name/title/display-value candidate matching from P2;
4. salience may rank ambiguous candidates but MUST NOT turn ambiguity into certainty.

Never resolve solely by LLM intuition.

If more than one plausible Person remains, return ambiguity and enough bounded information for Assistant to ask the user which one. Do not silently choose a winner.

## 2. Person-aware communication retrieval

Add a bounded READ path/tool for:
- one resolved `person_id`;
- optional provider filter;
- optional time range / recent limit;
- optional direction if current canonical metadata supports it safely.

Retrieve communication Objects linked through that Person's **active exact identities**, provider-neutrally:
- email identities;
- Mattermost exact server-scoped user id/username;
- Teams exact tenant-scoped human user id;
- Telegram MTProto exact account-scoped positive user id.

No display-name-only attribution.

Returned objects must:
- belong to the current Secretary user;
- be active/non-rejected;
- be bounded and deterministically ordered;
- expose object ids so normal Assistant follow-up tools can open/contextualize them;
- preserve normal model-visible serialization limits.

Prefer reusing canonical Objects and current retrieval/context services rather than creating a parallel content store.

## 3. Telegram AI quarantine is a hard model-visible boundary

Person graph may contain deterministic Telegram identity facts even while `TELEGRAM_MTPROTO_AI_ENABLED=false`.

However P5 Assistant-facing outputs MUST respect the existing Telegram MTProto AI eligibility policy:
- when gate is false, do not expose Telegram-derived inbound message content/metadata to the model except whatever is already permitted by the existing self-authored-scope policy;
- Person-aware retrieval must apply `telegram_mtproto_ai_predicate/eligible` consistently with current retrieval/correlation paths;
- do not leak Telegram identity/message facts through Person summaries in a way that bypasses the gate;
- do not change the flag default or semantics.

Implement the full gated path now so future activation remains configuration-only.

## 4. Assistant tool integration

Register the new read tool(s) in the canonical tool registry:
- `ToolPermission.READ`;
- Assistant-exposed;
- bounded schemas;
- outputs integrated into the existing seen-object-id mechanism so returned communication object ids can be used by `get_object`, `get_context`, task evidence, etc.

Do not expose new unrestricted raw metadata blobs to the model.

Update Assistant tool descriptions so the model uses Person resolution before broad semantic retrieval for prompts clearly referring to a person, e.g.:
- “что писала Ольга?”
- “покажи последние сообщения от Максима”
- “что мы обсуждали с VOA?”

The model should not guess that two names are the same Person.

## 5. Explicit identity feedback operations

Add narrow Assistant-exposed reversible annotation tools, e.g.:
- `confirm_person_identity`;
- `reject_person_identity`;
- optional `retract_person_identity_feedback` if needed for clean reversal.

Use existing P2 `PersonEvidenceService` semantics.

These are low-risk local reversible semantic annotations and may use `ToolPermission.ANNOTATE` in interactive Assistant if the existing policy/registry design supports it safely.

Hard requirements:
- user must have been shown/resolved the relevant Person and candidate identity in the same Assistant turn before feedback mutation;
- tool must validate same-user Person ownership and active state;
- identity tuple must be normalized through existing P1 helpers;
- confirmation records `user_confirmed`;
- rejection records `user_rejected`;
- rejection must suppress the same mistaken proposal;
- reversal/retraction must be auditable;
- multiple-confirmation conflict semantics from P4R remain intact;
- no Person merge is performed directly by these feedback tools;
- no external provider action occurs.

Do not let the model invent a raw email/user id/Telegram id and confirm it without that identity having been exposed as a candidate in this turn.

Extend the per-turn allowlist mechanism with a bounded “seen Person / seen candidate identity” concept rather than weakening existing object-id safety.

## 6. Retrieval semantics examples

Expected behavior:

### “Что писала Ольга?”
- resolver finds one confirmed Olga -> retrieve her linked communications across eligible providers;
- if two plausible Olgas -> return candidates and Assistant asks which one;
- if no Person candidate -> normal fallback can use existing retrieve/search, but must not create/merge Person automatically.

### “Что мы обсуждали с VOA?”
- if VOA is attached alias/identity to a Person -> resolve Person, then retrieve linked communications;
- cross-provider messages may be returned if exact identities are attached and AI eligibility allows them.

### “Да, этот Telegram аккаунт — Ольга”
- only after Assistant exposed that exact candidate identity and Person in the same turn;
- record confirmation;
- do not send anything;
- later P4/P6 may act on the confirmed identity.

### “Нет, это другая Ольга”
- record rejection for that Person/identity pair;
- future candidate generation should stop repeating the same mistaken suggestion unless explicitly reversed.

## 7. Bounded output and privacy

Set explicit constants for:
- max Person candidates;
- max identities per Person exposed to Assistant;
- max communication objects returned;
- max date window/default recent horizon where appropriate.

Do not expose:
- provider tokens;
- session ids/secrets;
- raw account credentials;
- arbitrary provider metadata.

Use display-safe identifiers only.

## 8. No send-by-person

P5 must not:
- select a communication route for sending;
- call `send_email` / `send_message` based on Person;
- stage external writes;
- create a pending action plan for communication.

That is P6.

## Focused proof

Add tests proving at minimum:
1. Exact identifier resolves one active Person.
2. Attached alias/title/name candidate resolution is deterministic.
3. Two plausible People remain ambiguous; salience may order them but never silently resolves one.
4. Rejected/deleted/cross-user People and identities are excluded.
5. Person communication retrieval returns only objects attributable through active exact identities.
6. Display-name-only message does not become Person-linked retrieval.
7. Cross-provider retrieval works for email + Mattermost/Teams where exact identities exist.
8. Telegram Person retrieval respects `TELEGRAM_MTPROTO_AI_ENABLED` and existing self-authored eligibility when false.
9. Returned communication ids become valid same-turn seen object ids for normal read/follow-up/evidence tooling.
10. Confirmation annotation is accepted only for a same-turn exposed Person + candidate identity.
11. Model-invented/unseen identity confirmation or rejection fails closed.
12. Rejection suppresses the same candidate; retraction/reversal restores eligibility and remains auditable.
13. Multiple active confirmations still surface P4R conflict semantics and do not merge.
14. Feedback operations perform no external provider call and no Person merge.
15. Existing Assistant action-plan/send safety tests remain green.
16. P1–P4 focused Graph Refined tests remain green.
17. No send-by-person path is introduced.

Prefer no migration: reuse `person_identities`, `person_identity_evidence`, Objects, current tool registry and per-turn safety state.

Run focused Person/Assistant tests, Ruff/compile on touched Python, and `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose P6 and do not deploy.
