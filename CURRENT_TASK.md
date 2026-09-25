# Current task — Graph Refined P6: Person-aware route discovery + safe send-by-person

Graph Refined P1–P5 are architect-accepted. Implement the final bounded Person Refinement interaction layer: sending to a resolved Person through a known exact route while preserving the existing external-action approval/freeze machinery.

Do not build a second provider send engine. Reuse the current `send_email` and provider-neutral `send_message` prepare/execution paths and the existing pending action plan.

Do not deploy.

Known unrelated baseline failures around the Assistant `pending_action_plan` JSON expectation and `ai_traces_user_id_fkey` remain outside this task; do not claim the full suite is green.

## Goal

Support Assistant flows such as:

- “Напиши Ольге, что встречу перенесли.”
- “Напиши Ольге в Telegram.”
- “Отправь Максиму письмо.”
- “Ответь/напиши через Teams.”

The safe sequence is:

1. resolve exactly one Person;
2. discover bounded known send routes for that Person;
3. if route is ambiguous, ask the user rather than guessing;
4. if the user explicitly chooses a route, record bounded route-choice feedback;
5. stage the existing external send action;
6. freeze exact provider/account/conversation/recipient in the pending action plan;
7. execute only after the existing explicit approval.

## 1. Read-only Person route discovery

Add an Assistant-exposed READ tool such as `list_person_routes`.

Input:
- `person_id` from a same-turn resolved Person;
- optional provider/category constraint where useful.

Output a bounded deterministic list of **concrete known routes**, not abstract provider names.

Each route should include only safe model-visible fields such as:
- stable/bounded route key;
- route kind: `email` or `chat`;
- provider/category;
- display-safe recipient/identity label;
- exact effective identity tuple where needed for allowlisting;
- for chat, an exact eligible `anchor_object_id`;
- safe conversation label if available;
- recent-use timestamp / route-choice reason if useful;
- whether previous explicit `user_route_choice` evidence exists;
- reasons/conflict state;
- truncation.

Do not expose provider tokens, encrypted references, session strings, OAuth data, raw credentials, or unrestricted provider metadata.

### Route sources

Only use effective exact identities and already stored canonical communication/account facts.

#### Email
- effective exact email identity is the recipient route;
- never derive email from display name/signature/body;
- if more than one email identity exists, they are separate routes;
- sending account must ultimately be resolved by the existing `prepare_send_email` path and frozen into its canonical action;
- if provider/account constraints cannot be resolved uniquely, fail/ask rather than invent.

#### Mattermost
- only an exact stored DM conversation safely anchored to the Person;
- no public/channel route just because the Person has posted there;
- route uses an exact existing chat_message anchor; existing `prepare_send_message` resolves/freeze server/account/channel.

#### Teams
- only exact oneOnOne conversation anchored to that Person;
- no group-chat route as “send to Person” unless future semantics explicitly support that;
- route uses an exact existing chat_message anchor.

#### Telegram MTProto
- only exact private Person conversation;
- route uses an exact existing eligible chat_message anchor;
- group/channel is not a Person route;
- model-visible route discovery MUST respect the existing Telegram AI eligibility/quarantine. Do not leak inbound Telegram identity/conversation metadata through this tool while disallowed.

Legacy Telegram Bot API remains retired.

## 2. Same-turn route allowlist

Extend `PerTurnToolBudget` with a bounded same-turn Person-route allowlist populated only from model-visible `list_person_routes` output.

A route key/recipient/anchor invented by the model must fail closed.

Do not weaken current:
- seen object id;
- resolved Person;
- seen Person+identity;
- send-message anchor
guards.

## 3. Person-targeted use of existing send tools

Prefer extending the existing input contracts minimally rather than adding a second execution engine.

A clean design is optional `person_id` on existing `SendEmailInput` / `SendMessageInput`:

### Person-targeted email compose
When `person_id` is present:
- Person must be same-turn resolved;
- exactly one recipient email must be supplied;
- that exact recipient route must have been exposed for that Person in the same turn;
- recipient must still be an effective identity at prepare time;
- any active rejection/ownership conflict fails closed;
- then call the existing email prepare path unchanged enough that canonical `SendEmailCanonicalInput` freezes:
  - resolved sender account;
  - provider;
  - exact `to`;
  - subject/body;
  - operation id/message id.

Do not let an LLM invent a Person email address.

Existing non-Person explicit-address compose behavior must remain backward compatible.

### Person-targeted chat send
When `person_id` is present:
- Person must be same-turn resolved;
- exact `conversation_object_id` must be an exposed route for that Person;
- route must still be active/effective and 1:1/private at prepare time;
- then delegate to current `prepare_send_message`, which freezes exact provider/account/conversation route.

Do not accept raw provider route metadata from the model.

Existing non-Person reply/conversation send remains backward compatible.

## 4. Route ambiguity

Never silently choose among multiple viable Person routes merely because:
- salience is higher;
- one provider was used more recently;
- P2 score is higher;
- a display name is a closer match.

Allowed automatic selection:
- exactly one viable route remains after the user's explicit wording/constraint;
- or the current request itself explicitly specifies a provider/route and that constraint resolves to exactly one concrete route.

If multiple concrete routes remain:
- Assistant should present bounded choices and ask;
- no external action may be staged yet.

