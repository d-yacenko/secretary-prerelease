# Current task — Graph Refined P5R: Assistant Person resolution/retrieval safety + real candidate feedback

Architect review of P5 implementation `59b54671ed0707c237bdf3d90d3eb70317ffc3eb` found several bounded but blocking semantic gaps.

Correct P5 only. Do not start P6 and do not implement send-by-person.

Do not add live provider/directory calls, LLM calls outside the existing Assistant model path, proactive behavior, voice/media work, migrations, or Task Graph redesign. Do not deploy.

## 1. Exact Person resolution must preserve P4R conflict semantics

Current `PersonAssistantService._resolve_exact()` immediately returns the attached Person when `PersonIdentityService.resolve(identity)` finds an owner.

This can hide:
- an active `user_rejected` for that owner/identity pair;
- one active `user_confirmed` for another Person;
- multiple contradictory active confirmations.

Required exact-resolution semantics for one normalized identity:

### attached owner, no active rejection/conflict
- may resolve to owner.

### attached owner + active `user_rejected` for same owner/identity
- MUST NOT resolve that identity to the rejected Person;
- the rejected pair is suppressed until explicit reversal/confirmation retracts the rejection.

### attached owner + active confirmation for a different Person
- return explicit ambiguity/conflict;
- do not silently prefer physical owner;
- reason must expose `identity_conflict`.

### multiple active confirmations
- preserve P4R semantics;
- return ambiguity/conflict, not resolved;
- reasons include `multiple_user_confirmations`;
- never merge/reassign.

### no attached owner
- one active confirmed/evidence Person may resolve if otherwise unambiguous;
- multiple active candidates remain ambiguous;
- active rejection suppresses only the rejected Person/identity pair.

Add focused tests for owner+rejection, owner+other-confirmation, owner+multiple-confirmation, and reversal.

## 2. Ambiguous candidates are visible, but not authorized for Person retrieval

Current same-turn guard for `find_person_communications` accepts any Person id present in `seen_object_ids`. `resolve_person` puts all ambiguous candidate Person ids there, so the model can silently choose the highest-salience candidate and retrieve communications without asking the user.

Required correction:
- keep ambiguous Person candidates visible as ordinary seen object ids so the model can describe them;
- add a separate bounded per-turn set for **resolved Person ids**;
- only `ResolvePersonOutput.state == "resolved"` + its exact `person_id` may enter that set;
- `find_person_communications` requires a same-turn **resolved Person id**, not merely a seen candidate;
- after an ambiguous result the Assistant must ask the user to disambiguate; a later user turn can call `resolve_person` again with the selected name/alias/exact identity and then retrieve;
- identity feedback may still use an explicitly shown ambiguous Person+identity candidate when the user's current utterance is itself an explicit confirmation/rejection.

Tests:
1. ambiguous result -> `find_person_communications` fails closed for either candidate;
2. resolved result -> retrieval succeeds;
3. generic `get_object`/inspection of ambiguous Person candidate remains allowed if already supported.

## 3. Active user rejection must suppress an attached identity in P5 retrieval

Current `find_person_communications` builds keys from all active `PersonIdentity` rows, even if P2 has an active `user_rejected` for that exact Person/identity pair.

Required correction:
- an active user rejection for Person+identity makes that identity ineligible for P5 resolution summaries and Person communication attribution;
- retraction or later explicit confirmation (which retracts the rejection under P2 semantics) restores eligibility;
- do not physically delete historical PersonIdentity rows;
- do not rewrite evidence history.

Prefer a small shared "effective Person identity" helper/predicate if useful. Do not broadly redesign P1.

At minimum ensure P5 resolve/summaries/retrieval are consistent. If P4 coverage/enrichment currently treats the same explicitly rejected attached identity as usable, correct that narrow inconsistency too so the rejected mapping is not immediately re-promoted by P4.

## 4. Person communication retrieval must include the safely attributable outbound side

Current matching uses `extract_person_identity_evidence(obj)` and only falls back to participant keys when extraction is empty. This causes outbound messages to be missed:
- outbound email extraction sees the user's From/sender and never reaches the Person recipient;
- outbound private Telegram extraction sees the user's sender id and never reaches the Person peer id.

Required provider-safe matching:

### Gmail / Yandex Mail
- when direction is safely outbound, match the Person against To/Cc recipients;
- when safely inbound, match sender;
- when `direction` filter is requested, role must be relative to the Secretary user;
- reuse the canonical Gmail/Yandex direction semantics already implemented in P3R;
- ambiguous direction fails closed for direction-filtered retrieval;
- no display-name-only linkage.

### Telegram MTProto
- private inbound: Person may match positive `sender_peer_id`;
- private outbound: Person may match positive `peer_id`;
- group/channel inbound: Person may match positive human sender id;
- group/channel outbound must not be attributed to an arbitrary Person merely because they are in the group;
- continue applying `telegram_mtproto_ai_predicate()` before model-visible results. With AI gate false, only the existing permitted self-authored scope may pass.