Examples:
- two email addresses -> ask which email unless user already specified one;
- email + Teams -> ask unless user says “по почте” / “в Teams”;
- two Teams oneOnOne conversations/accounts -> ask;
- conflicting/rejected identity -> do not offer as viable route.

Previous `user_route_choice` may order or annotate options but must not silently override current ambiguity in P6.

## 5. Explicit route-choice feedback

Add a narrow Assistant-exposed ANNOTATE operation such as `record_person_route_choice`.

Requirements:
- Person must be same-turn resolved;
- concrete route must have been exposed in the same turn;
- the user's current instruction must explicitly choose that route/provider;
- record existing P2 `user_route_choice` evidence against the route's exact Person identity;
- selection is positive evidence / route preference, NOT `user_confirmed`;
- repeated identical choice is idempotent/no score inflation;
- choosing a route does not merge People or transfer identity ownership;
- route choice remains auditable and reversible through existing evidence semantics if practical.

Do not automatically record a “user route choice” when the Assistant selected the only available route without an explicit user preference.

## 6. Freeze-before-approval invariant

The exact external destination must be frozen during the existing prepare/stage step, before approval.

For email pending plan, verify stored canonical action contains exact:
- provider;
- sending account;
- recipient;
- subject/body;
- operation id/message id.

For chat pending plan, verify exact:
- provider;
- account;
- conversation/channel/peer/chat id inside the existing canonical route;
- anchor object;
- body;
- operation id.

Approval/resume must execute exactly this frozen canonical destination even if:
- Person identities change after staging;
- route preference changes;
- a new “better” route appears;
- salience changes;
- new messages arrive.

Do NOT re-resolve Person or route on approval execution.

If the Person/identity becomes rejected after staging, the already-frozen pending plan semantics remain governed by the existing action-plan lifecycle; do not silently retarget it. The user can reject/cancel the pending plan and restage.

## 7. Route discovery and action-plan separation

`list_person_routes` is READ and must never stage/send.

`record_person_route_choice` is ANNOTATE and must never send.

Only existing COMMUNICATE send tools may create the pending external action.

Do not mix identity mutation and an irreversible send in one action plan. Existing invariant that COMMUNICATE is the sole action in its plan remains unchanged.

## 8. Telegram posture

Implement the complete MTProto Person-route path, but preserve:
- `TELEGRAM_MTPROTO_AI_ENABLED=false` default;
- existing AI eligibility;
- non-AI transport/storage unaffected;
- no Bot API;
- no hardcoded `TestML`.

When the AI gate later becomes permitted/enabled, route discovery should activate through the existing eligibility/config path, not redesign.

## 9. No live identity enrichment in P6

P6 sends only through already-known routes.

If Person has no viable route:
- report no known route / needs provider lookup;
- do not query remote directories;
- do not invent usernames/emails;
- do not create a Person or identity.

Live provider-profile enrichment remains a separate future capability if needed.

## 10. Assistant tool guidance

Update model-facing descriptions so:

For “напиши <Person> ...”:
1. `resolve_person`;
2. `list_person_routes`;
3. if ambiguous, ask user;
4. if exactly one route or explicit provider selection uniquely identifies it, call existing send tool with `person_id` + exact exposed route;
5. tool returns approval_required;
6. Assistant presents the existing pending action plan.

For “ответь на это” with an exact message already in UI context:
- existing reply flow remains valid and does not require Person resolution unless the user framed the target by Person name.

Do not ask for prose confirmation before a send tool returns approval_required.

## Focused proof

Add tests proving at minimum:

1. Resolved Person with one effective email route exposes exactly that route.
2. Two email identities remain route-ambiguous; no send staged without explicit choice.
3. Email + Teams remains ambiguous unless user/provider constraint narrows to one.
4. Rejected identity is never offered as a route.
5. Deleted/rejected/cross-user Person/identity is excluded.
6. Mattermost public channel is not a Person route; exact DM is.
7. Teams group chat is not a Person route; exact oneOnOne is.
8. Telegram group/channel is not a Person route; private MTProto route follows AI eligibility.
9. Invented route key/email/anchor fails same-turn allowlist.
10. Person-targeted email with exposed exact recipient stages the existing `send_email` COMMUNICATE action.
11. Person-targeted chat with exposed exact anchor stages existing `send_message`.
12. Existing generic explicit-address email and exact-anchor reply/send remain backward compatible.
13. Explicit user route choice writes `user_route_choice`, not `user_confirmed`, and does not merge/attach.
14. Repeated route choice is idempotent/no score inflation.
15. Route preference may order choices but multiple routes still remain ambiguous.
16. Pending action freezes exact email provider/account/recipient before approval.
17. Pending action freezes exact chat provider/account/conversation/recipient route before approval.
18. Changing Person identity/route after staging does not retarget approved execution.
19. Existing “COMMUNICATE must be only action in plan” invariant remains green.
20. P1–P5 focused Graph Refined tests remain green.
21. Existing external-send safety/idempotency tests remain green except already documented unrelated baseline failures.
22. No live provider directory/LLM enrichment and no deployment.

Prefer no migration. Reuse current PersonIdentity/P2 evidence/P5 effective identity, current communication Objects, current send services, current ToolRegistry/PerTurnToolBudget, and current PendingActionPlan.

Run focused Person/Assistant/send/action-plan tests, Ruff/compile on touched Python, and `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not deploy or choose the next major roadmap stage.