### Teams oneOnOne / Mattermost DM
Canonical outbound messages often carry the user's own sender identity, not the counterpart id.

For bounded P5 retrieval it is acceptable to use a conservative two-pass 1:1 conversation anchor:
- first identify a Teams oneOnOne `tenant_id + chat_id` or Mattermost DM `server_url + channel_id` from a message in the bounded scan whose exact inbound author identity matches the Person;
- once that 1:1 conversation is anchored to the Person, include other active/eligible messages from that exact 1:1 conversation, including the user's outbound side;
- never expand group/public channels this way;
- no provider call.

If current canonical facts are insufficient for a provider, fail closed rather than guess.

Add tests proving a "what we discussed" retrieval includes both inbound and safely attributable outbound messages for email and Telegram, plus bounded oneOnOne/DM expansion for Teams/Mattermost where canonical data supports it.

## 5. Real canonical-source identity candidate must be exposable before feedback

Current feedback safety is good, but the main same-turn test seeds an `EXACT_IDENTIFIER` evidence row manually before `resolve_person`.

In a real unresolved-contact flow, P4 may see:
- a recent canonical message with an exact provider identity;
- display/name similarity to an existing Person;
- no attached identity and no persisted Person evidence yet.

P5 currently has no Assistant READ path that exposes that real source-derived candidate identity, so the user cannot actually say "yes, this account is Olga" through the same-turn allowlist.

Add the smallest read-only Assistant path, for example `find_person_identity_candidates`, or an equivalent bounded extension.

Required behavior:
- operates on an already resolved/shown active Person;
- scans a bounded recent canonical communication window;
- extracts exact provider identities through the P1/P1R extractors;
- proposes only conservative source-derived candidates for that Person using existing P2 name/candidate logic;
- returns provider/type/realm/canonical value + display-safe label + bounded source object ids + reasons/assessment;
- never attaches or writes evidence;
- rejected pair is omitted/suppressed;
- identity owned by another Person is returned only as an explicit conflict, never as an ordinary confirmation candidate;
- Telegram candidate identity is model-visible only when current Telegram AI eligibility/gate permits it; no gate bypass through identity metadata;
- output candidate identities are added to the existing same-turn Person+identity feedback allowlist.

Then replace/add the feedback test with a real flow:
1. create Person;
2. create canonical message containing an unresolved exact identity with matching display evidence;
3. READ tool exposes Person + candidate identity;
4. explicit confirm/reject tool succeeds only after that output is committed model-visible;
5. invented/unseen tuple still fails closed.

Do not call P4 `plan()` from a READ tool if that would mutate evidence/identity state. Extract/refactor a pure helper instead.

## 6. Direction parity

`FindPersonCommunicationsInput.direction` currently supports inbound/outbound.

Ensure direction is implemented consistently for:
- Gmail;
- Yandex Mail using its existing sent/inbox folder semantics;
- Telegram MTProto;
- Teams/Mattermost only where direction is safely known or 1:1 conversation anchoring makes the requested relation defensible.

Unknown/ambiguous direction must fail closed for a direction-filtered request rather than return a false match.

## 7. Preserve existing privacy and mutation boundaries

- Telegram MTProto AI gate/default remains unchanged.
- No Telegram inbound identity/content leakage through candidate discovery or Person summaries.
- Feedback remains `ANNOTATE`, local, reversible, same-turn allowlisted.
- No Person merge.
- No external send/write.
- No pending communication action plan in P5R.
- No live provider/directory/model lookup.
- No migration unless a truly unavoidable schema issue is found; prefer service/domain changes.

## Focused proof

Add/extend tests proving at minimum:

1. Attached identity + active user rejection does not resolve/retrieve as that Person.
2. Reversal/confirmation restores effective eligibility without losing audit history.
3. Attached owner + confirmation of another Person returns conflict/ambiguity.
4. Multiple confirmations with owner preserve P4R conflict semantics.
5. Ambiguous Person candidates cannot be used directly by `find_person_communications`.
6. A same-turn resolved Person can be used by `find_person_communications`.
7. Outbound email to Person is returned; inbound email from Person is returned.
8. Yandex direction filter follows sent/inbox semantics.
9. Private Telegram outbound to Person is returned only when AI eligibility permits; group outbound is not attributed to an arbitrary Person.
10. Teams oneOnOne / Mattermost DM outbound side is included only after a bounded exact inbound anchor for that Person; group/public expansion does not occur.
11. A real source-derived unresolved identity can be exposed by a READ path and then confirmed/rejected in the same turn.
12. Invented/unseen identity feedback remains blocked.
13. Rejected source-derived candidate is suppressed until explicit reversal.
14. Telegram candidate identity stays hidden when AI gate/quarantine disallows model exposure.
15. Returned communication ids still become seen object ids.
16. Existing P1–P5 focused tests and Assistant action-plan/send safety tests remain green.
17. No send-by-person/P6 path is introduced.

Run focused Person/Assistant tests, touched provider-normalization tests where needed, Ruff/compile on touched Python, and `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose P6 and do not deploy.
